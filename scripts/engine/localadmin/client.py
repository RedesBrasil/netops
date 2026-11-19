"""Cliente do serviço netops-localadmin (só stdlib). Usado por session.py, cli.py e pelo console."""
from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path

import common
from common import LocalAdminError


def _connect(root) -> socket.socket:
    path = common.socket_path(root)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(path))
    except OSError:
        s.close()
        raise LocalAdminError("backend_unavailable")
    return s


def _lines(s: socket.socket):
    buf = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line:
                yield json.loads(line)


def request(root, req: dict):
    """Gera as respostas do serviço. Erro estruturado vira LocalAdminError."""
    s = _connect(root)
    try:
        s.sendall(json.dumps(req).encode() + b"\n")
        for msg in _lines(s):
            if msg.get("type") == "error":
                raise LocalAdminError(msg.get("code", "backend_unavailable"), msg.get("detail", ""))
            yield msg
    finally:
        s.close()


def status(root) -> dict:
    try:
        for msg in request(root, {"op": "status"}):
            if msg.get("type") == "end":
                return msg
    except LocalAdminError as e:
        return {"ready": False, "code": e.code, "detail": e.detail}
    return {"ready": False, "code": "backend_unavailable", "detail": common.ERRORS["backend_unavailable"]}


def run(root, *, argv=None, script=None, cwd="/root", timeout=900, user=None, scope="",
        operation_id=None, on_output=None) -> dict:
    """Executa como root no host Local. Devolve o `end` (exit_code, effective_uid, timeout...)."""
    req = {"op": "exec", "argv": argv, "script": script, "cwd": cwd, "timeout": timeout,
           "user": user if user is not None else os.environ.get("NETOPS_USER", ""),
           "scope": scope, "operation_id": operation_id}
    end = None
    for msg in request(root, req):
        if msg.get("type") == "out" and on_output:
            on_output(base64.b64decode(msg["data"]))
        elif msg.get("type") == "end":
            end = msg
    if end is None:
        raise LocalAdminError("backend_unavailable", "o serviço encerrou sem resultado")
    if end.get("effective_uid") != 0:
        raise LocalAdminError("verification_failed")
    return end


def open_sftp(root, user: str) -> socket.socket:
    """Canal ligado a um sftp-server ROOT (modo root dos Arquivos). Só o console usa."""
    s = _connect(root)
    try:
        s.sendall(json.dumps({"op": "sftp", "user": user, "client": "console"}).encode() + b"\n")
        msg, fds, _flags, _addr = socket.recv_fds(s, 65536, 1)
        reply = json.loads(msg.split(b"\n", 1)[0] or b"{}")
        if reply.get("type") == "error":
            for fd in fds:
                os.close(fd)
            raise LocalAdminError(reply.get("code", "backend_unavailable"), reply.get("detail", ""))
        if not fds or reply.get("effective_uid") != 0:
            for fd in fds:
                os.close(fd)
            raise LocalAdminError("verification_failed")
        return socket.socket(fileno=fds[0])
    finally:
        s.close()
