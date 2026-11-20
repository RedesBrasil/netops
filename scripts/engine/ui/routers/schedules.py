#!/usr/bin/env python3
"""Tarefas agendadas (network/schedules.yaml) — CRUD, executar agora, histórico e notificações.

O console só edita o cadastro e lê os resultados; quem dispara é o cron do sistema
(`/etc/cron.d/netops-scheduler` → `scripts/engine/scheduler/cli.py tick`). Mesmo motor do CLI
que o agente de IA usa ao agendar pelo chat. Ver scripts/engine/scheduler/SKILL.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Query, Request

import deps
from lib import i18n
from scheduler import runner, store

router = APIRouter(tags=["schedules"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except store.TaskError as e:
        raise deps.ValidationFailed(e.errors)
    except store.RevConflict as e:
        raise deps.ConflictError(e.current, i18n.t("api_schedules.conflict"))


@router.get("/schedules")
def overview():
    """Tarefas + próxima/última execução + saúde do cron + contador de não lidas."""
    return runner.overview(deps.DATA_ROOT)


@router.get("/schedules/notifications")
def notifications():
    return {"unread": len(store.read_state(deps.DATA_ROOT)["unread"])}


@router.post("/schedules/notifications/read")
def mark_read(body: dict = Body(default={})):
    """{"keys": ["<tarefa>/<run>", ...]} marca essas; sem keys marca todas."""
    keys = body.get("keys")
    return {"unread": runner.mark_read(keys if isinstance(keys, list) else None, deps.DATA_ROOT)}


@router.get("/schedules/preview")
def preview(type: str = "cron", expr: str = "", minutes: int = 0, at: str = ""):
    """Próximos horários de uma agenda (valida a expressão enquanto o usuário digita)."""
    cfg = store.load(deps.DATA_ROOT)["config"]
    sch = {"type": type, "expr": expr, "minutes": minutes, "at": at}
    try:
        return {"next_runs": store.preview({"schedule": sch}, cfg["timezone"], 5), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"next_runs": [], "error": str(e)}


@router.get("/schedules/scripts")
def script_candidates():
    """Scripts de scripts/tools/ (sugestões p/ o campo de comando)."""
    out = []
    for p in sorted(deps.TOOLS_DIR.rglob("*")):
        if p.suffix in deps.SCRIPT_EXTS and p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(deps.NETOPS_ROOT)
            out.append(("python3 " if p.suffix == ".py" else "bash ") + str(rel))
    return {"scripts": out}


@router.post("/schedules/tasks")
def create(request: Request, body: dict = Body(...)):
    from services import authz  # noqa: PLC0415
    who = authz.request_principal(request).username or "ui"
    return _call(store.create_task, {k: v for k, v in body.items() if k != "created_by"}, _rev(request),
                 deps.DATA_ROOT, created_by=who)


@router.put("/schedules/tasks/{task_id}")
def update(task_id: str, request: Request, body: dict = Body(...)):
    return _call(store.update_task, task_id, body, _rev(request), deps.DATA_ROOT)


@router.delete("/schedules/tasks/{task_id}")
def delete(task_id: str, request: Request):
    return _call(store.delete_task, task_id, _rev(request), deps.DATA_ROOT)


@router.post("/schedules/tasks/{task_id}/run")
def run_now(task_id: str):
    """Dispara agora, em segundo plano (mesmo executor do cron)."""
    return {"run_id": runner.run_now(task_id, deps.DATA_ROOT)}


@router.put("/schedules/timezone")
def set_timezone(request: Request, body: dict = Body(...)):
    return _call(store.set_timezone, str(body.get("timezone") or ""), _rev(request), deps.DATA_ROOT)


@router.post("/schedules/cron/install")
def install_cron():
    return store.install_cron(deps.DATA_ROOT)


@router.get("/schedules/runs")
def runs(task: str | None = Query(default=None), limit: int = 300):
    return {"runs": runner.list_runs(deps.DATA_ROOT, task or None, min(max(limit, 1), 1000))}


@router.get("/schedules/runs/{task_id}/{run_id}")
def run_detail(task_id: str, run_id: str):
    return runner.read_run(task_id, run_id, deps.DATA_ROOT)
