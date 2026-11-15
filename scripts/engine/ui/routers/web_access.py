#!/usr/bin/env python3
"""Estado do firewall de acesso web (a edição é pelo PUT /config → web_access; ver services/web_access_svc.py)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services import web_access_svc

router = APIRouter(tags=["web-access"])


@router.get("/web-access")
def get_web_access(request: Request):
    """Política vigente + IP que o servidor enxerga p/ quem pergunta + bloqueios recentes."""
    client = request.client.host if request.client else None
    return web_access_svc.status(client)
