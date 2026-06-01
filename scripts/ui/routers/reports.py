#!/usr/bin/env python3
"""Visualização read-only de reports/*.md."""
from __future__ import annotations

from fastapi import APIRouter

import deps
from services import docs_svc

router = APIRouter(tags=["reports"])


@router.get("/reports")
def list_reports():
    out = []
    if deps.REPORTS_DIR.exists():
        for f in sorted(deps.REPORTS_DIR.glob("*.md"), reverse=True):
            if f.name.startswith("_") or f.name.upper() == "README.MD":
                continue
            out.append({"file": f.name, "size": f.stat().st_size,
                        "mtime": int(f.stat().st_mtime)})
    return {"reports": out}


@router.get("/reports/{file}")
def get_report(file: str):
    path = docs_svc.safe_child(deps.REPORTS_DIR, file)
    if not path.exists() or path.suffix != ".md":
        raise KeyError(f"relatório '{file}' não existe")
    return {"file": file, "markdown": path.read_text(encoding="utf-8")}
