#!/usr/bin/env python3
"""CRUD dos scripts operacionais em scripts/tools/ (Python/Shell) — texto cru + trava otimista.

São os scripts que o usuário cria/edita p/ acessar roteadores, diagnosticar, analisar etc.
O motor do NetOps (scripts/engine: lib, vault, ui) NÃO é exposto aqui. A UI mostra UMA tabela
única (ordenável/pesquisável); a pasta de cada script vira uma coluna/tag ("location"). Só
lista .py/.sh — docs (.md) não viram linha, mas aparecem como ícone no próprio script.

Skills: cada pasta de tools/ é uma skill (padrão Agent Skills: pasta = SKILL.md + scripts).
`GET /scripts` devolve também `skills` (id=pasta, name/description do frontmatter do SKILL.md,
nº de scripts). Skill sem script é válida (só a doc); script sem SKILL.md fica "sem doc".
Não executa nada — rodar continua no Terminal/Claude. Caminho relativo a tools/ via `path`."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request

import deps
from services import docs_svc, yaml_io

router = APIRouter(tags=["scripts"])

_IGNORE = {"__pycache__", ".git", ".pytest_cache"}
_LANG = {".py": "python", ".sh": "shell"}


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _resolve(rel: str) -> Path:
    """Resolve um caminho relativo dentro de scripts/tools/, barrando traversal."""
    parts = [p for p in (rel or "").strip().strip("/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise deps.ValidationFailed([{"loc": "path", "msg": "caminho inválido"}])
    return docs_svc.safe_child(deps.TOOLS_DIR, *parts)   # garante dentro de tools/


def _describe(path: Path) -> str:
    """1ª linha útil do docstring (.py) ou comentário (.sh). Best-effort."""
    try:
        text, _, _ = yaml_io.read_text_meta(path)
        if not text.strip():
            return ""
        if path.suffix == ".py":
            for q in ('"""', "'''"):
                i = text.find(q)
                if 0 <= i < 200:
                    rest = text[i + 3:]
                    return (rest.splitlines()[0].strip() if rest.strip() else "")
            return ""
        if path.suffix == ".sh":
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("#!") or not s:
                    continue
                return s.lstrip("#").strip() if s.startswith("#") else ""
        return ""
    except Exception:
        return ""


def _doc_for(path: Path) -> str | None:
    """Doc associada a um script: .md de mesmo nome, senão o SKILL.md da pasta. Caminho rel a tools/."""
    sibling = path.with_suffix(".md")
    if sibling.exists():
        return str(sibling.relative_to(deps.TOOLS_DIR))
    skill = path.parent / "SKILL.md"
    if skill.exists():
        return str(skill.relative_to(deps.TOOLS_DIR))
    return None


def _skill_meta(folder: Path) -> dict:
    """name/description do frontmatter do SKILL.md (senão 1º título/parágrafo). Best-effort."""
    skill = folder / "SKILL.md"
    meta = {"id": folder.name, "name": folder.name, "description": "",
            "doc": str(skill.relative_to(deps.TOOLS_DIR)) if skill.exists() else None}
    if not skill.exists():
        return meta
    try:
        text, _, _ = yaml_io.read_text_meta(skill)
        fm, body = docs_svc.split_frontmatter(text)
        if isinstance(fm, dict):
            meta["name"] = str(fm.get("name") or folder.name)
            meta["description"] = str(fm.get("description") or "")
        if not meta["description"] or meta["name"] == folder.name:
            lines = [ln.strip() for ln in body.splitlines()]
            for ln in lines:
                if ln.startswith("# ") and meta["name"] == folder.name:
                    meta["name"] = ln[2:].replace("SKILL —", "").strip() or folder.name
                elif ln and not ln.startswith(("#", "|", "```", "-", ">")) and not meta["description"]:
                    meta["description"] = ln
                if meta["description"] and meta["name"] != folder.name:
                    break
    except Exception:
        pass
    return meta


def _skip(rel: Path) -> bool:
    return any(p in _IGNORE or p.startswith(".") or p.startswith("_") for p in rel.parts)


@router.get("/scripts")
def list_scripts():
    """Lista única de scripts operacionais (.py/.sh) de tools/. Cada item traz a pasta
    (location), a linguagem e a doc associada (se houver). Ignora _TEMPLATE e ocultos."""
    base = deps.TOOLS_DIR
    out = []
    if base.exists():
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix not in deps.SCRIPT_EXTS:
                continue
            rel = f.relative_to(base)
            if _skip(rel):
                continue
            location = rel.parts[0] if len(rel.parts) > 1 else "(raiz)"
            out.append({
                "path": str(rel), "name": f.name, "ext": f.suffix,
                "location": location, "lang": _LANG.get(f.suffix, f.suffix.lstrip(".")),
                "desc": _describe(f), "doc": _doc_for(f),
            })
    locations = sorted({s["location"] for s in out})
    skills = []
    if base.exists():
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if _skip(d.relative_to(base)):
                continue
            meta = _skill_meta(d)
            meta["scripts"] = sum(1 for s in out if s["location"] == d.name)
            if meta["scripts"] or meta["doc"]:
                skills.append(meta)
    return {"scripts": out, "locations": locations, "skills": skills}


@router.get("/scripts/file")
def get_script(path: str):
    p = _resolve(path)
    if not p.exists():
        raise KeyError(f"script '{path}' não existe")
    info = docs_svc.read_text_file(p)
    if p.suffix == ".md":
        info["frontmatter"], _ = docs_svc.split_frontmatter(info["text"])
    return info


@router.post("/scripts", status_code=201)
def create_script(body: dict):
    rel = (body.get("path") or "").strip()
    p = _resolve(rel)
    is_skill_doc = p.name == "SKILL.md" and p.parent != deps.TOOLS_DIR.resolve()
    if p.suffix not in deps.SCRIPT_EXTS and not is_skill_doc:
        raise deps.ValidationFailed(
            [{"loc": "path", "msg": f"só Python/Shell ({', '.join(deps.SCRIPT_EXTS)}) ou <skill>/SKILL.md"}]
        )
    if p.exists():
        raise deps.ValidationFailed([{"loc": "path", "msg": f"'{rel}' já existe"}])
    p.parent.mkdir(parents=True, exist_ok=True)
    yaml_io.atomic_write(p, body.get("text", ""))
    return {"path": str(p.relative_to(deps.TOOLS_DIR)), "rev": yaml_io.file_rev(p)}


@router.put("/scripts/file")
def update_script(body: dict, request: Request):
    rel = (body.get("path") or "").strip()
    p = _resolve(rel)
    if not p.exists():
        raise KeyError(f"script '{rel}' não existe")
    new_rev = yaml_io.write_text(p, body.get("text", ""), expected=_rev(request), backup=True)
    return {"path": str(p.relative_to(deps.TOOLS_DIR)), "rev": new_rev}


@router.post("/scripts/rename")
def rename_script(body: dict):
    src = _resolve((body.get("path") or "").strip())
    to = (body.get("to") or "").strip()
    dst = _resolve(to)
    if not src.exists():
        raise KeyError(f"script '{body.get('path')}' não existe")
    if dst.suffix not in deps.SCRIPT_EXTS:
        raise deps.ValidationFailed(
            [{"loc": "to", "msg": f"só Python/Shell: {', '.join(deps.SCRIPT_EXTS)}"}]
        )
    if dst == src:
        raise deps.ValidationFailed([{"loc": "to", "msg": "destino igual à origem"}])
    if dst.exists():
        raise deps.ValidationFailed([{"loc": "to", "msg": f"'{to}' já existe"}])
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    return {"renamed": {"from": str(src.relative_to(deps.TOOLS_DIR)),
                        "to": str(dst.relative_to(deps.TOOLS_DIR))},
            "rev": yaml_io.file_rev(dst)}


@router.delete("/scripts/file")
def delete_script(path: str):
    p = _resolve(path)
    if not p.exists():
        raise KeyError(f"script '{path}' não existe")
    p.unlink()
    return {"deleted": str(p.relative_to(deps.TOOLS_DIR))}
