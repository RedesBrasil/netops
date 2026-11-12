"""Retomada automática da aba Claude após restart do console — sem agente real."""
from types import SimpleNamespace
import asyncio
import json
import time

import pytest

from services import claude_svc


class FakeClient:
    def __init__(self):
        self.queries = []

    async def query(self, text):
        self.queries.append(text)

    async def disconnect(self):
        pass

    async def get_context_usage(self):
        return {}


@pytest.fixture()
def fake(monkeypatch):
    """Sessão persistente sem subprocesso: start() só pluga um FakeClient."""
    started = []

    async def start(self):
        async with self._start_lock:
            if self._started:
                return
            self.client = FakeClient()
            self._started = True
            started.append(self)

    async def send(self, obj, only=None, skip=None):
        self.sent = getattr(self, "sent", []) + [obj]

    monkeypatch.setattr(claude_svc.ClaudeWebSession, "start", start)
    monkeypatch.setattr(claude_svc.ClaudeWebSession, "_send", send)
    monkeypatch.setattr(claude_svc, "project_session_exists", lambda sid: True)
    monkeypatch.setattr(claude_svc.claude_prefs, "get_session", lambda sid: {})
    monkeypatch.setattr(claude_svc.claude_prefs, "set_session", lambda *a, **k: None)
    monkeypatch.setattr(claude_svc, "_SHUTTING_DOWN", False)
    monkeypatch.setattr(claude_svc, "_LIVE", {})
    cls = type("ResultMessage", (SimpleNamespace,), {})
    monkeypatch.setattr(claude_svc, "ResultMessage", cls, raising=False)
    for name in ("SystemMessage", "StreamEvent", "AssistantMessage", "UserMessage"):
        monkeypatch.setattr(claude_svc, name, type(name, (SimpleNamespace,), {}), raising=False)
    return SimpleNamespace(started=started, Result=cls)


def _entries():
    try:
        return json.loads(claude_svc._RESUME_FILE.read_text())
    except FileNotFoundError:
        return {}


def _write(entries):
    claude_svc._RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
    claude_svc._RESUME_FILE.write_text(json.dumps(entries))


def _live(sid="sid-1"):
    s = claude_svc.ClaudeWebSession(persist=True, resume=sid)
    s.client = FakeClient()
    s._started = True
    claude_svc._LIVE[sid] = s
    return s


def test_turno_em_andamento_fica_anotado_e_sai_no_fim(fake):
    s = _live()
    asyncio.run(s._query("faça X"))
    assert _entries()["sid-1"]["busy"] is True
    result = fake.Result(session_id="sid-1", total_cost_usd=0, usage={}, is_error=False, result="ok")
    asyncio.run(s._translate(result))
    assert "sid-1" not in _entries()


def test_shutdown_preserva_anotacao_e_bye_apaga(fake):
    s = _live()
    asyncio.run(s._query("faça X"))
    asyncio.run(claude_svc.shutdown_all())
    assert _entries()["sid-1"]["busy"] is True   # restart: tem que voltar

    claude_svc._SHUTTING_DOWN = False
    s2 = _live("sid-2")
    asyncio.run(s2._query("faça Y"))
    asyncio.run(s2.teardown())                     # bye/carência: encerrou de verdade
    assert "sid-2" not in _entries()


def test_restart_relanca_sessao_e_manda_prompt_de_continuacao(fake):
    _write({"sid-1": {"busy": True, "queue": ["depois isso"], "model": None, "effort": None,
                      "chain": 0, "t": time.time()}})
    done = asyncio.run(claude_svc.resume_after_restart(delay=0))
    assert done == ["sid-1"]
    s = claude_svc._LIVE["sid-1"]
    assert s.client.queries == [claude_svc.RESUME_PROMPT]
    assert [q["text"] for q in s._queue] == ["depois isso"]
    e = _entries()["sid-1"]
    assert e["chain"] == 1 and e["busy"] is True


def test_aba_que_reconectou_antes_recebe_o_prompt_sem_segundo_agente(fake):
    _write({"sid-1": {"busy": True, "queue": [], "chain": 0, "t": time.time()}})
    s, how = claude_svc.attach_or_create(owner="", resume="sid-1", model=None)
    assert how == "new" and claude_svc._LIVE["sid-1"] is s   # registrada já na criação
    asyncio.run(claude_svc.resume_after_restart(delay=0))
    assert claude_svc._LIVE["sid-1"] is s and len(fake.started) == 1
    assert s.client.queries == [claude_svc.RESUME_PROMPT]


def test_nao_retoma_velha_nem_em_loop_nem_ocioso(fake):
    old = time.time() - claude_svc._RESUME_MAX_AGE - 5
    _write({"velha": {"busy": True, "chain": 0, "t": old},
            "loop": {"busy": True, "chain": claude_svc._RESUME_MAX_CHAIN, "t": time.time()},
            "ociosa": {"busy": False, "queue": ["x"], "chain": 0, "t": time.time()}})
    assert asyncio.run(claude_svc.resume_after_restart(delay=0)) == []
    assert fake.started == [] and _entries() == {}


def test_prompt_humano_zera_cadeia(fake):
    s = _live()
    s._auto_chain = 2

    class WS:
        query_params = {}
        inbox = [{"type": "prompt", "text": "oi"}]

        async def receive_json(self):
            if not self.inbox:
                raise claude_svc.WebSocketDisconnect()
            return self.inbox.pop(0)

    asyncio.run(s._ws_pump(WS()))
    assert s._auto_chain == 0 and _entries()["sid-1"]["chain"] == 0


def test_aba_reconectando_antes_nao_apaga_anotacao(fake):
    """Regressão 12/11: serve(first) da aba chama _send_queue(fresh) -> _track() da sessão nova e
    ociosa apagava a anotação antes da retomada ler o arquivo."""
    _write({"sid-1": {"busy": True, "queue": [], "chain": 0, "t": time.time()}})
    s, how = claude_svc.attach_or_create(owner="", resume="sid-1", model=None)
    asyncio.run(s.start())
    asyncio.run(s._send_queue(fresh=True))          # o que serve(first=True) faz
    assert _entries()["sid-1"]["busy"] is True      # anotação intacta
    assert asyncio.run(claude_svc.resume_after_restart(delay=0)) == ["sid-1"]
    assert s.client.queries == [claude_svc.RESUME_PROMPT]


def test_snapshot_do_startup_prevalece(fake):
    snap = {"sid-1": {"busy": True, "queue": [], "chain": 0, "t": time.time()}}
    _write({})                                      # arquivo mexido depois do startup
    assert asyncio.run(claude_svc.resume_after_restart(delay=0, snapshot=snap)) == ["sid-1"]
