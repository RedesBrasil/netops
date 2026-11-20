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
from lib import i18n
from services import claude_auth, claude_models, claude_prefs, claude_svc, projects_svc

router = APIRouter(tags=["claude"])

UPLOAD_DIR = deps.RUNS_DIR / "claude" / "uploads"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_UPLOAD = 20 * 1024 * 1024  # 20 MiB
# Cookie HttpOnly que identifica o DONO de uma sessão viva (re-anexo). Ver claude_svc.mint_owner.
_ATTACH_COOKIE = "netops_claude_attach"


class _BadProject(Exception):
    """`?project=` aponta para um projeto inexistente (ou cuja pasta sumiu)."""

def _cwd(project: str | None) -> str | None:
    """Pasta do projeto, ou None (= NetOps, aba Claude Code). Nunca cai no NetOps por engano:
    projeto informado e inválido levanta _BadProject, senão a conversa rodaria na pasta errada."""
    if not project:
        return None
    path = projects_svc.path_of(project)
    if not path:
        raise _BadProject(project)
    return path

def _bad_project() -> JSONResponse:
    return JSONResponse({"error": "project_not_found", "detail": i18n.t("api_common.project_not_found")}, status_code=404)

def _ws_authorized(ws: WebSocket, *, need_sdk: bool = True, perm: str = "claude.use") -> bool:
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
    from services import authz  # noqa: PLC0415
    p = authz.ws_principal(ws, perm)
    if p is None:
        return False
    ws.state.principal = p
    return True


# ------------------------------------------------------------- dono da conversa
# Cada conversa tem DONO (usuário do console que a criou; banco de acesso). Não-admin só vê e mexe
# nas suas; admin vê todas. Conversa sem dono = anterior ao multiusuário -> só admin.
def _may_access(principal, sid: str) -> bool:
    if principal is None:
        return False
    if principal.is_admin:
        return True
    return claude_svc._owner_of(sid) == principal.username


def _owner_guard(request: Request) -> None:
    sid = request.path_params.get("sid")
    if not sid:
        return
    from services import authz  # noqa: PLC0415
    if not _may_access(authz.request_principal(request), sid):
        raise authz.Forbidden("claude.use", i18n.t("api_claude.other_users_session"))


def _visible(request: Request, sessions: list[dict]) -> list[dict]:
    from lib import accessdb  # noqa: PLC0415
    from services import authz  # noqa: PLC0415
    p = authz.request_principal(request)
    owners = accessdb.claude_owners(deps.db_file())
    names = accessdb.first_names(deps.db_file(), owners.values())
    out = []
    for x in sessions:
        owner = owners.get(x.get("id"), "")
        if p.is_admin or owner == p.username:
            out.append({**x, "owner": owner, "owner_name": names.get(owner, "")})
    return out


@router.websocket("/claude")
async def claude_ws(ws: WebSocket):
    if not _ws_authorized(ws):
        await ws.close(code=4403)
        return
    resume = ws.query_params.get("resume") or None
    principal = ws.state.principal
    if resume and not _may_access(principal, resume):
        await ws.close(code=4403)   # conversa de outro usuário
        return
    try:
        cwd = _cwd(ws.query_params.get("project") or None)
    except _BadProject:
        await ws.accept()
        await ws.close(code=4404, reason="project_not_found")
        return
    if resume and not claude_svc.project_session_exists(resume, cwd):
        # Nunca passar um UUID ausente/de outro projeto ou caminho arbitrário ao agente.
        await ws.accept()
        await ws.close(code=4404, reason="session_not_found")
        return
    # Modo clássico (persist OFF): vida do agente = vida do socket, como sempre.
    if not deps.STATE.claude_persist:
        await ws.accept()
        await claude_svc.ClaudeWebSession(ws, user=principal.username, cwd=cwd).run()
        return
    # Modo persistente. O WS já passou por _ws_authorized (login). O cookie de dono NÃO é mais
    # requisito p/ persistir: antes, cookie ausente/expirado/perdido no restart degradava CALADO p/
    # o modo clássico (vida do agente = vida do socket) e o turno morria quando o celular
    # bloqueava ou o navegador fechava. Agora a sessão persiste sempre; o cookie só rotula o dono
    # (o takeover por qualquer usuário autenticado já era permitido em attach_or_create).
    owner = ws.cookies.get(_ATTACH_COOKIE) or ""
    model = ws.query_params.get("model") or None
    session, how = claude_svc.attach_or_create(owner=owner, resume=resume, model=model,
                                                  effort=ws.query_params.get("effort") or None,
                                                  user=principal.username, cwd=cwd)
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
    if not _ws_authorized(ws, need_sdk=False, perm="config"):   # conta Claude do servidor = admin
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
    return claude_prefs.set_defaults(body.get("default_model"), body.get("default_mode"),
                                     body.get("default_netperms"))


@router.get("/claude/sessions")
def claude_sessions(request: Request):
    """Lista as sessões Claude Code passadas deste projeto (p/ retomar)."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    return {"sessions": _visible(request, claude_svc.list_project_sessions())}


@router.get("/claude/sessions/search")
def claude_sessions_search(request: Request, q: str = ""):
    """Busca sessões por título/preview OU conteúdo do transcript."""
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    return {"sessions": _visible(request, claude_svc.search_project_sessions(q))}


@router.get("/claude/sessions/{sid}/messages")
def claude_session_messages(sid: str, request: Request, project: str = ""):
    """Histórico de uma sessão, já no formato da transcrição da UI. `project` = pasta do Projeto."""
    _owner_guard(request)
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    try:
        return {"items": claude_svc.session_items(sid, _cwd(project))}
    except _BadProject:
        return _bad_project()


@router.get("/claude/sessions/{sid}")
def claude_session_info(sid: str, request: Request, project: str = ""):
    """Lookup individual: links antigos funcionam além do limite da lista recente."""
    _owner_guard(request)
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    try:
        cwd = _cwd(project)
    except _BadProject:
        return _bad_project()
    if not claude_svc.project_session_exists(sid, cwd):
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    return {"id": sid}


@router.post("/claude/sessions/{sid}/fork")
def claude_session_fork(sid: str, body: dict, request: Request, project: str = ""):
    """Ramifica a conversa ANTES de um prompt (histórico até o turno anterior; o front repõe o texto no campo).

    body: {uuid?, text?, occurrence?, title?} — uuid vem do histórico; text+occurrence da
    conversa ao vivo. Devolve {id} da nova conversa; a de origem fica intacta.
    """
    _owner_guard(request)
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    try:
        occ = int(body.get("occurrence") or 0)
    except (TypeError, ValueError):
        occ = 0
    try:
        cwd = _cwd(project)
    except _BadProject:
        return _bad_project()
    try:
        new = claude_svc.fork_project_session(
            sid, uuid=(body.get("uuid") or None), text=(body.get("text") or None),
            occurrence=occ, title=((body.get("title") or "").strip()[:120] or None), cwd=cwd)
    except FileNotFoundError:
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": "fork_failed", "detail": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": "fork_failed", "detail": str(e)[:300]}, status_code=500)
    if new:
        from lib import accessdb  # noqa: PLC0415
        from services import authz  # noqa: PLC0415
        accessdb.set_claude_owner(deps.db_file(), new, authz.request_principal(request).username, overwrite=True)
    return {"id": new or None, "first": not new}


@router.post("/claude/sessions/{sid}/rewind")
async def claude_session_rewind(sid: str, body: dict, request: Request, project: str = ""):
    """Edita um prompt: APAGA o prompt escolhido e tudo depois dele, na MESMA conversa.

    body: {uuid?, text?, occurrence?, dry?} — mesma identificação do fork. `dry` só informa o
    que seria apagado. Encerra o `claude` vivo da conversa (as abas conectadas reconectam),
    guarda cópia em runs/copias-seguranca/claude-rewind/ e corta o transcript. O front então
    retoma a conversa e envia o texto editado. {first:true} = era o 1º prompt: a conversa foi
    apagada e o front abre uma nova.
    """
    _owner_guard(request)
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    try:
        occ = int(body.get("occurrence") or 0)
    except (TypeError, ValueError):
        occ = 0
    try:
        cwd = _cwd(project)
    except _BadProject:
        return _bad_project()
    try:
        plan = claude_svc.rewind_plan(sid, uuid=(body.get("uuid") or None),
                                      text=(body.get("text") or None), occurrence=occ, cwd=cwd)
        if body.get("dry"):
            return plan
        live = claude_svc._LIVE.get(sid)
        if live is not None and not live._closing_done:
            await live.teardown()   # sem subprocesso vivo escrevendo no arquivo
        res = claude_svc.rewind_apply(sid, plan["prompt_uuid"], first=plan["first"], cwd=cwd)
    except FileNotFoundError:
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": "rewind_failed", "detail": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": "rewind_failed", "detail": str(e)[:300]}, status_code=500)
    return {"id": sid, "first": plan["first"], "removed_prompts": plan["removed_prompts"], **res}


@router.put("/claude/sessions/{sid}/completed")
def claude_session_completed(sid: str, body: dict, request: Request, project: str = ""):
    """Marca/desmarca a conversa como concluída por completo (checkbox manual do usuário)."""
    _owner_guard(request)
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    try:
        cwd = _cwd(project)
    except _BadProject:
        return _bad_project()
    if not claude_svc.project_session_exists(sid, cwd):
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    done = bool(body.get("completed"))
    claude_prefs.set_completed(sid, done)
    return {"id": sid, "completed": done}


@router.put("/claude/sessions/{sid}/title")
def claude_session_rename(sid: str, body: dict, request: Request, project: str = ""):
    """Renomeia a conversa (grava o custom_title no transcript, via SDK)."""
    _owner_guard(request)
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    title = " ".join(str(body.get("title") or "").split())[:120]
    if not title:
        return JSONResponse({"error": "empty_title"}, status_code=400)
    try:
        cwd = _cwd(project)
    except _BadProject:
        return _bad_project()
    if not claude_svc.project_session_exists(sid, cwd):
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    try:
        claude_svc.rename_project_session(sid, title, cwd)
    except Exception as e:
        return JSONResponse({"error": "rename_failed", "detail": str(e)[:300]}, status_code=500)
    return {"id": sid, "title": title}


@router.delete("/claude/sessions/{sid}", status_code=204)
def claude_session_delete(sid: str, request: Request, project: str = ""):
    _owner_guard(request)
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    try:
        cwd = _cwd(project)
    except _BadProject:
        return _bad_project()
    claude_svc.delete_project_session(sid, cwd)
    from lib import accessdb  # noqa: PLC0415
    accessdb.forget_claude_owner(deps.db_file(), sid)


@router.post("/claude/upload")
async def claude_upload(file: UploadFile, project: str = ""):
    """Recebe um anexo e grava em runs/claude/uploads/; devolve o caminho relativo p/ @referência.

    Passa pelo middleware http normal (sessão + Origin + not read-only). Só responde
    se a página Claude estiver ligada — não cria um canal de escrita quando a feature está off.
    """
    if not deps.STATE.enable_claude:
        return JSONResponse({"error": "claude_disabled"}, status_code=403)
    try:
        cwd = _cwd(project)
    except _BadProject:
        return _bad_project()
    raw = await file.read(_MAX_UPLOAD + 1)
    if len(raw) > _MAX_UPLOAD:
        return JSONResponse(
            {"error": "too_large", "detail": i18n.t("api_common.size_limit_mib", mib=_MAX_UPLOAD // (1024 * 1024))},
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
    # Projeto: o agente roda em OUTRA pasta, onde "runs/claude/uploads/x" não existe -> caminho absoluto.
    rel = dest.as_posix() if cwd else dest.relative_to(deps.NETOPS_ROOT).as_posix()
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
