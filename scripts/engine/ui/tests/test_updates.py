"""Atualizações somente em instalações fictícias, nunca no código ou dados reais."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest
import deps  # bootstrap de scripts/engine no sys.path

from update import engine, releases
from update.common import PROTOCOL, REPOSITORY, STATE_DIR, UpdateError, private_dir, read_json, write_json
from update.release import build_package, release_notes


def entries(version="1.0.0"):
    raw = {p: b"# fixture\n" for p in engine.REQUIRED}
    raw["core/config/core-config.yaml"] = f'metadata:\n  version: "{version}"\n'.encode()
    raw["requirements.txt"] = b"# empty fixture\n"
    raw["agents/local.agent.md"] = b"original agent\n"
    raw["workflows/old.workflow.yaml"] = b"original workflow\n"
    return {p: {"raw": content, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
                "mode": 0o755 if p.endswith(".sh") else 0o644} for p, content in raw.items()}


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "installation"
    root.mkdir()
    (root / "network").mkdir()
    old = entries()
    for rel, info in old.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(info["raw"])
        dest.chmod(info["mode"])
    private_dir(root / STATE_DIR)
    manifest = {"protocol": PROTOCOL, "repository": REPOSITORY, "version": "1.0.0",
                "files": {p: {k: v for k, v in i.items() if k != "raw"} for p, i in old.items()}}
    write_json(root / STATE_DIR / "installed.json", manifest)
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python3").write_text("fixture interpreter")
    write_json(root / STATE_DIR / "job.json", {"id": "a" * 32, "phase": "queued"})
    return root


def package(tmp_path, version="1.1.0", files=None):
    output = tmp_path / (version + ".tar.gz")
    build_package(files or entries(version), version, output)
    return output


def test_update_preserves_all_local_data_and_customizations(installation, tmp_path):
    root = installation
    data = {"network/hosts.yaml": b"hosts: {}\n", "network/credentials.yaml": b"secret: enc.v1:fixture\n",
            "network/maps.yaml": b"maps: []\n", "core/config/project-config.yaml": b"project: local\n",
            "memory/MEMORY.md": b"private lessons\n", "runs/test/state.json": b"{}",
            "reports/local.md": b"private\n", "backups/device/config": b"private backup\n",
            ".claude/projects/history.jsonl": b"fictional history\n", "unknown.file": b"keep\n"}
    for rel, content in data.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        p.chmod(0o600)
    (root / "agents/local.agent.md").write_text("custom agent\n")
    (root / "workflows/old.workflow.yaml").unlink()
    # git tracks only executable bit: group-writable checkout is not a local source edit.
    (root / "scripts/engine/ui/app.py").chmod(0o664)
    journal = engine.prepare(root, root, package(tmp_path), "1.1.0", "a" * 32)
    engine.apply(root, journal)
    engine.commit(root, journal)
    for rel, content in data.items():
        assert (root / rel).read_bytes() == content
        assert (root / rel).stat().st_mode & 0o777 == 0o600
    assert (root / "agents/local.agent.md").read_text() == "custom agent\n"
    assert not (root / "workflows/old.workflow.yaml").exists()
    assert engine.read_version(root) == "1.1.0"
    assert read_json(root / STATE_DIR / "job.json")["phase"] == "completed"
    assert set(journal["preserved"]) == {"agents/local.agent.md", "workflows/old.workflow.yaml"}


def test_rollback_restores_code_but_not_live_data(installation, tmp_path):
    root = installation
    (root / "network/hosts.yaml").write_text("before\n")
    journal = engine.prepare(root, root, package(tmp_path), "1.1.0", "a" * 32)
    engine.apply(root, journal)
    (root / "network/hosts.yaml").write_text("later independent change\n")
    engine.rollback(root, journal)
    assert engine.read_version(root) == "1.0.0"
    assert (root / "network/hosts.yaml").read_text() == "later independent change\n"
    assert read_json(root / STATE_DIR / "installed.json")["version"] == "1.0.0"


def test_engine_edits_block_application(installation, tmp_path):
    (installation / "scripts/engine/ui/app.py").write_text("custom code")
    with pytest.raises(UpdateError, match="Motor alterado"):
        engine.prepare(installation, installation, package(tmp_path), "1.1.0", "a" * 32)
    assert engine.read_version(installation) == "1.0.0"


def test_unknown_collision_and_symlink_rejected(installation, tmp_path):
    new = entries("1.1.0")
    new["scripts/new.py"] = {"raw": b"new", "sha256": hashlib.sha256(b"new").hexdigest(), "size": 3, "mode": 0o644}
    (installation / "scripts/new.py").write_text("local")
    with pytest.raises(UpdateError, match="colide"):
        engine.prepare(installation, installation, package(tmp_path, files=new), "1.1.0", "a" * 32)
    (installation / "scripts/new.py").unlink()
    (installation / "scripts/new.py").symlink_to(tmp_path / "outside")
    with pytest.raises(UpdateError, match="link"):
        engine.plan_files(installation, engine.installed_manifest(installation), {"files": {"scripts/new.py": new["scripts/new.py"]}})


def test_external_data_snapshot(installation, tmp_path):
    data = tmp_path / "external"
    (data / "network").mkdir(parents=True)
    (data / "network/hosts.yaml").write_text("external fixture\n")
    journal = engine.prepare(installation, data, package(tmp_path), "1.1.0", "a" * 32)
    backup = installation / STATE_DIR / "jobs" / journal["job_id"] / "backup"
    assert (backup / "data/network/hosts.yaml").read_text() == "external fixture\n"
    assert (backup / "data/network/hosts.yaml").stat().st_mode & 0o777 == 0o600


def test_disk_space_blocks_before_changes(installation, tmp_path, monkeypatch):
    from collections import namedtuple
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100, 100, 0))
    with pytest.raises(UpdateError, match="Espaço insuficiente"):
        engine.prepare(installation, installation, package(tmp_path), "1.1.0", "a" * 32)
    assert engine.read_version(installation) == "1.0.0"


def test_interruption_after_first_write_rolls_back(installation, tmp_path, monkeypatch):
    journal = engine.prepare(installation, installation, package(tmp_path), "1.1.0", "a" * 32)
    original = engine.atomic_bytes
    def fail(path, *args, **kwargs):
        if path == installation / "core/config/core-config.yaml":
            original(path, *args, **kwargs)
            raise OSError("simulated power failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(engine, "atomic_bytes", fail)
    with pytest.raises(OSError):
        engine.apply(installation, journal)
    monkeypatch.setattr(engine, "atomic_bytes", original)
    persisted = read_json(installation / STATE_DIR / "journal.json")
    assert persisted["phase"] == "applying"
    engine.rollback(installation, persisted)
    assert engine.read_version(installation) == "1.0.0"


def test_snapshot_corruption_fails_closed(installation, tmp_path):
    journal = engine.prepare(installation, installation, package(tmp_path), "1.1.0", "a" * 32)
    engine.apply(installation, journal)
    backup = installation / STATE_DIR / "jobs" / journal["job_id"] / "backup/installation/core/config/core-config.yaml"
    backup.write_text("corrupt")
    with pytest.raises(UpdateError, match="Snapshot"):
        engine.rollback(installation, journal)


def test_package_traversal_rejected(tmp_path):
    import io
    path = tmp_path / "bad.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("../outside")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bad"))
    with pytest.raises(UpdateError):
        engine.unpack(path, tmp_path / "stage", "1.1.0")
    assert not (tmp_path / "outside").exists()


def test_protected_path_cannot_enter_manifest(tmp_path):
    files = entries("1.1.0")
    files["network/credentials.yaml"] = files["requirements.txt"]
    with pytest.raises(UpdateError, match="protegido"):
        package(tmp_path, files=files)


def test_release_listing_numeric_order_all_newer(monkeypatch):
    def row(n, tag, **kw):
        return {"id": n, "tag_name": tag, "body": "Changes " + tag, "assets": [], **kw}
    monkeypatch.setattr(releases, "api_json", lambda url: [row(1, "v1.9.0"), row(2, "v1.10.0"),
                        row(3, "v1.11.0", draft=True), row(4, "v2.0.0-rc1", prerelease=True)])
    result = releases.stable_releases()
    assert [r["version"] for r in result] == ["1.10.0", "1.9.0"]
    assert all(not r["installable"] for r in result)


def test_release_listing_paginates(monkeypatch):
    calls = []
    def api(url):
        calls.append(url)
        if "page=2" in url:
            return [{"id": 101, "tag_name": "v2.0.0", "assets": []}]
        return [{"id": i + 1, "tag_name": f"v1.0.{i}", "assets": []} for i in range(100)]
    monkeypatch.setattr(releases, "api_json", api)
    assert len(releases.stable_releases()) == 101
    assert len(calls) == 2


def test_github_failures_are_not_no_updates():
    assert releases._failure(b"HTTP 401").code == "github_auth"
    assert releases._failure(b"HTTP 404").code == "github_access"
    assert releases._failure(b"API rate limit exceeded").code == "rate_limit"
    assert releases._failure(b"connection refused").code == "github_unavailable"


def test_changelog_requires_version_section():
    assert "Novidade" in release_notes("## [1.1.0] - 2026-11-10\n\n### Novidade\n- Atualizações seguras.\n", "1.1.0")
    with pytest.raises(UpdateError):
        release_notes("nothing", "1.1.0")


def test_apply_requires_login_even_without_vault(client, env):
    response = client.post("/api/updates/apply", json={"release_id": 1, "confirm": True})
    assert response.status_code == 401


def test_updates_read_only_origin_and_arbitrary_input(client, env):
    import deps
    deps.STATE.read_only = True
    assert client.post("/api/updates/apply", json={"release_id": 1, "confirm": True}).status_code == 403
    deps.STATE.read_only = False
    assert client.post("/api/updates/apply", json={"release_id": 1, "confirm": True}, headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/updates/apply", json={"release_id": 1, "confirm": True, "url": "http://evil"}).status_code == 422


def test_maintenance_blocks_mutation_and_socket(client, env, monkeypatch):
    import deps
    from services import updates_svc
    deps.STATE.update_pending = True
    try:
        assert client.put("/api/config", json={}).status_code == 503
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/term"):
                pass
    finally:
        deps.STATE.update_pending = False


def test_status_does_not_expose_arbitrary_state(client, env, monkeypatch, installation):
    import deps
    monkeypatch.setattr(deps, "NETOPS_ROOT", installation)
    write_json(installation / STATE_DIR / "job.json", {"id": "test", "phase": "completed", "secret": "NEVER_EXPOSE"})
    response = client.get("/api/updates/status")
    assert response.status_code == 200
    assert "NEVER_EXPOSE" not in response.text
