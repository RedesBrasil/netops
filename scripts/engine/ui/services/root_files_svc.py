#!/usr/bin/env python3
"""Modo ROOT do gerenciador de Arquivos (botão "Abrir como root"; Adendo A §6 do plano 2026-11-19).

O console roda como a conta operacional (`netops`). Para gerenciar arquivos como root, o admin abre
uma sessão curta: o serviço netops-localadmin autentica `su - netops-admin` (senha do cofre, que
nunca chega aqui), sobe um `sftp-server` do OpenSSH como root e devolve o canal por SCM_RIGHTS.
O console fala SFTP nesse canal com o mesmo cliente do painel SFTP de hosts (asyncssh), então a
interface é a de `RemoteFS`.

Regras (exceção explícita à "sem sessão root persistente"):
  * exclusiva do painel Arquivos (src `root:<token>`), só com `server.admin` (admin);
  * expira após IDLE_SECONDS sem uso (5 min) e no fechamento; uma por usuário;
  * toda operação de escrita passa pela auditoria normal dos Arquivos e o serviço Local registra
    abertura/fechamento (runs/localadmin/audit.jsonl + journal);
  * nunca é oferecida à IA (o token só existe na memória do console e no navegador do admin).
"""
from __future__ import annotations

import asyncio
import secrets
import sys
import time
from pathlib import Path

import deps
from services import files_svc as fsvc

IDLE_SECONDS = 300
_ENGINE = Path(__file__).resolve().parents[2]


def _localadmin():
    p = str(_ENGINE / "localadmin")
    if p not in sys.path:
        sys.path.insert(0, p)
    import client  # noqa: PLC0415
    import common  # noqa: PLC0415
    return client, common


class _Chan:
    def __init__(self, w):
        self.w = w

    def is_closing(self):
        return self.w.is_closing()

    async def wait_closed(self):
        try:
            await self.w.wait_closed()
        except Exception:  # noqa: BLE001
            pass


class _Reader:
    def __init__(self, r):
        from asyncssh.logging import logger
        self.r, self.logger = r, logger

    async def readexactly(self, n):
        return await self.r.readexactly(n)

    def get_extra_info(self, name, default=None):
        return default


class _Writer:
    def __init__(self, w):
        self.w, self.channel = w, _Chan(w)

    def write(self, data):
        self.w.write(data)

    def write_eof(self):
        try:
            self.w.write_eof()
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        self.w.close()


class _Conn:
    def create_task(self, coro, logger=None):
        return asyncio.ensure_future(coro)


class RootSession(fsvc.RemoteSession):
    def __init__(self, user: str, sock):
        super().__init__(None, {"id": "root", "hostname": "este servidor (root)"}, "root", asyncio.get_running_loop())
        self.console_user = user
        self.sock = sock
        self.last = time.monotonic()
        self.opened = time.time()

    @property
    def label(self) -> str:
        return "root@este-servidor"

    async def client(self):
        self.last = time.monotonic()
        async with self._lock:
            if self.sftp is None:
                from asyncssh import sftp as asftp
                reader, writer = await asyncio.open_unix_connection(sock=self.sock)
                self.sftp = await asftp.start_sftp_client(_Conn(), asyncio.get_running_loop(), "strict",
                                                          _Reader(reader), _Writer(writer), "utf-8", "strict", 3)
            return self.sftp

    def close(self):
        super().close()
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


ROOT_SESSIONS: dict[str, RootSession] = {}


def _sweep() -> None:
    now = time.monotonic()
    for tok, s in list(ROOT_SESSIONS.items()):
        if now - s.last > IDLE_SECONDS:
            ROOT_SESSIONS.pop(tok, None)
            s.close()
            fsvc.audit("root", "fechar-sessão-root", f"inatividade ({s.console_user})")


def status() -> dict:
    client, _common = _localadmin()
    st = client.status(deps.NETOPS_ROOT)
    return {"ready": bool(st.get("ready")), "code": st.get("code", ""), "detail": st.get("detail", ""),
            "idle_seconds": IDLE_SECONDS}


async def open_session(user: str) -> dict:
    _sweep()
    client, common = _localadmin()
    for tok, s in list(ROOT_SESSIONS.items()):     # uma por usuário
        if s.console_user == user:
            ROOT_SESSIONS.pop(tok, None)
            s.close()
    try:
        sock = await asyncio.to_thread(client.open_sftp, deps.NETOPS_ROOT, user)
    except common.LocalAdminError as e:
        raise fsvc.Denied(f"{e.code}: {e.detail}")
    sock.setblocking(False)
    token = "root:" + secrets.token_urlsafe(24)
    ROOT_SESSIONS[token] = RootSession(user, sock)
    fsvc.audit("root", "abrir-sessão-root", user)
    return {"src": token, "idle_seconds": IDLE_SECONDS}


def close_session(token: str) -> None:
    s = ROOT_SESSIONS.pop(token or "", None)
    if s:
        s.close()
        fsvc.audit("root", "fechar-sessão-root", s.console_user)


def get(token: str) -> RootSession:
    _sweep()
    s = ROOT_SESSIONS.get(token)
    if s is None:
        raise fsvc.NotFound("sessão root encerrada (inatividade de 5 min ou fechada) — clique em \"Abrir como root\" de novo")
    return s
