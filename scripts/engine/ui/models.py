#!/usr/bin/env python3
"""Modelos Pydantic (validação de entrada). A validação AUTORITATIVA de hosts roda
contra core/schemas/inventory.schema.json no inventory_svc; estes modelos dão erro
rápido por campo e documentam o contrato (OpenAPI em /api/docs)."""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field

Vendor = Literal[
    "mikrotik", "unifi", "ubiquiti", "cisco", "huawei", "proxmox",
    "vmware", "datacom", "linux", "fiberhome", "intelbras", "other",
]
Role = Literal["core", "distribution", "access", "firewall", "wireless", "server", "other"]
Method = Literal["ssh", "telnet", "api", "winbox"]
Port = Annotated[int, Field(ge=1, le=65535)]


class Access(BaseModel):
    model_config = {"extra": "forbid"}
    method: Optional[Method] = None
    port: Optional[Port] = None


class NodeUpsert(BaseModel):
    """Campos comuns a host e grupo (herdáveis)."""
    model_config = {"extra": "forbid"}
    vendor: Optional[Vendor] = None
    role: Optional[Role] = None
    model: Optional[str] = None
    site: Optional[str] = None
    notes: Optional[str] = None
    credential: Optional[str] = None
    access: Optional[Access] = None


class HostUpsert(NodeUpsert):
    hostname: Optional[str] = Field(default=None, min_length=1)
    mgmt_ip: Optional[str] = Field(default=None, min_length=1)
    group: Optional[str] = None


class HostCreate(HostUpsert):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    hostname: str = Field(min_length=1)
    mgmt_ip: str = Field(min_length=1)


class GroupCreate(NodeUpsert):
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")


# --------------------------------------------------------------------------- #
# Credenciais
# --------------------------------------------------------------------------- #
class CredentialCreate(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    username: Optional[str] = None
    key_file: Optional[str] = None
    api_ssl: Optional[bool] = None


class CredentialUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    username: Optional[str] = None
    key_file: Optional[str] = None
    api_ssl: Optional[bool] = None


class PasswordSet(BaseModel):
    model_config = {"extra": "forbid"}
    value: str = Field(min_length=1)
    field: Literal["password", "secret"] = "password"


class RenameBody(BaseModel):
    """Novo ID/nome de um recurso de mapa (host/grupo/credencial). O mesmo padrão de
    slug de HostCreate/GroupCreate/CredentialCreate; a unicidade é checada no serviço."""
    model_config = {"extra": "forbid"}
    to: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")


# --------------------------------------------------------------------------- #
# Cofre (destrancar pela web)
# --------------------------------------------------------------------------- #
class VaultUnlock(BaseModel):
    """A senha-mestra trafega só nesta request: deriva a chave (Argon2id) e é descartada.
    Nunca é gravada, logada nem devolvida ao navegador."""
    model_config = {"extra": "forbid"}
    master_password: str = Field(min_length=1)
    ttl: Optional[int] = Field(default=None, ge=30, le=86400)


# --------------------------------------------------------------------------- #
# Topologia
# --------------------------------------------------------------------------- #
class LinkEnd(BaseModel):
    model_config = {"extra": "forbid"}
    host: str = Field(min_length=1)
    port: str = Field(min_length=1)


class Link(BaseModel):
    model_config = {"extra": "forbid"}
    a: LinkEnd
    b: LinkEnd
    media: Optional[Literal["fiber", "copper"]] = None
    speed: Optional[str] = None
    desc: Optional[str] = None


class Segment(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1)
    vlan: Optional[int] = Field(default=None, ge=1, le=4094)
    subnet: Optional[str] = None
