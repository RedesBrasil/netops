"""Tarefas agendadas: expressão cron, despachante (tick), executor e API do console.

Tudo numa raiz de dados temporária — o cron real (/etc/cron.d) nunca é tocado.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import deps  # noqa: F401  (põe scripts/engine no sys.path)
from scheduler import runner, store
from scheduler.cronexpr import CronError, CronExpr

TZ = store.tzinfo("America/Sao_Paulo")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


# ---------------------------------------------------------------- cron -----
def test_cron_next_and_match():
    e = CronExpr("0 9 * * 1-5")
    assert e.next_after(_dt("2026-11-13T09:00")) == _dt("2026-11-16T09:00")   # sex 09:00 -> seg
    assert e.matches(_dt("2026-11-16T09:00")) and not e.matches(_dt("2026-11-15T09:00"))
    assert CronExpr("*/15 * * * *").next_after(_dt("2026-11-12T10:07")) == _dt("2026-11-12T10:15")
    assert CronExpr("@daily").next_after(_dt("2026-11-12T10:00")) == _dt("2026-11-13T00:00")
    assert CronExpr("0 8 1 * mon").matches(_dt("2026-11-16T08:00"))   # dia-mês OU dia-semana (Vixie)
    assert CronExpr("0 0 * * 7").matches(_dt("2026-11-15T00:00"))     # 7 = domingo


@pytest.mark.parametrize("bad", ["", "* * *", "61 * * * *", "0 25 * * *", "5-1 * * * *", "*/0 * * * *", "x * * * *"])
def test_cron_invalid(bad):
    with pytest.raises(CronError):
        CronExpr(bad)


# ---------------------------------------------------------------- store ----
def test_create_validates_and_installs_cron_inside_data_root(tmp_path):
    with pytest.raises(store.TaskError) as ei:
        store.create_task({"name": "x", "kind": "agent", "schedule": {"type": "cron", "expr": "99 * * * *"}},
                          root=tmp_path)
    locs = {e["loc"] for e in ei.value.errors}
    assert {"prompt", "schedule/expr"} <= locs
    r = store.create_task({"name": "Changelog MikroTik", "kind": "agent", "prompt": "veja",
                           "schedule": {"type": "cron", "expr": "0 8 * * *"}}, root=tmp_path)
    assert r["task"]["id"] == "changelog-mikrotik"
    again = store.create_task({"name": "Changelog MikroTik", "kind": "script", "script": "true",
                               "schedule": {"type": "interval", "minutes": 5}}, root=tmp_path)
    assert again["task"]["id"] == "changelog-mikrotik-2"
    cf = store.cron_file(tmp_path)
    assert str(cf).startswith(str(tmp_path)) and "cli.py --data-root" in cf.read_text()


def test_rev_conflict_and_nested_scheduling_block(tmp_path, monkeypatch):
    r = store.create_task({"name": "a", "kind": "script", "script": "true",
                           "schedule": {"type": "interval", "minutes": 5}}, root=tmp_path)
    store.update_task("a", {"enabled": False}, root=tmp_path)
    with pytest.raises(store.RevConflict):
        store.update_task("a", {"enabled": True}, rev=r["rev"], root=tmp_path)
    monkeypatch.setenv("NETOPS_SCHEDULED_RUN", "1")
    with pytest.raises(store.TaskError):
        store.create_task({"name": "b", "kind": "script", "script": "true",
                           "schedule": {"type": "interval", "minutes": 5}}, root=tmp_path)


# ---------------------------------------------------------------- tick -----
def _cfg(*tasks):
    return {"timezone": "America/Sao_Paulo", "tasks": list(tasks)}


def test_compute_due_cron_advances_before_dispatch():
    t = {"id": "a", "enabled": True, "schedule": {"type": "cron", "expr": "0 9 * * *"}}
    st = {"tasks": {}, "unread": []}
    assert runner.compute_due(_cfg(t), st, _dt("2026-11-12T08:59")) == []
    assert st["tasks"]["a"]["next_run_at"] == _dt("2026-11-12T09:00").timestamp()
    assert runner.compute_due(_cfg(t), st, _dt("2026-11-12T09:00")) == ["a"]
    assert runner.compute_due(_cfg(t), st, _dt("2026-11-12T09:00")) == []      # mesmo minuto não repete
    assert st["tasks"]["a"]["next_run_at"] == _dt("2026-11-13T09:00").timestamp()


def test_compute_due_missed_once_and_disabled():
    t = {"id": "a", "enabled": True, "schedule": {"type": "cron", "expr": "0 9 * * *"}}
    st = {"tasks": {}, "unread": []}
    runner.compute_due(_cfg(t), st, _dt("2026-11-12T08:00"))
    assert runner.compute_due(_cfg(t), st, _dt("2026-11-12T11:30")) == []      # cron parado > 1 h: pula
    assert st["tasks"]["a"]["last_status"] == "missed"
    once = {"id": "o", "enabled": True, "schedule": {"type": "once", "at": "2026-11-12T10:00"}}
    st2 = {"tasks": {}, "unread": []}
    runner.compute_due(_cfg(once), st2, _dt("2026-11-12T09:00"))
    assert runner.compute_due(_cfg(once), st2, _dt("2026-11-12T10:00")) == ["o"]
    assert st2["tasks"]["o"]["completed"] and runner.compute_due(_cfg(once), st2, _dt("2026-11-12T10:05")) == []
    off = {**t, "id": "off", "enabled": False}
    assert runner.compute_due(_cfg(off), st, _dt("2026-11-12T09:00")) == []


def test_silent_wake_and_notify_rules():
    assert runner.is_silent("[SILENT]") and runner.is_silent("nada\n[SILENT]") and runner.is_silent("")
    assert not runner.is_silent("Saiu a 7.21 com correção do bug [SILENT] no meio")
    assert not runner.wake_agent("") and not runner.wake_agent('x\n{"wakeAgent": false}')
    assert runner.wake_agent("versão 7.21")
    sc, ag = {"kind": "script"}, {"kind": "agent"}
    assert not runner.should_notify(sc, "ok", False) and runner.should_notify(sc, "error", False)
    assert runner.should_notify(ag, "ok", False) and not runner.should_notify(ag, "ok", True)
    assert not runner.should_notify({**ag, "notify": "never"}, "error", False)
    assert runner.should_notify({**sc, "notify": "always"}, "ok", False)


def test_agent_command_permissions():
    restricted = runner.agent_command({"agent": {}}, "p")
    assert "--dangerously-skip-permissions" not in restricted and "Bash" in restricted
    assert "CronCreate" in restricted
    full = runner.agent_command({"agent": {"permissions": "full", "model": "sonnet"}}, "p")
    assert "--dangerously-skip-permissions" in full and full[full.index("--model") + 1] == "sonnet"


def test_run_script_and_hybrid_skip(tmp_path):
    store.create_task({"name": "falha", "kind": "script", "script": "echo oi; exit 3",
                       "schedule": {"type": "interval", "minutes": 5}}, root=tmp_path)
    store.create_task({"name": "hib", "kind": "hybrid", "script": "true", "prompt": "analise",
                       "schedule": {"type": "interval", "minutes": 5}}, root=tmp_path)
    rec = runner.run("falha", "20261112-100000-aaaaaa", root=tmp_path)
    assert rec["status"] == "error" and rec["exit_code"] == 3 and "oi" in rec["script_output"]
    assert rec["notified"]
    rec2 = runner.run("hib", "20261112-100000-bbbbbb", root=tmp_path)
    assert rec2["status"] == "ok" and rec2["agent_skipped"] and not rec2["notified"]
    st = store.read_state(tmp_path)
    assert st["unread"] == ["falha/20261112-100000-aaaaaa"]
    assert st["tasks"]["falha"]["failures"] == 1
    assert runner.mark_read(None, tmp_path) == 0


# ---------------------------------------------------------------- API ------
@pytest.fixture()
def client(env):
    from app import create_app
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_api_crud_run_and_notifications(client, env):
    ov = client.get("/api/schedules").json()
    assert ov["config"]["tasks"] == [] and ov["unread"] == 0
    r = client.post("/api/schedules/tasks", json={"name": "Eco", "kind": "script", "script": "echo eco",
                                                  "schedule": {"type": "cron", "expr": "0 3 * * *"}},
                    headers={"If-Match": ov["rev"]})
    assert r.status_code == 200, r.text
    bad = client.post("/api/schedules/tasks", json={"name": "", "kind": "agent", "schedule": {"type": "cron", "expr": "x"}})
    assert bad.status_code == 422
    stale = client.put("/api/schedules/tasks/eco", json={"enabled": False}, headers={"If-Match": ov["rev"]})
    assert stale.status_code == 409
    ov = client.get("/api/schedules").json()
    t = ov["config"]["tasks"][0]
    assert t["kind_label"] == "Determinística / script" and t["state"]["next_run_at"]
    assert client.get("/api/schedules/preview", params={"type": "cron", "expr": "0 9 * * *"}).json()["next_runs"]
    assert client.get("/api/schedules/preview", params={"type": "cron", "expr": "nope"}).json()["error"]
    run_id = client.post("/api/schedules/tasks/eco/run").json()["run_id"]
    for _ in range(50):
        d = client.get(f"/api/schedules/runs/eco/{run_id}")
        if d.status_code == 200 and d.json()["state"] == "done":
            break
        time.sleep(0.1)
    assert d.json()["status"] == "ok" and "eco" in d.json()["script_output"]
    assert client.get("/api/schedules/runs").json()["runs"][0]["run_id"] == run_id
    assert client.get("/api/schedules/runs/eco/../../etc").status_code == 404
    assert client.delete("/api/schedules/tasks/eco").status_code == 200
    assert client.get("/api/schedules").json()["config"]["tasks"] == []
    assert json.loads((env / "runs" / "schedules" / "state.json").read_text())["tasks"] == {}


# ------------------------------------------------- instalação nova ---------
def _task(root):
    store.create_task({"name": "t", "kind": "script", "script": "true",
                       "schedule": {"type": "interval", "minutes": 5}}, root=root)


def test_self_heal_reinstalls_missing_cron_line(tmp_path):
    assert store.ensure_cron_if_tasks(tmp_path) is None          # sem tarefas: não instala nada
    _task(tmp_path)
    cf = store.cron_file(tmp_path)
    cf.unlink()                                                   # reinstalação/restore perdeu a linha
    assert store.cron_status(tmp_path, check_daemon=False)["installed"] is False
    assert store.ensure_cron_if_tasks(tmp_path)["installed"] is True
    assert cf.exists() and store.ensure_cron_if_tasks(tmp_path) is None   # idempotente


def test_non_root_falls_back_to_user_crontab(tmp_path, monkeypatch):
    """Console sem root não escreve em /etc/cron.d: usa o crontab do usuário (bloco idempotente)."""
    tab = tmp_path / "crontab.txt"
    tab.write_text("0 1 * * * /usr/bin/outra-coisa\n")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "crontab").write_text(f'#!/bin/bash\nif [ "$1" = "-l" ]; then cat {tab}; else cat > {tab}; fi\n')
    (fake / "crontab").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    monkeypatch.setattr(store, "_cron_mode", lambda root=None: "user")
    r1 = store.install_cron(tmp_path)
    r2 = store.install_cron(tmp_path)
    text = tab.read_text()
    assert r1["installed"] and r2["mode"] == "user"
    assert text.count(store.USER_BEGIN) == 1 and "outra-coisa" in text      # preserva o resto
    assert " root " not in text.split(store.USER_BEGIN)[1]                 # crontab de usuário: sem campo usuário
    assert store.cron_status(tmp_path, check_daemon=False)["installed"] is True
