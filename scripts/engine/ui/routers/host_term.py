#!/usr/bin/env python3
"""Terminal web para HOSTS do inventário (SSH/Telnet) — endpoint WebSocket.

  /api/term/host/<id>?method=ssh|telnet[&port=N]&cols=&rows=&auth=<sessão>

Mesmo gate do /api/term (o middleware http não cobre WebSocket): --enable-terminal, fora de
--read-only, Host/Origin e sessão de login. A lógica (inventário, credencial, SSH/Telnet) fica em
services/host_term_svc.py.
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket

from routers.terminal import _ws_authorized
from services import host_term_svc

router = APIRouter()


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@router.websocket("/term/host/{host_id}")
async def host_term(ws: WebSocket, host_id: str):
    if not _ws_authorized(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    q = ws.query_params
    await host_term_svc.serve(
        ws, host_id, q.get("method"), _int(q.get("port")),
        cols=max(1, min(host_term_svc.MAX_DIM, _int(q.get("cols"), 120))),
        rows=max(1, min(host_term_svc.MAX_DIM, _int(q.get("rows"), 32))))
    try:
        await ws.close()
    except Exception:  # noqa: BLE001 — já fechado pelo cliente
        pass
