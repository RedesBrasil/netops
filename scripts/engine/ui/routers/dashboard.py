#!/usr/bin/env python3
"""Painel: consumo do host e consumo de IA (read-only)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from services import dashboard_svc

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/host")
def host():
    return dashboard_svc.host_stats()


@router.get("/dashboard/ai")
def ai(days: int = Query(30, ge=1, le=365), start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
       end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), model: str | None = None,
       tz: int = Query(0, ge=-900, le=900)):
    return dashboard_svc.ai_usage(days=days, start=start, end=end, model=model or None, tz_offset_min=tz)
