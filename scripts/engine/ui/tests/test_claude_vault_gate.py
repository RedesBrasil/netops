"""Hook de cofre trancado na aba Claude: segura o comando e pede a senha — sem agente real."""
import asyncio

import pytest

from services import claude_svc


def _session():
    class WS:
        query_params = {}
    s = claude_svc.ClaudeWebSession(WS())
    sent = []

    async def _send(obj, only=None, skip=None):
        sent.append(obj["type"])

    s._send = _send
    s._busy = True
    return s, sent


def _cmd(c):
    return {"tool_input": {"command": c}}


def test_comando_sem_cofre_passa_direto(monkeypatch):
    s, sent = _session()
    monkeypatch.setattr(s, "_vault_locked", lambda: True)
    r = asyncio.run(s._hook_vault_gate(_cmd("ls -la /tmp"), "t1", None))
    assert r == {} and sent == []


def test_cofre_aberto_passa_direto(monkeypatch):
    s, sent = _session()
    monkeypatch.setattr(s, "_vault_locked", lambda: False)
    r = asyncio.run(s._hook_vault_gate(_cmd("python3 scripts/tools/access/session.py exec --host-id 1"), "t1", None))
    assert r == {} and sent == []


def test_aguarda_destrancar_e_libera(monkeypatch):
    monkeypatch.setattr(claude_svc, "VAULT_WAIT_POLL", 0.01)
    s, sent = _session()
    state = {"locked": True}
    monkeypatch.setattr(s, "_vault_locked", lambda: state["locked"])

    async def go():
        t = asyncio.create_task(s._hook_vault_gate(_cmd("python3 scripts/tools/access/session.py exec --host-id 1"), "t1", None))
        await asyncio.sleep(0.1)
        assert not t.done() and sent == ["vault_request"] and s._vault_waiting == 1
        state["locked"] = False
        return await asyncio.wait_for(t, 2)

    assert asyncio.run(go()) == {}
    assert sent == ["vault_request", "vault_resolved"] and s._vault_waiting == 0


def test_timeout_nega_com_motivo(monkeypatch):
    monkeypatch.setattr(claude_svc, "VAULT_WAIT_POLL", 0.01)
    monkeypatch.setattr(claude_svc, "VAULT_WAIT_MAX", 0.05)
    s, sent = _session()
    monkeypatch.setattr(s, "_vault_locked", lambda: True)
    r = asyncio.run(s._hook_vault_gate(_cmd("python3 scripts/tools/backup/change.py begin --host-id 1"), "t1", None))
    assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert sent[-1] == "vault_resolved"


def test_interromper_turno_solta_o_hook(monkeypatch):
    monkeypatch.setattr(claude_svc, "VAULT_WAIT_POLL", 0.01)
    s, sent = _session()
    monkeypatch.setattr(s, "_vault_locked", lambda: True)

    async def go():
        t = asyncio.create_task(s._hook_vault_gate(_cmd("python3 scripts/tools/access/session.py run --host-id 2"), "t", None))
        await asyncio.sleep(0.05)
        s._busy = False
        return await asyncio.wait_for(t, 2)

    assert asyncio.run(go())["hookSpecificOutput"]["permissionDecision"] == "deny"
