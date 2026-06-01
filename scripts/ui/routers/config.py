#!/usr/bin/env python3
"""Edição do core/config/project-config.yaml (deep-merge via ruamel, preserva comentários)."""
from __future__ import annotations

from fastapi import APIRouter, Request

import deps
from services import yaml_io

router = APIRouter(tags=["config"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


@router.get("/config")
def get_config():
    import yaml  # noqa: PLC0415
    text, rev, _ = yaml_io.read_text_meta(deps.PROJECT_CONFIG)
    data = (yaml.safe_load(text) if text.strip() else {}) or {}
    return {"data": data, "rev": rev}


@router.put("/config")
def put_config(body: dict, request: Request):
    data, rev, y = yaml_io.load_rt(deps.PROJECT_CONFIG)
    if data is None:
        data = {}
    patch = {k: v for k, v in body.items() if k != "_rev"}
    _deep_merge(data, patch)
    new_rev = yaml_io.write_rt(deps.PROJECT_CONFIG, y, data, expected=_rev(request), backup=True)
    return {"data": dict(data), "rev": new_rev}
