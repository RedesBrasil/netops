#!/usr/bin/env python3
"""Auditoria do console (menu Sistema → Auditoria; só admin, `audit.view`).

Registra quem fez o quê: login/logout/falha de login, toda escrita na API (método, caminho, status —
nunca o corpo), abertura de terminal de servidor/host, aba Claude e mudanças de usuário/grupo.
Fica no banco de acesso (lib/accessdb.py, tabela `audit`); retenção em ui.audit_keep_days (365).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

import deps
from lib import accessdb

router = APIRouter(tags=["audit"])


@router.get("/audit")
def audit_list(user: str = "", action: str = "", q: str = "", since: Optional[float] = None,
               until: Optional[float] = None, limit: int = 200, offset: int = 0) -> dict:
    return accessdb.query_audit(deps.db_file(), username=user, action=action, q=q, since=since,
                                until=until, limit=limit, offset=offset)
