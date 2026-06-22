#!/usr/bin/env python3
"""Helpers de arquivos de texto/markdown e travas de caminho (anti path-traversal).

Usado por memory/knowledge/catalog. Mantém a UI dentro dos diretórios canônicos."""
from __future__ import annotations

import re
from pathlib import Path

import deps
from services import yaml_io


def token_estimate(text: str) -> int:
    """Estimativa grosseira de tokens (~4 chars/token) p/ o medidor de orçamento."""
    return max(1, round(len(text) / 4))


def read_text_file(path: Path) -> dict:
    text, rev, _ = yaml_io.read_text_meta(path)
    return {"text": text, "rev": rev, "tokens": token_estimate(text), "exists": path.exists()}


def safe_child(base: Path, *parts: str) -> Path:
    """Resolve base/<parts...> garantindo que o resultado fique DENTRO de base."""
    candidate = base.joinpath(*parts).resolve()
    base_resolved = base.resolve()
    if base_resolved != candidate and base_resolved not in candidate.parents:
        raise deps.ValidationFailed([{"loc": "path", "msg": "caminho fora do diretório permitido"}])
    return candidate


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def assert_slug(value: str, loc: str = "name") -> None:
    if not SLUG_RE.match(value):
        raise deps.ValidationFailed(
            [{"loc": loc, "msg": "use kebab-case (a-z, 0-9, hífen), começando por letra/dígito"}]
        )


def assert_vendor(vendor: str) -> None:
    if vendor not in deps.VENDORS:
        raise deps.ValidationFailed(
            [{"loc": "vendor", "msg": f"vendor inválido. Use um de: {', '.join(deps.VENDORS)}"}]
        )


# --------------------------------------------------------------------------- #
# Frontmatter (agents/*.agent.md, best-practices/*.md)
# --------------------------------------------------------------------------- #
_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict | None, str]:
    import yaml  # noqa: PLC0415
    m = _FM_RE.match(text)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        fm = None
    return fm, m.group(2)
