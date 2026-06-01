#!/usr/bin/env python3
"""Terminal web (PTY) — endpoint WebSocket. ⚠ EXECUÇÃO DE COMANDO ARBITRÁRIO.

Cada conexão abre um shell (PTY) que roda COMO O USUÁRIO DO SERVIDOR, em NETOPS_ROOT.
Isso rompe a fronteira "a UI é só CRUD" — por isso só liga com `--enable-terminal`
(default DESLIGADO) e nunca em `--read-only`.

A autenticação do handshake é feita À MÃO aqui porque o middleware http do app
(token + Host + Origin) NÃO roda em conexões WebSocket no Starlette. Replicamos as
mesmas defesas: token de sessão, Host loopback/IP-de-bind (anti DNS-rebinding) e
Origin (anti Cross-Site WebSocket Hijacking).

Protocolo de quadros (xterm.js <-> PTY):
  cliente -> servidor: BINÁRIO = teclas (escreve no PTY); TEXTO JSON {"resize":[cols,rows]}
  servidor -> cliente: BINÁRIO = saída do PTY
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import termios
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import deps

router = APIRouter()

SHELL = os.environ.get("SHELL", "/bin/bash")
SHELL_ARGV = [SHELL, "-l"]
MAX_DIM = 1000


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    rows = max(1, min(MAX_DIM, int(rows)))
    cols = max(1, min(MAX_DIM, int(cols)))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _ws_authorized(ws: WebSocket) -> bool:
    """Mesmas defesas do middleware http (que NÃO cobre WebSocket)."""
    if not deps.STATE.enable_terminal or deps.STATE.read_only:
        return False
    host = ws.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0].strip("[]")
    if hostname not in deps.STATE.allowed_hosts:
        return False
    origin = ws.headers.get("origin")
    if origin:
        try:
            if (urlparse(origin).hostname or "") not in deps.STATE.allowed_hosts:
                return False
        except ValueError:
            return False
    return deps.token_matches(ws.query_params.get("token"))


@router.websocket("/term")
async def term(ws: WebSocket):
    if not _ws_authorized(ws):
        await ws.close(code=4403)
        return
    await ws.accept()

    # Pré-monta env/argv/cwd NO PAI: assim o filho do forkpty só faz chdir+execvpe
    # (ambos async-signal-safe), evitando alocação num fork de processo multi-thread.
    child_env = dict(os.environ)
    child_env["TERM"] = "xterm-256color"
    cwd = str(deps.NETOPS_ROOT)

    pid, fd = pty.fork()
    if pid == 0:
        # filho: vira o shell de login.
        try:
            os.chdir(cwd)
        except OSError:
            pass
        try:
            os.execvpe(SHELL, SHELL_ARGV, child_env)
        except OSError:
            pass
        os._exit(127)  # só alcançado se o exec falhar

    # pai: ponte entre o PTY (fd mestre) e o WebSocket.
    loop = asyncio.get_event_loop()
    os.set_blocking(fd, False)
    out_q: asyncio.Queue = asyncio.Queue()

    def _on_readable():
        try:
            data = os.read(fd, 65536)
        except (BlockingIOError, OSError):
            return
        out_q.put_nowait(data or None)  # b"" (EOF) -> None encerra

    loop.add_reader(fd, _on_readable)

    async def pump_out():
        while True:
            data = await out_q.get()
            if data is None:
                return
            await ws.send_bytes(data)

    async def pump_in():
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                data = msg.get("bytes")
                if data is not None:
                    os.write(fd, data)
                    continue
                text = msg.get("text")
                if not text:
                    continue
                try:
                    ctrl = json.loads(text)
                except ValueError:
                    os.write(fd, text.encode("utf-8"))
                    continue
                if isinstance(ctrl, dict) and isinstance(ctrl.get("resize"), list):
                    cols, rows = ctrl["resize"][0], ctrl["resize"][1]
                    _set_winsize(fd, rows, cols)
        except WebSocketDisconnect:
            return

    t_out = asyncio.create_task(pump_out())
    t_in = asyncio.create_task(pump_in())
    try:
        _done, pending = await asyncio.wait({t_out, t_in}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        try:
            loop.remove_reader(fd)
        except Exception:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        try:
            await ws.close()
        except Exception:
            pass
