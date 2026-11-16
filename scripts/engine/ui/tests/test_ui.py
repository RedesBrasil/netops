"""Testes E2E do NetOps Console (verificação do plano). Tudo em tmp isolado."""
from __future__ import annotations

import json
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


def test_reverse_proxy_any_domain_when_login_active(env, monkeypatch):
    """Com login ativo, qualquer Host/Origin (domínio do proxy) passa; o gate é a sessão."""
    import deps
    from app import create_app
    monkeypatch.setattr(deps, "auth_required", lambda: True)
    c = TestClient(create_app(), base_url="https://netops.exemplo.com.br")
    assert c.get("/api/config/meta").status_code == 200
    assert c.get("/api/hosts").status_code == 401            # pede autenticação, não forbidden_host
    r = c.post("/api/auth/login", json={"password": "x"}, headers={"Origin": "https://netops.exemplo.com.br"})
    assert r.status_code != 403


def test_no_login_keeps_strict_host_and_allowlist(env, monkeypatch):
    """Sem login o console está aberto: Host estranho segue barrado, salvo NETOPS_UI_ALLOWED_HOSTS."""
    from app import create_app
    c = TestClient(create_app(), base_url="https://netops.exemplo.com.br")
    r = c.get("/api/hosts")
    assert r.status_code == 403 and r.json()["error"] == "forbidden_host"
    monkeypatch.setenv("NETOPS_UI_ALLOWED_HOSTS", ".exemplo.com.br")
    assert c.get("/api/hosts").status_code == 200
    ok = {"Origin": "https://netops.exemplo.com.br"}
    assert c.post("/api/hosts", json={}, headers=ok).status_code != 403        # same-origin
    assert c.post("/api/hosts", json={}, headers={"Origin": "https://evil.invalid"}).status_code == 403


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
    r = client.post("/api/hosts", json={"hostname": "N", "mgmt_ip": "10.0.0.9",
                                        "group": "mikrotik-dist"}, headers={"If-Match": rev})
    assert r.status_code == 201, r.text
    assert type(r.json()["id"]) is int
    h = client.get(f"/api/hosts/{r.json()['id']}").json()
    assert h["explicit"].get("vendor") is None          # não materializou herança
    assert h["effective"]["vendor"] == "mikrotik"        # herdou do grupo
    assert h["effective"]["access"]["method"] == "ssh"


def test_pydantic_rejects_bad_vendor(client):
    r = client.post("/api/hosts", json={"hostname": "h", "mgmt_ip": "1.1.1.1", "vendor": "juniper"})
    assert r.status_code == 422


def test_delta_validation_missing_credential(client):
    """Host sem credential resolvível => 422; mas NÃO barra por nulls pré-existentes."""
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/hosts", json={"hostname": "h", "mgmt_ip": "1.1.1.1",
                                        "vendor": "linux"}, headers={"If-Match": rev})
    assert r.status_code == 422
    locs = {e["loc"] for e in r.json()["errors"]}
    assert any(loc.startswith("hosts/") and loc.endswith("/credential") for loc in locs)
    # e o erro pré-existente (model null nos hosts do seed) NÃO aparece como novo:
    assert not any("model" in loc for loc in locs)


def test_optimistic_concurrency_conflict(client):
    r = client.post("/api/hosts", json={"hostname": "h", "mgmt_ip": "1.1.1.1",
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
    hid = _seed_host(client, "rt-dist-03")
    rev = client.get("/api/hosts").json()["rev"]
    r = client.delete(f"/api/hosts/{hid}", headers={"If-Match": rev})
    assert r.status_code == 200
    assert hid not in [h["id"] for h in client.get("/api/hosts").json()["hosts"]]


def test_interrupted_identity_migration_returns_recovery_action(client, env):
    path = env / "network/.host-id-migration.json"
    before = (env / "network/hosts.yaml").read_bytes()
    path.write_text(json.dumps({"version": 1, "status": "applying"}))
    response = client.get("/api/hosts")
    assert response.status_code == 503
    assert response.json()["error"] == "migration_incomplete"
    assert "recover" in response.json()["action"]
    response = client.post("/api/hosts", json={
        "hostname": "Fixture", "mgmt_ip": "192.0.2.1", "group": "linux-servers",
    })
    assert response.status_code == 503
    assert (env / "network/hosts.yaml").read_bytes() == before
    path.write_text(json.dumps({"version": 1, "status": "rolled_back"}))
    assert client.get("/api/hosts").status_code == 200


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
    token = data["credentials"]["CRED_X"]["password"]
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
# Conta do agente (/login pela aba) — gating + parsing do fluxo OAuth, SEM logar de verdade.
# --------------------------------------------------------------------------- #
def test_claude_auth_endpoints_gated_by_flag(client, env):
    import deps
    assert client.get("/api/claude/auth/status").status_code == 403
    assert client.post("/api/claude/auth/logout").status_code == 403
    deps.STATE.enable_claude = True
    r = client.get("/api/claude/auth/status")
    assert r.status_code == 200 and "loggedIn" in r.json()


def test_claude_auth_status_never_leaks_secrets(client, env):
    """O estado do login é metadado — token/refresh nunca podem sair pela API."""
    import deps
    deps.STATE.enable_claude = True
    body = client.get("/api/claude/auth/status").text.lower()
    for leak in ("accesstoken", "refreshtoken", "sk-ant"):
        assert leak not in body


def test_claude_login_ws_blocked_in_read_only(client, env):
    import deps
    _allow_testserver(); deps.STATE.enable_claude = True; deps.STATE.read_only = True
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/claude/login"):
            pass
    assert ei.value.code == 4403


def test_claude_login_store_points_at_server_home(monkeypatch, tmp_path):
    """O login grava no HOME do SERVIDOR — o mesmo store que o agente lê. É o ponto todo:
    logar por outro usuário (terminal web) não vale para a aba."""
    from services import claude_auth
    monkeypatch.setenv("HOME", str(tmp_path))
    store = claude_auth._store()
    assert store["credentials"] == str(tmp_path / ".claude" / ".credentials.json")


def test_claude_login_parses_url_and_prompt():
    """A saída real do `claude auth login` traz a URL num hyperlink OSC-8 + a URL em texto.
    O parser tem de achar a URL e o pedido do código depois de limpar o ANSI."""
    from services import claude_auth
    raw = ("Opening browser to sign in\r\n"
           "If the browser didn't open, visit: \x1b]8;;https://claude.com/cai/oauth/authorize?code=true\x07"
           "https://claude.com/cai/oauth/authorize?code=true\x1b]8;;\x07\r\n"
           "Paste code here if prompted > ")
    clean = claude_auth._clean(raw)
    assert "\x1b" not in clean and clean.count("https://") == 1
    assert claude_auth._URL.search(clean).group(0) == "https://claude.com/cai/oauth/authorize?code=true"
    assert claude_auth._ASK_CODE.search(clean)


def _drive_login(chunks, code=None):
    """Roda o tradutor do login sobre pedaços de saída do CLI e devolve os eventos emitidos."""
    import asyncio
    from services import claude_auth

    sent = []

    class _FakeWS:
        async def send_text(self, s):
            sent.append(json.loads(s))

    async def go():
        s = claude_auth.ClaudeLoginSession(_FakeWS())
        if code:
            s._code, s._pending_code = code, True
        for c in chunks:
            await s._translate(c)

    asyncio.run(go())
    return sent


def test_claude_login_rearms_after_invalid_code():
    """Código mal colado: o CLI diz "Invalid code" e SEGUE esperando, sem reimprimir o prompt.
    Sem re-armar, a UI travaria num fluxo ainda vivo."""
    evs = _drive_login(["Invalid code. Please make sure the full code was copied.\r\n"], code="XYZ")
    assert [e["type"] for e in evs] == ["log", "awaiting_code"]


def test_claude_login_never_echoes_the_pasted_code():
    """O código OAuth é credencial: nem eco do PTY, nem log — nunca sai pela conexão."""
    evs = _drive_login(["> SEGREDO-123\r\nLogin failed: Request failed with status code 400\r\n"],
                       code="SEGREDO-123")
    assert all("SEGREDO-123" not in json.dumps(e) for e in evs), evs


# --------------------------------------------------------------------------- #
# Topologia
# --------------------------------------------------------------------------- #
def test_topology_dangling_and_render(client, env):
    import yaml
    path = env / "network/topology.yaml"
    document = yaml.safe_load(path.read_text())
    document["links"].append({"a": {"host": 900}, "b": {"host": 901}})
    path.write_text(yaml.safe_dump(document))
    t = client.get("/api/topology").json()
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
    body = {"hostname": hid.upper().replace("-", "_"), "mgmt_ip": "10.99.0.9",
            "vendor": "linux", "credential": "cred_seed", "access": {"method": "ssh", "port": 22}}
    body.update(fields)
    r = client.post("/api/hosts", json=body, headers={"If-Match": rev})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_link(client, ah, bh=1, ap="e1", bp="e2"):
    rev = client.get("/api/topology").json()["rev"]
    r = client.post("/api/topology/links",
                    json={"a": {"host": ah, "port": ap}, "b": {"host": bh, "port": bp}},
                    headers={"If-Match": rev})
    assert r.status_code == 200, r.text


def test_host_references_lists_topology(client):
    hid = _seed_host(client, "t-ref")
    _seed_link(client, hid)
    refs = client.get(f"/api/hosts/{hid}/references").json()
    assert refs["count"] >= 1
    assert any(x["kind"] == "topology-link" for x in refs["references"])


def test_edit_hostname_preserves_host_id_and_topology(client, env):
    import yaml
    hid = _seed_host(client, "t-old")
    _seed_link(client, hid)
    rev = client.get("/api/hosts").json()["rev"]
    r = client.patch(f"/api/hosts/{hid}", json={"hostname": "t-new"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == hid
    hosts = _hosts_yaml(env)["hosts"]
    assert next(host for host in hosts if host["id"] == hid)["hostname"] == "T-NEW"
    topo = yaml.safe_load((env / "network" / "topology.yaml").read_text())
    ends = [e.get("host") for lk in topo["links"] for e in (lk.get("a"), lk.get("b")) if e]
    assert hid in ends and all(type(value) is int for value in ends)


def test_edit_host_preserves_comments(client, env):
    hid = _seed_host(client, "t-cmt")
    rev = client.get("/api/hosts").json()["rev"]
    assert client.patch(f"/api/hosts/{hid}", json={"hostname": "t-cmt2"}, headers={"If-Match": rev}).status_code == 200
    text = (env / "network" / "hosts.yaml").read_text()
    assert text.startswith("# NetOps")          # cabeçalho preservado
    assert "API RouterOS" in text               # comentário inline (em outro bloco) intacto


def test_host_id_cannot_be_reassigned(client):
    hid = _seed_host(client, "t-a")
    peer = _seed_host(client, "t-b", mgmt_ip="10.99.0.10")
    rev = client.get("/api/hosts").json()["rev"]
    r = client.patch(f"/api/hosts/{hid}", json={"id": peer}, headers={"If-Match": rev})
    assert r.status_code == 422


def test_edit_host_conflict_409(client):
    hid = _seed_host(client, "t-c")
    r = client.patch(f"/api/hosts/{hid}", json={"hostname": "t-c2"}, headers={"If-Match": "stale"})
    assert r.status_code == 409


def test_create_host_rejects_user_supplied_id(client):
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/hosts", json={"id": 42, "hostname": "h", "mgmt_ip": "192.0.2.1", "group": "linux-servers"}, headers={"If-Match": rev})
    assert r.status_code == 422


def test_rename_group_cascades_hosts(client, env):
    grev = client.get("/api/hosts").json()["rev"]
    assert client.post("/api/groups", json={"name": "grp-x", "vendor": "linux", "role": "server",
                                            "credential": "cred_seed", "access": {"method": "ssh", "port": 22}},
                       headers={"If-Match": grev}).status_code == 201
    h1 = _seed_host(client, "t-g1", group="grp-x")
    h2 = _seed_host(client, "t-g2", group="grp-x", mgmt_ip="10.99.0.10")
    rev = client.get("/api/hosts").json()["rev"]
    r = client.post("/api/groups/grp-x/rename", json={"to": "grp-y"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text
    data = _hosts_yaml(env)
    assert "GRP-Y" in data["groups"] and "GRP-X" not in data["groups"]
    hosts = {host["id"]: host for host in data["hosts"]}
    assert hosts[h1]["group"] == "GRP-Y"
    assert hosts[h2]["group"] == "GRP-Y"


def test_rename_credential_cascades_and_keeps_mode(client, env):
    import yaml
    client.post("/api/credentials", json={"name": "cred_t", "username": "admin"})
    hid = _seed_host(client, "t-cred", credential="cred_t")
    refs = client.get("/api/credentials/cred_t/references").json()
    assert refs["count"] >= 1
    rev = client.get("/api/credentials").json()["rev"]
    r = client.post("/api/credentials/cred_t/rename", json={"to": "cred_t2"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text
    creds = yaml.safe_load((env / "network" / "credentials.yaml").read_text())["credentials"]
    assert "CRED_T2" in creds and "CRED_T" not in creds and "cred_t" not in creds
    assert next(host for host in _hosts_yaml(env)["hosts"] if host["id"] == hid)["credential"] == "CRED_T2"
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
    token = creds["CRED_Y"]["password"]
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
    (root / "access" / "session.py").write_text(
        '#!/usr/bin/env python3\n"""Acesso a equipamentos (SSH/Telnet)."""\n', encoding="utf-8")
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
    assert "access/session.py" in paths and "access/backup.sh" in paths
    assert not any(p.endswith(".md") for p in paths)
    assert not any(p.startswith("_TEMPLATE") for p in paths)
    ssh = next(s for s in data["scripts"] if s["path"] == "access/session.py")
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


def test_auth_sessions_never_touch_real_install_and_survive_restart(env):
    """Regressão 11/11/2026: a suíte gravava no arquivo de logins REAL. Agora as sessões vivem no
    banco de acesso (SQLite) — que tem que seguir o DATA_ROOT — e sobrevivem a um 'restart'."""
    import json
    import deps
    assert str(deps.db_file()).startswith(str(env))
    sid = deps.create_auth_session(3600)
    deps.load_auth_sessions()                     # arranque: não perde nada
    assert deps.auth_session_valid(sid)
    other = deps.create_auth_session(3600)
    assert deps.auth_session_valid(sid) and deps.auth_session_valid(other)
    deps.drop_auth_session(sid)
    assert not deps.auth_session_valid(sid) and deps.auth_session_valid(other)


def test_legacy_json_sessions_are_imported_once(env):
    """Atualização: quem estava logado (JSON antigo) continua logado, como o admin legado."""
    import hashlib
    import json
    import time
    import deps
    sid = "ab" * 24
    f = deps._auth_sessions_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({hashlib.sha256(sid.encode()).hexdigest(): {"exp": time.time() + 600}}))
    deps.load_auth_sessions()
    assert deps.auth_session_user(sid) == "admin"
    deps.drop_auth_session(sid)
    deps.load_auth_sessions()                     # 2ª vez não reimporta
    assert deps.auth_session_user(sid) is None

# --------------------------------------------------------------------------- #
# Memória: MEMORY.md + AGENTS.md + notas memory/*.md
# --------------------------------------------------------------------------- #
def test_memory_files_lists_index_agents_and_notes(client, env):
    (env / "AGENTS.md").write_text("# NetOps\nregras\n", encoding="utf-8")
    (env / "memory" / "nota-x.md").write_text("---\nname: Nota X\n---\ncorpo\n", encoding="utf-8")
    (env / "memory" / "MEMORY.md.bak.20260101").write_text("velho", encoding="utf-8")
    files = client.get("/api/memory/files").json()["files"]
    names = [f["name"] for f in files]
    assert names[:2] == ["MEMORY.md", "AGENTS.md"]
    assert "nota-x.md" in names and not any(".bak" in n for n in names)
    assert next(f for f in files if f["name"] == "nota-x.md")["title"] == "Nota X"


def test_memory_file_roundtrip_agents_md(client, env):
    (env / "AGENTS.md").write_text("# NetOps\n", encoding="utf-8")
    g = client.get("/api/memory/file", params={"name": "AGENTS.md"})
    assert g.status_code == 200
    w = client.put("/api/memory/file", json={"name": "AGENTS.md", "text": "# NetOps\nnovo\n"},
                   headers={"If-Match": g.json()["rev"]})
    assert w.status_code == 200
    assert (env / "AGENTS.md").read_text(encoding="utf-8") == "# NetOps\nnovo\n"
    stale = client.put("/api/memory/file", json={"name": "AGENTS.md", "text": "x"},
                       headers={"If-Match": g.json()["rev"]})
    assert stale.status_code == 409


def test_memory_file_blocks_traversal(client, env):
    for bad in ("../AGENTS.md", "../network/hosts.yaml", "x.yaml", "sub/n.md"):
        assert client.get("/api/memory/file", params={"name": bad}).status_code == 422, bad
    assert client.get("/api/memory/file", params={"name": "nao-existe.md"}).status_code == 404


def test_scripts_lists_skills(client, env, monkeypatch):
    root = _tools_tree(env, monkeypatch)
    (root / "docs").mkdir()
    (root / "docs" / "SKILL.md").write_text("---\nname: Docs\ndescription: Gera docs.\n---\n", encoding="utf-8")
    (root / "zabbix").mkdir()
    (root / "zabbix" / "a.py").write_text('"""x"""\n', encoding="utf-8")
    skills = {k["id"]: k for k in client.get("/api/scripts").json()["skills"]}
    assert set(skills) == {"access", "docs", "zabbix"}           # _TEMPLATE fora
    assert skills["access"]["scripts"] == 2 and skills["access"]["doc"] == "access/SKILL.md"
    assert skills["docs"]["name"] == "Docs" and skills["docs"]["scripts"] == 0   # skill só de doc
    assert skills["zabbix"]["doc"] is None
    # cria o SKILL.md que falta; .md comum continua barrado
    assert client.post("/api/scripts", json={"path": "zabbix/SKILL.md", "text": "# Z\n"}).status_code == 201
    assert client.post("/api/scripts", json={"path": "SKILL.md", "text": "x"}).status_code == 422


def test_cadastro_host_grava_maiusculas_exceto_site_e_notes(client, env):
    """Padrão: nome, modelo, vendor, role, método, grupo e credencial em MAIÚSCULAS; site/notes livres."""
    client.post("/api/credentials", json={"name": "cred_up", "username": "admin"})
    client.post("/api/groups", json={"name": "grp-up", "vendor": "linux"})
    r = client.post("/api/hosts", json={
        "hostname": "rt-up", "mgmt_ip": "10.9.9.9", "group": "grp-up", "vendor": "mikrotik", "role": "core",
        "model": "ccr1036", "site": "Matriz", "notes": "texto livre", "credential": "cred_up",
        "access": {"method": "ssh", "port": 22}})
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    h = next(x for x in _hosts_yaml(env)["hosts"] if x["id"] == hid)
    assert (h["hostname"], h["model"], h["vendor"], h["role"], h["group"], h["credential"]) == (
        "RT-UP", "CCR1036", "MIKROTIK", "CORE", "GRP-UP", "CRED_UP")
    assert h["access"]["method"] == "SSH"
    assert h["site"] == "Matriz" and h["notes"] == "texto livre"
    assert client.patch(f"/api/hosts/{hid}", json={"model": "x1", "role": "access"}).status_code == 200
    h = next(x for x in _hosts_yaml(env)["hosts"] if x["id"] == hid)
    assert h["model"] == "X1" and h["role"] == "ACCESS"
