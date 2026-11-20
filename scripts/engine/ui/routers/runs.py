#!/usr/bin/env python3
"""Visualização read-only de runs/<id>/ (estado, coletas, propostas, achados)."""
from __future__ import annotations

from fastapi import APIRouter

import deps
from lib import i18n
from services import docs_svc

router = APIRouter(tags=["runs"])

TEXT_SUFFIXES = {".txt", ".md", ".yaml", ".yml", ".json", ".log", ".rsc", ".cfg", ".conf"}


@router.get("/runs")
def list_runs():
    out = []
    if deps.RUNS_DIR.exists():
        for d in sorted(deps.RUNS_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            status = None
            state = d / "state.json"
            if state.exists():
                import json  # noqa: PLC0415
                try:
                    status = (json.loads(state.read_text(encoding="utf-8")) or {}).get("status")
                except Exception:
                    status = "?"
            out.append({"id": d.name, "status": status})
    return {"runs": out}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    import json  # noqa: PLC0415
    d = docs_svc.safe_child(deps.RUNS_DIR, run_id)
    if not d.exists() or not d.is_dir():
        raise KeyError(i18n.t("api_runs.run_not_exists", run_id=run_id))
    state = {}
    sf = d / "state.json"
    if sf.exists():
        try:
            state = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            state = {"_parse_error": True}
    artifacts = []
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.name != "state.json":
            artifacts.append(str(f.relative_to(d)))
    return {"id": run_id, "state": state, "artifacts": artifacts}


@router.get("/runs/{run_id}/artifact")
def get_artifact(run_id: str, path: str):
    d = docs_svc.safe_child(deps.RUNS_DIR, run_id)
    f = docs_svc.safe_child(d, *path.split("/"))
    if not f.exists() or not f.is_file():
        raise KeyError(i18n.t("api_runs.artifact_not_exists", path=path))
    if f.suffix.lower() not in TEXT_SUFFIXES:
        raise KeyError(i18n.t("api_runs.artifact_not_text"))
    return {"path": path, "text": f.read_text(encoding="utf-8", errors="replace")}
