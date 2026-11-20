"""Integração do console com o atualizador, sem credenciais ou conteúdo privado na API."""
from __future__ import annotations

import json
import os
import uuid

import deps
from lib import i18n
from update import engine, releases
from update.common import (STATE_DIR, TERMINAL_STATES, UpdateError, private_dir,
                           read_json, read_version, version_tuple, write_json)


def _directory():
    return deps.NETOPS_ROOT / STATE_DIR


def managed() -> bool:
    supervisor = read_json(_directory() / "supervisor.json", {})
    return os.environ.get("NETOPS_UPDATE_MANAGED") == "1" and supervisor.get("server_pid") == os.getpid()


def maintenance() -> bool:
    from services import host_migration_svc
    job = read_json(_directory() / "job.json", {})
    return (host_migration_svc.blocking() or bool(job and job.get("phase") not in TERMINAL_STATES)
            or job.get("phase") == "recovery_failed")


def local_status() -> dict:
    from services import host_migration_svc
    job = read_json(_directory() / "job.json", {})
    migration = host_migration_svc.status()
    if job.get("phase") == "completed" and migration["blocking"]:
        job = {**job, "phase": "migration_failed" if migration["phase"] == "failed" else "migrating",
               "detail": migration["detail"]}
    allowed = ("id", "phase", "version", "from_version", "detail", "updated_at", "preserved", "backup")
    return {"current_version": read_version(deps.NETOPS_ROOT), "managed": managed(),
            "requires_setup": not deps.auth_required(),
            "read_only": deps.STATE.read_only, "host_migration": migration,
            "job": {key: job[key] for key in allowed if key in job}}


def check() -> dict:
    result = local_status()
    stable = releases.stable_releases()
    newer = [r for r in stable if version_tuple(r["version"]) > version_tuple(result["current_version"])]
    result.update(releases=newer, latest=stable[0] if stable else None,
                  no_releases=not stable, can_apply=bool(newer and newer[0]["installable"]
                                                      and result["managed"] and not result["requires_setup"]
                                                      and not deps.STATE.read_only and not maintenance()))
    return result


def activity() -> list[str]:
    active = []
    # Sessões abertas (terminal web, aba Claude — conectada, desanexada ou em turno) NÃO
    # bloqueiam: o socket da aba Claude fica aberto em todas as páginas e reconecta sozinho,
    # o que travava a atualização sem nenhuma sessão visível. O reinício encerra as sessões;
    # as conversas do agente estão no transcript em disco e são retomadas depois.
    # Só bloqueia trabalho que gravaria dados pela metade (backup/workflow em execução).
    if deps.BACKUPS_RUNS.exists():
        for path in deps.BACKUPS_RUNS.glob("*.json"):
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("state") == "running":
                    active.append(i18n.t("api_updates.backup_running"))
                    break
            except (ValueError, OSError):
                raise UpdateError("unknown_activity", i18n.t("api_updates.backup_check_failed")) from None
    runs = deps.NETOPS_ROOT / "runs"
    if runs.exists():
        for path in runs.glob("*/state.json"):
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("status") in {"running", "in_progress"}:
                    active.append(i18n.t("api_updates.workflow_running"))
                    break
            except (ValueError, OSError):
                raise UpdateError("unknown_activity", i18n.t("api_updates.workflow_check_failed")) from None
    return active


def request_update(release_id: int) -> dict:
    if not managed():
        raise UpdateError("unmanaged", i18n.t("api_updates.unmanaged"))
    if maintenance():
        raise UpdateError("busy", i18n.t("api_updates.pending"))
    busy = activity()
    if busy:
        raise UpdateError("active_work", i18n.t("api_updates.active_work", items="; ".join(busy)))
    stable = releases.stable_releases()
    if not stable or stable[0]["id"] != release_id:
        raise UpdateError("release_changed", i18n.t("api_updates.release_changed"))
    release = stable[0]
    if not release["installable"]:
        raise UpdateError("no_package", i18n.t("api_updates.no_package"))
    if version_tuple(release["version"]) <= version_tuple(read_version(deps.NETOPS_ROOT)):
        raise UpdateError("not_newer", i18n.t("api_updates.not_newer"))
    # Detecta conflitos antes de parar o console. A comparação completa é repetida no worker.
    engine.installed_manifest(deps.NETOPS_ROOT)
    directory = private_dir(_directory())
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "phase": "queued", "version": release["version"],
           "from_version": read_version(deps.NETOPS_ROOT), "detail": i18n.t("api_updates.confirmed")}
    write_json(directory / "job.json", job)
    try:
        write_json(directory / "request.json", {"job_id": job_id, "release_id": release_id,
                                               "asset": release["asset"], "data_root": str(deps.DATA_ROOT)})
    except OSError:
        engine.status(deps.NETOPS_ROOT, "failed", detail=i18n.t("api_updates.forward_failed"))
        raise UpdateError("request_failed", i18n.t("api_updates.request_failed")) from None
    return job
