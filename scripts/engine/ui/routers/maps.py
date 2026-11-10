#!/usr/bin/env python3
"""Mapas visuais, sujeitos ao mesmo gate de segurança do restante do console."""
from fastapi import APIRouter, Request

from models import MapSave
from services import maps_svc

router = APIRouter(tags=["maps"])


@router.get("/maps")
def get_maps():
    return maps_svc.snapshot()


@router.put("/maps/{map_id}")
def save_map(map_id: str, body: MapSave, request: Request):
    if map_id != body.map.id:
        maps_svc._fail("id", "ID do mapa diverge da URL")
    return maps_svc.save_map(body.map.model_dump(exclude_none=True), request.headers.get("if-match"),
                             body.hosts_rev, body.topology_rev)


@router.delete("/maps/{map_id}")
def delete_map(map_id: str, request: Request):
    return maps_svc.delete_map(map_id, request.headers.get("if-match"))
