"""Revisão independente da migração: identidade do histórico e confinamento dos arquivos."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ENGINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE))


@pytest.fixture()
def migration_root(tmp_path):
    network = tmp_path / "network"
    network.mkdir()
    documents = {
        "hosts.yaml": {
            "version": 1,
            "groups": {"routers": {"vendor": "linux", "credential": "dummy-reference", "access": {"method": "ssh"}}},
            "hosts": {"alpha": {"hostname": "Host de teste", "mgmt_ip": "192.0.2.7", "group": "routers"}},
        },
        "topology.yaml": {"version": 1, "links": []},
        "maps.yaml": {"version": 1, "maps": []},
        "backups.yaml": {"version": 2, "services": []},
    }
    for name, document in documents.items():
        (network / name).write_text(yaml.safe_dump(document), encoding="utf-8")
    return tmp_path, documents


def test_migration_rejects_conflicting_legacy_history_owners(migration_root):
    from lib.host_id_migration import PreflightError, transform

    _, documents = migration_root
    documents["backups.yaml"]["legacy_sources"] = [
        {"host_id": 1, "directory": "alpha"}, {"host_id": 1, "directory": "alpha"}]
    with pytest.raises(PreflightError) as error:
        transform(documents)
    assert any("duplicad" in item["msg"] for item in error.value.problems)


def test_migration_does_not_follow_network_parent_symlink(tmp_path):
    from lib.host_id_migration import plan

    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "network").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        plan(root)
    assert list(outside.iterdir()) == []


def test_migration_refuses_reassigning_existing_canonical_archive(migration_root):
    from lib.host_id_migration import PreflightError, plan

    root, _ = migration_root
    archive = root / "backups" / "by-id" / "1" / "existing.cfg"
    archive.parent.mkdir(parents=True)
    archive.write_text("configuração fictícia", encoding="utf-8")
    with pytest.raises(PreflightError):
        plan(root)


def test_migration_allows_legacy_host_named_by_id_with_flat_history(migration_root):
    from lib.host_id_migration import plan

    root, documents = migration_root
    documents["hosts.yaml"]["hosts"]["by-id"] = {"hostname": "Outro host", "mgmt_ip": "192.0.2.8", "group": "routers"}
    (root / "network" / "hosts.yaml").write_text(yaml.safe_dump(documents["hosts.yaml"]), encoding="utf-8")
    archive = root / "backups" / "by-id" / "old.cfg"
    archive.parent.mkdir(parents=True)
    archive.write_text("configuração fictícia", encoding="utf-8")
    migration = plan(root)
    converted = yaml.safe_load(migration["after"]["backups.yaml"])
    assert converted["legacy_sources"] == [{"host_id": 2, "directory": "by-id"}]


def test_rollback_refuses_recycling_identity_after_new_backup(migration_root):
    from lib.host_id_migration import apply, recover

    root, _ = migration_root
    result = apply(root)
    baseline = root / result["run_dir"] / "baseline"
    assert {path.name for path in baseline.iterdir()} == {"hosts.yaml", "topology.yaml", "maps.yaml", "backups.yaml"}
    archive = root / "backups" / "by-id" / "1" / "after-migration.cfg"
    archive.parent.mkdir(parents=True)
    archive.write_text("configuração fictícia", encoding="utf-8")
    with pytest.raises(ValueError, match="histórico|backup|inteiro"):
        recover(root, rollback_complete=True)
    assert yaml.safe_load((root / "network" / "hosts.yaml").read_text(encoding="utf-8"))["version"] == 2
