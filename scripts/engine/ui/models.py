#!/usr/bin/env python3
"""Modelos Pydantic (validação de entrada). A validação AUTORITATIVA de hosts roda
contra core/schemas/inventory.schema.json no inventory_svc; estes modelos dão erro
rápido por campo e documentam o contrato (OpenAPI em /api/docs)."""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, FiniteFloat, model_validator, field_validator

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
    icon: Optional[str] = Field(default=None, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    @field_validator("icon")
    @classmethod
    def valid_icon(cls, value):
        from services import icons_svc
        if value is not None and not icons_svc.known_icon(value):
            raise ValueError("ícone não existe na biblioteca local")
        return value

class MapPlacement(BaseModel):
    model_config = {"extra": "forbid"}
    map_id: str = Field(min_length=1, max_length=100)
    maps_rev: str = Field(min_length=64, max_length=64)
    x: FiniteFloat = Field(default=0, ge=-1000000, le=1000000)
    y: FiniteFloat = Field(default=0, ge=-1000000, le=1000000)

class HostCreate(HostUpsert):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    hostname: str = Field(min_length=1)
    mgmt_ip: str = Field(min_length=1)
    placement: Optional[MapPlacement] = None

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
    port: Optional[str] = None


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


# --------------------------------------------------------------------------- #
# Backups (config: quem faz backup e quando)
# --------------------------------------------------------------------------- #
Frequency = Literal["hourly", "daily", "weekly"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class BackupSchedule(BaseModel):
    model_config = {"extra": "forbid"}
    frequency: Frequency = "daily"
    time: str = Field(default="03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: Weekday = "sun"


class BackupTargets(BaseModel):
    model_config = {"extra": "forbid"}
    hosts: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)


RetentionMode = Literal["days", "count"]


class BackupRetention(BaseModel):
    model_config = {"extra": "forbid"}
    mode: RetentionMode = "count"
    value: int = Field(default=7, ge=1, le=3650)


class BackupService(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1)
    enabled: bool = True
    schedule: BackupSchedule = Field(default_factory=BackupSchedule)
    targets: BackupTargets = Field(default_factory=BackupTargets)
    retention: BackupRetention = Field(default_factory=BackupRetention)


class BackupsConfig(BaseModel):
    model_config = {"extra": "forbid"}
    version: int = 2
    services: list[BackupService] = Field(default_factory=list)


class BackupDeleteRequest(BaseModel):
    model_config = {"extra": "forbid"}
    paths: list[str] = Field(default_factory=list)


# Mapas: apresentação apenas. Dispositivos e enlaces vivem nos arquivos canônicos.
class MapPoint(BaseModel):
    model_config = {"extra": "forbid"}
    x: FiniteFloat = Field(ge=-1000000, le=1000000)
    y: FiniteFloat = Field(ge=-1000000, le=1000000)

class MapAnchor(BaseModel):
    model_config = {"extra": "forbid"}
    side: Literal["left", "right", "top", "bottom"]
    ratio: FiniteFloat = Field(ge=0, le=1)

class MapAnchors(BaseModel):
    model_config = {"extra": "forbid"}
    source: MapAnchor
    target: MapAnchor

class MapRoute(BaseModel):
    model_config = {"extra": "forbid"}
    axis: Literal["x", "y"]
    tracks: list[Annotated[FiniteFloat, Field(ge=-1000000, le=1000000)]] = Field(max_length=500)

class MapEdgeLayout(BaseModel):
    model_config = {"extra": "forbid"}
    anchors: Optional[MapAnchors] = None
    route: Optional[MapRoute] = None

class MapObject(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    type: Literal["note", "shape", "reference"]
    position: MapPoint
    label: str = Field(default="", max_length=4000)
    form: Literal["rect", "ellipse"] = "rect"
    width: FiniteFloat = Field(default=320, ge=100, le=10000)
    height: FiniteFloat = Field(default=200, ge=60, le=10000)
    map_id: Optional[str] = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def reference_target(self):
        if self.type == "reference" and not self.map_id:
            raise ValueError("referência precisa de um mapa de destino")
        return self

class MapVisualLink(MapEdgeLayout):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)
    speed: str = Field(default="WAN", max_length=40)

class NetworkMap(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["all", "site", "custom"] = "custom"
    site: Optional[str] = Field(default=None, max_length=200)
    members: list[str] = Field(default_factory=list, max_length=5000)
    positions: dict[str, MapPoint] = Field(default_factory=dict, max_length=5000)
    objects: list[MapObject] = Field(default_factory=list, max_length=1000)
    edges: dict[str, MapEdgeLayout] = Field(default_factory=dict, max_length=10000)
    visual_links: list[MapVisualLink] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def map_rule(self):
        if self.kind == "site" and not self.site:
            raise ValueError("mapa por localidade precisa de site")
        if self.kind == "all" and self.id != "all":
            raise ValueError("o mapa geral usa o ID all")
        if self.id == "all" and self.kind != "all":
            raise ValueError("o mapa geral não pode mudar de tipo")
        return self

class MapSave(BaseModel):
    model_config = {"extra": "forbid"}
    map: NetworkMap
    hosts_rev: str = Field(min_length=64, max_length=64)
    topology_rev: str = Field(min_length=64, max_length=64)
