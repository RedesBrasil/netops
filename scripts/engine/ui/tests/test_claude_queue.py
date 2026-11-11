"""Fila de prompts da aba Claude: "enviar agora" x "colocar na fila" — sem agente real."""
from types import SimpleNamespace
import asyncio

import pytest

from services import claude_svc


class FakeClient:
    def __init__(self):
        self.queries = []
        self.interrupts = 0

    async def query(self, text):
        self.queries.append(text)

    async def interrupt(self):
        self.interrupts += 1

    async def get_context_usage(self):
        return {}


class FakeWS:
    """receive_json devolve os comandos da lista e depois 'desconecta'."""
    query_params = {}

    def __init__(self, inbox):
        self.inbox = list(inbox)

    async def receive_json(self):
        if not self.inbox:
            raise claude_svc.WebSocketDisconnect()
        return self.inbox.pop(0)


@pytest.fixture()
def result_cls(monkeypatch):
    cls = type("ResultMessage", (SimpleNamespace,), {})
    monkeypatch.setattr(claude_svc, "ResultMessage", cls, raising=False)
    for name in ("SystemMessage", "StreamEvent", "AssistantMessage", "UserMessage"):
        monkeypatch.setattr(claude_svc, name, type(name, (SimpleNamespace,), {}), raising=False)
    return cls


def _session(inbox=()):
    s = claude_svc.ClaudeWebSession(FakeWS(inbox))
    s.client = FakeClient()
    sent = []

    async def capture(ev):
        sent.append(ev)
    s._send = capture
    return s, sent


def _result(cls, is_error=False):
    return cls(session_id=None, total_cost_usd=0, usage={}, is_error=is_error, result="ok")


def test_prompt_immediate_while_busy_goes_straight_to_agent(env):
    async def check():
        s, sent = _session([{"type": "prompt", "text": "tarefa"},
                            {"type": "prompt", "text": "ajuste agora"}])
        await s._ws_pump()
        assert s.client.queries == ["tarefa", "ajuste agora"]
        assert s._queue == []
    asyncio.run(check())


def test_queued_prompt_waits_for_turn_end_then_runs_in_order(env, result_cls):
    async def check():
        s, sent = _session([{"type": "prompt", "text": "tarefa"},
                            {"type": "prompt", "text": "depois 1", "queue": True},
                            {"type": "prompt", "text": "depois 2", "queue": True}])
        await s._ws_pump()
        assert s.client.queries == ["tarefa"]            # nada da fila foi enviado ainda
        assert [q["text"] for q in s._queue] == ["depois 1", "depois 2"]
        assert sent[-1] == {"type": "queue", "items": s._queue}
        await s._translate(_result(result_cls))          # fim do turno 1 -> despacha "depois 1"
        assert s.client.queries == ["tarefa", "depois 1"]
        assert s._busy is True
        disp = [e for e in sent if e["type"] == "queue_dispatched"]
        assert [d["text"] for d in disp] == ["depois 1"]
        # o result do turno sai ANTES do despacho (a UI encerra o turno e abre o próximo)
        kinds = [e["type"] for e in sent]
        assert kinds.index("result") < kinds.index("queue_dispatched")
        await s._translate(_result(result_cls))
        assert s.client.queries[-1] == "depois 2"
        await s._translate(_result(result_cls))
        assert s._busy is False and s._queue == []
    asyncio.run(check())


def test_queue_flag_when_idle_runs_now_and_tells_ui(env):
    async def check():
        s, sent = _session([{"type": "prompt", "text": "x", "queue": True}])
        await s._ws_pump()
        assert s.client.queries == ["x"]
        assert {"type": "queue_dispatched", "id": None, "text": "x"} in sent
    asyncio.run(check())


def test_interrupt_does_not_run_queue_and_restores_texts(env, result_cls):
    async def check():
        s, sent = _session([{"type": "prompt", "text": "tarefa"},
                            {"type": "prompt", "text": "fila", "queue": True},
                            {"type": "interrupt"}])
        await s._ws_pump()
        assert s.client.interrupts == 1
        await s._translate(_result(result_cls))
        assert s.client.queries == ["tarefa"]
        assert {"type": "queue_restored", "items": [{"id": "q1", "text": "fila"}]} in sent
        assert s._queue == [] and s._interrupted is False
        assert s._busy is False
    asyncio.run(check())


def test_error_result_does_not_run_queue(env, result_cls):
    async def check():
        s, sent = _session([{"type": "prompt", "text": "tarefa"},
                            {"type": "prompt", "text": "fila", "queue": True}])
        await s._ws_pump()
        await s._translate(_result(result_cls, is_error=True))
        assert s.client.queries == ["tarefa"]
        assert any(e["type"] == "queue_restored" for e in sent)
    asyncio.run(check())


def test_detached_restore_is_delivered_on_reattach(env, result_cls):
    async def check():
        s, sent = _session([{"type": "prompt", "text": "tarefa"},
                            {"type": "prompt", "text": "fila", "queue": True},
                            {"type": "interrupt"}])
        await s._ws_pump()
        s.ws = None                                       # aba fechada
        await s._translate(_result(result_cls))
        assert s._restore_pending == [{"id": "q1", "text": "fila"}]
        s._started = True
        sent.clear()
        await s.serve(FakeWS([]), first=False)
        assert {"type": "queue_restored", "items": [{"id": "q1", "text": "fila"}]} in sent
        assert {"type": "queue", "items": []} in sent
        assert s._restore_pending == []
    asyncio.run(check())


def test_queue_runs_with_tab_closed(env, result_cls):
    """Persist: aba fechada não impede a fila de andar (o turno roda sem ninguém olhando)."""
    async def check():
        s, sent = _session([{"type": "prompt", "text": "tarefa"},
                            {"type": "prompt", "text": "fila", "queue": True}])
        await s._ws_pump()
        s.ws = None
        await s._translate(_result(result_cls))
        assert s.client.queries == ["tarefa", "fila"]
    asyncio.run(check())


def test_remove_and_send_now(env):
    async def check():
        s, sent = _session([{"type": "prompt", "text": "tarefa"},
                            {"type": "prompt", "text": "a", "queue": True},
                            {"type": "prompt", "text": "b", "queue": True},
                            {"type": "queue_remove", "id": "q1"},
                            {"type": "queue_send_now", "id": "q2"},
                            {"type": "queue_remove", "id": "nao-existe"}])
        await s._ws_pump()
        assert s._queue == []
        assert s.client.queries == ["tarefa", "b"]       # "b" foi já, absorvido no turno atual
        assert {"type": "queue_dispatched", "id": "q2", "text": "b"} in sent
    asyncio.run(check())


def test_queue_has_static_limit(env):
    async def check():
        inbox = [{"type": "prompt", "text": "tarefa"}] + [
            {"type": "prompt", "text": f"m{i}", "queue": True} for i in range(claude_svc.MAX_QUEUE + 3)]
        s, sent = _session(inbox)
        await s._ws_pump()
        assert len(s._queue) == claude_svc.MAX_QUEUE
        assert any(e["type"] == "error" and "Fila cheia" in e["detail"] for e in sent)
    asyncio.run(check())
