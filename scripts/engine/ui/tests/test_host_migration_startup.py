"""Migração automática: barreira do supervisor publicado, dados e estado público."""
from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest
import yaml


def legacy(env):
    (env / "network/hosts.yaml").write_text(
        "version: 1\ngroups: {}\nhosts:\n  router:\n    hostname: Router\n"
        "    mgmt_ip: 192.0.2.1\n    vendor: linux\n    credential: fixture\n"
        "    access: {method: ssh}\n", encoding="utf-8")
    (env / "network/topology.yaml").write_text("version: 1\nlinks: []\n", encoding="utf-8")
    (env / "network/maps.yaml").write_text("version: 1\nmaps: []\n", encoding="utf-8")
    (env / "network/backups.yaml").write_text("version: 2\nservices: []\n", encoding="utf-8")


def contents(env):
    return {p.name: p.read_bytes() for p in (env / "network").glob("*.yaml")}


def test_automatic_conversion_idempotent_and_opaque_credentials(env):
    from services import host_migration_svc as svc
    legacy(env)
    opaque = b"fixture opaca: nao analisar nem alterar\n"
    (env / "network/credentials.yaml").write_bytes(opaque)
    assert svc._convert()["phase"] == "completed"
    assert yaml.safe_load((env / "network/hosts.yaml").read_text())["hosts"][0]["id"] == 1
    before = contents(env)
    assert svc._convert()["phase"] == "not_required"
    assert contents(env) == before
    assert (env / "network/credentials.yaml").read_bytes() == opaque


def test_absent_inventory_does_not_create_network_data(env):
    from services import host_migration_svc as svc
    (env / "network/hosts.yaml").unlink()
    before = contents(env)
    assert svc._convert()["phase"] == "not_required"
    assert contents(env) == before
    assert not (env / "network/.host-id-migration.json").exists()


def test_candidate_waits_for_complete_rollback_barrier(env, monkeypatch):
    import deps
    from services import host_migration_svc as svc
    from update.common import STATE_DIR, private_dir, read_version, write_json
    monkeypatch.setattr(deps.STATE, "host_migration", {})
    monkeypatch.setenv("NETOPS_UPDATE_MANAGED", "1")
    monkeypatch.setenv("NETOPS_UPDATE_RECOVERING", "1")
    directory = private_dir(env / STATE_DIR)
    journal = {"job_id": "a" * 32, "phase": "restarting", "new": {"version": read_version(env)}}
    write_json(directory / "journal.json", journal)
    write_json(directory / "supervisor.json", {"server_pid": os.getpid() + 1})
    (directory / "recovery-supervisor").write_text("fixture", encoding="utf-8")
    calls = []
    monkeypatch.setattr(svc, "_convert", lambda hashes: calls.append(hashes) or {"phase": "completed", "required": False})

    async def run():
        task = svc.start({"expected": "hash"})
        await asyncio.sleep(.15)
        assert not calls
        journal["phase"] = "completed"
        write_json(directory / "journal.json", journal)
        await asyncio.sleep(.15)
        assert not calls, "journal completed ainda fica dentro da janela de rollback antiga"
        write_json(directory / "supervisor.json", {"server_pid": os.getpid()})
        await asyncio.sleep(.15)
        assert not calls, "marcador de recuperação ainda impede a conversão"
        (directory / "recovery-supervisor").unlink()
        await asyncio.wait_for(task, 2)

    asyncio.run(run())
    assert calls == [{"expected": "hash"}]
    assert svc.status()["phase"] == "completed"


def test_candidate_preflight_invalid_reference_changes_no_data(env, monkeypatch):
    from services import host_migration_svc as svc
    monkeypatch.setenv("NETOPS_UPDATE_RECOVERING", "1")
    legacy(env)
    (env / "network/topology.yaml").write_text(
        "version: 1\nlinks:\n  - a: {host: router}\n    b: {host: missing}\n", encoding="utf-8")
    before = contents(env)
    with pytest.raises(RuntimeError, match="Pré-validação"):
        asyncio.run(svc.prepare())
    assert contents(env) == before
    report = env / ".netops-update/host-migration-preflight.json"
    assert json.loads(report.read_text())["code"] == "host_migration_preflight"
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    assert not (env / "network/.host-id-migration.json").exists()


def test_read_only_start_makes_no_writes(env, monkeypatch):
    import deps
    from services import host_migration_svc as svc
    legacy(env)
    monkeypatch.setattr(deps.STATE, "host_migration", {})
    monkeypatch.setattr(deps.STATE, "read_only", True)
    monkeypatch.setenv("NETOPS_UPDATE_RECOVERING", "1")
    before = contents(env)
    assert asyncio.run(svc.prepare()) is None
    assert svc.start() is None
    assert contents(env) == before
    assert not (env / ".netops-update").exists()


def test_interrupted_migration_recovers_original_baseline_then_retries(env, monkeypatch):
    from lib import host_id_migration as migration
    from services import host_migration_svc as svc
    legacy(env)
    original = migration._atomic_write

    def crash(path, data, mode=0o600):
        if path == env / "network/topology.yaml":
            raise SystemExit("queda simulada")
        return original(path, data, mode)

    monkeypatch.setattr(migration, "_atomic_write", crash)
    with pytest.raises(SystemExit):
        migration.apply(env)
    assert yaml.safe_load((env / "network/hosts.yaml").read_text())["version"] == 2
    assert yaml.safe_load((env / "network/topology.yaml").read_text())["version"] == 1
    monkeypatch.setattr(migration, "_atomic_write", original)
    assert svc._convert()["phase"] == "completed"
    assert json.loads((env / "network/.host-id-migration.json").read_text())["status"] == "complete"


def test_public_status_never_completed_during_conversion(env, monkeypatch):
    import deps
    from services import updates_svc
    from update.common import STATE_DIR, private_dir, write_json
    monkeypatch.setattr(deps.STATE, "host_migration", {"phase": "running", "required": True, "detail": "Convertendo"})
    directory = private_dir(env / STATE_DIR)
    write_json(directory / "job.json", {"id": "a" * 32, "phase": "completed"})
    assert updates_svc.local_status()["job"]["phase"] == "migrating"
    deps.STATE.host_migration = {"phase": "failed", "required": True, "detail": "Pré-validação bloqueada"}
    assert updates_svc.local_status()["job"]["phase"] == "migration_failed"


def test_migration_blocks_data_writes_and_websockets_before_login(client, monkeypatch):
    import deps
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setattr(deps.STATE, "host_migration", {"phase": "running", "required": True, "detail": "Convertendo"})
    assert client.get("/api/config/meta").json()["host_migration"]["blocking"] is True
    assert client.get("/api/hosts").status_code == 503
    assert client.post("/api/auth/login", json={}).status_code == 503
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/api/term"):
            pass
    assert error.value.code == 4423
