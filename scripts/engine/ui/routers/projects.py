#!/usr/bin/env python3
"""Projetos da aba Claude Code — nome + pasta do servidor, e as sessões de cada um.

Só HTTP e gate; a lógica vive em services/projects_svc.py (registro) e claude_svc.py (sessões,
sempre com `cwd` = pasta do projeto). Mesmo gate do router claude: `--enable-claude`, e o
middleware de app.py já barra escritas em `--read-only`.

Permissões (services/authz.RULES): ver projetos e usar as sessões = `claude.use`; criar, renomear,
remover, marcar como confiável e navegar nas pastas do servidor = `projects.manage` (só admin: escolher a
pasta onde um agente com shell roda como o usuário do servidor é decisão de administrador).
O seletor só lista pastas, nunca arquivos.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import deps
from routers.claude import _visible   # mesma regra de dono da aba Claude Code: não-admin só vê as suas conversas
from services import claude_models, claude_svc, projects_svc

router = APIRouter(tags=["projects"])


def _off():
    return JSONResponse({"error": "claude_disabled"}, status_code=403)


def _err(exc: projects_svc.ProjectError) -> JSONResponse:
    return JSONResponse({"error": exc.code, "detail": str(exc)}, status_code=exc.status)


def _not_found() -> JSONResponse:
    return JSONResponse({"error": "project_not_found", "detail": "Projeto não encontrado."}, status_code=404)


@router.get("/projects")
def projects_list():
    if not deps.STATE.enable_claude:
        return _off()
    return {"projects": projects_svc.list_projects(),
            # conta do agente só nos settings do NetOps = sessões de projeto não a acham (ver claude_models)
            "account_warning": claude_models.account_only_in_netops()}


@router.post("/projects")
def projects_create(body: dict):
    if not deps.STATE.enable_claude:
        return _off()
    try:
        return projects_svc.create(body.get("name"), body.get("path"), trust=bool(body.get("trust")),
                                   new_folder=(body.get("new_folder") or None))
    except projects_svc.ProjectError as e:
        return _err(e)


# Antes de /projects/{pid}: "browse" não pode ser lido como id de projeto.
@router.get("/projects/browse")
def projects_browse(path: str = "", hidden: bool = False):
    if not deps.STATE.enable_claude:
        return _off()
    try:
        return projects_svc.browse(path, hidden)
    except projects_svc.ProjectError as e:
        return _err(e)


@router.get("/projects/{pid}")
def projects_get(pid: str):
    if not deps.STATE.enable_claude:
        return _off()
    p = projects_svc.get(pid)
    return p if p else _not_found()


@router.patch("/projects/{pid}")
def projects_update(pid: str, body: dict):
    """body: {name?} renomeia; {trusted: bool} marca/desmarca a pasta como confiável."""
    if not deps.STATE.enable_claude:
        return _off()
    try:
        out = None
        if "name" in body:
            out = projects_svc.rename(pid, body.get("name"))
        if "trusted" in body:
            out = projects_svc.set_trusted(pid, bool(body.get("trusted")))
        if out is None:
            return JSONResponse({"error": "nothing_to_update", "detail": "Nada para alterar."}, status_code=400)
        return out
    except projects_svc.ProjectError as e:
        return _err(e)


@router.delete("/projects/{pid}", status_code=204)
def projects_delete(pid: str):
    if not deps.STATE.enable_claude:
        return _off()
    if not projects_svc.delete(pid):
        return _not_found()


@router.get("/projects/{pid}/sessions")
def projects_sessions(pid: str, request: Request):
    if not deps.STATE.enable_claude:
        return _off()
    cwd = projects_svc.path_of(pid)
    if not cwd:
        return _not_found()
    return {"sessions": _visible(request, claude_svc.list_project_sessions(cwd=cwd))}


@router.get("/projects/{pid}/sessions/search")
def projects_sessions_search(pid: str, request: Request, q: str = ""):
    if not deps.STATE.enable_claude:
        return _off()
    cwd = projects_svc.path_of(pid)
    if not cwd:
        return _not_found()
    return {"sessions": _visible(request, claude_svc.search_project_sessions(q, cwd=cwd))}
