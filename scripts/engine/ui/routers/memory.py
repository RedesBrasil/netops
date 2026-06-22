#!/usr/bin/env python3
"""CRUD de memória: um arquivo único, memory/MEMORY.md (Markdown).

Preferências, fatos da rede e lições aprendidas vivem todos em MEMORY.md, em seções
(ver core/rules/memory-protocol.md). Sem schema, sem YAML, sem ciclo de vida — KISS."""
from __future__ import annotations

from fastapi import APIRouter, Request

import deps
from services import docs_svc, yaml_io

router = APIRouter(tags=["memory"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


@router.get("/memory")
def get_memory():
    return docs_svc.read_text_file(deps.MEMORY_MD)


@router.put("/memory")
def put_memory(body: dict, request: Request):
    text = body.get("text", "")
    new_rev = yaml_io.write_text(deps.MEMORY_MD, text, expected=_rev(request), backup=True)
    return {"rev": new_rev, "tokens": docs_svc.token_estimate(text)}
