"""Gerenciador de arquivos — /api/files/* (routers/files.py + services/files_svc.py).

Local: tudo num tmp (caminhos absolutos do tmp_path). Remoto: SFTP sobre a conexão do terminal de
host contra um servidor asyncssh local com subsistema SFTP (mesmo padrão de test_host_term.py).
"""
from __future__ import annotations

import io
import os
import time
import zipfile

import pytest

from test_host_term import PASSWORD, USER, _collect, _free_port, _LoopThread, _write_inventory


def _on():
    import deps
    deps.STATE.allowed_hosts = ("testserver", "127.0.0.1", "localhost")
    deps.STATE.enable_terminal = True
    deps.STATE.read_only = False


@pytest.fixture()
def fs(client, env, tmp_path, monkeypatch):
    _on()
    monkeypatch.delenv("NETOPS_UI_FILES", raising=False)
    root = tmp_path / "area"
    (root / "pasta" / "sub").mkdir(parents=True)
    (root / "pasta" / "a.txt").write_text("alfa\n")
    (root / "pasta" / "sub" / "b.bin").write_bytes(b"\x00\x01" * 1000)
    (root / "z.conf").write_text("x=1\n")
    return root


def test_gate_follows_terminal_flag(client, env, monkeypatch):
    import deps
    deps.STATE.enable_terminal = False
    r = client.get("/api/files/list", params={"path": "/"})
    assert r.status_code == 403 and r.json()["error"] == "files_disabled"
    _on()
    monkeypatch.setenv("NETOPS_UI_FILES", "0")
    assert client.get("/api/files/list", params={"path": "/"}).status_code == 403
    assert client.get("/api/config/meta").json()["files_enabled"] is False
    monkeypatch.delenv("NETOPS_UI_FILES")
    assert client.get("/api/config/meta").json()["files_enabled"] is True


def test_list_dirs_first_and_metadata(client, fs):
    r = client.get("/api/files/list", params={"path": str(fs)})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["path"] == str(fs) and d["parent"] == str(fs.parent)
    assert [e["name"] for e in d["entries"]] == ["pasta", "z.conf"]
    pasta, conf = d["entries"]
    assert pasta["is_dir"] and pasta["type"] == "dir" and pasta["perms"].startswith("d")
    assert conf["size"] == 4 and conf["owner"] and conf["mtime"] > 0
    assert client.get("/api/files/list", params={"path": "relativo"}).status_code == 400
    assert client.get("/api/files/list", params={"path": str(fs / "nao")}).status_code == 404
    assert client.get("/api/files/list", params={"path": "/"}).json()["parent"] is None


def test_symlink_to_dir_listed_as_dir_and_delete_keeps_target(client, fs):
    os.symlink(fs / "pasta", fs / "atalho")
    e = {x["name"]: x for x in client.get("/api/files/list", params={"path": str(fs)}).json()["entries"]}
    assert e["atalho"]["type"] == "link" and e["atalho"]["is_dir"] and e["atalho"]["target"] == str(fs / "pasta")
    r = client.post("/api/files/delete", json={"paths": [str(fs / "atalho")]})
    assert r.json()["ok"]
    assert not os.path.lexists(fs / "atalho") and (fs / "pasta" / "a.txt").exists()


def test_mkdir_touch_rename_chmod_delete(client, fs):
    assert client.post("/api/files/mkdir", json={"path": str(fs / "nova")}).status_code == 200
    assert client.post("/api/files/mkdir", json={"path": str(fs / "nova")}).status_code == 409
    assert client.post("/api/files/touch", json={"path": str(fs / "nova" / "x.txt")}).json()["ok"]
    r = client.post("/api/files/rename", json={"path": str(fs / "nova" / "x.txt"), "name": "y.txt"})
    assert r.json()["path"] == str(fs / "nova" / "y.txt")
    assert client.post("/api/files/rename", json={"path": str(fs / "nova"), "name": "../fora"}).status_code == 400
    r = client.post("/api/files/chmod", json={"path": str(fs / "nova" / "y.txt"), "mode": "600"})
    assert r.json()["perms"] == "-rw-------"
    r = client.post("/api/files/delete", json={"paths": [str(fs / "nova"), str(fs / "nao-existe")]})
    res = r.json()["results"]
    assert res[0]["ok"] and not res[1]["ok"] and res[1]["code"] == "not_found"
    assert not (fs / "nova").exists()
    log = (fs.parent / "runs" / "files" / "audit.log").read_text()
    assert "MKDIR" in log and "RENOMEAR" in log and "APAGAR" in log


def test_protected_paths_refused(client, fs):
    for p in ("/", "/etc", "/usr", "/etc/../usr"):
        r = client.post("/api/files/delete", json={"paths": [p]})
        assert r.json()["results"][0]["code"] == "denied", p
    r = client.post("/api/files/rename", json={"path": "/etc", "name": "etc2"})
    assert r.status_code == 403


def test_paste_copy_same_folder_makes_copy_name_and_move(client, fs):
    r = client.post("/api/files/paste", json={"op": "copy", "paths": [str(fs / "z.conf"), str(fs / "pasta")], "dest": str(fs)})
    assert r.json()["ok"], r.text
    names = sorted(os.listdir(fs))
    assert "z (cópia).conf" in names and "pasta (cópia)" in names
    assert (fs / "pasta (cópia)" / "sub" / "b.bin").read_bytes() == b"\x00\x01" * 1000
    r = client.post("/api/files/paste", json={"op": "move", "paths": [str(fs / "z (cópia).conf")], "dest": str(fs / "pasta")})
    assert r.json()["ok"] and (fs / "pasta" / "z (cópia).conf").exists()
    r = client.post("/api/files/paste", json={"op": "move", "paths": [str(fs / "pasta")], "dest": str(fs / "pasta" / "sub")})
    assert not r.json()["ok"] and "dentro dela mesma" in r.json()["results"][0]["error"]


def test_read_write_with_conflict_detection(client, fs):
    r = client.get("/api/files/read", params={"path": str(fs / "z.conf")}).json()
    assert r["content"] == "x=1\n" and not r["binary"]
    os.chmod(fs / "z.conf", 0o640)
    w = client.put("/api/files/write", json={"path": str(fs / "z.conf"), "content": "x=2\n", "mtime": r["mtime"], "size": r["size"]})
    assert w.status_code == 200, w.text
    assert (fs / "z.conf").read_text() == "x=2\n" and (os.stat(fs / "z.conf").st_mode & 0o777) == 0o640
    stale = client.put("/api/files/write", json={"path": str(fs / "z.conf"), "content": "x=3\n", "mtime": r["mtime"], "size": 999})
    assert stale.status_code == 409 and stale.json()["error"] == "changed"
    assert client.get("/api/files/read", params={"path": str(fs / "pasta" / "sub" / "b.bin")}).json()["binary"] is True
    c = client.put("/api/files/write", json={"path": str(fs / "novo.txt"), "content": "oi", "create": True})
    assert c.status_code == 200 and (fs / "novo.txt").read_text() == "oi"
    assert client.put("/api/files/write", json={"path": str(fs / "novo.txt"), "content": "x", "create": True}).status_code == 409


def test_chunked_upload_creates_parents_and_respects_overwrite(client, fs):
    target = str(fs / "up" / "deep" / "f.bin")
    q = {"path": target, "uid": "abcdefgh12"}
    assert client.put("/api/files/upload", params={**q, "offset": 0}, content=b"A" * 10).json() == {"done": False, "received": 10}
    bad = client.put("/api/files/upload", params={**q, "offset": 5}, content=b"B")
    assert bad.status_code == 400
    r = client.put("/api/files/upload", params={**q, "offset": 10, "final": 1}, content=b"B" * 5)
    assert r.json() == {"done": True, "size": 15}
    assert (fs / "up" / "deep" / "f.bin").read_bytes() == b"A" * 10 + b"B" * 5
    assert not [n for n in os.listdir(fs / "up" / "deep") if n.startswith(".netops-upload-")]
    again = client.put("/api/files/upload", params={**q, "offset": 0, "final": 1}, content=b"C")
    assert again.status_code == 409
    ok = client.put("/api/files/upload", params={**q, "offset": 0, "final": 1, "overwrite": 1}, content=b"C")
    assert ok.status_code == 200 and (fs / "up" / "deep" / "f.bin").read_bytes() == b"C"


def test_download_single_file_ticket_is_single_use_and_needs_no_session(client, fs, env):
    from fastapi.testclient import TestClient
    from app import create_app
    link = client.get("/api/files/download-link", params={"path": str(fs / "pasta" / "a.txt")}).json()
    assert link["zip"] is False and link["name"] == "a.txt"
    anon = TestClient(create_app(), base_url="http://127.0.0.1")       # sem X-Netops-Session
    r = anon.get(link["url"])
    assert r.status_code == 200 and r.content == b"alfa\n"
    assert "a.txt" in r.headers["content-disposition"]
    assert anon.get(link["url"]).status_code == 410                    # uso único


def test_download_zip_of_folder_and_files(client, fs):
    link = client.get("/api/files/download-link", params=[("path", str(fs / "pasta")), ("path", str(fs / "z.conf"))]).json()
    assert link["zip"] is True and link["name"] == "area.zip"
    r = client.get(link["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"pasta/", "pasta/a.txt", "pasta/sub/", "pasta/sub/b.bin", "z.conf"} <= names
    assert z.read("pasta/sub/b.bin") == b"\x00\x01" * 1000 and z.testzip() is None


def test_login_required_when_vault_initialized(client, fs, monkeypatch):
    import deps
    from fastapi.testclient import TestClient
    from app import create_app
    monkeypatch.setattr(deps, "auth_required", lambda: True)
    anon = TestClient(create_app(), base_url="http://127.0.0.1")
    assert anon.get("/api/files/list", params={"path": str(fs)}).status_code == 401
    assert anon.get("/api/files/download-link", params={"path": str(fs / "z.conf")}).status_code == 401
    assert anon.get("/api/files/dl/inventado").status_code == 410   # passa o login, mas o ticket não existe


# --------------------------------------------------------------------------- #
# Remoto: SFTP sobre o terminal de host
# --------------------------------------------------------------------------- #
@pytest.fixture()
def sftp_server(tmp_path):
    asyncssh = pytest.importorskip("asyncssh")
    key = asyncssh.generate_private_key("ssh-ed25519")
    port = _free_port()
    home = tmp_path / "remote-home"
    (home / "etcx").mkdir(parents=True)
    (home / "etcx" / "r.conf").write_text("remoto\n")

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True

        def password_auth_supported(self):
            return True

        def validate_password(self, username, password):
            return username == USER and password == PASSWORD

    async def handle(process):
        process.stdout.write("SHELL-PRONTO\r\n")
        await process.stdin.readline()
        process.exit(0)

    class SFTP(asyncssh.SFTPServer):
        def __init__(self, chan):
            super().__init__(chan, chroot=str(home))

    lt = _LoopThread()
    server = lt.run(asyncssh.create_server(Server, "127.0.0.1", port, server_host_keys=[key],
                                           process_factory=handle, encoding="utf-8", sftp_factory=SFTP))
    yield port, home
    server.close()
    lt.stop()


def test_remote_sftp_panel_over_terminal_connection(client, env, sftp_server):
    _on()
    port, home = sftp_server
    _write_inventory(env, ssh_port=port)
    # `with client`: HTTP e WebSocket no MESMO loop (como no uvicorn) — a conexão SSH do terminal
    # vive no loop do servidor e o SFTP reaproveita essa conexão.
    with client, client.websocket_connect("/api/term/host/1?method=ssh") as ws:
        _out, statuses = _collect(ws, "SHELL-PRONTO")
        tok = next(s["sftp"] for s in statuses if s.get("status") == "conectado")
        assert tok
        info = client.get("/api/files/info", params={"src": tok}).json()
        assert info["kind"] == "remote" and info["host_id"] == 1 and info["user"] == USER
        lst = client.get("/api/files/list", params={"src": tok, "path": "/etcx"}).json()
        assert [e["name"] for e in lst["entries"]] == ["r.conf"]
        # upload em 2 partes + leitura/edição + download por link
        q = {"src": tok, "path": "/novo/arq.txt", "uid": "remote1234"}
        assert client.put("/api/files/upload", params={**q, "offset": 0}, content=b"abc").status_code == 200
        assert client.put("/api/files/upload", params={**q, "offset": 3, "final": 1}, content=b"def").json()["done"]
        assert (home / "novo" / "arq.txt").read_bytes() == b"abcdef"
        r = client.get("/api/files/read", params={"src": tok, "path": "/etcx/r.conf"}).json()
        w = client.put("/api/files/write", json={"src": tok, "path": "/etcx/r.conf", "content": "editado\n",
                                                 "mtime": r["mtime"], "size": r["size"]})
        assert w.status_code == 200, w.text
        assert (home / "etcx" / "r.conf").read_text() == "editado\n"
        assert client.post("/api/files/paste", json={"src": tok, "op": "copy", "paths": ["/etcx"], "dest": "/"}).json()["ok"]
        assert (home / "etcx (cópia)" / "r.conf").read_text() == "editado\n"
        link = client.get("/api/files/download-link", params=[("src", tok), ("path", "/novo"), ("path", "/etcx")]).json()
        z = zipfile.ZipFile(io.BytesIO(client.get(link["url"]).content))
        assert z.read("novo/arq.txt") == b"abcdef" and z.read("etcx/r.conf") == b"editado\n"
        one = client.get("/api/files/download-link", params={"src": tok, "path": "/novo/arq.txt"}).json()
        assert client.get(one["url"]).content == b"abcdef"
        assert client.post("/api/files/mkdir", json={"src": tok, "path": "/novo/sub"}).status_code == 200
        assert client.post("/api/files/touch", json={"src": tok, "path": "/novo/sub/t.txt"}).status_code == 200
        assert client.post("/api/files/touch", json={"src": tok, "path": "/novo/sub/t.txt"}).status_code == 409
        assert client.post("/api/files/rename", json={"src": tok, "path": "/novo/sub/t.txt", "name": "u.txt"}).status_code == 200
        r = client.post("/api/files/chmod", json={"src": tok, "path": "/novo/sub/u.txt", "mode": "600"})
        assert r.status_code == 200 and r.json()["perms"] == "-rw-------"
        assert (home / "novo" / "sub" / "u.txt").exists()
        assert client.post("/api/files/delete", json={"src": tok, "paths": ["/novo"]}).json()["ok"]
        assert not (home / "novo").exists()
        ws.send_bytes(b"sair\r")
        _collect(ws, None, timeout=5)
    # terminal fechou: a sessão SFTP some junto
    deadline = time.time() + 5
    while time.time() < deadline:
        r = client.get("/api/files/list", params={"src": tok, "path": "/"})
        if r.status_code == 404:
            break
        time.sleep(0.1)
    assert r.status_code == 404 and "terminal" in r.json()["detail"]
