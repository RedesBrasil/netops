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


@pytest.fixture()
def sdk_message_types(monkeypatch):
    """Mensagens falsas permitem testar tradução sem instalar ou iniciar o SDK."""
    classes = {}
    for name in ("SystemMessage", "StreamEvent", "AssistantMessage", "UserMessage",
                 "ResultMessage", "TextBlock", "ThinkingBlock", "ToolUseBlock", "ToolResultBlock"):
        cls = type(name, (SimpleNamespace,), {})
        classes[name] = cls
        monkeypatch.setattr(claude_svc, name, cls, raising=False)
    return SimpleNamespace(**classes)


def _translated_events(message):
    sent = []
    async def check():
        session = claude_svc.ClaudeWebSession()
        async def capture(event):
            sent.append(event)
        session._send = capture
        await session._translate(message)
    asyncio.run(check())
    return sent


@pytest.mark.parametrize("error_code", ["not_found", "rate_limit", "authentication_failed"])
def test_assistant_error_preserves_detail_without_assistant_text(sdk_message_types, error_code):
    detail = "There is an issue with the selected model (fixture-model)."
    msg = sdk_message_types.AssistantMessage(
        model="fixture-model", error=error_code,
        content=[sdk_message_types.TextBlock(text=detail)],
    )
    events = _translated_events(msg)
    errors = [event for event in events if event["type"] == "error"]
    assert len(errors) == 1
    assert detail in errors[0]["detail"]
    assert errors[0]["error_code"] == error_code
    assert not any(event["type"] == "text_delta" for event in events)


@pytest.mark.parametrize("status", [429, 529, 401, 403])
def test_result_preserves_structured_api_failure(sdk_message_types, status):
    msg = sdk_message_types.ResultMessage(
        session_id=A, total_cost_usd=0, usage={}, is_error=True,
        result=None, errors=["Falha simulada da API"], api_error_status=status,
    )
    events = _translated_events(msg)
    result = next(event for event in events if event["type"] == "result")
    assert result["is_error"] is True
    assert result["result"] is None
    assert result["errors"] == ["Falha simulada da API"]
    assert result["api_error_status"] == status


def test_result_remains_compatible_with_sdk_without_error_metadata(sdk_message_types):
    msg = sdk_message_types.ResultMessage(
        session_id=A, total_cost_usd=0, usage={}, is_error=False, result="Resposta simulada",
    )
    events = _translated_events(msg)
    result = next(event for event in events if event["type"] == "result")
    assert result["result"] == "Resposta simulada"
    assert result.get("errors") is None
    assert result.get("api_error_status") is None


def test_start_with_cold_cache_discovers_model_outside_websocket_loop(env, monkeypatch):
    """A descoberta síncrona possui seu próprio loop e precisa ocorrer em outra thread."""
    import threading
    from services import claude_models

    thread_id = threading.get_ident()
    discovered = []
    clients = []
    expected = "claude-sonnet-5-5[1m]"

    async def discover():
        assert threading.get_ident() != thread_id
        discovered.append(True)
        return [{"id": expected, "name": "Sonnet fictício"}]

    class Client:
        def __init__(self, *, options):
            self.options = options
            self.connected = False
            self.disconnected = False
            clients.append(self)

        async def connect(self, prompt=None):
            assert prompt is None
            self.connected = True

        async def disconnect(self):
            self.disconnected = True

        async def receive_messages(self):
            if False:
                yield None

    monkeypatch.setattr(claude_models, "_cache", {"at": 0.0, "models": None})
    monkeypatch.setattr(claude_models, "_retry_after", 0.0)
    monkeypatch.setattr(claude_models, "_load_disk", lambda: None)
    monkeypatch.setattr(claude_models, "_save_disk", lambda *args: None)
    monkeypatch.setattr(claude_models, "_fetch_cli", discover)
    monkeypatch.setattr(claude_svc, "ClaudeSDKClient", Client, raising=False)

    async def check():
        session = claude_svc.ClaudeWebSession()
        monkeypatch.setattr(session, "_options", lambda: SimpleNamespace(model=session._model))
        try:
            await session.start()
            assert discovered == [True]
            assert clients[0].options.model == expected
            assert clients[0].connected
            assert claude_models._retry_after == 0.0
        finally:
            await session.teardown()
        assert clients[0].disconnected

    asyncio.run(check())
