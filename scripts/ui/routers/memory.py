#!/usr/bin/env python3
"""CRUD de memória: USER.md, MEMORY.md, learned-patterns.yaml e lições (append-only).

Lições NUNCA são apagadas (constituição §II) — só transições de estado
(ativo/stale/archived). Por isso NÃO existe rota de DELETE de lição."""
from __future__ import annotations

import datetime
import re

from fastapi import APIRouter, Request

import deps
from services import docs_svc, yaml_io

router = APIRouter(tags=["memory"])

ESTADOS = ("ativo", "stale", "archived")
_FILES = {"user": deps.USER_MD, "notes": deps.MEMORY_MD}


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _today() -> str:
    return datetime.date.today().isoformat()


# --------------------------------------------------------------------------- #
# learned-patterns.yaml
# --------------------------------------------------------------------------- #
@router.get("/memory/patterns")
def list_patterns():
    import yaml  # noqa: PLC0415
    text, rev, _ = yaml_io.read_text_meta(deps.PATTERNS_FILE)
    data = (yaml.safe_load(text) if text.strip() else {}) or {}
    return {"patterns": data.get("patterns") or [], "last_updated": data.get("last_updated"), "rev": rev}


def _load_patterns_doc():
    data, rev, y = yaml_io.load_rt(deps.PATTERNS_FILE)
    if data is None:
        data = {"version": 1, "patterns": []}
    data.setdefault("patterns", [])
    return data, y


@router.post("/memory/patterns", status_code=201)
def create_pattern(body: dict, request: Request):
    pid = (body.get("id") or "").strip()
    docs_svc.assert_slug(pid, "id")
    data, y = _load_patterns_doc()
    if any(p.get("id") == pid for p in data["patterns"]):
        raise deps.ValidationFailed([{"loc": "id", "msg": f"padrão '{pid}' já existe"}])
    entry = {k: body[k] for k in ("id", "vendor", "tipo", "padrao", "aplicar") if body.get(k) not in (None, "")}
    data["patterns"].append(entry)
    data["last_updated"] = _today()
    new_rev = yaml_io.write_rt(deps.PATTERNS_FILE, y, data, expected=_rev(request), backup=True)
    return {"pattern": entry, "rev": new_rev}


@router.put("/memory/patterns/{pid}")
def update_pattern(pid: str, body: dict, request: Request):
    data, y = _load_patterns_doc()
    target = next((p for p in data["patterns"] if p.get("id") == pid), None)
    if target is None:
        raise KeyError(f"padrão '{pid}' não existe")
    for k in ("vendor", "tipo", "padrao", "aplicar"):
        if k in body:
            target[k] = body[k]
    data["last_updated"] = _today()
    new_rev = yaml_io.write_rt(deps.PATTERNS_FILE, y, data, expected=_rev(request), backup=True)
    return {"pattern": dict(target), "rev": new_rev}


@router.delete("/memory/patterns/{pid}")
def delete_pattern(pid: str, request: Request):
    data, y = _load_patterns_doc()
    before = len(data["patterns"])
    data["patterns"] = [p for p in data["patterns"] if p.get("id") != pid]
    if len(data["patterns"]) == before:
        raise KeyError(f"padrão '{pid}' não existe")
    data["last_updated"] = _today()
    new_rev = yaml_io.write_rt(deps.PATTERNS_FILE, y, data, expected=_rev(request), backup=True)
    return {"deleted": pid, "rev": new_rev}


@router.post("/memory/patterns/{pid}/rename")
def rename_pattern(pid: str, body: dict, request: Request):
    """Renomeia o 'id' do padrão. Padrões não são referenciados por chave => sem cascade."""
    new = (body.get("to") or "").strip()
    docs_svc.assert_slug(new, "to")
    data, y = _load_patterns_doc()
    target = next((p for p in data["patterns"] if p.get("id") == pid), None)
    if target is None:
        raise KeyError(f"padrão '{pid}' não existe")
    if new == pid:
        raise deps.ValidationFailed([{"loc": "to", "msg": "o novo ID é igual ao atual"}])
    if any(p.get("id") == new for p in data["patterns"]):
        raise deps.ValidationFailed([{"loc": "to", "msg": f"padrão '{new}' já existe"}])
    target["id"] = new
    data["last_updated"] = _today()
    new_rev = yaml_io.write_rt(deps.PATTERNS_FILE, y, data, expected=_rev(request), backup=True)
    return {"renamed": {"from": pid, "to": new}, "updated": [], "rev": new_rev}


# --------------------------------------------------------------------------- #
# Lições (append-only)
# --------------------------------------------------------------------------- #
@router.get("/memory/lessons")
def list_lessons():
    import yaml  # noqa: PLC0415
    out = []
    if deps.LESSONS_DIR.exists():
        for f in sorted(deps.LESSONS_DIR.glob("*.yaml")):
            if f.name.startswith("_"):
                continue
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {"_parse_error": True}
            out.append({"file": f.name, **data})
    return {"lessons": out}


@router.get("/memory/lessons/{file}")
def get_lesson(file: str):
    path = docs_svc.safe_child(deps.LESSONS_DIR, file)
    if not path.exists() or path.name.startswith("_"):
        raise KeyError(f"lição '{file}' não existe")
    return docs_svc.read_text_file(path)


@router.post("/memory/lessons", status_code=201)
def create_lesson(body: dict):
    slug = (body.get("slug") or body.get("id") or "").strip()
    docs_svc.assert_slug(slug, "slug")
    fname = f"{_today()}-{slug}.yaml"
    path = docs_svc.safe_child(deps.LESSONS_DIR, fname)
    if path.exists():
        raise deps.ValidationFailed([{"loc": "slug", "msg": f"lição '{fname}' já existe"}])
    lesson = {
        "id": slug,
        "tipo": body.get("tipo", "operational"),
        "vendor": body.get("vendor", "general"),
        "gatilho": body.get("gatilho", ""),
        "licao": body.get("licao", ""),
        "correcao": body.get("correcao", ""),
        "ocorrencias": int(body.get("ocorrencias", 1)),
        "estado": body.get("estado", "ativo"),
        "data": _today(),
        "run_id": body.get("run_id", ""),
    }
    import yaml  # noqa: PLC0415
    deps.LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    yaml_io.atomic_write(path, yaml.safe_dump(lesson, allow_unicode=True, sort_keys=False))
    return {"file": fname, **lesson}


@router.patch("/memory/lessons/{file}/estado")
def set_estado(file: str, body: dict, request: Request):
    estado = body.get("estado")
    if estado not in ESTADOS:
        raise deps.ValidationFailed([{"loc": "estado", "msg": f"use um de: {', '.join(ESTADOS)}"}])
    path = docs_svc.safe_child(deps.LESSONS_DIR, file)
    if not path.exists() or path.name.startswith("_"):
        raise KeyError(f"lição '{file}' não existe")
    data, _, y = yaml_io.load_rt(path)
    if data is None:
        raise KeyError(f"lição '{file}' vazia")
    data["estado"] = estado
    new_rev = yaml_io.write_rt(path, y, data, expected=_rev(request))
    return {"file": file, "estado": estado, "rev": new_rev}


# --------------------------------------------------------------------------- #
# Markdown (USER.md / MEMORY.md) — registrado por ÚLTIMO: o param {which} é genérico
# e não pode sombrear /memory/patterns nem /memory/lessons.
# --------------------------------------------------------------------------- #
@router.get("/memory/{which}")
def get_md(which: str):
    if which not in _FILES:
        raise KeyError(f"arquivo de memória '{which}' inválido")
    return docs_svc.read_text_file(_FILES[which])


@router.put("/memory/{which}")
def put_md(which: str, body: dict, request: Request):
    if which not in _FILES:
        raise KeyError(f"arquivo de memória '{which}' inválido")
    text = body.get("text", "")
    new_rev = yaml_io.write_text(_FILES[which], text, expected=_rev(request), backup=True)
    return {"rev": new_rev, "tokens": docs_svc.token_estimate(text)}
