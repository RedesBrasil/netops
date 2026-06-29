"""Testes E2E do NetOps Console (verificação do plano). Tudo em tmp isolado."""
from __future__ import annotations

import os
import shutil
import stat

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


# --------------------------------------------------------------------------- #
# Segurança / bind
# --------------------------------------------------------------------------- #
def test_rejects_non_loopback_host(env):
    from app import create_app
    c = TestClient(create_app(), base_url="http://evil.example.com")
    assert c.get("/api/hosts").status_code == 403


def test_read_only_blocks_writes(env):
    import deps
    from app import create_app
    deps.STATE.read_only = True
    c = TestClient(create_app(), base_url="http://127.0.0.1")
    assert c.get("/api/hosts").status_code == 200
    r = c.post("/api/hosts", json={"id": "x", "hostname": "h", "mgmt_ip": "1.1.1.1", "group": "mikrotik-dist"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Gate de login: senha-mestra do cofre trava o console inteiro
# --------------------------------------------------------------------------- #
def _bare_client():
    """Cliente SEM sessão de login (nenhum header X-Netops-Session)."""
    from app import create_app
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_no_login_required_without_vault(env):
    """Sem cofre inicializado: não há login (senha-mestra), o console abre direto."""
    c = _bare_client()
    assert c.get("/api/auth/status").json()["auth_required"] is False
    assert c.get("/api/hosts").status_code == 200


def test_console_requires_login_when_vault_initialized(env):
    """Com cofre: /api exige a sessão de login; sem ela => 401 auth_required."""
    _init_vault(env)
    c = _bare_client()
    s = c.get("/api/auth/status").json()
    assert s["auth_required"] is True and s["authenticated"] is False
    r = c.get("/api/hosts")
    assert r.status_code == 401 and r.json()["error"] == "auth_required"


def test_login_wrong_password_401_no_leak(env):
    _init_vault(env, master="correta")
    c = _bare_client()
    r = c.post("/api/auth/login", json={"master_password": "errada"})
    assert r.status_code == 401 and r.json()["error"] == "bad_password"
    assert "errada" not in r.text                              # nunca ecoa a senha


def test_login_correct_password_grants_session(env):
    _init_vault(env, master="senha-mestra-teste")
    c = _bare_client()
    assert c.get("/api/hosts").status_code == 401              # antes do login
    r = c.post("/api/auth/login", json={"master_password": "senha-mestra-teste"})
    assert r.status_code == 200, r.text
    sid = r.json()["auth_token"]
    assert sid and "senha-mestra-teste" not in r.text          # devolve sid, não a senha
    hdr = {"X-Netops-Session": sid}
    assert c.get("/api/auth/status", headers=hdr).json()["authenticated"] is True
    assert c.get("/api/hosts", headers=hdr).status_code == 200 # com a sessão, passa


def test_login_also_unlocks_vault(env):
    """A mesma ação de login destranca o cofre (mesma sessão da CLI)."""
    from lib import vault_session
    _init_vault(env, master="m")
    vault_session.clear_session()                              # começa trancado
    c = _bare_client()
    sid = c.post("/api/auth/login", json={"master_password": "m"}).json()["auth_token"]
    assert c.get("/api/vault/status", headers={"X-Netops-Session": sid}).json()["state"] == "cache"


def test_logout_drops_session(env):
    _init_vault(env, master="m")
    c = _bare_client()
    sid = c.post("/api/auth/login", json={"master_password": "m"}).json()["auth_token"]
    hdr = {"X-Netops-Session": sid}
    assert c.get("/api/hosts", headers=hdr).status_code == 200
    assert c.post("/api/auth/logout", headers=hdr).status_code == 200
    assert c.get("/api/hosts", headers=hdr).status_code == 401  # sessão encerrada


# --------------------------------------------------------------------------- #
# Inventário: validação, herança, concorrência
# --------------------------------------------------------------------------- #
def test_enums_from_schema(client):
    e = client.get("/api/meta/enums").json()
    assert "mikrotik" in e["vendor"] and "ssh" in e["method"] and "core" in e["role"]


def test_create_host_ok_and_inheritance(client):
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/hosts", json={"id": "rt-new", "hostname": "N", "mgmt_ip": "10.0.0.9",
                                        "group": "mikrotik-dist"}, headers={"If-Match": rev})
    assert r.status_code == 201, r.text
    h = client.get("/api/hosts/rt-new").json()
    assert h["explicit"].get("vendor") is None          # não materializou herança
    assert h["effective"]["vendor"] == "mikrotik"        # herdou do grupo
    assert h["effective"]["access"]["method"] == "ssh"


def test_pydantic_rejects_bad_vendor(client):
    r = client.post("/api/hosts", json={"id": "b", "hostname": "h", "mgmt_ip": "1.1.1.1", "vendor": "juniper"})
    assert r.status_code == 422


def test_delta_validation_missing_credential(client):
    """Host sem credential resolvível => 422; mas NÃO barra por nulls pré-existentes."""
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/hosts", json={"id": "nc", "hostname": "h", "mgmt_ip": "1.1.1.1",
                                        "vendor": "linux"}, headers={"If-Match": rev})
    assert r.status_code == 422
    locs = {e["loc"] for e in r.json()["errors"]}
    assert "hosts/nc/credential" in locs
    # e o erro pré-existente (model null nos hosts do seed) NÃO aparece como novo:
    assert not any("model" in loc for loc in locs)


def test_optimistic_concurrency_conflict(client):
    r = client.post("/api/hosts", json={"id": "z", "hostname": "h", "mgmt_ip": "1.1.1.1",
                                        "group": "mikrotik-dist"}, headers={"If-Match": "stale"})
    assert r.status_code == 409


def test_comments_preserved_on_edit(client, env):
    data = client.get("/api/hosts").json()         # 1º host do inventário (seja qual for o nome)
    hid = data["hosts"][0]["id"]
    client.patch(f"/api/hosts/{hid}", json={"site": "datacenter"}, headers={"If-Match": data["rev"]})
    text = (env / "network" / "hosts.yaml").read_text()
    assert text.startswith("# NetOps")            # cabeçalho preservado
    assert "API RouterOS" in text                 # comentário inline preservado
    assert "site: datacenter" in text


def test_delete_host_then_validate(client):
    rev = client.get("/api/hosts").json()["rev"]
    r = client.delete("/api/hosts/rt-dist-03", headers={"If-Match": rev})
    assert r.status_code == 200
    assert "rt-dist-03" not in [h["id"] for h in client.get("/api/hosts").json()["hosts"]]


# --------------------------------------------------------------------------- #
# Credenciais + cofre (crypto round-trip real)
# --------------------------------------------------------------------------- #
def _init_vault(env, master="senha-mestra-teste"):
    """Inicializa um cofre no credentials.yaml tmp e destranca a sessão."""
    import deps
    from lib import vault, vault_session
    from vault import cli
    base = "version: 1\n\ncredentials: {}\n"
    meta, key = vault.build_meta(master)
    cli._atomic_write(deps.CREDS_FILE, cli._set_vault_block(base, meta))
    vault_session.set_session_key(key, 900)
    return key


def test_password_locked_returns_423(client, env):
    _init_vault(env)
    from lib import vault_session
    vault_session.clear_session()                 # tranca
    client.post("/api/credentials", json={"name": "cred_x", "username": "admin"})
    r = client.put("/api/credentials/cred_x/password", json={"value": "s3nha", "field": "password"})
    assert r.status_code == 423
    assert "unlock" in r.json()["action"]


def test_password_uninitialized_returns_409(client, env):
    client.post("/api/credentials", json={"name": "cred_x", "username": "admin"})
    r = client.put("/api/credentials/cred_x/password", json={"value": "s3nha"})
    assert r.status_code == 409 and r.json()["error"] == "vault_uninitialized"


def test_encrypt_on_write_roundtrip(client, env):
    _init_vault(env)
    client.post("/api/credentials", json={"name": "cred_x", "username": "admin"})
    r = client.put("/api/credentials/cred_x/password", json={"value": "super-secreto", "field": "password"})
    assert r.status_code == 200
    # nunca devolve plaintext, só metadados mascarados
    body = r.json()
    assert body["password"] == {"set": True, "encrypted": True}
    assert "super-secreto" not in r.text
    # round-trip: o token enc.v1: decifra de volta ao original via resolve_secret
    from lib.inventory import resolve_secret
    import yaml
    data = yaml.safe_load(env.joinpath("network/credentials.yaml").read_text())
    token = data["credentials"]["cred_x"]["password"]
    assert token.startswith("enc.v1:")
    assert resolve_secret(token) == "super-secreto"


def test_credentials_file_mode_600(client, env):
    _init_vault(env)
    client.post("/api/credentials", json={"name": "cred_x", "username": "admin"})
    client.put("/api/credentials/cred_x/password", json={"value": "x", "field": "password"})
    mode = stat.S_IMODE(os.stat(env / "network" / "credentials.yaml").st_mode)
    assert mode == 0o600


def test_credentials_list_never_leaks_plaintext(client, env):
    _init_vault(env)
    client.post("/api/credentials", json={"name": "cred_x", "username": "admin"})
    client.put("/api/credentials/cred_x/password", json={"value": "TOPSECRET", "field": "password"})
    r = client.get("/api/credentials")
    assert "TOPSECRET" not in r.text
    cred = r.json()["credentials"][0]
    assert cred["password"]["encrypted"] is True


# --------------------------------------------------------------------------- #
# Cofre: status NÃO renova o TTL
# --------------------------------------------------------------------------- #
def test_status_does_not_renew_ttl(client, env):
    _init_vault(env)
    s1 = client.get("/api/vault/status").json()
    assert s1["state"] == "cache" and s1["writable_secrets"] is True
    s2 = client.get("/api/vault/status").json()
    # status usa session_status() (sem renovar): expires_in não pode AUMENTAR.
    assert s2["expires_in"] <= s1["expires_in"]


# --------------------------------------------------------------------------- #
# Cofre: destrancar/trancar pela web (senha-mestra digitada na UI)
# --------------------------------------------------------------------------- #
def test_unlock_via_web_then_write_secret(client, env):
    from lib import vault_session
    _init_vault(env, master="senha-mestra-teste")
    vault_session.clear_session()                                  # começa trancado
    assert client.get("/api/vault/status").json()["state"] == "locked"
    r = client.post("/api/vault/unlock", json={"master_password": "senha-mestra-teste"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "cache" and r.json()["writable_secrets"] is True
    # sessão real destrancada => escrita de segredo funciona (mesma sessão da CLI)
    client.post("/api/credentials", json={"name": "cred_u", "username": "admin"})
    assert client.put("/api/credentials/cred_u/password", json={"value": "abc"}).status_code == 200


def test_unlock_wrong_password_401_no_leak(client, env):
    from lib import vault_session
    _init_vault(env, master="correta")
    vault_session.clear_session()
    r = client.post("/api/vault/unlock", json={"master_password": "errada"})
    assert r.status_code == 401 and r.json()["error"] == "vault_wrong_key"
    assert "errada" not in r.text                                  # nunca ecoa a senha
    assert client.get("/api/vault/status").json()["state"] == "locked"  # segue trancado


def test_unlock_uninitialized_409(client, env):
    r = client.post("/api/vault/unlock", json={"master_password": "qualquer"})
    assert r.status_code == 409 and r.json()["error"] == "vault_uninitialized"


def test_unlock_disabled_returns_403(client, env):
    import deps
    from lib import vault_session
    _init_vault(env)
    vault_session.clear_session()
    deps.STATE.allow_vault_unlock = False                          # --no-vault-unlock
    r = client.post("/api/vault/unlock", json={"master_password": "senha-mestra-teste"})
    assert r.status_code == 403 and r.json()["error"] == "unlock_disabled"
    assert client.get("/api/vault/status").json()["allow_unlock"] is False


def test_lock_via_web(client, env):
    _init_vault(env)                                               # destrancado
    assert client.get("/api/vault/status").json()["state"] == "cache"
    r = client.post("/api/vault/lock")
    assert r.status_code == 200 and r.json()["state"] == "locked"


# --------------------------------------------------------------------------- #
# Memória: arquivo único MEMORY.md (GET/PUT com concorrência otimista)
# --------------------------------------------------------------------------- #
def test_memory_single_file_roundtrip(client):
    r = client.get("/api/memory")
    assert r.status_code == 200 and "text" in r.json() and "rev" in r.json()
    rev = r.json()["rev"]
    novo = r.json()["text"] + "\n- nota de teste\n"
    w = client.put("/api/memory", json={"text": novo}, headers={"If-Match": rev})
    assert w.status_code == 200 and "rev" in w.json()
    assert client.get("/api/memory").json()["text"] == novo


# --------------------------------------------------------------------------- #
# Terminal web (PTY via WebSocket) — gating de segurança + echo
# (o TestClient manda Host: 'testserver' no handshake WS; liberar quando a conexão
#  precisa passar pelo anti-DNS-rebind.)
# --------------------------------------------------------------------------- #
def _allow_testserver():
    import deps
    deps.STATE.allowed_hosts = ("testserver", "127.0.0.1", "localhost")


def test_terminal_off_by_default(client, env):
    _allow_testserver()                                        # sem --enable-terminal
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/term"):
            pass
    assert ei.value.code == 4403


def test_terminal_blocked_in_read_only(client, env):
    import deps
    _allow_testserver(); deps.STATE.enable_terminal = True; deps.STATE.read_only = True
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/term"):    # terminal nunca em read-only
            pass


def test_terminal_rejects_unlisted_host(client, env):
    import deps
    deps.STATE.enable_terminal = True                          # Host 'testserver' NÃO liberado
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/term"):
            pass
    assert ei.value.code == 4403


def test_terminal_requires_auth_session_when_vault_initialized(client, env):
    """Com cofre inicializado, o WS do terminal exige &auth (mesmo gate do /api)."""
    import deps
    _allow_testserver(); deps.STATE.enable_terminal = True
    _init_vault(env, master="m")
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/term"):       # sem a sessao (&auth)
            pass
    assert ei.value.code == 4403


@pytest.mark.skipif(not shutil.which("bash"), reason="bash ausente")
def test_terminal_echo_roundtrip(client, env):
    import deps
    _allow_testserver(); deps.STATE.enable_terminal = True
    with client.websocket_connect("/api/term") as ws:
        ws.send_bytes(b"echo NETOPS_TERM_OK\n")                # teclas (binário)
        buf = b""
        for _ in range(80):
            buf += ws.receive_bytes()                          # saída do PTY (binário)
            if b"NETOPS_TERM_OK" in buf:
                break
        assert b"NETOPS_TERM_OK" in buf


# --------------------------------------------------------------------------- #
# Página Claude Code (agente via WebSocket) — gating de segurança + meta + upload
# (mesma postura do terminal; os testes NÃO disparam o SDK — só exercitam o gate,
#  que fecha em 4403 antes de aceitar a conexão.)
# --------------------------------------------------------------------------- #
def test_claude_off_by_default(client, env):
    _allow_testserver()                                        # sem --enable-claude
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/claude"):
            pass
    assert ei.value.code == 4403


def test_claude_blocked_in_read_only(client, env):
    import deps
    _allow_testserver(); deps.STATE.enable_claude = True; deps.STATE.read_only = True
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/claude"):  # nunca em read-only
            pass
    assert ei.value.code == 4403


def test_claude_requires_auth_session_when_vault_initialized(client, env):
    """Com cofre inicializado, o WS do Claude exige &auth (mesmo gate do /api e do terminal)."""
    import deps
    _allow_testserver(); deps.STATE.enable_claude = True
    _init_vault(env, master="m")
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/claude"):  # sem a sessao (&auth)
            pass
    assert ei.value.code == 4403


def test_config_meta_exposes_claude_flag(client, env):
    import deps
    assert client.get("/api/config/meta").json()["claude_enabled"] is False
    deps.STATE.enable_claude = True
    assert client.get("/api/config/meta").json()["claude_enabled"] is True


def test_claude_upload_disabled_returns_403(client, env):
    """Com a página desligada, o canal de upload não cria escrita (403 antes de gravar)."""
    files = {"file": ("a.txt", b"oi", "text/plain")}
    r = client.post("/api/claude/upload", files=files)
    assert r.status_code == 403 and r.json()["error"] == "claude_disabled"


def test_claude_sessions_gated_by_flag(client, env):
    """Listar/retomar sessões só responde com a página ligada."""
    import deps
    assert client.get("/api/claude/sessions").status_code == 403
    deps.STATE.enable_claude = True
    r = client.get("/api/claude/sessions")
    assert r.status_code == 200 and "sessions" in r.json()


# --------------------------------------------------------------------------- #
# Topologia
# --------------------------------------------------------------------------- #
def test_topology_dangling_and_render(client):
    t = client.get("/api/topology").json()
    # o seed referencia hosts inexistentes => sinaliza dangling, não bloqueia
    assert any(lk["dangling"] for lk in t["links"])
    r = client.post("/api/topology/render")
    assert r.status_code == 200 and "graph TD" in r.json()["markdown"]


# --------------------------------------------------------------------------- #
# Conhecimento + catálogo
# --------------------------------------------------------------------------- #
def test_knowledge_index_reads(client, env):
    # _catalog não foi copiado -> índice vazio mas rota responde
    r = client.get("/api/knowledge/best-practices")
    assert r.status_code == 200 and "index" in r.json()


def test_workflow_validation_rejects_garbage(client, env):
    (env / "workflows").mkdir(exist_ok=True)
    import deps
    deps.WORKFLOWS_DIR = env / "workflows"
    r = client.post("/api/workflows", json={"file": "x.workflow.yaml", "text": "nope: 1"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Renomear ID/nome com cascade nas referências
# --------------------------------------------------------------------------- #
def _hosts_yaml(env):
    import yaml
    return yaml.safe_load((env / "network" / "hosts.yaml").read_text())


def _seed_host(client, hid, **fields):
    """Cria um host válido e AUTOSSUFICIENTE (não depende dos nomes do seed real, que o
    operador pode renomear pela própria UI). `fields` sobrescreve os defaults."""
    rev = client.get("/api/hosts").json()["rev"]
    body = {"id": hid, "hostname": hid.upper().replace("-", "_"), "mgmt_ip": "10.99.0.9",
            "vendor": "linux", "credential": "cred_seed", "access": {"method": "ssh", "port": 22}}
    body.update(fields)
    r = client.post("/api/hosts", json=body, headers={"If-Match": rev})
    assert r.status_code == 201, r.text


def _seed_link(client, ah, bh="t-peer", ap="e1", bp="e2"):
    rev = client.get("/api/topology").json()["rev"]
    r = client.post("/api/topology/links",
                    json={"a": {"host": ah, "port": ap}, "b": {"host": bh, "port": bp}},
                    headers={"If-Match": rev})
    assert r.status_code == 200, r.text


def test_host_references_lists_topology(client):
    _seed_host(client, "t-ref")
    _seed_link(client, "t-ref")
    refs = client.get("/api/hosts/t-ref/references").json()
    assert refs["count"] >= 1
    assert all(x["kind"] == "topology-link" for x in refs["references"])


def test_rename_host_cascades_topology(client, env):
    import yaml
    _seed_host(client, "t-old")
    _seed_link(client, "t-old")
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/hosts/t-old/rename", json={"to": "t-new"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text
    assert r.json()["renamed"] == {"from": "t-old", "to": "t-new"}
    assert r.json()["updated"], "deveria ter atualizado ao menos um enlace"
    hosts = _hosts_yaml(env)["hosts"]
    assert "t-new" in hosts and "t-old" not in hosts
    topo = yaml.safe_load((env / "network" / "topology.yaml").read_text())
    ends = [e.get("host") for lk in topo["links"] for e in (lk.get("a"), lk.get("b")) if e]
    assert "t-old" not in ends and "t-new" in ends


def test_rename_host_preserves_comments(client, env):
    _seed_host(client, "t-cmt")
    rev = client.get("/api/hosts").json()["rev"]
    client.post("/api/hosts/t-cmt/rename", json={"to": "t-cmt2"}, headers={"If-Match": rev})
    text = (env / "network" / "hosts.yaml").read_text()
    assert text.startswith("# NetOps")          # cabeçalho preservado
    assert "API RouterOS" in text               # comentário inline (em outro bloco) intacto


def test_rename_host_collision_422(client):
    _seed_host(client, "t-a")
    _seed_host(client, "t-b", mgmt_ip="10.99.0.10")
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/hosts/t-a/rename", json={"to": "t-b"}, headers={"If-Match": rev})
    assert r.status_code == 422


def test_rename_host_conflict_409(client):
    _seed_host(client, "t-c")
    r = client.post("/api/hosts/t-c/rename", json={"to": "t-c2"}, headers={"If-Match": "stale"})
    assert r.status_code == 409


def test_rename_host_bad_slug_422(client):
    _seed_host(client, "t-slug")
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/hosts/t-slug/rename", json={"to": "nome com espaço"}, headers={"If-Match": rev})
    assert r.status_code == 422


def test_rename_group_cascades_hosts(client, env):
    grev = client.get("/api/hosts").json()["rev"]
    assert client.post("/api/groups", json={"name": "grp-x", "vendor": "linux", "role": "server",
                                            "credential": "cred_seed", "access": {"method": "ssh", "port": 22}},
                       headers={"If-Match": grev}).status_code == 201
    _seed_host(client, "t-g1", group="grp-x")
    _seed_host(client, "t-g2", group="grp-x", mgmt_ip="10.99.0.10")
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/groups/grp-x/rename", json={"to": "grp-y"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text
    data = _hosts_yaml(env)
    assert "grp-y" in data["groups"] and "grp-x" not in data["groups"]
    assert data["hosts"]["t-g1"]["group"] == "grp-y"
    assert data["hosts"]["t-g2"]["group"] == "grp-y"


def test_rename_credential_cascades_and_keeps_mode(client, env):
    import yaml
    client.post("/api/credentials", json={"name": "cred_t", "username": "admin"})
    _seed_host(client, "t-cred", credential="cred_t")
    refs = client.get("/api/credentials/cred_t/references").json()
    assert refs["count"] >= 1
    rev = client.get("/api/credentials").json()["rev"]
    r = client.post("/api/credentials/cred_t/rename", json={"to": "cred_t2"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text
    creds = yaml.safe_load((env / "network" / "credentials.yaml").read_text())["credentials"]
    assert "cred_t2" in creds and "cred_t" not in creds
    assert _hosts_yaml(env)["hosts"]["t-cred"]["credential"] == "cred_t2"
    mode = stat.S_IMODE(os.stat(env / "network" / "credentials.yaml").st_mode)
    assert mode == 0o600


def test_rename_credential_preserves_encrypted_secret(client, env):
    _init_vault(env)
    client.post("/api/credentials", json={"name": "cred_x", "username": "admin"})
    client.put("/api/credentials/cred_x/password", json={"value": "super-secreto", "field": "password"})
    rev = client.get("/api/credentials").json()["rev"]
    r = client.post("/api/credentials/cred_x/rename", json={"to": "cred_y"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text
    import yaml
    from lib.inventory import resolve_secret
    creds = yaml.safe_load((env / "network" / "credentials.yaml").read_text())["credentials"]
    token = creds["cred_y"]["password"]
    assert token.startswith("enc.v1:")
    assert resolve_secret(token) == "super-secreto"     # round-trip intacto sob o novo nome


def test_rename_workflow_file(client, env):
    import deps
    (env / "workflows").mkdir(exist_ok=True)
    deps.WORKFLOWS_DIR = env / "workflows"
    wf = "workflow:\n  id: w\n  name: W\n  steps:\n    - id: '01'\n      agent: coordinator\n"
    assert client.post("/api/workflows", json={"file": "a.workflow.yaml", "text": wf}).status_code == 201
    r = client.post("/api/workflows/a.workflow.yaml/rename", json={"to": "b.workflow.yaml"})
    assert r.status_code == 200, r.text
    assert (env / "workflows" / "b.workflow.yaml").exists()
    assert not (env / "workflows" / "a.workflow.yaml").exists()


def test_rename_knowledge_updates_index(client, env, monkeypatch):
    # knowledge.KINDS captura os caminhos de deps no import => monkeypatch direto na KINDS
    # (e via fixture monkeypatch p/ restaurar depois — nunca toca nos dirs reais).
    from routers import knowledge
    bp = env / "best-practices"
    bp.mkdir(exist_ok=True)
    monkeypatch.setattr(knowledge, "KINDS", {
        "best-practices": (bp, bp / "_catalog.yaml", "guides"),
        "config-examples": (bp / "ce", bp / "ce" / "_index.yaml", "examples"),
    })
    client.post("/api/knowledge/best-practices",
                json={"vendor": "mikrotik", "name": "fw.md", "titulo": "Firewall", "text": "# fw"})
    r = client.post("/api/knowledge/best-practices/rename",
                    json={"vendor": "mikrotik", "name": "fw.md", "to_name": "firewall.md"})
    assert r.status_code == 200, r.text
    assert (bp / "mikrotik" / "firewall.md").exists()
    assert not (bp / "mikrotik" / "fw.md").exists()
    import yaml
    idx = yaml.safe_load((bp / "_catalog.yaml").read_text())["guides"]
    assert any(e["file"] == "mikrotik/firewall.md" for e in idx)


# --------------------------------------------------------------------------- #
# Scripts CRUD (scripts/tools/ — só operacionais, Python/Shell)
# --------------------------------------------------------------------------- #
def _tools_tree(env, monkeypatch):
    """Monta uma árvore scripts/tools/ de teste e reaponta deps.TOOLS_DIR p/ ela."""
    import deps
    root = env / "scripts" / "tools"
    (root / "access").mkdir(parents=True)
    (root / "_TEMPLATE").mkdir(parents=True)
    (root / "access" / "ssh.py").write_text(
        '#!/usr/bin/env python3\n"""Acesso SSH multi-fabricante."""\n', encoding="utf-8")
    (root / "access" / "SKILL.md").write_text("# Acesso\nDoc da família.\n", encoding="utf-8")
    (root / "access" / "backup.sh").write_text("#!/usr/bin/env bash\n# Faz backup\n", encoding="utf-8")
    (root / "_TEMPLATE" / "script.py").write_text('"""template"""\n', encoding="utf-8")
    monkeypatch.setattr(deps, "TOOLS_DIR", root)
    return root


def test_scripts_list_only_py_sh_with_metadata(client, env, monkeypatch):
    _tools_tree(env, monkeypatch)
    r = client.get("/api/scripts")
    assert r.status_code == 200, r.text
    data = r.json()
    paths = {s["path"] for s in data["scripts"]}
    # só .py/.sh; nada de .md como linha; _TEMPLATE ignorado
    assert "access/ssh.py" in paths and "access/backup.sh" in paths
    assert not any(p.endswith(".md") for p in paths)
    assert not any(p.startswith("_TEMPLATE") for p in paths)
    ssh = next(s for s in data["scripts"] if s["path"] == "access/ssh.py")
    assert ssh["location"] == "access" and ssh["lang"] == "python" and ssh["desc"]
    assert ssh["doc"] == "access/SKILL.md"             # ícone de doc -> SKILL.md da pasta
    assert "access" in data["locations"]


def test_scripts_create_read_update_delete(client, env, monkeypatch):
    root = _tools_tree(env, monkeypatch)
    r = client.post("/api/scripts", json={"path": "diagnostics/check.py", "text": "print(1)\n"})
    assert r.status_code == 201, r.text
    assert (root / "diagnostics" / "check.py").exists()
    g = client.get("/api/scripts/file", params={"path": "diagnostics/check.py"})
    assert g.status_code == 200 and g.json()["text"] == "print(1)\n"
    rev = g.json()["rev"]
    bad = client.put("/api/scripts/file", json={"path": "diagnostics/check.py", "text": "print(2)\n"},
                     headers={"If-Match": "deadbeef"})
    assert bad.status_code == 409
    ok = client.put("/api/scripts/file", json={"path": "diagnostics/check.py", "text": "print(2)\n"},
                    headers={"If-Match": rev})
    assert ok.status_code == 200, ok.text
    d = client.delete("/api/scripts/file", params={"path": "diagnostics/check.py"})
    assert d.status_code == 200 and not (root / "diagnostics" / "check.py").exists()


def test_scripts_blocks_traversal_and_nonscript(client, env, monkeypatch):
    _tools_tree(env, monkeypatch)
    assert client.post("/api/scripts", json={"path": "../evil.py", "text": "x"}).status_code == 422
    # só Python/Shell na criação
    assert client.post("/api/scripts", json={"path": "access/x.md", "text": "x"}).status_code == 422
    assert client.post("/api/scripts", json={"path": "access/x.bin", "text": "x"}).status_code == 422


def test_scripts_rename(client, env, monkeypatch):
    root = _tools_tree(env, monkeypatch)
    client.post("/api/scripts", json={"path": "diagnostics/temp.py", "text": "x\n"})
    r = client.post("/api/scripts/rename", json={"path": "diagnostics/temp.py", "to": "diagnostics/final.py"})
    assert r.status_code == 200, r.text
    assert (root / "diagnostics" / "final.py").exists()
    assert not (root / "diagnostics" / "temp.py").exists()
    # destino fora de extensão permitida
    assert client.post("/api/scripts/rename",
                       json={"path": "diagnostics/final.py", "to": "diagnostics/final.md"}).status_code == 422
