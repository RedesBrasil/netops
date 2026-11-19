#!/usr/bin/env python3
"""Cofre de senhas (network/vault.yaml): itens, templates e campos. Segredos só com o cofre aberto."""
from __future__ import annotations

from fastapi import APIRouter, Request

from models import (VaultFieldCreate, VaultFieldUpdate, VaultItemBody, VaultReveal,
                    VaultTemplateBody)
from services import authz, vault_items_svc as svc

router = APIRouter(tags=["vault-items"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _user(request: Request) -> str:
    p = authz.request_principal(request)
    return p.display_name or p.username or ""


# catálogo (campos + templates)
@router.get("/vault/catalog")
def get_catalog():
    return svc.catalog()


@router.post("/vault/fields", status_code=201)
def create_field(body: VaultFieldCreate, request: Request):
    return svc.create_field(body.name, body.kind, _rev(request))


@router.patch("/vault/fields/{name}")
def update_field(name: str, body: VaultFieldUpdate, request: Request):
    return svc.update_field(name, body.name, body.kind, _rev(request))


@router.delete("/vault/fields/{name}")
def delete_field(name: str, request: Request):
    return svc.delete_field(name, _rev(request))


@router.post("/vault/templates", status_code=201)
def create_template(body: VaultTemplateBody, request: Request):
    return svc.create_template(body.model_dump(), _rev(request))


@router.put("/vault/templates/{tid}")
def update_template(tid: str, body: VaultTemplateBody, request: Request):
    return svc.update_template(tid, body.model_dump(), _rev(request))


@router.delete("/vault/templates/{tid}")
def delete_template(tid: str, request: Request):
    return svc.delete_template(tid, _rev(request))


# itens
@router.get("/vault/items")
def list_items():
    return svc.list_items()


@router.get("/vault/items/{iid}")
def get_item(iid: str):
    return svc.get_item(iid)


@router.post("/vault/items", status_code=201)
def create_item(body: VaultItemBody, request: Request):
    return svc.create_item(body.model_dump(), _rev(request), _user(request))


@router.put("/vault/items/{iid}")
def update_item(iid: str, body: VaultItemBody, request: Request):
    return svc.update_item(iid, body.model_dump(), _rev(request), _user(request))


@router.delete("/vault/items/{iid}")
def delete_item(iid: str, request: Request):
    return svc.delete_item(iid, _rev(request))


@router.post("/vault/items/{iid}/reveal")
def reveal(iid: str, body: VaultReveal):
    """Segredo em claro para o humano no console (cofre destrancado + vault.reveal). Auditado."""
    return svc.reveal(iid, body.field)
