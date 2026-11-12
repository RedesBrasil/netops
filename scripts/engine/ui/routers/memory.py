#!/usr/bin/env python3
"""CRUD de memória: o índice memory/MEMORY.md, o AGENTS.md da raiz e as notas memory/*.md.

MEMORY.md é o índice (preferências, fatos da rede, lições — ver core/rules/memory-protocol.md);
AGENTS.md é a memória de projeto que toda IA lê primeiro; as notas são os detalhes que o índice
aponta. Tudo Markdown cru com trava otimista + backup. Nome = whitelist (sem caminho)."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Request

import deps
from services import docs_svc, yaml_io

router = APIRouter(tags=["memory"])

_NOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _agents_md() -> Path:
    return deps.NETOPS_ROOT / "AGENTS.md"


def _resolve(name: str) -> Path:
    """MEMORY.md / AGENTS.md / <nota>.md de memory/ — nada além disso."""
    name = (name or "").strip()
    if name == "AGENTS.md":
        return _agents_md()
    if not _NOTE_RE.match(name):
        raise deps.ValidationFailed([{"loc": "name", "msg": "nome inválido (use <nota>.md)"}])
    return docs_svc.safe_child(deps.MEMORY_DIR, name)


def _title(path: Path) -> str:
    """1º título Markdown (# ...) ou name: do frontmatter. Best-effort."""
    try:
        text, _, _ = yaml_io.read_text_meta(path)
        fm, body = docs_svc.split_frontmatter(text)
        if isinstance(fm, dict) and fm.get("name"):
            return str(fm["name"])
        for line in body.splitlines()[:40]:
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    return ""


@router.get("/memory")
def get_memory():
    return docs_svc.read_text_file(deps.MEMORY_MD)


@router.put("/memory")
def put_memory(body: dict, request: Request):
    text = body.get("text", "")
    new_rev = yaml_io.write_text(deps.MEMORY_MD, text, expected=_rev(request), backup=True)
    return {"rev": new_rev, "tokens": docs_svc.token_estimate(text)}


@router.get("/memory/files")
def list_memory_files():
    """Índice + AGENTS.md fixos no topo; depois as notas de memory/ (sem backups .bak*)."""
    out = [
        {"name": "MEMORY.md", "kind": "index", "title": "Índice da memória",
         "exists": deps.MEMORY_MD.exists()},
        {"name": "AGENTS.md", "kind": "agents", "title": "Instruções do projeto (lido primeiro por toda IA)",
         "exists": _agents_md().exists()},
    ]
    if deps.MEMORY_DIR.exists():
        for f in sorted(deps.MEMORY_DIR.glob("*.md")):
            if f.name == "MEMORY.md" or not f.is_file() or not _NOTE_RE.match(f.name):
                continue
            out.append({"name": f.name, "kind": "note", "title": _title(f), "exists": True,
                        "size": f.stat().st_size})
    return {"files": out}


@router.get("/memory/file")
def get_memory_file(name: str):
    p = _resolve(name)
    if not p.exists():
        raise KeyError(f"'{name}' não existe")
    return docs_svc.read_text_file(p)


@router.put("/memory/file")
def put_memory_file(body: dict, request: Request):
    name = (body.get("name") or "").strip()
    p = _resolve(name)
    if not p.exists():
        raise KeyError(f"'{name}' não existe")
    text = body.get("text", "")
    new_rev = yaml_io.write_text(p, text, expected=_rev(request), backup=True)
    return {"name": name, "rev": new_rev, "tokens": docs_svc.token_estimate(text)}
