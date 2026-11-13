"""Terminal web de HOST (SSH/Telnet) — /api/term/host/<id> (services/host_term_svc.py).

Gate de segurança, escolha do método pelo inventário e ponta a ponta contra servidores
SSH (asyncssh) e Telnet (telnetlib3) locais: login automático com a credencial do cofre e
login manual (sem credencial -> o terminal pede usuário/senha).
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import pytest
from starlette.websockets import WebSocketDisconnect

USER, PASSWORD = "operador", "s3nh4-teste"


def _allow():
    import deps
    deps.STATE.allowed_hosts = ("testserver", "127.0.0.1", "localhost")
    deps.STATE.enable_terminal = True
    deps.STATE.read_only = False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_inventory(env, *, ssh_port=None, telnet_port=None, credential="CRED_T", extra_api=False):
    import deps
    access = []
    if ssh_port:
        access.append({"method": "SSH", "port": ssh_port})
    if telnet_port:
        access.append({"method": "TELNET", "port": telnet_port})
    host = {"id": 1, "hostname": "RT-TESTE", "mgmt_ip": "127.0.0.1", "vendor": "LINUX", "access": access[0]}
    if credential:
        host["credential"] = credential
    extra = access[1:] + ([{"method": "API", "port": 8728}] if extra_api else [])
    if extra:
        host["extra_access"] = extra
    import yaml
    deps.HOSTS_FILE.write_text(yaml.safe_dump({"version": 2, "next_host_id": 2, "groups": {}, "hosts": [host]}))
    deps.CREDS_FILE.write_text(yaml.safe_dump({"version": 1, "credentials": {
        "CRED_T": {"username": USER, "password": PASSWORD}}}))


# --------------------------------------------------------------------------- #
# Servidores de teste em thread própria (loop separado do TestClient)
# --------------------------------------------------------------------------- #
class _LoopThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def run(self, awaitable):
        async def _await():
            return await awaitable
        return asyncio.run_coroutine_threadsafe(_await(), self.loop).result(10)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture()
def ssh_server(tmp_path):
    asyncssh = pytest.importorskip("asyncssh")
    key = asyncssh.generate_private_key("ssh-ed25519")
    port = _free_port()

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True

        def password_auth_supported(self):
            return True

        def validate_password(self, username, password):
            return username == USER and password == PASSWORD

    async def handle(process):
        size = process.get_terminal_size()
        process.stdout.write(f"BEM-VINDO {process.get_terminal_type()} {size[0]}x{size[1]}\r\n")
        line = await process.stdin.readline()
        process.stdout.write(f"ECO:{line.strip()}\r\n")
        process.exit(0)

    lt = _LoopThread()
    server = lt.run(asyncssh.create_server(Server, "127.0.0.1", port, server_host_keys=[key],
                                           process_factory=handle, encoding="utf-8"))
    yield port
    server.close()
    lt.stop()


@pytest.fixture()
def telnet_server():
    telnetlib3 = pytest.importorskip("telnetlib3")
    port = _free_port()

    async def shell(reader, writer):
        writer.write("login: ")
        user = (await reader.readline()).strip()
        writer.write("Password: ")
        pw = (await reader.readline()).strip()
        writer.write(f"\r\nLOGIN {'OK' if (user, pw) == (USER, PASSWORD) else 'FALHOU'} {user}\r\n")
        await writer.drain()
        await asyncio.sleep(0.3)
        writer.close()

    lt = _LoopThread()
    server = lt.run(telnetlib3.create_server(host="127.0.0.1", port=port, shell=shell, connect_maxwait=0.5))
    yield port
    server.close()
    lt.stop()


def _collect(ws, until: str | None, timeout=15.0) -> tuple[str, list[dict]]:
    """Lê quadros até `until` aparecer na saída (None = até a sessão fechar)."""
    out, statuses, deadline = "", [], time.time() + timeout
    while time.time() < deadline and (until is None or until not in out):
        try:
            msg = ws.receive()
        except WebSocketDisconnect:
            break
        if msg.get("type") == "websocket.close":
            break
        if msg.get("bytes") is not None:
            out += msg["bytes"].decode("utf-8", "replace")
        elif msg.get("text"):
            statuses.append(json.loads(msg["text"]))
    return out, statuses


# --------------------------------------------------------------------------- #
def test_access_entries_order_dedupe_and_filter():
    from services.host_term_svc import access_entries, pick_entry, TargetError
    host = {"access": {"method": "ssh", "port": 2222}, "credential": "A",
            "extra_access": [{"method": "api", "port": 8728}, {"method": "telnet"},
                             {"method": "ssh", "port": 2222}, {"method": "ssh", "credential": "B"}]}
    entries = access_entries(host)
    assert entries == [{"method": "ssh", "port": 2222, "credential": "A"},
                       {"method": "telnet", "port": 23, "credential": "A"},
                       {"method": "ssh", "port": 22, "credential": "B"}]
    assert pick_entry(entries, "ssh", None)["port"] == 2222          # sem porta: o 1º do método
    assert pick_entry(entries, "ssh", 22)["credential"] == "B"
    with pytest.raises(TargetError):
        pick_entry(entries, "telnet", 2323)                           # porta não cadastrada
    assert access_entries({"access": {"method": "api"}}) == []      # só API: sem terminal


def test_host_term_requires_terminal_enabled(client, env):
    import deps
    deps.STATE.allowed_hosts = ("testserver", "127.0.0.1", "localhost")
    deps.STATE.enable_terminal = False
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/api/term/host/1?method=ssh"):
            pass
    assert ei.value.code == 4403


def test_host_term_rejects_method_not_registered(client, env):
    _allow()
    _write_inventory(env, ssh_port=_free_port())
    with client.websocket_connect("/api/term/host/1?method=telnet") as ws:
        out, statuses = _collect(ws, None)
    assert "não está cadastrado" in out
    assert statuses[-1]["status"] == "erro"


def test_host_term_rejects_unknown_host(client, env):
    _allow()
    _write_inventory(env, ssh_port=_free_port())
    with client.websocket_connect("/api/term/host/99?method=ssh") as ws:
        out, _ = _collect(ws, "inventário")
    assert "não está no inventário" in out


def test_ssh_autologin_with_vault_credential(client, env, ssh_server):
    _allow()
    _write_inventory(env, ssh_port=ssh_server)
    with client.websocket_connect("/api/term/host/1?method=ssh&cols=100&rows=30") as ws:
        out, statuses = _collect(ws, "BEM-VINDO")
        assert "BEM-VINDO xterm-256color 100x30" in out             # PTY com tipo e tamanho
        assert "password" not in out.lower()                         # não pediu senha
        assert PASSWORD not in out                                   # senha nunca vai ao navegador
        assert any(s["status"] == "conectado" and s.get("user") == USER for s in statuses)
        ws.send_bytes(b"show version\r")
        out, _ = _collect(ws, "ECO:")
    assert "ECO:show version" in out
    logs = list((env / "runs").glob("*-terminal-1/session.log"))
    text = logs[0].read_text()
    assert "CONECTADO" in text and "FECHADO" in text and PASSWORD not in text


def test_ssh_manual_login_without_credential(client, env, ssh_server):
    _allow()
    _write_inventory(env, ssh_port=ssh_server, credential=None)
    with client.websocket_connect("/api/term/host/1?method=ssh") as ws:
        out, _ = _collect(ws, "login as:")
        assert "sem credencial" in out
        ws.send_bytes(USER.encode() + b"\r")
        out, _ = _collect(ws, "password:")
        ws.send_bytes(PASSWORD.encode() + b"\r")
        out, _ = _collect(ws, "BEM-VINDO")
        assert "BEM-VINDO" in out and PASSWORD not in out           # senha digitada sem eco


def test_ssh_wrong_stored_password_falls_back_to_prompt(client, env, ssh_server):
    import deps
    _allow()
    _write_inventory(env, ssh_port=ssh_server)
    deps.CREDS_FILE.write_text(f"version: 1\ncredentials:\n  CRED_T: {{username: {USER}, password: errada}}\n")
    with client.websocket_connect("/api/term/host/1?method=ssh") as ws:
        out, _ = _collect(ws, "login as:")
        assert "Acesso negado" in out


def test_telnet_autologin_when_host_has_two_methods(client, env, ssh_server, telnet_server):
    _allow()
    _write_inventory(env, ssh_port=ssh_server, telnet_port=telnet_server, extra_api=True)
    with client.websocket_connect(f"/api/term/host/1?method=telnet&port={telnet_server}") as ws:
        out, statuses = _collect(ws, "LOGIN ")
    assert f"LOGIN OK {USER}" in out
    assert PASSWORD not in out
    assert any(s["status"] == "conectado" for s in statuses)
