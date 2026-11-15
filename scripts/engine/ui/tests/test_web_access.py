"""Firewall de acesso web: allowlist, IP real atrás de proxy, anti-spoofing, anti auto-bloqueio."""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

import deps
from app import create_app
from services import web_access_svc as wa


def _cfg(env, **section):
    p = env / "core" / "config" / "project-config.yaml"
    data = yaml.safe_load(p.read_text()) or {}
    data["web_access"] = section
    p.write_text(yaml.safe_dump(data))


def _scope(peer, xff=None, proto=None):
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    if proto:
        headers.append((b"x-forwarded-proto", proto.encode()))
    return {"type": "http", "client": (peer, 1234), "headers": headers, "scheme": "http"}


POL = wa.Policy(True, tuple(wa.parse_network(n) for n in ("10.0.0.0/8", "203.0.113.0/24", "2001:db8::/32")), (wa.parse_network("10.0.0.10"),))


@pytest.mark.parametrize("ip,ok", [
    ("10.1.2.3", True), ("203.0.113.9", True), ("203.0.114.1", False), ("2001:db8:1::5", True),
    ("2001:db9::1", False), ("198.51.100.7", False), ("100.64.0.1", False), ("127.0.0.1", True),
    ("::1", True), ("::ffff:10.1.1.1", True), ("::ffff:8.8.8.8", False),
])
def test_allowlist(ip, ok):
    assert wa.is_allowed(wa.parse_ip(ip), POL) is ok


def test_ilegivel_e_negado_e_desligado_libera():
    assert not wa.is_allowed(None, POL)
    assert wa.is_allowed(wa.parse_ip("8.8.8.8"), wa.Policy(False))


def test_proxy_confiavel_usa_xff():
    s = _scope("10.0.0.10", "198.51.100.7", "https")
    ip = wa.resolve_client(s, POL)
    assert str(ip) == "198.51.100.7" and s["client"][0] == "198.51.100.7" and s["scheme"] == "https"
    assert not wa.is_allowed(ip, POL)            # o proxy está em 10/8, mas o visitante não
    assert wa.is_allowed(wa.resolve_client(_scope("10.0.0.10", "10.0.0.1"), POL), POL)


def test_xff_forjado_pela_esquerda_nao_vale():
    # cliente de fora mandou "10.1.1.1"; o proxy anexou o IP real à direita
    ip = wa.resolve_client(_scope("10.0.0.10", "10.1.1.1, 198.51.100.7"), POL)
    assert str(ip) == "198.51.100.7"


def test_xff_de_origem_nao_confiavel_e_ignorado():
    s = _scope("198.51.100.7", "10.1.1.1")
    assert str(wa.resolve_client(s, POL)) == "198.51.100.7"
    assert s["client"][0] == "198.51.100.7" and s["scheme"] == "http"


def test_xff_lixo_e_negado_e_sem_xff_vale_o_socket():
    assert wa.resolve_client(_scope("10.0.0.10", "lixo"), POL) is None
    assert str(wa.resolve_client(_scope("10.0.0.10"), POL)) == "10.0.0.10"
    assert wa.resolve_client({"type": "http", "client": None, "headers": []}, POL) is None


def test_cadeia_de_proxies_confiaveis():
    pol = wa.Policy(True, POL.networks, (wa.parse_network("10.0.0.10"), wa.parse_network("10.0.100.0/24")))
    assert str(wa.resolve_client(_scope("10.0.0.10", "8.8.8.8, 10.0.100.7"), pol)) == "8.8.8.8"


def test_legado_desligado_sem_proxies_confia_no_esquema():
    s = _scope("172.16.0.9", "8.8.8.8", "https")
    wa.resolve_client(s, wa.Policy(False))
    assert s["scheme"] == "https"


def _client(env, peer, headers=None):
    return TestClient(create_app(), base_url="http://127.0.0.1", client=(peer, 5000), headers=headers or {})


def test_middleware_bloqueia_e_libera(env):
    _cfg(env, enabled=True, allowed_networks=["10.0.0.0/8"], trusted_proxies=["10.0.0.10"])
    assert _client(env, "10.5.5.5").get("/api/config/meta").status_code == 200
    r = _client(env, "8.8.8.8").get("/api/config/meta")
    assert r.status_code == 403 and "8.8.8.8" in r.text
    assert _client(env, "8.8.8.8").get("/").status_code == 403          # estáticos também
    # via proxy: mesmo com o socket em 10/8, vale o IP real do visitante
    assert _client(env, "10.0.0.10", {"X-Forwarded-For": "8.8.8.8"}).get("/api/config/meta").status_code == 403
    assert _client(env, "10.0.0.10", {"X-Forwarded-For": "10.9.9.9"}).get("/api/config/meta").status_code == 200
    assert any(e["ip"] == "8.8.8.8" for e in wa.recent_denied())


def test_websocket_negado(env):
    _cfg(env, enabled=True, allowed_networks=["10.0.0.0/8"])
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with _client(env, "8.8.8.8").websocket_connect("/api/terminal/ws"):
            pass


def test_desligado_libera_tudo_e_vale_na_hora(env):
    _cfg(env, enabled=False, allowed_networks=["10.0.0.0/8"])
    assert _client(env, "8.8.8.8").get("/api/config/meta").status_code == 200
    _cfg(env, enabled=True, allowed_networks=["10.0.0.0/8"])
    assert _client(env, "8.8.8.8").get("/api/config/meta").status_code == 403


def test_config_invalida_mantem_politica_anterior(env):
    _cfg(env, enabled=True, allowed_networks=["10.0.0.0/8"])
    assert _client(env, "8.8.8.8").get("/api/config/meta").status_code == 403
    (env / "core" / "config" / "project-config.yaml").write_text("web_access: [quebrado\n")
    assert _client(env, "8.8.8.8").get("/api/config/meta").status_code == 403


def test_put_config_valida_e_normaliza(env):
    client = _client(env, "127.0.0.1")
    r = client.get("/api/config")
    rev = r.json()["rev"]
    bad = client.put("/api/config", json={"web_access": {"allowed_networks": ["10.0.0.0/99"]}}, headers={"If-Match": rev})
    assert bad.status_code == 422
    ok = client.put("/api/config", json={"web_access": {"enabled": True, "allowed_networks": ["10.1.2.3", "2001:db8::/32", "127.0.0.1"]}},
                    headers={"If-Match": rev})
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["web_access"]["allowed_networks"] == ["10.1.2.3/32", "2001:db8::/32", "127.0.0.1/32"]


def test_put_config_impede_auto_bloqueio(env):
    c = _client(env, "8.8.8.8")
    rev = c.get("/api/config").json()["rev"]
    r = c.put("/api/config", json={"web_access": {"enabled": True, "allowed_networks": ["10.0.0.0/8"]}}, headers={"If-Match": rev})
    assert r.status_code == 422 and "bloqueado" in r.text
    empty = c.put("/api/config", json={"web_access": {"enabled": True, "allowed_networks": []}}, headers={"If-Match": rev})
    assert empty.status_code == 422
    ok = c.put("/api/config", json={"web_access": {"enabled": True, "allowed_networks": ["10.0.0.0/8", "8.8.8.0/24"]}}, headers={"If-Match": rev})
    assert ok.status_code == 200


def test_endpoint_status(env):
    _cfg(env, enabled=True, allowed_networks=["10.0.0.0/8"], trusted_proxies=["10.0.0.10"])
    d = _client(env, "10.0.0.10", {"X-Forwarded-For": "10.9.9.9"}).get("/api/web-access").json()
    assert d["client_ip"] == "10.9.9.9" and d["client_allowed"] and d["enabled"] and "192.168.0.0/16" in d["defaults"]
