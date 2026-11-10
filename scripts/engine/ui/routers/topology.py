#!/usr/bin/env python3
"""CRUD de topologia (links/segments) + regenerar topology.md."""
from __future__ import annotations

from fastapi import APIRouter, Request

from models import Link, Segment
from services import topology_svc

router = APIRouter(tags=["topology"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


@router.get("/topology")
def get_topology():
    return topology_svc.load_topology()


@router.post("/topology/links")
def add_link(body: Link, request: Request):
    return topology_svc.add_link(body.model_dump(exclude_none=True), _rev(request))


@router.put("/topology/links/{index}")
def update_link(index: int, body: Link, request: Request):
    return topology_svc.update_link(index, body.model_dump(exclude_none=True), _rev(request))


@router.delete("/topology/links/{index}")
def delete_link(index: int, request: Request):
    return topology_svc.delete_link(index, _rev(request))


@router.post("/topology/segments")
def add_segment(body: Segment, request: Request):
    return topology_svc.add_segment(body.model_dump(exclude_none=True), _rev(request))


@router.put("/topology/segments/{index}")
def update_segment(index: int, body: Segment, request: Request):
    return topology_svc.update_segment(index, body.model_dump(exclude_none=True), _rev(request))


@router.delete("/topology/segments/{index}")
def delete_segment(index: int, request: Request):
    return topology_svc.delete_segment(index, _rev(request))


@router.get("/topology/md")
def topology_md():
    return topology_svc.read_md()


@router.get("/topology/preview")
def topology_preview():
    return topology_svc.preview()


@router.post("/topology/render")
def topology_render():
    return topology_svc.render_to_file()


@router.put("/topology/link/{link_id}")
def update_link_by_id(link_id: str, body: Link, request: Request):
    from services import yaml_io
    with yaml_io.COMMIT_LOCK:
        return topology_svc.update_link(topology_svc.link_index(link_id), body.model_dump(exclude_none=True), _rev(request))

@router.delete("/topology/link/{link_id}")
def delete_link_by_id(link_id: str, request: Request):
    from services import yaml_io
    with yaml_io.COMMIT_LOCK:
        return topology_svc.delete_link(topology_svc.link_index(link_id), _rev(request))
