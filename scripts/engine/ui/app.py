#!/usr/bin/env python3
"""Monta o app FastAPI: segurança (Origin/Host + login por senha-mestra), handlers de erro, routers, static.

O servidor é STATELESS — cada request lê/escreve os arquivos canônicos. Não há cache de
inventário em RAM, nem worker, nem conexão a equipamento. (Ver scripts/engine/ui/SKILL.md e a
cláusula da constituição §VII sobre ferramentas de operador efêmeras.)
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


class _NoCacheStatic(StaticFiles):
    """Estaticos com revalidacao obrigatoria: o browser sempre checa com o servidor
    (ETag/Last-Modified -> 304 quando nao mudou), entao nunca serve JS/CSS velho de cache."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

import deps
from routers import (
    auth,
    backups,
    catalog,
    claude,
    config,
    credentials,
    hosts,
    knowledge,
    memory,
    meta,
    reports,
    runs,
    scripts,
    terminal,
    topology,
)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Endpoints de bootstrap do login — alcançáveis sem sessão (a própria tela de login os chama).
AUTH_OPEN_PATHS = {"/api/auth/login", "/api/auth/status", "/api/auth/logout", "/api/config/meta"}


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


def create_app() -> FastAPI:
    app = FastAPI(title="NetOps Console", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api"):
            # Anti DNS-rebinding: Host tem que ser loopback.
            if not _host_ok(request.headers.get("host")):
                return JSONResponse({"error": "forbidden_host"}, status_code=403)
            # Gate de login: com cofre inicializado, todo /api exige sessão (senha-mestra),
            # exceto a allow-list de bootstrap (login/status/logout/meta).
            if (deps.auth_required() and path not in AUTH_OPEN_PATHS
                    and not deps.auth_session_valid(request.headers.get("x-netops-session"))):
                return JSONResponse({"error": "auth_required"}, status_code=401)
            if request.method in MUTATING:
                if not _origin_ok(request.headers.get("origin")):
                    return JSONResponse({"error": "forbidden_origin"}, status_code=403)
                if deps.STATE.read_only:
                    return JSONResponse(
                        {"error": "read_only", "detail": "servidor em modo somente-leitura (--read-only)"},
                        status_code=403,
                    )

        response = await call_next(request)

        # O shell do SPA (index.html) não é cacheado: garante que o front sempre venha da rede
        # (o HTML tem ~1 KB). Os assets estáticos (js/css/vendor) seguem cacheáveis pelo ETag.
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    _register_error_handlers(app)

    for mod in (auth, meta, hosts, credentials, topology, config, memory, knowledge, catalog, scripts, reports, runs, backups, terminal, claude):
        app.include_router(mod.router, prefix="/api")

    @app.on_event("shutdown")
    async def _claude_shutdown():  # noqa: ANN202
        # Mata sessões Claude vivas (persist) p/ não deixar subprocesso `claude` órfão num deploy.
        from services import claude_svc  # noqa: PLC0415
        await claude_svc.shutdown_all()

    # SPA: serve scripts/engine/ui/static/ na raiz (index.html cobre o fallback de rotas hash).
    if deps.STATIC_DIR.exists():
        app.mount("/", _NoCacheStatic(directory=str(deps.STATIC_DIR), html=True), name="static")

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
                "action": "cd /opt/netops && .venv/bin/python3 scripts/engine/vault/cli.py unlock",
            },
            status_code=423,
        )

    @app.exception_handler(VaultNotInitialized)
    async def _uninit(_request, exc: VaultNotInitialized):
        return JSONResponse(
            {
                "error": "vault_uninitialized",
                "detail": str(exc),
                "action": "python scripts/engine/vault/cli.py init",
            },
            status_code=409,
        )

    @app.exception_handler(VaultWrongKey)
    async def _wrongkey(_request, exc: VaultWrongKey):
        return JSONResponse({"error": "vault_wrong_key", "detail": str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def _notfound(_request, exc: KeyError):
        return JSONResponse({"error": "not_found", "detail": str(exc).strip("'\"")}, status_code=404)
