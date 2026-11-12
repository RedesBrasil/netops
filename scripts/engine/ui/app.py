#!/usr/bin/env python3
"""Monta o app FastAPI: segurança (Origin/Host + login por senha-mestra), handlers de erro, routers, static.

O servidor é STATELESS — cada request lê/escreve os arquivos canônicos. Não há cache de
inventário em RAM, nem worker, nem conexão a equipamento. (Ver scripts/engine/ui/SKILL.md e a
cláusula da constituição §VII sobre ferramentas de operador efêmeras.)
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


class _SessionGate:
    """Conta conexões interativas antes do handshake e bloqueia novas em manutenção."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            return await self.app(scope, receive, send)
        from services import updates_svc
        if deps.STATE.update_pending or updates_svc.maintenance():
            await send({"type": "websocket.close", "code": 4423})
            return
        deps.STATE.active_sessions += 1
        try:
            await self.app(scope, receive, send)
        finally:
            deps.STATE.active_sessions -= 1


class _NoCacheStatic(StaticFiles):
    """Estaticos com revalidacao obrigatoria: o browser sempre checa com o servidor
    (ETag/Last-Modified -> 304 quando nao mudou), entao nunca serve JS/CSS velho de cache."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

import deps
from routers import (
    audio,
    auth,
    backups,
    catalog,
    claude,
    config,
    credentials,
    hosts,
    knowledge,
    memory,
    maps,
    meta,
    reports,
    runs,
    schedules,
    scripts,
    terminal,
    topology,
    updates,
)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Endpoints de bootstrap do login — alcançáveis sem sessão (a própria tela de login os chama).
AUTH_OPEN_PATHS = {"/api/auth/login", "/api/auth/status", "/api/auth/logout", "/api/config/meta"}


def _host_ok(host_header: str | None) -> bool:
    """Anti DNS-rebinding — política em deps.host_origin_allowed (proxy reverso com login ativo passa)."""
    return deps.host_origin_allowed(host_header)


def _origin_ok(origin: str | None, host_header: str | None = None) -> bool:
    """Origin ausente é ok (cliente não-browser). Presente => ver deps.host_origin_allowed."""
    if not origin:
        return True
    return deps.host_origin_allowed(host_header, origin)


def create_app() -> FastAPI:
    app = FastAPI(title="NetOps Console", docs_url="/api/docs", openapi_url="/api/openapi.json")

    app.add_middleware(_SessionGate)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api"):
            # Anti DNS-rebinding: sem login, Host tem que ser loopback/bind/NETOPS_UI_ALLOWED_HOSTS.
            if not _host_ok(request.headers.get("host")):
                return JSONResponse({"error": "forbidden_host", "detail":
                    "Host não autorizado e o console está sem login (cofre não inicializado). Inicialize o cofre "
                    "(scripts/engine/vault/cli.py init) ou defina NETOPS_UI_ALLOWED_HOSTS=<dominio> e reinicie."},
                    status_code=403)
            from services import host_migration_svc
            # Meta/status públicos continuam disponíveis antes do login para explicar
            # a manutenção; nenhum escritor nem leitor de dados observa uma mistura.
            migration_open = request.method in {"GET", "HEAD"} and path in {
                "/api/config/meta", "/api/auth/status", "/api/updates/status"}
            if host_migration_svc.blocking() and not migration_open:
                migration = host_migration_svc.status()
                return JSONResponse({"error": "host_migration", "detail": migration["detail"],
                                     "migration": migration}, status_code=503)
            # Gate de login: com cofre inicializado, todo /api exige sessão (senha-mestra),
            # exceto a allow-list de bootstrap (login/status/logout/meta).
            if (deps.auth_required() and path not in AUTH_OPEN_PATHS
                    and not deps.auth_session_valid(request.headers.get("x-netops-session"))):
                return JSONResponse({"error": "auth_required"}, status_code=401)
            if request.method in MUTATING:
                if not _origin_ok(request.headers.get("origin"), request.headers.get("host")):
                    return JSONResponse({"error": "forbidden_origin"}, status_code=403)
                if deps.STATE.read_only:
                    return JSONResponse(
                        {"error": "read_only", "detail": "servidor em modo somente-leitura (--read-only)"},
                        status_code=403,
                    )

        from services import updates_svc
        is_write = path.startswith("/api") and request.method in MUTATING and path != "/api/updates/apply"
        allowed_during_update = path in AUTH_OPEN_PATHS or path.startswith("/api/updates/")
        if path.startswith("/api") and not allowed_during_update and (
                deps.STATE.update_pending or updates_svc.maintenance()):
            return JSONResponse({"error": "maintenance", "detail": "Atualização em andamento. Aguarde o console reiniciar."}, status_code=503)
        if is_write:
            deps.STATE.active_writes += 1
        deps.STATE.active_requests += 1
        try:
            response = await call_next(request)
        finally:
            deps.STATE.active_requests -= 1
            if is_write:
                deps.STATE.active_writes -= 1

        # O shell do SPA (index.html) não é cacheado: garante que o front sempre venha da rede
        # (o HTML tem ~1 KB). Os assets estáticos (js/css/vendor) seguem cacheáveis pelo ETag.
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    _register_error_handlers(app)

    for mod in (audio, auth, meta, hosts, credentials, topology, maps, config, memory, knowledge, catalog, scripts, reports, runs, backups, schedules, terminal, claude, updates):
        app.include_router(mod.router, prefix="/api")

    @app.on_event("startup")
    async def _restore_logins():
        deps.load_auth_sessions()  # logins válidos (7 dias) sobrevivem ao restart

    @app.on_event("startup")
    async def _scheduler_cron():
        # Auto-reparo: há tarefas agendadas mas a linha do cron sumiu (instalação nova restaurada,
        # reinstalação, alguém apagou /etc/cron.d/netops-scheduler). Nunca derruba o startup.
        try:
            from scheduler import store as sched_store  # noqa: PLC0415
            sched_store.ensure_cron_if_tasks(deps.DATA_ROOT)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger("netops").exception("Tarefas agendadas: não consegui garantir o cron")

    @app.on_event("startup")
    async def _update_readiness():
        import asyncio
        import os
        from update.common import STATE_DIR, read_version, write_json
        from services import host_migration_svc

        try:
            prepared_hashes = await host_migration_svc.prepare()
            app.state.host_migration_task = host_migration_svc.start(prepared_hashes)
            if app.state.host_migration_task and os.environ.get("NETOPS_UPDATE_RECOVERING") != "1":
                # Na abertura normal não há commit de código pendente. Termina a
                # recuperação/conversão antes de aceitar as primeiras requisições.
                await app.state.host_migration_task
        except Exception:
            # Durante uma ATUALIZAÇÃO (candidato recém-instalado), a falha precisa
            # derrubar o startup: o supervisor então restaura o código anterior e os
            # dados antigos ficam intactos (relatório em host-migration-preflight.json).
            if os.environ.get("NETOPS_UPDATE_RECOVERING") == "1":
                raise
            # Fora de atualização, o console sobe mesmo assim; o erro aparece na UI.
            import logging
            logging.getLogger("netops").exception("Migração de IDs falhou no startup")

        async def receipt():
            await asyncio.sleep(0.15)
            write_json(deps.NETOPS_ROOT / STATE_DIR / "ready.json", {
                "nonce": os.environ["NETOPS_UPDATE_NONCE"], "pid": os.getpid(),
                "version": read_version(deps.NETOPS_ROOT),
            })

        if os.environ.get("NETOPS_UPDATE_MANAGED") == "1":
            asyncio.create_task(receipt())

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
    from lib.inventory_lock import MigrationIncomplete

    @app.exception_handler(MigrationIncomplete)
    async def _migration_incomplete(_request, exc: MigrationIncomplete):
        return JSONResponse(
            {"error": "migration_incomplete", "detail": str(exc),
             "action": ".venv/bin/python scripts/engine/lib/host_id_migration.py recover"},
            status_code=503,
        )

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
