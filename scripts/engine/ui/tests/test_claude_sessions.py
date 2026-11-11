"""Links individuais de conversa: consultas e sockets fictícios, sem agente real."""
from types import SimpleNamespace
import asyncio
import sys

import pytest

import deps
from services import claude_svc

A = "11111111-1111-4111-8111-111111111111"


def test_lookup_requires_feature_and_returns_404_for_missing(client, monkeypatch):
    assert client.get(f"/api/claude/sessions/{A}").status_code == 403
    monkeypatch.setattr(deps.STATE, "enable_claude", True)
    monkeypatch.setattr(claude_svc, "project_session_exists", lambda sid: sid == A)
    assert client.get(f"/api/claude/sessions/{A}").json() == {"id": A}
    assert client.get("/api/claude/sessions/invalid").status_code == 404


def test_project_lookup_uses_current_project_without_recent_list(env, monkeypatch):
    calls = []
    def lookup(sid, *, directory):
        calls.append((sid, directory))
        return SimpleNamespace(session_id=sid) if sid == A else None
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", SimpleNamespace(get_session_info=lookup))
    monkeypatch.setattr(claude_svc, "_SDK_OK", True)
    assert claude_svc.project_session_exists(A)
    assert calls == [(A, str(env))]
    assert not claude_svc.project_session_exists("../../other-project")
    assert len(calls) == 1
    assert not claude_svc.project_session_exists("22222222-2222-4222-8222-222222222222")


def test_live_session_can_be_found_before_transcript_exists(env, monkeypatch):
    monkeypatch.setattr(claude_svc, "_LIVE", {A: SimpleNamespace(_closing_done=False)})
    monkeypatch.setattr(claude_svc, "_SDK_OK", False)
    assert claude_svc.project_session_exists(A)
    claude_svc._LIVE[A]._closing_done = True
    assert not claude_svc.project_session_exists(A)


def test_lookup_older_sdk_fallback_has_no_recent_limit(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", SimpleNamespace())
    monkeypatch.setattr(claude_svc, "_SDK_OK", True)
    calls = []
    def listing(limit):
        calls.append(limit)
        return [{"id": A}]
    monkeypatch.setattr(claude_svc, "list_project_sessions", listing)
    assert claude_svc.project_session_exists(A)
    assert calls == [None]


@pytest.mark.parametrize("persist", [False, True])
def test_missing_resume_never_launches_agent(client, monkeypatch, persist):
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setattr(deps.STATE, "enable_claude", True)
    monkeypatch.setattr(deps.STATE, "claude_persist", persist)
    monkeypatch.setattr(deps.STATE, "allowed_hosts", ("127.0.0.1", "testserver"))
    monkeypatch.setattr(claude_svc, "is_available", lambda: True)
    monkeypatch.setattr(claude_svc, "project_session_exists", lambda sid: False)
    monkeypatch.setattr(claude_svc, "ClaudeWebSession", lambda *a, **kw: pytest.fail("Agente não deve iniciar"))
    with client.websocket_connect(f"/api/claude?resume={A}") as ws:
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 4404


def test_takeover_uses_close_code_without_reconnect_loop(env):
    async def check():
        closes = []
        class Socket:
            query_params = {}
            async def close(self, **kw):
                closes.append(kw)
        old, new = Socket(), Socket()
        session = claude_svc.ClaudeWebSession(old)
        session.attach(new)
        await asyncio.sleep(0)
        assert session.ws is new
        assert closes == [{"code": 4409, "reason": "session_superseded"}]
    asyncio.run(check())
