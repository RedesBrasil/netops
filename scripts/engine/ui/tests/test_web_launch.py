"""Acessar → Web: POST /api/hosts/<id>/web-launch e provedores lib/web_login (Proxmox, Zabbix).

Servidores falsos em thread (http.server) imitam o contrato do Proxmox (/api2/json/access/ticket) e do
Zabbix (index.php 302 + zbx_session). Garante: destino só do inventário, gate, cofre trancado, senha
NUNCA no handoff do Proxmox (só o ticket), erros de credencial/2FA e app sem provedor = só abrir a URL.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import pytest
import yaml

USER, PASSWORD, TICKET = "operador", "s3nh4-web-teste", "PVE:operador@pam:ABCDEF"


class _Fake(BaseHTTPRequestHandler):
    mode = "proxmox"          # proxmox | proxmox-2fa | zabbix | zabbix-mfa

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, b"ok")

    def do_POST(self):
        form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
        good = form.get("username", [""])[0].split("@")[0] == USER and form.get("password", [""])[0] == PASSWORD \
            or form.get("name", [""])[0] == USER and form.get("password", [""])[0] == PASSWORD
        if self.path == "/api2/json/access/ticket":
            if not good:
                return self._send(401, b"{}")
            ticket = "PVE:!tfa!{}" if self.mode == "proxmox-2fa" else TICKET
            data = {"ticket": ticket, **({"NeedTFA": 1} if self.mode == "proxmox-2fa" else {})}
            return self._send(200, json.dumps({"data": data}).encode(), {"Content-Type": "application/json"})
        if self.path == "/zabbix/index.php":
            if not good:
                return self._send(200, b"<div>Incorrect user name or password</div>")
            loc = "index_mfa.php" if self.mode == "zabbix-mfa" else "zabbix.php?action=dashboard.view"
            return self._send(302, headers={"Location": loc, "Set-Cookie": "zbx_session=abc; path=/"})
        self._send(404)


@pytest.fixture()
def fake():
    srv = HTTPServer(("127.0.0.1", 0), type("H", (_Fake,), {}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _setup(env, port, *, app, path="/", method="HTTP", vendor="LINUX", credential="CRED_T"):
    import deps
    deps.STATE.allowed_hosts = ("testserver", "127.0.0.1", "localhost")
    deps.STATE.enable_terminal = True
    deps.STATE.read_only = False
    host = {"id": 1, "hostname": "WEB-TESTE", "mgmt_ip": "127.0.0.1", "vendor": vendor,
            "access": {"method": "SSH", "port": 22},
            "extra_access": [{"method": method, "port": port, "app": app, "path": path}]}
    if credential:
        host["credential"] = credential
    deps.HOSTS_FILE.write_text(yaml.safe_dump({"version": 2, "next_host_id": 2, "groups": {}, "hosts": [host]}))
    deps.CREDS_FILE.write_text(yaml.safe_dump({"version": 1, "credentials": {
        "CRED_T": {"username": USER, "password": PASSWORD}}}))


def _launch(client, port, **body):
    return client.post("/api/hosts/1/web-launch", json={"method": "http", "port": port, **body})


def test_web_entries_app_by_vendor_and_dedupe():
    from lib.terminal_access import web_entries
    host = {"vendor": "PROXMOX", "credential": "C", "access": {"method": "SSH", "port": 22},
            "extra_access": [{"method": "HTTPS", "port": 8006}, {"method": "https", "port": 8006},
                             {"method": "HTTP", "port": 80, "app": "zabbix", "path": "/zabbix", "credential": "Z"}]}
    assert web_entries(host) == [
        {"method": "https", "port": 8006, "credential": "C", "app": "proxmox", "path": "/"},
        {"method": "http", "port": 80, "credential": "Z", "app": "zabbix", "path": "/zabbix"}]


def test_web_entries_vendor_zabbix_implies_app_and_path():
    from lib.terminal_access import web_entries
    host = {"vendor": "ZABBIX", "credential": "C", "access": {"method": "SSH", "port": 22},
            "extra_access": [{"method": "HTTP", "port": 80}]}
    assert web_entries(host) == [{"method": "http", "port": 80, "credential": "C", "app": "zabbix", "path": "/zabbix"}]


def test_proxmox_handoff_has_ticket_not_password(client, env, fake):
    _setup(env, fake.server_port, app="proxmox")
    r = _launch(client, fake.server_port)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "form_post" and body["action"].endswith("/api2/html/access/ticket")
    assert body["fields"] == {"username": f"{USER}@pam", "password": TICKET}
    assert PASSWORD not in r.text
    assert r.headers["cache-control"] == "no-store"
    assert body["then_url"] == f"http://127.0.0.1:{fake.server_port}/"


def test_proxmox_wrong_credential_and_2fa(client, env, fake):
    _setup(env, fake.server_port, app="proxmox")
    import deps
    deps.CREDS_FILE.write_text(yaml.safe_dump({"version": 1, "credentials": {"CRED_T": {"username": USER, "password": "errada"}}}))
    assert _launch(client, fake.server_port).status_code == 401
    deps.CREDS_FILE.write_text(yaml.safe_dump({"version": 1, "credentials": {"CRED_T": {"username": USER, "password": PASSWORD}}}))
    fake.RequestHandlerClass.mode = "proxmox-2fa"
    r = _launch(client, fake.server_port)
    assert r.status_code == 422 and r.json()["error"] == "unsupported"


def test_zabbix_handoff_and_errors(client, env, fake):
    fake.RequestHandlerClass.mode = "zabbix"
    _setup(env, fake.server_port, app="zabbix", path="/zabbix")
    r = _launch(client, fake.server_port)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == f"http://127.0.0.1:{fake.server_port}/zabbix/index.php"
    assert body["fields"]["name"] == USER and body["fields"]["password"] == PASSWORD   # exceção constitucional (§VII)
    import deps
    deps.CREDS_FILE.write_text(yaml.safe_dump({"version": 1, "credentials": {"CRED_T": {"username": USER, "password": "x"}}}))
    assert _launch(client, fake.server_port).status_code == 401
    deps.CREDS_FILE.write_text(yaml.safe_dump({"version": 1, "credentials": {"CRED_T": {"username": USER, "password": PASSWORD}}}))
    fake.RequestHandlerClass.mode = "zabbix-mfa"
    assert _launch(client, fake.server_port).json()["error"] == "unsupported"


def test_gate_target_and_fallbacks(client, env, fake):
    _setup(env, fake.server_port, app="")
    r = _launch(client, fake.server_port)                       # sem provedor = só abre a URL
    assert r.status_code == 200 and r.json()["mode"] == "open"
    assert r.json()["then_url"] == f"http://127.0.0.1:{fake.server_port}/"
    assert _launch(client, 9999).status_code == 400            # porta não cadastrada
    assert client.post("/api/hosts/99/web-launch", json={"method": "http"}).status_code == 404
    assert client.post("/api/hosts/1/web-launch", json={"method": "ssh", "port": 22}).status_code == 400  # ssh não é web
    _setup(env, fake.server_port, app="proxmox", credential=None)   # sem credencial = abre a URL
    assert _launch(client, fake.server_port).json()["mode"] == "open"
    import deps
    deps.STATE.read_only = True
    assert _launch(client, fake.server_port).status_code == 403
    deps.STATE.read_only = False
    deps.STATE.enable_terminal = False
    assert _launch(client, fake.server_port).status_code == 403


def test_unreachable_target(client, env):
    _setup(env, 1, app="proxmox")                                # porta 1: recusa conexão
    r = _launch(client, 1)
    assert r.status_code == 502 and r.json()["error"] == "unreachable"
