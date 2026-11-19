"""Central de Avisos: store (SQLite), blocos netops-inbox do agente, integração com tarefas agendadas e API.

Tudo numa raiz de dados temporária (runs/inbox.db de teste).
"""
from __future__ import annotations

import time

import pytest

import deps  # noqa: F401  (põe scripts/engine no sys.path)
from inbox import actions, store
from scheduler import runner
from scheduler import store as sstore

SID = "11111111-2222-3333-4444-555555555555"


def test_add_validates_and_dedupes(tmp_path):
    with pytest.raises(store.InboxError) as ei:
        store.add({"kind": "nope", "title": ""}, tmp_path)
    assert {"kind", "title"} <= {e["loc"] for e in ei.value.errors}
    with pytest.raises(store.InboxError):   # ação só em pedido de aprovação
        store.add({"kind": "alert", "title": "x", "action": {"type": "command", "command": "ls"}}, tmp_path)
    a = store.add({"kind": "alert", "severity": "critical", "title": "Telnet aberto", "dedupe_key": "telnet"}, tmp_path)
    store.mark_read([a["id"]], "ana", tmp_path)
    b = store.add({"kind": "alert", "severity": "critical", "title": "Telnet aberto (de novo)", "dedupe_key": "telnet"}, tmp_path)
    assert b["id"] == a["id"] and b["occurrences"] == 2 and b["unread"]          # repetiu = volta a ficar não lida
    assert store.summary(tmp_path) == {"unread": 1, "pending": 0, "badge": 1, "critical": 1}


def test_approval_decide_once_and_badge(tmp_path):
    m = store.add({"kind": "approval", "title": "Apagar temporários"}, tmp_path)
    assert m["status"] == "pending" and not m["actionable"]
    store.mark_read([m["id"]], "ana", tmp_path)
    assert store.summary(tmp_path)["badge"] == 1                                 # pendente conta até decidir
    with pytest.raises(store.NotPending):
        store.decide(m["id"], "approve", "ana", root=tmp_path) and store.decide(m["id"], "reject", "bia", root=tmp_path)
    rec = store.get(m["id"], tmp_path)
    assert rec["status"] == "approved" and rec["decided_by"] == "ana"
    assert store.summary(tmp_path)["badge"] == 0
    assert store.set_archived([m["id"]], True, "ana", tmp_path) == 1


def test_pending_does_not_archive_and_expires(tmp_path):
    m = store.add({"kind": "approval", "title": "x", "expires_at": time.time() - 1}, tmp_path)
    assert store.get(m["id"], tmp_path)["status"] == "expired"
    p = store.add({"kind": "approval", "title": "y"}, tmp_path)
    assert store.set_archived([p["id"]], True, "", tmp_path) == 0


def test_command_action_runs_with_decision_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NETOPS_UI_DATA_ROOT", str(tmp_path))
    m = store.add({"kind": "approval", "title": "eco", "action": {
        "type": "command", "command": 'echo "$NETOPS_INBOX_DECISION por $NETOPS_INBOX_DECIDED_BY: $NETOPS_INBOX_NOTE"'}}, tmp_path)
    store.mark_read([m["id"]], "ana", tmp_path)
    store.decide(m["id"], "approve", "ana", "pode", tmp_path)
    res = actions.execute(m["id"], tmp_path)
    assert res["status"] == "ok" and "approved por ana: pode" in res["output"]
    rec = store.get(m["id"], tmp_path)
    assert rec["result"]["state"] == "done" and rec["unread"]                    # resultado volta para o sino


def test_agent_blocks_become_messages(tmp_path):
    text = ("Varredura concluída.\n```netops-inbox\n"
            '[{"kind": "approval", "title": "Remover CT 999", "body": "parado há 90 dias"},'
            ' {"kind": "alert", "severity": "critical", "title": "root via SSH com senha"}]\n```\n'
            "```netops-inbox\n{quebrado\n```")
    created, rest = actions.ingest_agent_output(text, task={"id": "varredura", "name": "Varredura"},
                                                run_id="20261119-010000-abcdef", session_id=SID, root=tmp_path)
    assert [c["kind"] for c in created] == ["approval", "alert"]
    appr = created[0]
    assert appr["action"]["type"] == "agent" and appr["action"]["resume"] and appr["action"]["permissions"] == "restricted"
    assert appr["session_id"] == SID and appr["link"] == "#schedules/runs/varredura/20261119-010000-abcdef"
    assert "→ enviado à Central de Avisos: Remover CT 999" in rest and "JSON inválido" in rest
    prompt = actions.decision_prompt({**store.get(appr["id"], tmp_path), "status": "approved", "decided_by": "ana"},
                                     appr["action"])
    assert "ana APROVOU" in prompt and "Remover CT 999" in prompt


def test_scheduled_failure_posts_alert_and_read_syncs(tmp_path, monkeypatch):
    monkeypatch.setenv("NETOPS_UI_DATA_ROOT", str(tmp_path))
    sstore.create_task({"name": "Falha", "kind": "script", "script": "echo oops; exit 3",
                        "schedule": {"type": "cron", "expr": "0 3 * * *"}}, root=tmp_path)
    r1 = runner.run("falha", "20261119-030000-aaaaaa", "manual", tmp_path)
    runner.run("falha", "20261119-030100-bbbbbb", "manual", tmp_path)
    assert r1["status"] == "error"
    items = store.list_messages("open", root=tmp_path)
    assert len(items) == 1 and items[0]["kind"] == "alert" and items[0]["occurrences"] == 2   # falha repetida agrupa
    assert items[0]["task_id"] == "falha"
    # lida na Central = lida nas execuções
    store.mark_read([items[0]["id"]], "ana", tmp_path)
    assert "falha/20261119-030100-bbbbbb" not in sstore.read_state(tmp_path)["unread"]
    # e o contrário
    store.mark_unread(items[0]["id"], tmp_path)
    runner.mark_read(None, tmp_path)
    assert store.summary(tmp_path)["unread"] == 0


def test_agent_hint_documents_inbox():
    assert "netops-inbox" in runner._agent_hint()


def test_cli_env_source(monkeypatch):
    monkeypatch.setenv("NETOPS_SCHEDULED_TASK", "limpeza")
    monkeypatch.setenv("NETOPS_SCHEDULED_RUN_ID", "20261119-010000-abcdef")
    src = actions._env_source()
    assert src["source"] == "schedule" and src["link"] == "#schedules/runs/limpeza/20261119-010000-abcdef"


# ---------------------------------------------------------------- API ------
def test_api_flow(client, env):
    store.add({"kind": "info", "title": "Backup ok"}, env)
    m = store.add({"kind": "approval", "title": "Apagar x", "action": {"type": "command", "command": "true"}}, env)
    s = client.get("/api/inbox/summary").json()
    assert s["badge"] == 2 and s["pending"] == 1
    lst = client.get("/api/inbox", params={"view": "pending"}).json()["items"]
    assert [x["id"] for x in lst] == [m["id"]] and "body" not in lst[0]
    assert client.get(f"/api/inbox/{m['id']}").json()["actionable"] is True
    assert client.get("/api/inbox/99999").status_code == 404
    assert client.post(f"/api/inbox/{m['id']}/decision", json={"decision": "talvez"}).status_code in (400, 422)
    r = client.post(f"/api/inbox/{m['id']}/decision", json={"decision": "approve", "note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/api/inbox/{m['id']}/decision", json={"decision": "reject"}).status_code == 409
    for _ in range(50):   # ação roda num processo destacado
        rec = client.get(f"/api/inbox/{m['id']}").json()
        if rec["result"] and rec["result"].get("state") == "done":
            break
        time.sleep(0.2)
    assert rec["result"]["status"] == "ok"
    assert client.post("/api/inbox/read", json={}).json()["unread"] == 0
    assert client.post("/api/inbox/archive", json={"read": True}).json()["changed"] == 2
    assert client.get("/api/inbox").json()["items"] == []


def test_authz_rules():
    from services import authz
    assert authz.required_perm("GET", "/inbox") == "inbox.view"
    assert authz.required_perm("GET", "/inbox/summary") == "inbox.view"
    assert authz.required_perm("POST", "/inbox/read") == "inbox.view"
    assert authz.required_perm("POST", "/inbox/3/unread") == "inbox.view"
    assert authz.required_perm("POST", "/inbox/3/decision") == "inbox.decide"
    assert authz.required_perm("POST", "/inbox/archive") == "inbox.decide"
    assert authz.required_perm("POST", "/inbox") == authz.UNMAPPED          # sem rota de criação pelo navegador
