#!/usr/bin/env python3
"""CRUD de hosts e grupos (network/hosts.yaml)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from models import GroupCreate, HostCreate, HostUpsert, NodeUpsert, RenameBody
from services import inventory_svc

router = APIRouter(tags=["inventory"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


# --------------------------------------------------------------------------- #
# Hosts
# --------------------------------------------------------------------------- #
@router.get("/hosts")
def list_hosts():
    return inventory_svc.list_hosts_detailed()


@router.get("/hosts/validate")
def validate_hosts():
    data, _ = inventory_svc.load_hosts()
    errors = inventory_svc.validate_data(data)
    return {"ok": not errors, "errors": errors}


@router.get("/hosts/{host_id}")
def get_host(host_id: str):
    return inventory_svc.get_host(host_id)


@router.post("/hosts", status_code=201)
def create_host(body: HostCreate, request: Request):
    fields = body.model_dump(exclude={"id", "placement"}, exclude_unset=True)
    return inventory_svc.create_host(body.id, fields, _rev(request), placement=body.placement.model_dump() if body.placement else None)


@router.put("/hosts/{host_id}")
def replace_host(host_id: str, body: HostUpsert, request: Request):
    fields = body.model_dump(exclude_unset=True)
    return inventory_svc.update_host(host_id, fields, _rev(request), partial=False)


@router.patch("/hosts/{host_id}")
def patch_host(host_id: str, body: HostUpsert, request: Request):
    fields = body.model_dump(exclude_unset=True)
    return inventory_svc.update_host(host_id, fields, _rev(request), partial=True)


@router.delete("/hosts/{host_id}")
def delete_host(host_id: str, request: Request):
    return inventory_svc.delete_host(host_id, _rev(request))


@router.get("/hosts/{host_id}/references")
def host_references(host_id: str):
    """Onde o host é referenciado (preview do cascade do rename)."""
    return inventory_svc.host_references(host_id)


@router.post("/hosts/{host_id}/rename")
def rename_host(host_id: str, body: RenameBody, request: Request):
    """Renomeia o ID do host e atualiza as referências em topology.yaml (atômico)."""
    return inventory_svc.rename_host(host_id, body.to, _rev(request))


# --------------------------------------------------------------------------- #
# Grupos
# --------------------------------------------------------------------------- #
@router.get("/groups")
def list_groups():
    return inventory_svc.list_groups()


@router.post("/groups", status_code=201)
def create_group(body: GroupCreate, request: Request):
    fields = body.model_dump(exclude={"name"}, exclude_unset=True)
    return inventory_svc.create_group(body.name, fields, _rev(request))


@router.put("/groups/{name}")
def replace_group(name: str, body: NodeUpsert, request: Request):
    fields = body.model_dump(exclude_unset=True)
    return inventory_svc.update_group(name, fields, _rev(request), partial=False)


@router.patch("/groups/{name}")
def patch_group(name: str, body: NodeUpsert, request: Request):
    fields = body.model_dump(exclude_unset=True)
    return inventory_svc.update_group(name, fields, _rev(request), partial=True)


@router.delete("/groups/{name}")
def delete_group(name: str, request: Request, force: bool = False):
    return inventory_svc.delete_group(name, _rev(request), force=force)


@router.get("/groups/{name}/references")
def group_references(name: str):
    return inventory_svc.group_references(name)


@router.post("/groups/{name}/rename")
def rename_group(name: str, body: RenameBody, request: Request):
    """Renomeia o grupo e atualiza o campo 'group' dos hosts que o usam (atômico)."""
    return inventory_svc.rename_group(name, body.to, _rev(request))
