"""Persistência da aba Claude: sair/trocar de conversa NÃO pode matar turno em andamento."""
import asyncio

from services import claude_svc


class FakeWS:
    query_params = {}

    def __init__(self, inbox):
        self.inbox = list(inbox)

    async def receive_json(self):
        if not self.inbox:
            raise claude_svc.WebSocketDisconnect()
        return self.inbox.pop(0)

    async def send_text(self, data):
        pass

    async def close(self):
        pass


def _session():
    s = claude_svc.ClaudeWebSession(owner="o", persist=True)
    s._started = True
    return s


def _serve(s, ws):
    async def go():
        s._send = _noop
        await s.serve(ws, first=False)
    asyncio.run(go())


async def _noop(*a, **k):
    return None


def test_bye_com_turno_rodando_nao_mata_a_sessao(env):
    s = _session()
    s._busy = True
    _serve(s, FakeWS([{"type": "bye"}]))
    assert not s._closing_done and s._wss == []


def test_bye_com_fila_ou_pergunta_aberta_nao_mata(env):
    s = _session()
    s._queue = [{"id": "q1", "text": "x"}]
    _serve(s, FakeWS([{"type": "bye"}]))
    assert not s._closing_done


def test_bye_de_uma_aba_nao_mata_a_sessao_das_outras(env):
    s = _session()
    outra = FakeWS([])
    s._wss.append(outra)
    _serve(s, FakeWS([{"type": "bye"}]))
    assert not s._closing_done and s._wss == [outra]


def test_bye_em_sessao_ociosa_e_sozinha_encerra(env):
    s = _session()
    _serve(s, FakeWS([{"type": "bye"}]))
    assert s._closing_done


def test_queda_de_socket_sem_bye_nunca_encerra(env):
    s = _session()
    _serve(s, FakeWS([]))
    assert not s._closing_done
