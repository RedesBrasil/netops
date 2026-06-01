#!/usr/bin/env python3
"""CRUD de credenciais (network/credentials.yaml). Segredos sempre mascarados."""
from __future__ import annotations

from fastapi import APIRouter, Request

from models import CredentialCreate, CredentialUpdate, PasswordSet
from services import credentials_svc

router = APIRouter(tags=["credentials"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


@router.get("/credentials")
def list_credentials():
    return credentials_svc.list_credentials()


@router.get("/credentials/{name}")
def get_credential(name: str):
    return credentials_svc.get_credential(name)


@router.post("/credentials", status_code=201)
def create_credential(body: CredentialCreate, request: Request):
    fields = body.model_dump(exclude={"name"}, exclude_unset=True)
    return credentials_svc.create_credential(body.name, fields, _rev(request))


@router.put("/credentials/{name}")
def update_credential(name: str, body: CredentialUpdate, request: Request):
    return credentials_svc.update_credential(name, body.model_dump(exclude_unset=True),
                                             _rev(request), partial=False)


@router.patch("/credentials/{name}")
def patch_credential(name: str, body: CredentialUpdate, request: Request):
    return credentials_svc.update_credential(name, body.model_dump(exclude_unset=True),
                                             _rev(request), partial=True)


@router.delete("/credentials/{name}")
def delete_credential(name: str, request: Request, force: bool = False):
    return credentials_svc.delete_credential(name, _rev(request), force=force)


@router.put("/credentials/{name}/password")
def set_password(name: str, body: PasswordSet, request: Request):
    """Define/rotaciona password|secret. Cofre trancado => 423; não iniciado => 409."""
    return credentials_svc.set_secret(name, body.field, body.value, _rev(request))
