#!/usr/bin/env python3
"""Projetos da aba Claude Code: nome + pasta do servidor.

Arquivo único `runs/claude/projects.json` (só nome e caminho, nada sensível):
  {"projects": [{"id": "meu-site", "name": "Meu site", "path": "/srv/meu-site", "created": 1760000000}]}

As conversas NÃO são guardadas aqui. O Claude Code já separa os transcripts por pasta
(~/.claude/projects/<pasta>/), então "sessões do projeto" = as sessões daquela pasta
(`directory=` do SDK, ver claude_svc). Remover um projeto só apaga o registro: nunca a pasta
nem as conversas.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import deps

_FILE = deps.RUNS_DIR / "claude" / "projects.json"
_LOCK = threading.Lock()
_MAX_PROJECTS = 200
_MAX_NAME = 80
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RESERVED = {"new"}   # #projects/new é o formulário de criação


class ProjectError(Exception):
    """Erro de validação com código estável (a UI mostra `detail`)."""

    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code = code
        self.status = status


def valid_id(pid: str) -> bool:
    return isinstance(pid, str) and bool(_SLUG_RE.match(pid)) and pid not in _RESERVED


def _load() -> list[dict]:
    try:
        with _FILE.open(encoding="utf-8") as fh:
            d = json.load(fh)
        items = d.get("projects") if isinstance(d, dict) else None
        if isinstance(items, list):
            return [p for p in items if isinstance(p, dict) and valid_id(p.get("id")) and p.get("path")]
    except (OSError, ValueError):
        pass
    return []


def _save(items: list[dict]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump({"projects": items}, fh, ensure_ascii=False, indent=1)
    tmp.replace(_FILE)


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48].strip("-")
    return s or "projeto"


def _clean_name(name) -> str:
    n = " ".join(str(name or "").split())[:_MAX_NAME]
    if not n:
        raise ProjectError("empty_name", "Dê um nome ao projeto.")
    return n


def _resolve_dir(path) -> str:
    raw = str(path or "").strip()
    if not raw or not os.path.isabs(raw):
        raise ProjectError("bad_path", "Informe o caminho absoluto da pasta (começa com /).")
    p = Path(raw)
    try:
        real = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ProjectError("path_not_found", "Essa pasta não existe no servidor.", 404)
    if not real.is_dir():
        raise ProjectError("not_a_dir", "O caminho informado não é uma pasta.")
    if not os.access(real, os.R_OK | os.X_OK):
        raise ProjectError("no_access", "O servidor não tem permissão para ler essa pasta.", 403)
    return str(real)


def _public(p: dict) -> dict:
    return {"id": p["id"], "name": p.get("name") or p["id"], "path": p["path"],
            "created": p.get("created") or 0, "exists": os.path.isdir(p["path"])}


def list_projects() -> list[dict]:
    with _LOCK:
        items = _load()
    return [_public(p) for p in sorted(items, key=lambda x: (x.get("name") or "").lower())]


def get(pid: str) -> dict | None:
    if not valid_id(pid):
        return None
    with _LOCK:
        items = _load()
    for p in items:
        if p["id"] == pid:
            return _public(p)
    return None


def path_of(pid: str) -> str | None:
    """Pasta do projeto, só se ainda existir (o agente nunca roda numa pasta que sumiu)."""
    p = get(pid)
    return p["path"] if p and p["exists"] else None


def create(name, path) -> dict:
    clean = _clean_name(name)
    real = _resolve_dir(path)
    if Path(real) == Path(deps.NETOPS_ROOT).resolve():
        raise ProjectError("is_netops", "A pasta do NetOps já é a aba Claude Code. Escolha outra pasta.")
    with _LOCK:
        items = _load()
        if len(items) >= _MAX_PROJECTS:
            raise ProjectError("too_many", "Limite de projetos atingido.")
        # Dois projetos na mesma pasta dividiriam as mesmas conversas.
        dup = next((p for p in items if p["path"] == real), None)
        if dup:
            raise ProjectError("duplicate_path", f"Essa pasta já é o projeto “{dup.get('name') or dup['id']}”.", 409)
        base = _slug(clean)
        if base in _RESERVED:
            base += "-1"
        taken = {p["id"] for p in items}
        pid, n = base, 1
        while pid in taken or pid in _RESERVED:
            n += 1
            pid = f"{base[:60]}-{n}"
        item = {"id": pid, "name": clean, "path": real, "created": int(time.time())}
        items.append(item)
        _save(items)
    return _public(item)


def rename(pid: str, name) -> dict:
    clean = _clean_name(name)
    with _LOCK:
        items = _load()
        for p in items:
            if p["id"] == pid:
                p["name"] = clean
                _save(items)
                return _public(p)
    raise ProjectError("not_found", "Projeto não encontrado.", 404)


def delete(pid: str) -> bool:
    """Remove só o registro. Pasta e conversas ficam intactas."""
    with _LOCK:
        items = _load()
        keep = [p for p in items if p["id"] != pid]
        if len(keep) == len(items):
            return False
        _save(keep)
    return True


def browse(path: str | None = None, hidden: bool = False) -> dict:
    """Subpastas de `path` (padrão: home do usuário do servidor) para o seletor de pasta."""
    raw = (path or "").strip() or os.path.expanduser("~") or "/"
    real = _resolve_dir(raw)
    dirs: list[dict] = []
    try:
        with os.scandir(real) as it:
            for e in it:
                if not hidden and e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=True):
                        dirs.append({"name": e.name, "path": os.path.join(real, e.name)})
                except OSError:
                    continue
    except OSError:
        raise ProjectError("no_access", "Não foi possível listar essa pasta.", 403)
    dirs.sort(key=lambda d: d["name"].lower())
    parent = None if real == "/" else (os.path.dirname(real) or "/")
    return {"path": real, "parent": parent, "dirs": dirs}
