"""Ditado: config da Cloudflare (token nunca volta) e validações da rota de transcrição."""
import pytest

from services import audio_svc

AID = "a" * 32


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_svc, "_FILE", tmp_path / "audio.json")


def test_config_never_returns_token_and_preserves_on_empty(client):
    assert client.get("/api/audio/config").json() == {"configured": False, "has_token": False}
    r = client.put("/api/audio/config", json={"account_id": AID, "token": "SEGREDO"})
    assert r.status_code == 200 and r.json()["configured"] is True and "SEGREDO" not in r.text
    r = client.put("/api/audio/config", json={"account_id": AID, "token": ""})   # vazio preserva
    assert r.json()["has_token"] is True
    assert "SEGREDO" not in client.get("/api/audio/config").text
    assert oct(audio_svc._FILE.stat().st_mode & 0o777) == "0o600"
    assert client.delete("/api/audio/config").json()["configured"] is False


def test_invalid_account_id_and_account_swap_needs_token(client):
    assert client.put("/api/audio/config", json={"account_id": "xyz"}).status_code == 422
    client.put("/api/audio/config", json={"account_id": AID, "token": "t"})
    assert client.put("/api/audio/config", json={"account_id": "b" * 32}).status_code == 422


def test_transcribe_validations(client):
    f = lambda b: {"audio": ("voice.ogg", b, "audio/ogg")}
    assert client.post("/api/audio/transcribe", files=f(b"x")).status_code == 400   # não configurado
    client.put("/api/audio/config", json={"account_id": AID, "token": "t"})
    assert client.post("/api/audio/transcribe", files=f(b"")).status_code == 400
    assert client.post("/api/audio/transcribe", files=f(b"RIFFxxxx")).status_code == 415
    big = b"OggS" + b"\0" * (audio_svc.MAX_AUDIO_BYTES + 1)
    assert client.post("/api/audio/transcribe", files=f(big)).status_code == 413


def test_transcribe_success_via_mock(client, monkeypatch):
    client.put("/api/audio/config", json={"account_id": AID, "token": "t"})

    class R:
        status_code, is_success = 200, True
        def json(self): return {"success": True, "result": {"text": " Olá. "}}

    class C:
        def __init__(self, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json, headers):
            assert url.endswith("/ai/run/@cf/openai/whisper-large-v3-turbo") and json["language"] == "pt"
            return R()

    monkeypatch.setattr(audio_svc.httpx, "AsyncClient", C)
    ogg = b"OggS" + b"\0" * 24 + b"OpusHead" + b"\0" * 20
    r = client.post("/api/audio/transcribe", files={"audio": ("v.ogg", ogg, "audio/ogg")})
    assert r.status_code == 200 and r.json() == {"transcription": "Olá."}


def _fake_accounts(monkeypatch, accounts):
    class R:
        status_code, is_success = 200, True
        def json(self): return {"result": accounts, "result_info": {"total_pages": 1}}

    class C:
        def __init__(self, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, headers=None): return R()

    monkeypatch.setattr(audio_svc.httpx, "AsyncClient", C)


def test_token_only_autodiscovers_single_account(client, monkeypatch):
    _fake_accounts(monkeypatch, [{"id": AID, "name": "Minha"}])
    r = client.put("/api/audio/config", json={"token": "SEGREDO"})
    assert r.json()["configured"] is True and r.json()["account_id"] == AID


def test_token_only_multiple_accounts_asks_choice_without_saving(client, monkeypatch):
    _fake_accounts(monkeypatch, [{"id": AID, "name": "A"}, {"id": "b" * 32, "name": "B"}])
    r = client.put("/api/audio/config", json={"token": "SEGREDO"})
    assert r.json()["needs_account"] is True and len(r.json()["accounts"]) == 2 and "SEGREDO" not in r.text
    assert client.get("/api/audio/config").json()["configured"] is False
