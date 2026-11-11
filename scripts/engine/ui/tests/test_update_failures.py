"""Cenários adicionais de falha, ambiente Python e autenticação."""
import hashlib
import json
import subprocess

import pytest
import deps
from update import engine
from update.common import STATE_DIR, UpdateError, read_json
from test_updates import installation, package, entries


def test_staging_tampering_is_rejected(installation, tmp_path):
    journal = engine.prepare(installation, installation, package(tmp_path), "1.1.0", "a" * 32)
    stage = installation / STATE_DIR / "jobs" / journal["job_id"] / "stage/scripts/engine/ui/app.py"
    stage.write_text("changed")
    with pytest.raises(UpdateError, match="staging"):
        engine.apply(installation, journal)
    assert engine.read_version(installation) == "1.0.0"


def test_failed_dependencies_leave_original_venv(installation, tmp_path, monkeypatch):
    new = entries("1.1.0")
    content = b"new-dependency==1.0\n"
    new["requirements.txt"].update(raw=content, size=len(content), sha256=hashlib.sha256(content).hexdigest())
    marker = installation / ".venv/original"
    marker.write_text("keep")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1))
    with pytest.raises(UpdateError, match="ambiente Python"):
        engine.prepare(installation, installation, package(tmp_path, files=new), "1.1.0", "a" * 32)
    assert marker.read_text() == "keep"
    assert engine.read_version(installation) == "1.0.0"


def test_venv_swap_is_reversible(installation, tmp_path, monkeypatch):
    new = entries("1.1.0")
    content = b"# different fixture requirements\n"
    new["requirements.txt"].update(raw=content, size=len(content), sha256=hashlib.sha256(content).hexdigest())
    marker = installation / ".venv/original"
    marker.write_text("keep")
    def command(args, **kw):
        if "venv" in args:
            from pathlib import Path
            (Path(args[-1]) / "bin").mkdir(parents=True)
            (Path(args[-1]) / "bin/python3").write_text("fixture interpreter")
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(subprocess, "run", command)
    journal = engine.prepare(installation, installation, package(tmp_path, files=new), "1.1.0", "a" * 32)
    engine.apply(installation, journal)
    assert (installation / ".venv").is_symlink()
    engine.rollback(installation, journal)
    assert not (installation / ".venv").is_symlink()
    assert marker.read_text() == "keep"


def test_venv_recovery_after_pointer_gap(installation, tmp_path):
    journal = engine.prepare(installation, installation, package(tmp_path), "1.1.0", "a" * 32)
    candidate = installation / ".netops-venvs/candidate"
    candidate.mkdir(parents=True)
    journal["candidate"] = str(candidate)
    engine.apply(installation, journal)
    (installation / ".venv").unlink()
    engine.rollback(installation, journal)
    assert (installation / ".venv/bin/python3").exists()
    assert engine.read_version(installation) == "1.0.0"


def test_no_downgrade(installation, tmp_path):
    with pytest.raises(UpdateError, match="superior"):
        engine.prepare(installation, installation, package(tmp_path, "1.0.0"), "1.0.0", "a" * 32)


def test_rollback_does_not_overwrite_external_code_changes(installation, tmp_path):
    journal = engine.prepare(installation, installation, package(tmp_path), "1.1.0", "a" * 32)
    engine.apply(installation, journal)
    (installation / "core/config/core-config.yaml").write_text("external code change")
    with pytest.raises(UpdateError, match="outro processo"):
        engine.rollback(installation, journal)
    assert (installation / "core/config/core-config.yaml").read_text() == "external code change"


def _gate_ready(installation, monkeypatch):
    from services import updates_svc
    monkeypatch.setattr(deps, "NETOPS_ROOT", installation)
    monkeypatch.setattr(deps, "BACKUPS_RUNS", installation / "runs/backups")
    monkeypatch.setattr(updates_svc, "managed", lambda: True)
    from update.common import write_json
    write_json(installation / STATE_DIR / "job.json", {"phase": "completed"})
    return updates_svc


@pytest.mark.parametrize("state", ["idle", "detached", "turn", "question"])
def test_open_sessions_never_block_update(installation, monkeypatch, state):
    """Regressão: terminal ou aba Claude abertos (o socket da aba fica aberto em todas as
    páginas) recusavam a atualização com "encerre: terminal ou sessão interativa aberta"."""
    updates_svc = _gate_ready(installation, monkeypatch)
    from services import claude_svc
    monkeypatch.setattr(deps.STATE, "active_sessions", 2)       # /api/term + /api/claude
    session = claude_svc.ClaudeWebSession(persist=True, resume="sid")
    session._busy = state == "turn"
    if state == "question":
        session._pending["q1"] = object()
    monkeypatch.setitem(claude_svc._LIVE, "sid", session)
    assert updates_svc.activity() == []


def test_running_workflow_still_blocks(installation, monkeypatch):
    updates_svc = _gate_ready(installation, monkeypatch)
    run = installation / "runs/x"
    run.mkdir(parents=True)
    (run / "state.json").write_text('{"status": "running"}')
    with pytest.raises(UpdateError, match="aguarde: workflow em andamento"):
        updates_svc.request_update(1)


def test_authenticated_confirmation_enqueues_once(client, env, monkeypatch):
    from services import updates_svc
    monkeypatch.setattr(deps, "auth_required", lambda: True)
    calls = []
    monkeypatch.setattr(updates_svc, "request_update", lambda ident: calls.append(ident) or {"id": "job", "phase": "queued"})
    result = client.post("/api/updates/apply", json={"release_id": 12, "confirm": True})
    assert result.status_code == 202
    assert calls == [12]
    assert not deps.STATE.update_pending
    monkeypatch.setattr(deps.STATE, "update_pending", True)
    assert client.post("/api/updates/apply", json={"release_id": 12, "confirm": True}).status_code == 409
    assert calls == [12]
