#!/usr/bin/env python3
"""Terminal web (PTY) — endpoint WebSocket. ⚠ EXECUÇÃO DE COMANDO ARBITRÁRIO.

Cada conexão abre um shell (PTY) que roda COMO O USUÁRIO DO SERVIDOR, em NETOPS_ROOT.
Isso rompe a fronteira "a UI é só CRUD" — por isso só liga com `--enable-terminal`
(default DESLIGADO) e nunca em `--read-only`.

A autenticação do handshake é feita À MÃO aqui porque o middleware http do app
(Host + Origin + login) NÃO roda em conexões WebSocket no Starlette. Replicamos as
mesmas defesas: sessão de login (senha-mestra), Host loopback/IP-de-bind (anti
DNS-rebinding) e Origin (anti Cross-Site WebSocket Hijacking).

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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import deps

router = APIRouter()

SHELL = os.environ.get("SHELL", "/bin/bash")
SHELL_ARGV = [SHELL, "-l"]
MAX_DIM = 1000
TERM_USER = os.environ.get("NETOPS_TERM_USER", "netops")  # ZT: o terminal web dropa p/ este usuario


def _drop_target():
    """Usuario para o qual o PTY deve dropar (ZT: o terminal web nunca e um shell root).

    - Servidor como root  -> DEVE dropar para TERM_USER; se nao existir, retorna False (recusar).
    - Servidor nao-root   -> None (roda como o proprio usuario; nada a dropar)."""
    if os.getuid() != 0:
        return None
    import pwd  # noqa: PLC0415
    try:
        pw = pwd.getpwnam(TERM_USER)
    except KeyError:
        return False
    return {
        "uid": pw.pw_uid,
        "gid": pw.pw_gid,
        "groups": os.getgrouplist(TERM_USER, pw.pw_gid),
        "home": pw.pw_dir,
        "name": TERM_USER,
        "shell": pw.pw_shell or "/bin/bash",
    }


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    rows = max(1, min(MAX_DIM, int(rows)))
    cols = max(1, min(MAX_DIM, int(cols)))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _ws_authorized(ws: WebSocket, perm: str = "server.terminal") -> bool:
    """Mesmas defesas do middleware http (que NÃO cobre WebSocket) + permissão do usuário.
    Terminal do servidor = `server.terminal` (só admin); terminal de host = `host.terminal`."""
    if not deps.STATE.enable_terminal or deps.STATE.read_only:
        return False
    if not deps.host_origin_allowed(ws.headers.get("host"), ws.headers.get("origin")):
        return False
    from services import authz  # noqa: PLC0415
    p = authz.ws_principal(ws, perm)
    if p is None:
        return False
    ws.state.principal = p
    return True


def _audit_ws(ws: WebSocket, action: str, target: str = "") -> None:
    from lib import accessdb  # noqa: PLC0415
    p = getattr(ws.state, "principal", None)
    accessdb.audit(deps.db_file(), action, username=getattr(p, "username", ""),
                   ip=ws.client.host if ws.client else "", target=target)


@router.websocket("/term")
async def term(ws: WebSocket):
    if not _ws_authorized(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    _audit_ws(ws, "server_terminal_open")

    drop = _drop_target()
    if drop is False:
        # Servidor roda como root mas o usuário de drop não existe: recusa (ZT — sem shell root).
        await ws.send_bytes(
            f"\r\n[netops] usuário '{TERM_USER}' não existe neste host — terminal recusado "
            f"(por segurança, não abrimos um shell root).\r\n".encode()
        )
        await ws.close(code=4500)
        return

    # Pré-monta env/argv/cwd NO PAI: o filho do forkpty só faz drop+chdir+execvpe
    # (async-signal-safe), evitando alocação num fork de processo multi-thread.
    child_env = dict(os.environ)
    child_env["TERM"] = "xterm-256color"
    # quem abriu o terminal (autorização da administração Local: server.admin; ver scripts/engine/localadmin)
    child_env["NETOPS_USER"] = getattr(getattr(ws.state, "principal", None), "username", "") or ""
    if drop:
        child_env["HOME"] = drop["home"]
        child_env["USER"] = child_env["LOGNAME"] = drop["name"]
        child_env["SHELL"] = drop["shell"]
        child_env.pop("XDG_RUNTIME_DIR", None)   # não herdar o runtime dir do root (0700, inacessível)
        shell = drop["shell"]
    else:
        shell = SHELL
    shell_argv = [shell, "-l"]
    cwd = str(deps.NETOPS_ROOT)

    pid, fd = pty.fork()
    if pid == 0:
        # filho: dropa privilégio (se o servidor for root) e vira o shell de login.
        if drop:
            try:
                os.setgid(drop["gid"])
                os.setgroups(drop["groups"])
                os.setuid(drop["uid"])
            except OSError:
                os._exit(126)   # falhou o drop -> NUNCA seguir como root
        try:
            os.chdir(cwd)
        except OSError:
            pass
        try:
            os.execvpe(shell, shell_argv, child_env)
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
