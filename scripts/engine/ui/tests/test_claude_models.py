"""Catálogo do CLI e cache isolados, sem prompts, rede ou credenciais reais."""
from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
import urllib.request

import pytest

from services import claude_models, claude_svc


SOURCE = "claude-cli-v1"
CATALOG = [
    {"id": "claude-sonnet-4-10", "name": "Sonnet de teste"},
    {"id": "claude-haiku-4-5", "name": "Haiku de teste"},
]


def _forbidden(*args, **kwargs):
    pytest.fail("O teste não pode consultar a API, credenciais ou o agente real.")


@pytest.fixture(autouse=True)
def isolated_models(env, monkeypatch):
    """Cada teste recebe cache privado e relógio controlado."""
    clock = [1_800_000_000.0]
    monkeypatch.setenv("HOME", str(env))
    monkeypatch.setattr(claude_models, "_CACHE_FILE", env / "runs" / "models-cache.json")
    monkeypatch.setattr(claude_models, "_cache", {"at": 0.0, "models": None})
    monkeypatch.setattr(claude_models, "_retry_after", 0.0, raising=False)
    monkeypatch.setattr(claude_models, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    if hasattr(claude_models, "_token"):
        monkeypatch.setattr(claude_models, "_token", _forbidden)
    return clock


def _cache_on_disk(at, models, source=SOURCE):
    data = {"at": at, "models": models}
    if source is not None:
        data["source"] = source
    path = claude_models._CACHE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_cli_catalog_uses_only_handshake_and_resolves_default(env, monkeypatch):
    """O catálogo vem do mesmo CLI da sessão, sem query nem ferramentas."""
    calls = []
    info = {"models": [
        {"value": "default", "displayName": "Padrão", "resolvedModel": "claude-sonnet-4-10"},
        {"value": "claude-sonnet-4-5", "displayName": "Sonnet anterior"},
        {"value": "claude-haiku-4-5", "displayName": "Haiku"},
    ]}

    class Options(SimpleNamespace):
        pass

    class Client:
        def __init__(self, *, options):
            calls.append(("options", options))

        async def connect(self, prompt=None):
            assert prompt is None, "Consultar modelos não pode executar um prompt."
            calls.append(("connect", None))

        async def disconnect(self):
            calls.append(("disconnect", None))

        async def __aenter__(self):
            await self.connect()
            return self

        async def __aexit__(self, *args):
            await self.disconnect()

        async def get_server_info(self):
            calls.append(("info", None))
            return info

        async def query(self, *args, **kwargs):
            _forbidden()

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", SimpleNamespace(
        ClaudeAgentOptions=Options, ClaudeSDKClient=Client,
    ))
    monkeypatch.setattr(claude_svc, "claude_path", lambda: "/fixture/bin/claude")
    monkeypatch.setattr(claude_svc, "ClaudeSDKClient", Client, raising=False)
    monkeypatch.setattr(claude_svc, "ClaudeAgentOptions", Options, raising=False)
    # Também cobre uma importação do SDK feita no escopo do módulo.
    for name, value in (("ClaudeSDKClient", Client), ("ClaudeAgentOptions", Options)):
        if hasattr(claude_models, name):
            monkeypatch.setattr(claude_models, name, value)

    models = asyncio.run(claude_models._fetch_cli())
    assert {item["id"] for item in models} == {
        "claude-sonnet-4-10", "claude-sonnet-4-5", "claude-haiku-4-5",
    }
    assert {item["id"]: item["name"] for item in models}["claude-haiku-4-5"] == "Haiku"
    assert all(set(item) == {"id", "name"} for item in models)
    options = next(value for name, value in calls if name == "options")
    assert options.cwd == str(env)
    assert options.setting_sources == ["user", "project", "local"]
    assert options.cli_path == "/fixture/bin/claude"
    assert options.tools == []
    assert [name for name, _ in calls].count("connect") == 1
    assert [name for name, _ in calls].count("info") == 1
    assert [name for name, _ in calls].count("disconnect") == 1


def test_fetch_converts_handshake_failure_to_unavailable(monkeypatch):
    async def unavailable():
        raise RuntimeError("CLI fictício indisponível")
    monkeypatch.setattr(claude_models, "_fetch_cli", unavailable)
    assert claude_models._fetch() is None


def test_fresh_cli_cache_survives_restart_without_query(isolated_models, monkeypatch):
    _cache_on_disk(isolated_models[0], CATALOG)
    monkeypatch.setattr(claude_models, "_fetch", _forbidden)
    assert claude_models.list_models() == CATALOG
    assert claude_models.list_models() == CATALOG


@pytest.mark.parametrize("source", [None, "anthropic-api-v1"])
def test_legacy_api_cache_is_replaced_even_when_fresh(isolated_models, monkeypatch, source):
    _cache_on_disk(isolated_models[0], [{"id": "legacy-unavailable", "name": "Legado"}], source)
    calls = []
    def fetch():
        calls.append(True)
        return CATALOG
    monkeypatch.setattr(claude_models, "_fetch", fetch)
    assert claude_models.list_models() == CATALOG
    assert calls == [True]
    saved = json.loads(claude_models._CACHE_FILE.read_text(encoding="utf-8"))
    assert saved["source"] == SOURCE
    assert saved["models"] == CATALOG


def test_failed_discovery_uses_cli_default_and_backoff(isolated_models, monkeypatch):
    calls = []
    def fetch():
        calls.append(True)
        return None
    monkeypatch.setattr(claude_models, "_fetch", fetch)
    assert claude_models.list_models() == [{"id": "default", "name": "Padrão do Claude Code"}]
    assert claude_models.list_models() == [{"id": "default", "name": "Padrão do Claude Code"}]
    assert len(calls) == 1
    isolated_models[0] += claude_models._RETRY_TTL + 1
    claude_models.list_models()
    assert len(calls) == 2


def test_force_refresh_bypasses_failure_backoff(monkeypatch):
    responses = iter([None, CATALOG])
    monkeypatch.setattr(claude_models, "_fetch", lambda: next(responses))
    assert claude_models.list_models()[0]["id"] == "default"
    assert claude_models.list_models(force=True) == CATALOG


def test_failed_refresh_preserves_good_cache_and_limits_retries(isolated_models, monkeypatch):
    stale_at = isolated_models[0] - claude_models._CACHE_TTL - 1
    _cache_on_disk(stale_at, CATALOG)
    calls = []
    def fetch():
        calls.append(True)
        return None
    monkeypatch.setattr(claude_models, "_fetch", fetch)
    assert claude_models.list_models() == CATALOG
    assert claude_models.list_models() == CATALOG
    assert len(calls) == 1
    saved = json.loads(claude_models._CACHE_FILE.read_text(encoding="utf-8"))
    assert saved["at"] == stale_at
    assert saved["models"] == CATALOG


def test_successful_catalog_is_refreshed_after_week(isolated_models, monkeypatch):
    calls = []
    def fetch():
        calls.append(True)
        return CATALOG
    monkeypatch.setattr(claude_models, "_fetch", fetch)
    assert claude_models.list_models() == CATALOG
    assert claude_models.list_models() == CATALOG
    assert len(calls) == 1
    isolated_models[0] += claude_models._CACHE_TTL + 1
    assert claude_models.list_models() == CATALOG
    assert len(calls) == 2


@pytest.mark.parametrize(("ids", "expected"), [
    (["claude-sonnet-4-5", "claude-sonnet-4-9", "claude-sonnet-4-10"], "claude-sonnet-4-10"),
    (["claude-sonnet-4-10", "claude-sonnet-5-1", "default"], "claude-sonnet-5-1"),
    (["claude-opus-4-8", "default"], "default"),
    (["claude-haiku-4-5", "claude-opus-4-8"], "claude-haiku-4-5"),
    ([], "default"),
])
def test_default_model_prefers_latest_sonnet_numerically(ids, expected):
    assert claude_models.default_model([{"id": mid, "name": mid} for mid in ids]) == expected
