#!/usr/bin/env python3
"""Usuários e grupos de acesso do console (menu Sistema → Usuários / Grupos de acesso). Só admin
(`users.manage`, aplicado pelo middleware de app.py). Lógica e travas em lib/accessdb.py:
não apaga/desativa o último admin, não remove o admin de si mesmo, grupo admin é fixo.

Concorrência: `rev` (If-Match) por usuário/grupo -> 409 se outro admin mudou antes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import deps
from lib import accessdb
from lib import github_identity as ghid
from services import authz

router = APIRouter(tags=["users"])


class UserCreate(BaseModel):
    model_config = {"extra": "forbid"}
    email: str = Field(min_length=3, max_length=120)                    # login
    password: str = Field(min_length=1, max_length=1024)
    username: Optional[str] = Field(default=None, max_length=32)        # ID interno (padrão: derivado do e-mail)
    display_name: str = Field(default="", max_length=80)
    groups: list[str] = Field(default_factory=list)
    must_change_password: bool = True


class UserPatch(BaseModel):
    model_config = {"extra": "forbid"}
    display_name: Optional[str] = Field(default=None, max_length=80)
    email: Optional[str] = Field(default=None, max_length=120)
    groups: Optional[list[str]] = None
    disabled: Optional[bool] = None
    must_change_password: Optional[bool] = None


class PasswordReset(BaseModel):
    model_config = {"extra": "forbid"}
    password: str = Field(min_length=1, max_length=1024)
    must_change_password: bool = True


class GroupCreate(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=2, max_length=40)
    description: str = Field(default="", max_length=200)
    permissions: list[str] = Field(default_factory=list)
    net_perms: list[str] = Field(default_factory=lambda: ["read"])


class GroupPatch(BaseModel):
    model_config = {"extra": "forbid"}
    description: Optional[str] = Field(default=None, max_length=200)
    permissions: Optional[list[str]] = None
    net_perms: Optional[list[str]] = None
    members: Optional[list[str]] = None


def _db():
    return deps.db_file()


def _actor(request: Request) -> authz.Principal:
    return authz.request_principal(request)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _vault_key_if_open() -> bytes | None:
    from routers.auth import _open_vault_key, _vault_meta  # noqa: PLC0415
    return _open_vault_key(_vault_meta())


def _audit(request: Request, action: str, target: str, detail: str = "") -> None:
    accessdb.audit(_db(), action, username=_actor(request).username, ip=_ip(request), target=target, detail=detail)


# ----------------------------------------------------------------- catálogo
@router.get("/access-catalog")
def access_catalog() -> dict:
    return {"permissions": accessdb.PERMISSIONS, "net_perms": list(accessdb.NET_PERMS),
            "admin_group": accessdb.ADMIN_GROUP, "password_min": accessdb.PASSWORD_MIN,
            "multiuser": deps.has_users()}


# ----------------------------------------------------------------- usuários
@router.get("/users")
def users_list() -> dict:
    return {"users": accessdb.list_users(_db()), "multiuser": deps.has_users(),
            "groups": [g["name"] for g in accessdb.list_groups(_db())]}


@router.post("/users", status_code=201)
def users_create(body: UserCreate, request: Request):
    actor = _actor(request)
    user = accessdb.create_user(
        _db(), body.username or None, body.password, display_name=body.display_name, email=body.email,
        groups=body.groups, must_change=body.must_change_password, created_by=actor.username,
        vault_key=_vault_key_if_open(), require_email=True)
    _audit(request, "user_created", user["username"], f"{user['email']} · grupos: " + ", ".join(user["groups"]))
    return user


@router.get("/users/{username}")
def users_get(username: str):
    u = accessdb.get_user(_db(), username)
    if not u:
        raise accessdb.NotFound(f"Usuário '{username}' não encontrado.")
    u["session_list"] = accessdb.list_sessions(_db(), u["username"])
    return u


@router.patch("/users/{username}")
def users_patch(username: str, body: UserPatch, request: Request):
    fields = body.model_dump(exclude_none=True)
    u = accessdb.update_user(_db(), username, rev=request.headers.get("if-match"),
                             actor=_actor(request).username, **fields)
    _audit(request, "user_updated", u["username"], ", ".join(sorted(fields)))
    return u


@router.put("/users/{username}/password")
def users_reset_password(username: str, body: PasswordReset, request: Request):
    """Admin define senha nova (provisória por padrão). Derruba as sessões; keyslot refeito se o cofre
    estiver aberto (senão o usuário ganha o slot no 1º login com o cofre aberto)."""
    u = accessdb.set_password(_db(), username, body.password, must_change=body.must_change_password,
                              vault_key=_vault_key_if_open())
    _audit(request, "password_reset", u["username"])
    return u


@router.delete("/users/{username}", status_code=204)
def users_delete(username: str, request: Request):
    accessdb.delete_user(_db(), username, actor=_actor(request).username)
    ghid.purge_user(deps.DATA_ROOT, username.lower())   # some o login do GitHub dele também
    _audit(request, "user_deleted", username)


@router.get("/users/{username}/sessions")
def users_sessions(username: str) -> dict:
    return {"sessions": accessdb.list_sessions(_db(), username.lower())}


@router.delete("/users/{username}/sessions")
def users_sessions_drop(username: str, request: Request, id: str = "") -> dict:   # noqa: A002
    """Encerra as sessões do usuário (todas, ou só a `id` = prefixo exibido na lista)."""
    n = (accessdb.drop_session_prefix(_db(), username.lower(), id) if id
         else accessdb.drop_user_sessions(_db(), username.lower()))
    _audit(request, "sessions_dropped", username, f"{n} sessão(ões)")
    return {"dropped": n}


# ----------------------------------------------------------------- grupos
@router.get("/access-groups")
def groups_list() -> dict:
    return {"groups": accessdb.list_groups(_db()), "users": [u["username"] for u in accessdb.list_users(_db())]}


@router.post("/access-groups", status_code=201)
def groups_create(body: GroupCreate, request: Request):
    g = accessdb.create_group(_db(), body.name, description=body.description,
                              permissions=body.permissions, net_perms=body.net_perms)
    _audit(request, "group_created", g["name"])
    return g


@router.get("/access-groups/{name}")
def groups_get(name: str):
    g = accessdb.get_group(_db(), name)
    if not g:
        raise accessdb.NotFound(f"Grupo '{name}' não encontrado.")
    return g


@router.patch("/access-groups/{name}")
def groups_patch(name: str, body: GroupPatch, request: Request):
    fields = body.model_dump(exclude_none=True)
    g = accessdb.update_group(_db(), name, rev=request.headers.get("if-match"),
                              actor=_actor(request).username, **fields)
    _audit(request, "group_updated", g["name"], ", ".join(sorted(fields)))
    return g


@router.delete("/access-groups/{name}", status_code=204)
def groups_delete(name: str, request: Request):
    accessdb.delete_group(_db(), name)
    _audit(request, "group_deleted", name)
