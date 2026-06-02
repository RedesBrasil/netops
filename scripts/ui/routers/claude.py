#!/usr/bin/env python3
"""Página Claude Code — WebSocket do agente + upload de anexos. ⚠ EXECUTA COMANDOS E EDITA ARQUIVOS.

Dirige um agente Claude Code (via `claude-agent-sdk`) rodando COMO O USUÁRIO DO SERVIDOR,
com cwd=NETOPS_ROOT. Rompe a fronteira "a UI é só CRUD" — por isso só liga com
`--enable-claude` (default DESLIGADO) e nunca em `--read-only`, igual ao terminal web.

A auth do handshake WebSocket é feita À MÃO aqui (o middleware http do app não cobre
WebSocket no Starlette): replicamos token + Host (anti DNS-rebinding) + Origin (anti
Cross-Site WebSocket Hijacking) + sessão de login. A lógica da sessão vive em
services/claude_svc.py.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import APIRouter, UploadFile, WebSocket
from fastapi.responses import JSONResponse

import deps
from services import claude_svc

router = APIRouter(tags=["claude"])

UPLOAD_DIR = deps.RUNS_DIR / "claude" / "uploads"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_UPLOAD = 20 * 1024 * 1024  # 20 MiB


def _ws_authorized(ws: WebSocket) -> bool:
    """Mesmas defesas do middleware http (que NÃO cobre WebSocket) — ver routers/terminal.py."""
    if not deps.STATE.enable_claude or deps.STATE.read_only:
        return False
    if not claude_svc.is_available():
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
    if not deps.token_matches(ws.query_params.get("token")):
        return False
    if deps.auth_required() and not deps.auth_session_valid(ws.query_params.get("auth")):
        return False
    return True


@router.websocket("/claude")
async def claude_ws(ws: WebSocket):
    if not _ws_authorized(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    await claude_svc.ClaudeWebSession(ws).run()


@router.post("/claude/upload")
async def claude_upload(file: UploadFile):
    """Recebe um anexo e grava em runs/claude/uploads/; devolve o caminho relativo p/ @referência.

    Passa pelo middleware http normal (token + sessão + Origin + not read-only). Só responde
    se a página Claude estiver ligada — não cria um canal de escrita quando a feature está off.
    """
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    raw = await file.read(_MAX_UPLOAD + 1)
    if len(raw) > _MAX_UPLOAD:
        return JSONResponse(
            {"error": "too_large", "detail": f"limite de {_MAX_UPLOAD // (1024 * 1024)} MiB"},
            status_code=413,
        )
    name = _SAFE_NAME.sub("_", (file.filename or "anexo").rsplit("/", 1)[-1]).strip("._") or "anexo"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / name
    # Evita sobrescrever: acrescenta sufixo numérico se já existir.
    if dest.exists():
        stem, dot, ext = name.partition(".")
        i = 1
        while dest.exists():
            dest = UPLOAD_DIR / f"{stem}-{i}{dot}{ext}"
            i += 1
    dest.write_bytes(raw)
    rel = dest.relative_to(deps.NETOPS_ROOT).as_posix()
    return {"path": rel, "name": dest.name, "size": len(raw)}
