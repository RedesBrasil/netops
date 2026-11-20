"""Primeiro acesso (#setup) e escuta em todos os IPs (0.0.0.0).

- Na rede (bind fora do loopback), sem cofre e sem usuário: nada abre além do assistente; ele exige o
  token de uso único; concluir cria cofre + admin + idioma e faz o login; um segundo setup é recusado.
- Loopback sem token (dev/testes) continua aberto como antes.
- server.py aceita 0.0.0.0 (IPv4 + IPv6 com V6ONLY); supervisor e start.sh conferem pelo loopback.
"""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PW = "senha-do-admin-123"


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    from lib import vault
    monkeypatch.setattr(vault, "ARGON2_DEFAULTS", {"iterations": 1, "memory_cost": 1024, "lanes": 1, "length": 32})


@pytest.fixture()
def network_bind(monkeypatch):
    """Simula o console escutando em 0.0.0.0 (todos os IPs)."""
    import deps
    monkeypatch.setattr(deps.STATE, "bind_loopback", False)
    monkeypatch.setattr(deps.STATE, "bind_wildcard", True)
    deps._local_ips_cache.clear()


def _client():
    from app import create_app
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _token(env):
    from lib import setup_token
    return setup_token.issue(env)


def _body(token, **kw):
    return {"token": token, "language": "pt-BR", "name": "Admin", "email": "admin@empresa.com",
            "password": PW, **kw}


def test_loopback_sem_token_continua_aberto(env):
    import deps
    assert deps.STATE.bind_loopback is True
    c = _client()
    s = c.get("/api/auth/status").json()
    assert s["setup_required"] is False and s["authenticated"] is True
    assert c.get("/api/hosts").status_code == 200


def test_na_rede_sem_cofre_fica_fechado(env, network_bind):
    c = _client()
    s = c.get("/api/auth/status").json()
    assert s["setup_required"] is True and s["authenticated"] is False
    r = c.get("/api/hosts")
    assert r.status_code == 403 and r.json()["error"] == "setup_required"
    assert c.post("/api/auth/login", json={"email": "a@b.com", "master_password": "x"}).status_code == 403
    st = c.get("/api/setup/status").json()
    assert st["setup_required"] is True and st["token"] == "none"
    assert {x["code"] for x in st["languages"]} == {"en", "pt-BR"}


def test_websocket_recusado_no_primeiro_acesso(env, network_bind):
    from services import authz
    assert authz.principal_for_sid(None) is None


def test_token_errado_expirado_e_ausente(env, network_bind, monkeypatch):
    from lib import setup_token
    c = _client()
    assert c.post("/api/setup/complete", json=_body("nada")).status_code == 403
    tok = _token(env)
    assert c.post("/api/setup/complete", json=_body(tok + "x")).status_code == 403
    import time as _t
    real = _t.time
    monkeypatch.setattr(setup_token.time, "time", lambda: real() + 25 * 3600)
    r = c.post("/api/setup/complete", json=_body(tok))
    assert r.status_code == 403 and r.json()["error"] == "bad_token"


def test_concluir_cria_cofre_admin_idioma_e_loga(env, network_bind):
    import deps
    import yaml
    from lib import accessdb, setup_token
    c = _client()
    tok = _token(env)
    r = c.post("/api/setup/complete", json=_body(tok, language="en"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["auth_token"] and d["language"] == "en"
    assert deps.vault_initialized() and accessdb.has_users(deps.db_file())
    cfg = yaml.safe_load((env / "core/config/project-config.yaml").read_text())
    assert cfg["instance"]["language"] == "en"
    assert not setup_token.token_path(env).exists()          # token consumido
    c.headers["X-Netops-Session"] = d["auth_token"]
    assert c.get("/api/hosts").status_code == 200
    me = c.get("/api/auth/me").json()
    assert me.get("is_admin") or "admin" in (me.get("groups") or [])
    # sem sessão: login normal por e-mail e senha
    c2 = _client()
    assert c2.get("/api/auth/status").json()["setup_required"] is False
    r2 = c2.post("/api/auth/login", json={"email": "admin@empresa.com", "password": PW})
    assert r2.status_code == 200
    # segundo setup recusado, mesmo com token novo
    tok2 = setup_token.issue(env)
    r3 = _client().post("/api/setup/complete", json=_body(tok2, email="outro@empresa.com"))
    assert r3.status_code == 409


def test_senha_curta_e_idioma_invalido_nao_criam_nada(env, network_bind):
    import deps
    c = _client()
    tok = _token(env)
    assert c.post("/api/setup/complete", json=_body(tok, password="curta")).status_code == 422
    assert c.post("/api/setup/complete", json=_body(tok, language="xx")).status_code == 422
    assert not deps.vault_initialized()
    assert c.post("/api/setup/complete", json=_body(tok)).status_code == 200   # o token ainda vale


def test_token_no_disco_e_so_hash(env):
    from lib import setup_token
    tok = setup_token.issue(env)
    raw = setup_token.token_path(env).read_text()
    assert tok not in raw and "sha256" in raw
    assert oct(setup_token.token_path(env).stat().st_mode & 0o777) == "0o600"
    assert setup_token.check(env, tok) and not setup_token.check(env, "x" * 32)


def test_host_de_qualquer_ip_local_aceito_sem_login(env, network_bind, monkeypatch):
    import deps
    monkeypatch.setattr(deps, "local_ips", lambda: frozenset({"127.0.0.1", "::1", "10.9.9.9"}))
    assert deps.host_origin_allowed("10.9.9.9:8765")
    assert not deps.host_origin_allowed("evil.example.com")


def test_etapa_root_estado(env, network_bind, tmp_path, monkeypatch):
    from services import setup_svc
    from lib import setup_token
    ident = tmp_path / "ident"
    ident.mkdir()
    monkeypatch.setattr(setup_svc, "IDENT_DIR", ident)
    monkeypatch.setattr(setup_svc, "_slug", lambda: "opt-netops")
    assert setup_svc.finish_status()["state"] == "not_applicable"
    (ident / "opt-netops.setup-pending").write_text("x")
    st = setup_svc.request_finish()
    assert st["state"] == "pending" and setup_token.request_path(env).exists()
    assert "netops-setup-finish opt-netops" in st["command"]
    (ident / "opt-netops.setup-pending").unlink()
    (ident / "opt-netops.setup-done").write_text('{"state": "done", "pin": "ok", "localadmin": "ok"}')
    assert setup_svc.finish_status()["state"] == "done"


def test_rotas_de_setup_mapeadas():
    from services import authz
    assert authz.required_perm("GET", "/setup/status") is authz.ANY
    assert authz.required_perm("POST", "/setup/complete") is authz.ANY
    assert authz.required_perm("POST", "/setup/finish") == "server.admin"


# --------------------------------------------------------------------------- 0.0.0.0
def test_server_escuta_em_todos_os_ips():
    import server
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    socks = server._listen_sockets("0.0.0.0", port)
    try:
        fams = {s.family for s in socks}
        assert socket.AF_INET in fams
        assert socks[0].getsockname()[0] == "0.0.0.0"
        for s in socks:
            if s.family == socket.AF_INET6:
                assert s.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
    finally:
        for s in socks:
            s.close()
    assert server._listen_sockets("127.0.0.1", port) is None


def test_server_nao_recusa_mais_0000():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
    assert "0.0.0.0 recusado" not in src


def test_supervisor_confere_pelo_loopback(monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from update import supervisor
    seen = {}

    class _Child:
        pid = 1
        def poll(self):
            return 0          # sai na hora: só queremos ver a URL montada

    def fake_open(url, timeout=2):  # pragma: no cover - não chega aqui
        seen["url"] = url
        raise OSError

    monkeypatch.setattr(supervisor.urllib.request, "build_opener",
                        lambda *a: type("O", (), {"open": staticmethod(fake_open)})())
    supervisor.wait_ready(Path("/nonexistent"), _Child(), "n", "1", ["--host", "0.0.0.0", "--port", "1"], timeout=0.1)
    src = Path(supervisor.__file__).read_text()
    assert '"0.0.0.0": "127.0.0.1"' in src


def test_tls_san_sem_curinga():
    from services import tls_svc
    ips = tls_svc.local_ips("0.0.0.0")
    assert "0.0.0.0" not in ips and "127.0.0.1" in ips


def test_start_sh_padrao_todos_os_ips():
    src = (Path(__file__).resolve().parents[1] / "start.sh").read_text()
    assert 'HOST="${NETOPS_UI_HOST:-0.0.0.0}"' in src
    assert "hostname -I | awk '{print $1}'" not in src
    r = subprocess.run(["bash", "-n", str(Path(__file__).resolve().parents[1] / "start.sh")])
    assert r.returncode == 0
