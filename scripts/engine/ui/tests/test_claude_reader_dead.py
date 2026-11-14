"""Leitor do SDK morre (linha JSON > buffer): a sessão NÃO pode ficar "em andamento" para sempre."""
import asyncio

from services import claude_svc


class DeadClient:
    def __init__(self):
        self.disconnected = False

    async def receive_messages(self):
        raise RuntimeError("Failed to decode JSON: JSON message exceeded maximum buffer size of 1048576 bytes")
        yield  # pragma: no cover

    async def disconnect(self):
        self.disconnected = True


class FakeWS:
    query_params = {}


def test_options_buffer_acima_do_padrao_do_sdk():
    assert claude_svc.SDK_MAX_BUFFER >= 32 * 1024 * 1024


def test_leitor_morto_encerra_a_sessao():
    async def run():
        s = claude_svc.ClaudeWebSession(FakeWS())
        s.client = DeadClient()
        s._busy = True
        sent = []

        async def capture(ev, only=None, skip=None):
            sent.append(ev)
        s._send = capture
        s._sdk_task = asyncio.create_task(s._sdk_pump())
        await s._sdk_task
        for _ in range(5):
            await asyncio.sleep(0)
        return s, sent

    s, sent = asyncio.run(run())
    assert any(e.get("type") == "error" and "maximum buffer" in e.get("detail", "") for e in sent)
    assert s._busy is False
    assert s._closing_done is True
    assert s.client.disconnected is True
