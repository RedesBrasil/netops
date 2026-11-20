#!/usr/bin/env python3
"""Central de Avisos (runs/inbox.db) — listar, ler, arquivar e decidir pedidos de aprovação.

Mensagens nascem fora do console (tarefas agendadas, scripts e agentes via scripts/engine/inbox/cli.py);
por isso não há rota de criação aqui — nenhum navegador consegue enfileirar um comando para rodar como root.
Decidir pedido que tem AÇÃO (comando/agente rodando no servidor) = só administrador.
Ver scripts/engine/inbox/SKILL.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

import deps
from lib import i18n
from inbox import actions, store

router = APIRouter(tags=["inbox"])


def _user(request: Request) -> str:
    from services import authz  # noqa: PLC0415
    return authz.request_principal(request).username or "ui"


def _get(mid: int) -> dict:
    try:
        return store.get(mid, deps.DATA_ROOT)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


def _ids(body: dict) -> list[int] | None:
    ids = body.get("ids")
    if ids is None:
        return None
    if not isinstance(ids, list):
        raise deps.ValidationFailed([{"loc": "ids", "msg": i18n.t("api_inbox.ids_list")}])
    try:
        return [int(i) for i in ids]
    except (TypeError, ValueError):
        raise deps.ValidationFailed([{"loc": "ids", "msg": i18n.t("api_inbox.integer_ids")}])


@router.get("/inbox/summary")
def summary():
    """Contadores do sino do topo (badge = não lidas + pedidos pendentes)."""
    return store.summary(deps.DATA_ROOT)


@router.get("/inbox")
def list_messages(view: str = "open", limit: int = 500):
    if view not in store.VIEWS:
        view = "open"
    return {"items": store.list_messages(view, limit, deps.DATA_ROOT), "summary": store.summary(deps.DATA_ROOT)}


@router.get("/inbox/{mid}")
def detail(mid: int):
    rec = _get(mid)
    log = store.data_root(deps.DATA_ROOT) / "runs" / "inbox" / f"{int(mid)}.log"
    rec["log"] = log.read_text(encoding="utf-8", errors="replace")[-10_000:] if log.exists() else ""
    return rec


@router.post("/inbox/read")
def mark_read(request: Request, body: dict = Body(default={})):
    """{"ids": [..]} marca essas; sem ids marca todas como lidas."""
    store.mark_read(_ids(body), _user(request), deps.DATA_ROOT)
    return store.summary(deps.DATA_ROOT)


@router.post("/inbox/{mid}/unread")
def mark_unread(mid: int):
    _get(mid)
    store.mark_unread(mid, deps.DATA_ROOT)
    return store.summary(deps.DATA_ROOT)


@router.post("/inbox/archive")
def archive(request: Request, body: dict = Body(default={})):
    """{"ids": [..], "archived": true|false} ou {"read": true} = arquiva tudo que já foi lido."""
    if body.get("read"):
        n = store.archive_read(_user(request), deps.DATA_ROOT)
    else:
        n = store.set_archived(_ids(body) or [], body.get("archived", True) is not False, _user(request),
                               deps.DATA_ROOT)
    return {"changed": n, **store.summary(deps.DATA_ROOT)}


@router.post("/inbox/{mid}/decision")
def decide(mid: int, request: Request, body: dict = Body(...)):
    """{"decision": "approve"|"reject", "note": "..."} — o primeiro a decidir vence (409 depois)."""
    from services import authz  # noqa: PLC0415
    rec = _get(mid)
    if rec["actionable"]:
        p = authz.request_principal(request)
        if not p.is_admin:
            raise authz.Forbidden("inbox.decide", i18n.t("api_inbox.decide_admin_only"))
    try:
        rec = store.decide(mid, str(body.get("decision") or ""), _user(request), str(body.get("note") or ""),
                           deps.DATA_ROOT)
    except store.InboxError as e:
        raise deps.ValidationFailed(e.errors)
    except store.NotPending as e:
        raise HTTPException(409, str(e))
    if rec["actionable"]:
        actions.spawn(mid, deps.DATA_ROOT)
        rec = store.get(mid, deps.DATA_ROOT)
    return rec
