#!/usr/bin/env python3
"""GitHub por usuário: cada pessoa conecta a PRÓPRIA conta (Minha conta → GitHub, #account/github).

A conta vale para as conversas da aba Claude Code e dos Projetos abertas por ela (ver
lib/github_identity.py e services/claude_svc._options). Só existe no modo multiusuário: sem usuários
cadastrados o agente segue com o `gh` do servidor, como antes.

Rotas (sem /api):
  GET    /account/github            estado (sem token)
  WS     /account/github/login      login por dispositivo (services/github_auth.py)
  POST   /account/github/token      alternativa: token pessoal (PAT)
  PUT    /account/github/email      e-mail usado nos commits (um dos verificados / noreply)
  DELETE /account/github            desconectar
  GET    /users/{u}/github          admin: estado do GitHub de um usuário (users.manage)
  DELETE /users/{u}/github          admin: revogar (users.manage)
"""
from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import deps
from lib import accessdb
from lib import github_identity as ghid
from services import authz, github_auth

router = APIRouter(tags=["github"])


class TokenBody(BaseModel):
    model_config = {"extra": "forbid"}
    token: str = Field(min_length=10, max_length=400)


class EmailBody(BaseModel):
    model_config = {"extra": "forbid"}
    email: str = Field(min_length=3, max_length=200)


def _me(request: Request) -> authz.Principal | JSONResponse:
    p = authz.request_principal(request)
    if not deps.has_users() or p.legacy or not p.username:
        return JSONResponse({"error": "no_multiuser",
                             "detail": "GitHub por usuário só existe com usuários cadastrados (Sistema → Usuários). "
                                       "Sem eles, o agente usa o gh do servidor."}, status_code=409)
    return p


def _audit(request: Request, action: str, target: str, detail: str = "") -> None:
    accessdb.audit(deps.db_file(), action, username=authz.request_principal(request).username,
                   ip=authz.client_ip(request), target=target, detail=detail)


def _out(username: str) -> dict:
    return {**github_auth.status(username), "multiuser": True, "gh_available": bool(ghid.gh_bin())}


@router.get("/account/github")
def account_github(request: Request):
    p = _me(request)
    if isinstance(p, JSONResponse):
        return {"connected": False, "multiuser": False, "gh_available": bool(ghid.gh_bin())}
    return _out(p.username)


@router.websocket("/account/github/login")
async def account_github_login(ws: WebSocket):
    if deps.STATE.read_only or not deps.host_origin_allowed(ws.headers.get("host"), ws.headers.get("origin")):
        await ws.close(code=4403)
        return
    p = authz.ws_principal(ws, authz.ANY)
    if p is None or p.legacy or not deps.has_users():
        await ws.close(code=4403)
        return
    await ws.accept()

    def done(username: str) -> None:
        meta = ghid.get_meta(deps.DATA_ROOT, username) or {}
        accessdb.audit(deps.db_file(), "github_connected", username=username,
                       ip=getattr(ws.client, "host", "") or "", target=username,
                       detail=f"@{meta.get('login', '?')} (navegador)")

    await github_auth.GitHubLoginSession(ws, p.username, on_done=done).run()


@router.post("/account/github/token")
def account_github_token(body: TokenBody, request: Request):
    p = _me(request)
    if isinstance(p, JSONResponse):
        return p
    meta = ghid.login_with_token(deps.DATA_ROOT, p.username, body.token)
    _audit(request, "github_connected", p.username, f"@{meta['login']} (token)")
    return _out(p.username)


@router.put("/account/github/email")
def account_github_email(body: EmailBody, request: Request):
    p = _me(request)
    if isinstance(p, JSONResponse):
        return p
    ghid.set_email(deps.DATA_ROOT, p.username, body.email.strip())
    _audit(request, "github_email", p.username, body.email.strip())
    return _out(p.username)


@router.delete("/account/github")
def account_github_delete(request: Request):
    p = _me(request)
    if isinstance(p, JSONResponse):
        return p
    meta = ghid.get_meta(deps.DATA_ROOT, p.username) or {}
    if ghid.disconnect(deps.DATA_ROOT, p.username):
        _audit(request, "github_disconnected", p.username, f"@{meta.get('login', '?')}")
    return _out(p.username)


# ------------------------------------------------------------------ admin
def _user_or_404(username: str) -> str:
    u = accessdb.get_user(deps.db_file(), username)
    if not u:
        raise accessdb.NotFound(f"Usuário '{username}' não encontrado.")
    return u["username"]


@router.get("/users/{username}/github")
def user_github(username: str):
    return _out(_user_or_404(username))


@router.delete("/users/{username}/github")
def user_github_delete(username: str, request: Request):
    u = _user_or_404(username)
    meta = ghid.get_meta(deps.DATA_ROOT, u) or {}
    if ghid.disconnect(deps.DATA_ROOT, u):
        _audit(request, "github_revoked", u, f"@{meta.get('login', '?')}")
    return _out(u)
