#!/usr/bin/env python3
"""Catálogo local de ícones de rede. Nenhuma consulta remota em execução."""
import json

import deps


def catalog() -> list[dict]:
    path = deps.STATIC_DIR / "icons" / "network" / "catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))


def choices() -> dict:
    return {"icons": [{"id": icon["id"], "name": icon["name"],
                       "url": "/icons/network/thumbnails/" + icon["file"]} for icon in catalog()]}


def known_icon(ident: str) -> bool:
    return any(icon["id"] == ident for icon in catalog())
