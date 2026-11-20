#!/usr/bin/env python3
"""Editores de workflows/*.workflow.yaml e agents/*.agent.md (texto cru + validação).

Avançado: edição como texto. Workflows validam parse YAML + presença de workflow.steps;
agents validam o frontmatter (id/name/function)."""
from __future__ import annotations

from fastapi import APIRouter, Request

import deps
from lib import i18n
from services import docs_svc, yaml_io

router = APIRouter(tags=["catalog"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _safe(base, name: str):
    if not name.startswith("_") and ("/" in name or name.startswith(".")):
        raise deps.ValidationFailed([{"loc": "file", "msg": i18n.t("api_common.invalid_filename")}])
    return docs_svc.safe_child(base, name)


def _rename_doc(base, file: str, to: str, suffix: str) -> dict:
    """Renomeia o arquivo no disco (workflow/agent). O conteúdo não muda; o 'id' interno
    é independente do nome do arquivo, então não há cascade."""
    import os  # noqa: PLC0415
    if not to.endswith(suffix):
        raise deps.ValidationFailed([{"loc": "to", "msg": i18n.t("api_common.name_must_end", suffix=suffix)}])
    src = _safe(base, file)
    if not src.exists():
        raise KeyError(i18n.t("api_common.quoted_not_exists", name=file))
    dst = _safe(base, to)
    if dst == src:
        raise deps.ValidationFailed([{"loc": "to", "msg": i18n.t("api_common.same_target")}])
    if dst.exists():
        raise deps.ValidationFailed([{"loc": "to", "msg": i18n.t("api_common.quoted_exists", name=to)}])
    os.replace(src, dst)
    return {"renamed": {"from": file, "to": to}, "updated": []}


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #
@router.get("/workflows")
def list_workflows():
    import yaml  # noqa: PLC0415
    out = []
    for f in sorted(deps.WORKFLOWS_DIR.glob("*.workflow.yaml")):
        if f.name.startswith("_"):
            continue
        try:
            wf = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("workflow") or {}
        except Exception:
            wf = {}
        out.append({"file": f.name, "id": wf.get("id"), "name": wf.get("name"),
                    "steps": len(wf.get("steps") or [])})
    return {"workflows": out}


@router.get("/workflows/{file}")
def get_workflow(file: str):
    path = _safe(deps.WORKFLOWS_DIR, file)
    if not path.exists():
        raise KeyError(i18n.t("api_catalog.workflow_not_exists", file=file))
    return docs_svc.read_text_file(path)


@router.put("/workflows/{file}")
def put_workflow(file: str, body: dict, request: Request):
    path = _safe(deps.WORKFLOWS_DIR, file)
    text = body.get("text", "")
    _validate_workflow(text)
    new_rev = yaml_io.write_text(path, text, expected=_rev(request), backup=True)
    return {"file": file, "rev": new_rev}


@router.post("/workflows", status_code=201)
def create_workflow(body: dict):
    name = body.get("file", "")
    if not name.endswith(".workflow.yaml"):
        raise deps.ValidationFailed([{"loc": "file", "msg": i18n.t("api_common.name_must_end", suffix=".workflow.yaml")}])
    path = _safe(deps.WORKFLOWS_DIR, name)
    if path.exists():
        raise deps.ValidationFailed([{"loc": "file", "msg": i18n.t("api_common.quoted_exists", name=name)}])
    text = body.get("text", "")
    _validate_workflow(text)
    yaml_io.atomic_write(path, text)
    return {"file": name, "rev": yaml_io.file_rev(path)}


@router.post("/workflows/{file}/rename")
def rename_workflow(file: str, body: dict):
    return _rename_doc(deps.WORKFLOWS_DIR, file, (body.get("to") or "").strip(), ".workflow.yaml")


def _validate_workflow(text: str) -> None:
    import yaml  # noqa: PLC0415
    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:
        raise deps.ValidationFailed([{"loc": "text", "msg": i18n.t("api_common.invalid_yaml", error=exc)}]) from exc
    wf = data.get("workflow")
    if not isinstance(wf, dict) or not wf.get("steps"):
        raise deps.ValidationFailed([{"loc": "workflow", "msg": i18n.t("api_catalog.missing_workflow_steps")}])


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #
@router.get("/agents")
def list_agents():
    out = []
    for f in sorted(deps.AGENTS_DIR.glob("*.agent.md")):
        if f.name.startswith("_"):
            continue
        fm, _ = docs_svc.split_frontmatter(f.read_text(encoding="utf-8"))
        fm = fm or {}
        out.append({"file": f.name, "id": fm.get("id"), "name": fm.get("name"),
                    "icon": fm.get("icon"), "function": fm.get("function")})
    return {"agents": out}


@router.get("/agents/{file}")
def get_agent(file: str):
    path = _safe(deps.AGENTS_DIR, file)
    if not path.exists():
        raise KeyError(i18n.t("api_catalog.agent_not_exists", file=file))
    info = docs_svc.read_text_file(path)
    info["frontmatter"], _ = docs_svc.split_frontmatter(info["text"])
    return info


@router.put("/agents/{file}")
def put_agent(file: str, body: dict, request: Request):
    path = _safe(deps.AGENTS_DIR, file)
    text = body.get("text", "")
    _validate_agent(text)
    new_rev = yaml_io.write_text(path, text, expected=_rev(request), backup=True)
    return {"file": file, "rev": new_rev}


@router.post("/agents", status_code=201)
def create_agent(body: dict):
    name = body.get("file", "")
    if not name.endswith(".agent.md"):
        raise deps.ValidationFailed([{"loc": "file", "msg": i18n.t("api_common.name_must_end", suffix=".agent.md")}])
    path = _safe(deps.AGENTS_DIR, name)
    if path.exists():
        raise deps.ValidationFailed([{"loc": "file", "msg": i18n.t("api_common.quoted_exists", name=name)}])
    text = body.get("text", "")
    _validate_agent(text)
    yaml_io.atomic_write(path, text)
    return {"file": name, "rev": yaml_io.file_rev(path)}


@router.post("/agents/{file}/rename")
def rename_agent(file: str, body: dict):
    return _rename_doc(deps.AGENTS_DIR, file, (body.get("to") or "").strip(), ".agent.md")


def _validate_agent(text: str) -> None:
    fm, _ = docs_svc.split_frontmatter(text)
    if not isinstance(fm, dict):
        raise deps.ValidationFailed([{"loc": "text", "msg": i18n.t("api_catalog.bad_frontmatter")}])
    missing = [k for k in ("id", "name", "function") if not fm.get(k)]
    if missing:
        raise deps.ValidationFailed([{"loc": "frontmatter", "msg": i18n.t("api_catalog.missing_fields", fields=", ".join(missing))}])
