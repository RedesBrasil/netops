#!/usr/bin/env python3
"""Página Claude Code — WebSocket do agente + upload de anexos. ⚠ EXECUTA COMANDOS E EDITA ARQUIVOS.

Dirige um agente Claude Code (via `claude-agent-sdk`) rodando COMO O USUÁRIO DO SERVIDOR,
com cwd=NETOPS_ROOT. Rompe a fronteira "a UI é só CRUD" — por isso só liga com
`--enable-claude` (default DESLIGADO) e nunca em `--read-only`, igual ao terminal web.

A auth do handshake WebSocket é feita À MÃO aqui (o middleware http do app não cobre
WebSocket no Starlette): replicamos Host (anti DNS-rebinding) + Origin (anti
Cross-Site WebSocket Hijacking) + sessão de login. A lógica da sessão vive em
services/claude_svc.py.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import APIRouter, UploadFile, WebSocket
from fastapi.responses import JSONResponse

import deps
from services import claude_auth, claude_svc

router = APIRouter(tags=["claude"])

UPLOAD_DIR = deps.RUNS_DIR / "claude" / "uploads"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_UPLOAD = 20 * 1024 * 1024  # 20 MiB


def _ws_authorized(ws: WebSocket, *, need_sdk: bool = True) -> bool:
    """Mesmas defesas do middleware http (que NÃO cobre WebSocket) — ver routers/terminal.py.

    `need_sdk=False` no login: ali só o binário `claude` importa — e é justamente quando o
    SDK pode estar recusando conexão por falta de credencial que o operador precisa entrar.
    """
    if not deps.STATE.enable_claude or deps.STATE.read_only:
        return False
    if not (claude_svc.is_available() if need_sdk else claude_svc.claude_path()):
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


# ----------------------------------------------------------------- autenticação
# O `/login` do Claude Code é comando da TUI — não existe no SDK. Estes três endpoints
# reimplementam o fluxo pela aba, no MESMO HOME em que o agente roda (ver claude_auth).
@router.get("/claude/auth/status")
def claude_auth_status():
    """Estado do login do `claude` que a aba usa (sem token, sem segredo)."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    return claude_auth.status()


@router.post("/claude/auth/logout")
def claude_auth_logout():
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    return claude_auth.logout()


@router.websocket("/claude/login")
async def claude_login_ws(ws: WebSocket):
    """Conduz o `claude auth login` (OAuth com colagem de código) pela aba."""
    if not _ws_authorized(ws, need_sdk=False):
        await ws.close(code=4403)
        return
    await ws.accept()
    await claude_auth.ClaudeLoginSession(ws).run()


@router.get("/claude/sessions")
def claude_sessions():
    """Lista as sessões Claude Code passadas deste projeto (p/ retomar)."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    return {"sessions": claude_svc.list_project_sessions()}


@router.get("/claude/sessions/search")
def claude_sessions_search(q: str = ""):
    """Busca sessões por título/preview OU conteúdo do transcript."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    return {"sessions": claude_svc.search_project_sessions(q)}


@router.get("/claude/sessions/{sid}/messages")
def claude_session_messages(sid: str):
    """Histórico de uma sessão, já no formato da transcrição da UI."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    return {"items": claude_svc.session_items(sid)}


@router.delete("/claude/sessions/{sid}", status_code=204)
def claude_session_delete(sid: str):
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    claude_svc.delete_project_session(sid)


@router.post("/claude/upload")
async def claude_upload(file: UploadFile):
    """Recebe um anexo e grava em runs/claude/uploads/; devolve o caminho relativo p/ @referência.

    Passa pelo middleware http normal (sessão + Origin + not read-only). Só responde
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
