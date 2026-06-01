#!/usr/bin/env python3
"""Monta o app FastAPI: segurança (token + Origin/Host), handlers de erro, routers, static.

O servidor é STATELESS — cada request lê/escreve os arquivos canônicos. Não há cache de
inventário em RAM, nem worker, nem conexão a equipamento. (Ver scripts/ui/SKILL.md e a
cláusula da constituição §VII sobre ferramentas de operador efêmeras.)
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import deps
from routers import (
    catalog,
    config,
    credentials,
    hosts,
    knowledge,
    memory,
    meta,
    reports,
    runs,
    terminal,
    topology,
)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _host_ok(host_header: str | None) -> bool:
    """Host header (sem porta) precisa ser loopback — barra DNS-rebinding."""
    if not host_header:
        return False
    hostname = host_header.rsplit(":", 1)[0].strip("[]")
    return hostname in deps.STATE.allowed_hosts


def _origin_ok(origin: str | None) -> bool:
    """Origin ausente é ok (cliente não-browser). Presente => precisa ser loopback."""
    if not origin:
        return True
    try:
        hostname = urlparse(origin).hostname or ""
    except ValueError:
        return False
    return hostname in deps.STATE.allowed_hosts


def _supplied_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token")


def create_app() -> FastAPI:
    app = FastAPI(title="NetOps Console", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api"):
            # Anti DNS-rebinding: Host tem que ser loopback.
            if not _host_ok(request.headers.get("host")):
                return JSONResponse({"error": "forbidden_host"}, status_code=403)
            # Token obrigatório em toda a API (docs/openapi inclusos).
            if not deps.token_matches(_supplied_token(request)):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            if request.method in MUTATING:
                if not _origin_ok(request.headers.get("origin")):
                    return JSONResponse({"error": "forbidden_origin"}, status_code=403)
                if deps.STATE.read_only:
                    return JSONResponse(
                        {"error": "read_only", "detail": "servidor em modo somente-leitura (--read-only)"},
                        status_code=403,
                    )
        return await call_next(request)

    _register_error_handlers(app)

    for mod in (meta, hosts, credentials, topology, config, memory, knowledge, catalog, reports, runs, terminal):
        app.include_router(mod.router, prefix="/api")

    # SPA: serve scripts/ui/static/ na raiz (index.html cobre o fallback de rotas hash).
    if deps.STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(deps.STATIC_DIR), html=True), name="static")

    return app


def _register_error_handlers(app: FastAPI) -> None:
    from lib.vault import VaultLocked, VaultNotInitialized, VaultWrongKey

    @app.exception_handler(deps.ConflictError)
    async def _conflict(_request, exc: deps.ConflictError):
        return JSONResponse(
            {"error": "conflict", "detail": exc.detail, "current": exc.current_hash},
            status_code=409,
        )

    @app.exception_handler(deps.ValidationFailed)
    async def _validation(_request, exc: deps.ValidationFailed):
        return JSONResponse({"error": "validation", "errors": exc.errors}, status_code=422)

    @app.exception_handler(deps.ReadOnlyMode)
    async def _readonly(_request, _exc):
        return JSONResponse({"error": "read_only"}, status_code=403)

    @app.exception_handler(VaultLocked)
    async def _locked(_request, exc: VaultLocked):
        return JSONResponse(
            {
                "error": "vault_locked",
                "detail": str(exc),
                "action": "cd /home/francisco/netops && .venv/bin/python3 scripts/vault/cli.py unlock",
            },
            status_code=423,
        )

    @app.exception_handler(VaultNotInitialized)
    async def _uninit(_request, exc: VaultNotInitialized):
        return JSONResponse(
            {
                "error": "vault_uninitialized",
                "detail": str(exc),
                "action": "python scripts/vault/cli.py init",
            },
            status_code=409,
        )

    @app.exception_handler(VaultWrongKey)
    async def _wrongkey(_request, exc: VaultWrongKey):
        return JSONResponse({"error": "vault_wrong_key", "detail": str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def _notfound(_request, exc: KeyError):
        return JSONResponse({"error": "not_found", "detail": str(exc).strip("'\"")}, status_code=404)
