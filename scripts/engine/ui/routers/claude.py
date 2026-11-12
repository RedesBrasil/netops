#!/usr/bin/env python3
"""Página Claude Code — WebSocket do agente + upload de anexos. ⚠ EXECUTA COMANDOS E EDITA ARQUIVOS.

Dirige um agente Claude Code (via `claude-agent-sdk`) rodando COMO O USUÁRIO DO SERVIDOR,
com cwd=NETOPS_ROOT. Rompe a fronteira "a UI é só CRUD" — por isso só liga com
`--enable-claude` (default DESLIGADO) e nunca em `--read-only`.

A auth do handshake WebSocket é feita À MÃO aqui (o middleware http do app não cobre
WebSocket no Starlette): replicamos Host (anti DNS-rebinding) + Origin (anti
Cross-Site WebSocket Hijacking) + sessão de login. A lógica da sessão vive em
services/claude_svc.py.

Persistência (--enable-claude-persist): com a flag ligada, o WebSocket pode RE-ANEXAR a uma
sessão viva que sobreviveu a um standby/queda de socket. O dono é provado por um cookie
HttpOnly (netops_claude_attach) emitido em /claude/attach-ticket — o `session_id` é só índice,
não credencial. Sem cookie válido, degrada p/ o modo clássico (vida do agente = vida do socket).
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Request, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse

import deps
from services import claude_auth, claude_models, claude_prefs, claude_svc

router = APIRouter(tags=["claude"])

UPLOAD_DIR = deps.RUNS_DIR / "claude" / "uploads"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_UPLOAD = 20 * 1024 * 1024  # 20 MiB
# Cookie HttpOnly que identifica o DONO de uma sessão viva (re-anexo). Ver claude_svc.mint_owner.
_ATTACH_COOKIE = "netops_claude_attach"


def _ws_authorized(ws: WebSocket, *, need_sdk: bool = True) -> bool:
    """Mesmas defesas do middleware http (que NÃO cobre WebSocket) — ver routers/terminal.py.

    `need_sdk=False` no login: ali só o binário `claude` importa — e é justamente quando o
    SDK pode estar recusando conexão por falta de credencial que o operador precisa entrar.
    """
    if not deps.STATE.enable_claude or deps.STATE.read_only:
        return False
    if not (claude_svc.is_available() if need_sdk else claude_svc.claude_path()):
        return False
    if not deps.host_origin_allowed(ws.headers.get("host"), ws.headers.get("origin")):
        return False
    if deps.auth_required() and not deps.auth_session_valid(ws.query_params.get("auth")):
        return False
    return True


@router.websocket("/claude")
async def claude_ws(ws: WebSocket):
    if not _ws_authorized(ws):
        await ws.close(code=4403)
        return
    resume = ws.query_params.get("resume") or None
    if resume and not claude_svc.project_session_exists(resume):
        # Nunca passar um UUID ausente/de outro projeto ou caminho arbitrário ao agente.
        await ws.accept()
        await ws.close(code=4404, reason="session_not_found")
        return
    # Modo clássico (persist OFF): vida do agente = vida do socket, como sempre.
    if not deps.STATE.claude_persist:
        await ws.accept()
        await claude_svc.ClaudeWebSession(ws).run()
        return
    # Modo persistente. O WS já passou por _ws_authorized (login). O cookie de dono NÃO é mais
    # requisito p/ persistir: antes, cookie ausente/expirado/perdido no restart degradava CALADO p/
    # o modo clássico (vida do agente = vida do socket) e o turno morria quando o celular
    # bloqueava ou o navegador fechava. Agora a sessão persiste sempre; o cookie só rotula o dono
    # (o takeover por qualquer usuário autenticado já era permitido em attach_or_create).
    owner = ws.cookies.get(_ATTACH_COOKIE) or ""
    model = ws.query_params.get("model") or None
    session, how = claude_svc.attach_or_create(owner=owner, resume=resume, model=model,
                                                  effort=ws.query_params.get("effort") or None)
    if how == "too_many":
        await ws.accept()
        try:
            await ws.send_text(json.dumps({"type": "error", "detail": "too_many_sessions"}))
        finally:
            await ws.close(code=4423)
        return
    if how == "forbidden":
        await ws.close(code=4403)
        return
    await ws.accept()
    await session.serve(ws, first=(how == "new"))


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


@router.get("/claude/attach-ticket")
def claude_attach_ticket(request: Request, response: Response):
    """Emite o cookie de DONO (HttpOnly) que autoriza re-anexar a uma sessão viva. Só faz
    sentido com a persistência ligada; passa pela auth http normal (middleware de app.py)."""
    if not (deps.STATE.enable_claude and deps.STATE.claude_persist):
        return JSONResponse({"error": "persist_disabled"}, status_code=403)
    token = claude_svc.mint_owner(request.headers.get("x-netops-session"))
    # Sem TLS nesta rede (console é HTTP em LAN/túnel) -> Secure=False, senão o cookie não
    # viaja e o re-anexo quebra. HttpOnly (XSS não lê) + SameSite=strict (anti-CSRF) seguram.
    response.set_cookie(
        _ATTACH_COOKIE, token, max_age=12 * 3600, httponly=True, samesite="strict",
        secure=False, path="/api/claude",
    )
    response.status_code = 204
    return response


@router.get("/claude/models")
def claude_models_endpoint():
    """Modelos anunciados pelo CLI/provider da sessão + o padrão econômico.
    Nunca devolve token/segredo — só id e nome de exibição."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    models = claude_models.list_models()
    return {"models": models, "default": claude_models.default_model(models)}


@router.post("/claude/models/refresh")
def claude_models_refresh():
    """Releitura manual do catálogo do CLI, sem prompt; regrava o cache semanal."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    models = claude_models.list_models(force=True)
    return {"models": models, "default": claude_models.default_model(models)}


@router.get("/claude/prefs")
def claude_prefs_get(sid: str = ""):
    """Padrões p/ conversas novas + (se sid) o último modelo/modo daquela conversa."""
    return {**claude_prefs.defaults(), "session": claude_prefs.get_session(sid)}


@router.put("/claude/prefs")
def claude_prefs_put(body: dict):
    return claude_prefs.set_defaults(body.get("default_model"), body.get("default_mode"))


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


@router.get("/claude/sessions/{sid}")
def claude_session_info(sid: str):
    """Lookup individual: links antigos funcionam além do limite da lista recente."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    if not claude_svc.project_session_exists(sid):
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    return {"id": sid}


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


_IMG_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


@router.get("/claude/upload/{name}")
def claude_upload_get(name: str):
    """Serve um anexo de IMAGEM já enviado (preview no chat). Só imagens, só dentro de UPLOAD_DIR."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    if _SAFE_NAME.search(name) or name.startswith("."):
        return JSONResponse({"error": "bad_name"}, status_code=400)
    mt = _IMG_EXT.get(name.rsplit(".", 1)[-1].lower())
    f = UPLOAD_DIR / name
    if not mt or not f.is_file():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(str(f), media_type=mt, headers={"X-Content-Type-Options": "nosniff"})
