"""Consulta de releases e aplicação autenticada, com barreira de manutenção."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

import deps
from lib import i18n
from services import updates_svc
from update.common import UpdateError

router = APIRouter(tags=["updates"])


class ApplyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: int = Field(gt=0, strict=True)
    confirm: bool


def _error(exc: UpdateError):
    return JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=409)


@router.get("/updates/status")
def update_status():
    try:
        return updates_svc.local_status()
    except UpdateError as exc:
        return _error(exc)


@router.get("/updates/check")
def check_updates():
    try:
        return updates_svc.check()
    except UpdateError as exc:
        return _error(exc)


@router.post("/updates/apply", status_code=202)
async def apply_update(body: ApplyUpdate, request: Request):
    if not deps.auth_required() or not deps.auth_session_valid(request.headers.get("x-netops-session")):
        # Permissão (`updates`, só admin) já foi checada no middleware; aqui só exige login de verdade.
        return JSONResponse({"error": "auth_required", "detail": i18n.t("api_updates.login_required")}, status_code=401)
    if not body.confirm:
        return JSONResponse({"error": "confirmation_required"}, status_code=422)
    if deps.STATE.update_pending or updates_svc.maintenance():
        return JSONResponse({"error": "busy", "detail": i18n.t("api_updates.busy")}, status_code=409)
    deps.STATE.update_pending = True
    try:
        deadline = asyncio.get_running_loop().time() + 30
        while deps.STATE.active_writes or deps.STATE.active_requests > 1:
            if asyncio.get_running_loop().time() >= deadline:
                raise UpdateError("active_writes", i18n.t("api_updates.active_writes"))
            await asyncio.sleep(0.05)
        return await run_in_threadpool(updates_svc.request_update, body.release_id)
    except UpdateError as exc:
        return _error(exc)
    finally:
        deps.STATE.update_pending = False
