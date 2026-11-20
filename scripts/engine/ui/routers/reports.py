#!/usr/bin/env python3
"""Visualização read-only de reports/*.md."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse

import deps
from services import docs_svc

router = APIRouter(tags=["reports"])

# extensão -> content-type exibível no navegador (texto sempre como text/plain: nunca executa HTML)
VIEWABLE = {".md": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
            ".log": "text/plain; charset=utf-8", ".pdf": "application/pdf"}


@router.get("/reports")
def list_reports():
    out = []
    if deps.REPORTS_DIR.exists():
        for f in sorted((x for x in deps.REPORTS_DIR.iterdir() if x.suffix.lower() in VIEWABLE), reverse=True):
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


@router.get("/reports/{file}/raw")
def raw_report(file: str, download: bool = False):
    """Arquivo cru de reports/ (md/txt/log/pdf) p/ o visualizador e o botão Baixar."""
    path = docs_svc.safe_child(deps.REPORTS_DIR, file)
    ctype = VIEWABLE.get(path.suffix.lower())
    if not path.is_file() or not ctype:
        raise KeyError(f"relatório '{file}' não existe")
    disp = "attachment" if download else "inline"
    return FileResponse(path, media_type=ctype, headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(path.name)}",
        "X-Content-Type-Options": "nosniff"})
