"""Conversão automática de identidade, somente depois do commit do código.

Supervisores publicados executam rollback apenas do código. O candidato não pode
alterar dados até o supervisor sair da janela em que esse rollback ainda ocorre.
Reutiliza a transação com baseline/journal; nunca lê credentials.yaml.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import deps
from lib import i18n
from update.common import STATE_DIR, private_dir, read_json, read_version, write_json

LOG = logging.getLogger(__name__)
COMMIT_TIMEOUT = 120
BLOCKING_PHASES = {"waiting_for_commit", "running", "failed"}


def status() -> dict:
    value = dict(deps.STATE.host_migration)
    return {**value, "blocking": value.get("phase") in BLOCKING_PHASES}


def blocking() -> bool:
    return deps.STATE.host_migration.get("phase") in BLOCKING_PHASES


def _set(phase, detail, *, required=False, **extra):
    deps.STATE.host_migration = {"phase": phase, "detail": detail, "required": required, **extra}


async def prepare():
    """Pré-flight sem escrita de dados enquanto o supervisor ainda pode reverter código."""
    if (deps.STATE.read_only or os.environ.get("NETOPS_UPDATE_RECOVERING") != "1"
            or not (deps.DATA_ROOT / "network/hosts.yaml").exists()):
        return None
    from lib import host_id_migration as migration
    try:
        prepared = await asyncio.to_thread(migration.plan, deps.DATA_ROOT)
        return {name: migration._digest(value) for name, value in prepared["before"].items()}
    except Exception as exc:
        # Diagnóstico privado, nunca o conteúdo do cofre. O supervisor publicado
        # reconhecerá a falha de startup e restaurará o código sem tocar nos YAMLs.
        report = {"code": "host_migration_preflight", "version": read_version(deps.NETOPS_ROOT),
                  "problems": exc.problems if isinstance(exc, migration.PreflightError)
                  else [{"msg": "Não foi possível pré-validar os dados para a migração.",
                         "type": type(exc).__name__}]}
        directory = private_dir(deps.NETOPS_ROOT / STATE_DIR)
        write_json(directory / "host-migration-preflight.json", report)
        raise RuntimeError("Pré-validação da migração de IDs falhou; dados antigos preservados. "   # i18n-ok: startup log, not an API answer
                           "Consulte .netops-update/host-migration-preflight.json.") from None


def _convert(expected_hashes=None):
    from lib import host_id_migration as migration

    root = deps.DATA_ROOT
    if not (root / "network/hosts.yaml").exists():
        return {"phase": "not_required", "required": False,
                "detail": i18n.t("api_host_migration.no_inventory")}
    # Recover restaura a baseline original se houve uma queda entre substituições.
    # Ele recusa sobrescrever alterações posteriores ou baselines corrompidos.
    if (root / "network" / migration.JOURNAL_NAME).exists():
        migration.recover(root)
    raw = migration._read(root / "network/hosts.yaml")
    document = migration._yaml().load(raw.decode("utf-8")) if raw and raw.strip() else {}
    if isinstance(document, dict) and document.get("version") == 2:
        return {"phase": "not_required", "required": False,
                "detail": i18n.t("api_host_migration.already_int")}
    result = migration.apply(root, expected_hashes=expected_hashes)
    return {"phase": "completed", "required": False,
            "detail": i18n.t("api_host_migration.completed"),
            "hosts_migrated": len(result.get("mapping", [])),
            "baseline": result.get("run_dir")}


def _commit_published(expected_job, expected_version) -> bool:
    directory = deps.NETOPS_ROOT / STATE_DIR
    journal = read_json(directory / "journal.json", {})
    supervisor = read_json(directory / "supervisor.json", {})
    # engine.commit grava o journal ANTES do status. Um erro nessa escrita ainda
    # cai no rollback do supervisor antigo. O PID novo só é publicado DEPOIS de
    # sair desse try/except, portanto também faz parte da barreira de commit.
    return (journal.get("job_id") == expected_job and journal.get("phase") == "completed"
            and (journal.get("new") or {}).get("version") == expected_version
            and supervisor.get("server_pid") == os.getpid()
            and not (directory / "recovery-supervisor").exists())


async def _run(expected_hashes=None):
    try:
        if os.environ.get("NETOPS_UPDATE_RECOVERING") == "1":
            if os.environ.get("NETOPS_UPDATE_MANAGED") != "1":
                raise ValueError("candidato sem supervisor gerenciado")
            journal = read_json(deps.NETOPS_ROOT / STATE_DIR / "journal.json", {})
            expected_job = journal.get("job_id")
            expected_version = read_version(deps.NETOPS_ROOT)
            if not expected_job or (journal.get("new") or {}).get("version") != expected_version:
                raise ValueError("journal não corresponde ao candidato")   # i18n-ok: internal, caught
            deadline = time.monotonic() + COMMIT_TIMEOUT
            while not _commit_published(expected_job, expected_version):
                if time.monotonic() >= deadline:
                    _set("failed", i18n.t("api_host_migration.commit_unconfirmed"),
                         required=True, code="migration_commit_unconfirmed")
                    return
                await asyncio.sleep(.1)
        _set("running", i18n.t("api_host_migration.converting"), required=True)
        result = await asyncio.to_thread(_convert, expected_hashes)
        deps.STATE.host_migration = result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        from lib.host_id_migration import PreflightError
        if isinstance(exc, PreflightError):
            _set("failed", i18n.t("api_host_migration.preflight_blocked", count=len(exc.problems)),
                 required=True, code="migration_preflight", problems=len(exc.problems))
        else:
            _set("failed", i18n.t("api_host_migration.recovery_failed"),
                 required=True, code="migration_recovery_failed")
        # Não incluir valores dos documentos nem conteúdo de exceções na API/log.
        LOG.error("Migração automática bloqueada (%s)", type(exc).__name__)


def start(expected_hashes=None):
    """Chamado no startup antes da prontidão HTTP; não cria dados em read-only."""
    if deps.STATE.read_only:
        _set("read_only", i18n.t("api_host_migration.read_only"))
        return None
    if os.environ.get("NETOPS_UPDATE_RECOVERING") == "1":
        _set("waiting_for_commit", i18n.t("api_host_migration.waiting_commit"), required=True)
    else:
        _set("running", i18n.t("api_host_migration.checking"), required=True)
    return asyncio.create_task(_run(expected_hashes))
