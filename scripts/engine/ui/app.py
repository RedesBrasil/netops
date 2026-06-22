#!/usr/bin/env python3
"""Monta o app FastAPI: segurança (token + Origin/Host), handlers de erro, routers, static.

O servidor é STATELESS — cada request lê/escreve os arquivos canônicos. Não há cache de
inventário em RAM, nem worker, nem conexão a equipamento. (Ver scripts/engine/ui/SKILL.md e a
cláusula da constituição §VII sobre ferramentas de operador efêmeras.)
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import deps
from routers import (
    auth,
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
# Endpoints alcançáveis só com o token (sem sessão de login) — bootstrap do gate.
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


def _supplied_token(request: Request) -> str | None:
    """Token de transporte, em ordem de precedência: Authorization > ?token= > cookie.

    Um Bearer VAZIO (o front manda `Authorization: Bearer ` quando não tem token em memória,
    ex.: sessão nova após fechar a aba) é ignorado para que o cookie HttpOnly assuma —
    é o que permite acessar o IP "puro" sem o token na URL."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok:
            return tok
    qp = request.query_params.get("token")
    if qp:
        return qp
    return request.cookies.get(deps.TOKEN_COOKIE)


def _set_token_cookie(response) -> None:
    """Grava o token de transporte num cookie HttpOnly de longa duração (ver deps.TOKEN_COOKIE)."""
    response.set_cookie(
        key=deps.TOKEN_COOKIE,
        value=deps.STATE.token,
        max_age=deps.TOKEN_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        path="/",
    )


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

        # Persistência do token: quando a página é aberta com ?token=<válido> (tipicamente
        # "/?token=..."), grava o token num cookie HttpOnly. Nas próximas visitas o navegador
        # o envia sozinho — acessa-se o IP "puro", sem o token na URL. Só grava se o token da
        # query confere (comparação em tempo constante), nunca para token ausente/errado.
        qp_token = request.query_params.get("token")
        if qp_token and deps.token_matches(qp_token):
            _set_token_cookie(response)
        # O shell do SPA (index.html) NÃO pode ser cacheado: se o navegador o servir do
        # cache sem ir à rede, o Set-Cookie do token (acima) nunca chega e o cookie nunca é
        # gravado — o IP "puro" cai em 401/"unauthorized" sem nunca mostrar o login. no-store
        # força a ida à rede a cada carga do documento (o HTML tem ~1 KB). Os assets estáticos
        # (js/css/vendor) seguem cacheáveis pelo ETag — eles não carregam cookie.
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    _register_error_handlers(app)

    for mod in (auth, meta, hosts, credentials, topology, config, memory, knowledge, catalog, scripts, reports, runs, terminal, claude):
        app.include_router(mod.router, prefix="/api")

    # SPA: serve scripts/engine/ui/static/ na raiz (index.html cobre o fallback de rotas hash).
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
                "action": "cd /home/francisco/netops && .venv/bin/python3 scripts/engine/vault/cli.py unlock",
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
