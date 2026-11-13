#!/usr/bin/env python3
"""POST /api/hosts/<id>/web-launch {method, port} -> Handoff para abrir a interface web já logada.

Mesmo gate do terminal web (--enable-terminal, fora de --read-only; Host/Origin e login já cobertos pelo
middleware). Resposta com Cache-Control: no-store (pode conter ticket/senha; ver services/web_launch_svc.py).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import deps
from services import web_launch_svc

router = APIRouter()
_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post("/hosts/{host_id}/web-launch")
async def web_launch(host_id: str, body: dict | None = None):
    if not deps.STATE.enable_terminal or deps.STATE.read_only:
        return JSONResponse({"error": "disabled", "detail": "acesso web desligado (precisa do terminal ligado e fora de --read-only)"},
                            status_code=403, headers=_HEADERS)
    body = body or {}
    try:
        result = await web_launch_svc.launch(host_id, str(body.get("method") or "") or None, _int(body.get("port")))
    except web_launch_svc.LaunchError as exc:
        return JSONResponse({"error": exc.code, "detail": str(exc)}, status_code=exc.status, headers=_HEADERS)
    return JSONResponse(result, headers=_HEADERS)
