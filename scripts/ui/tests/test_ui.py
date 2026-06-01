"""Testes E2E do NetOps Console (verificação do plano). Tudo em tmp isolado."""
from __future__ import annotations

import os
import shutil
import stat

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


# --------------------------------------------------------------------------- #
# Segurança / bind / token
# --------------------------------------------------------------------------- #
def test_requires_token(env):
    from app import create_app
    c = TestClient(create_app(), base_url="http://127.0.0.1")
    assert c.get("/api/hosts").status_code == 401


def test_rejects_non_loopback_host(env):
    from app import create_app
    c = TestClient(create_app(), base_url="http://evil.example.com",
                   headers={"Authorization": "Bearer T"})
    assert c.get("/api/hosts").status_code == 403


def test_read_only_blocks_writes(env):
    import deps
    from app import create_app
    deps.STATE.read_only = True
    c = TestClient(create_app(), base_url="http://127.0.0.1", headers={"Authorization": "Bearer T"})
    assert c.get("/api/hosts").status_code == 200
    r = c.post("/api/hosts", json={"id": "x", "hostname": "h", "mgmt_ip": "1.1.1.1", "group": "mikrotik-dist"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Gate de login: senha-mestra do cofre trava o console inteiro
# --------------------------------------------------------------------------- #
def _bare_client():
    """Cliente só com o token de transporte (SEM sessão de login)."""
    from app import create_app
    return TestClient(create_app(), base_url="http://127.0.0.1", headers={"Authorization": "Bearer T"})


def test_no_login_required_without_vault(env):
    """Sem cofre inicializado: console abre só com o token (comportamento atual)."""
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
    rev = client.get("/api/hosts").json()["rev"]
    client.patch("/api/hosts/rt-dist-01", json={"site": "datacenter"}, headers={"If-Match": rev})
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
# Memória: patterns, lições append-only
# --------------------------------------------------------------------------- #
def test_patterns_route_not_shadowed(client):
    r = client.get("/api/memory/patterns")
    assert r.status_code == 200
    assert any(p["id"] == "mikrotik-api-port" for p in r.json()["patterns"])


def test_lessons_append_only(client):
    from app import create_app
    # cria uma lição
    r = client.post("/api/memory/lessons", json={"slug": "teste", "licao": "foo"})
    assert r.status_code == 201 and r.json()["file"].endswith("-teste.yaml")
    # NÃO existe rota DELETE de lição
    has_delete = any(
        getattr(route, "path", "") == "/api/memory/lessons/{file}" and "DELETE" in (route.methods or set())
        for route in create_app().routes
    )
    assert has_delete is False
    # transição de estado funciona
    f = r.json()["file"]
    rev = client.get(f"/api/memory/lessons/{f}").json()["rev"]
    r2 = client.patch(f"/api/memory/lessons/{f}/estado", json={"estado": "archived"}, headers={"If-Match": rev})
    assert r2.status_code == 200 and r2.json()["estado"] == "archived"


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
        with client.websocket_connect("/api/term?token=T"):
            pass
    assert ei.value.code == 4403


def test_terminal_requires_token(client, env):
    import deps
    _allow_testserver(); deps.STATE.enable_terminal = True
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/term"):           # sem token
            pass
    assert ei.value.code == 4403


def test_terminal_blocked_in_read_only(client, env):
    import deps
    _allow_testserver(); deps.STATE.enable_terminal = True; deps.STATE.read_only = True
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/term?token=T"):    # terminal nunca em read-only
            pass


def test_terminal_rejects_unlisted_host(client, env):
    import deps
    deps.STATE.enable_terminal = True                          # Host 'testserver' NÃO liberado
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/term?token=T"):
            pass
    assert ei.value.code == 4403


def test_terminal_requires_auth_session_when_vault_initialized(client, env):
    """Com cofre inicializado, o WS do terminal exige &auth (mesmo gate do /api)."""
    import deps
    _allow_testserver(); deps.STATE.enable_terminal = True
    _init_vault(env, master="m")
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/term?token=T"):       # token ok, sem &auth
            pass
    assert ei.value.code == 4403


@pytest.mark.skipif(not shutil.which("bash"), reason="bash ausente")
def test_terminal_echo_roundtrip(client, env):
    import deps
    _allow_testserver(); deps.STATE.enable_terminal = True
    with client.websocket_connect("/api/term?token=T") as ws:
        ws.send_bytes(b"echo NETOPS_TERM_OK\n")                # teclas (binário)
        buf = b""
        for _ in range(80):
            buf += ws.receive_bytes()                          # saída do PTY (binário)
            if b"NETOPS_TERM_OK" in buf:
                break
        assert b"NETOPS_TERM_OK" in buf


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
