#!/usr/bin/env python3
"""Catálogo do mesmo Claude Code usado pela aba, sem prompt nem leitura de segredos.

O handshake do SDK conhece os modelos do provider/gateway configurado. Consultar a
API pública da Anthropic ignora esse contexto e pode oferecer modelos sem acesso.
O cache semanal guarda só IDs/nomes; refresh manual força nova descoberta local.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time

import deps

_CACHE_SOURCE = "claude-cli-v1"
_CACHE_TTL = 7 * 24 * 3600
_RETRY_TTL = 60
_CACHE_FILE = deps.RUNS_DIR / "claude" / "models-cache.json"
_cache: dict = {"at": 0.0, "models": None}
_retry_after = 0.0
_cache_lock = threading.Lock()

# O próprio CLI resolve o padrão da conta; não inventa versões nem presume acesso.
_FALLBACK = [{"id": "default", "name": "Padrão do Claude Code"}]


def _load_disk() -> dict | None:
    try:
        with _CACHE_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if (isinstance(data, dict) and data.get("source") == _CACHE_SOURCE
                and isinstance(data.get("models"), list) and data["models"]):
            return {"at": float(data.get("at") or 0.0), "models": data["models"]}
    except (OSError, ValueError, TypeError):
        pass
    return None


def _save_disk(models: list[dict], at: float) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = _CACHE_FILE.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as fh:
            json.dump({"source": _CACHE_SOURCE, "at": at, "models": models}, fh)
        temporary.replace(_CACHE_FILE)
    except OSError:
        pass


async def _fetch_cli() -> list[dict] | None:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    from services import claude_svc

    cli = claude_svc.claude_path()
    if not cli:
        return None
    options = ClaudeAgentOptions(
        cwd=str(deps.NETOPS_ROOT), cli_path=cli,
        setting_sources=["user", "project", "local"],
        env={**os.environ, "IS_SANDBOX": "1"}, tools=[],
    )
    # Apenas initialize: nenhuma query/inferência, ferramenta ou token exposto à UI.
    async with ClaudeSDKClient(options=options) as client:
        info = await client.get_server_info() or {}
    out = []
    seen = set()
    for entry in info.get("models", []):
        if not isinstance(entry, dict):
            continue
        mid = entry.get("value")
        if mid == "default":
            mid = entry.get("resolvedModel") or mid
        if isinstance(mid, str) and mid and mid not in seen:
            seen.add(mid)
            out.append({"id": mid, "name": entry.get("displayName") or mid})
    return out or None


def _fetch() -> list[dict] | None:
    try:
        return asyncio.run(asyncio.wait_for(_fetch_cli(), timeout=20))
    except Exception:
        return None


def list_models(force: bool = False) -> list[dict]:
    # HTTP e abertura de sessão podem descobrir ao mesmo tempo; um único handshake basta.
    with _cache_lock:
        return _list_models(force)


def _list_models(force: bool = False) -> list[dict]:
    """Último catálogo bom; falhas têm backoff e nunca apagam a lista anterior."""
    global _retry_after
    now = time.time()
    if not force and _cache["models"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["models"]
    disk = _load_disk()
    if not force and disk and now - disk["at"] < _CACHE_TTL:
        _cache.update(disk)
        return disk["models"]
    previous = _cache["models"] or (disk["models"] if disk else None)
    if not force and now < _retry_after:
        return previous or list(_FALLBACK)
    models = _fetch()
    if not models:
        _retry_after = now + _RETRY_TTL
        return previous or list(_FALLBACK)
    _retry_after = 0.0
    _cache.update(at=now, models=models)
    _save_disk(models, now)
    return models


def default_model(models: list[dict] | None = None) -> str:
    """Sonnet mais recente anunciado pelo CLI, depois o padrão do provider."""
    models = models if models is not None else list_models()
    ids = [m["id"] for m in models]
    sonnets = [mid for mid in ids if "sonnet" in mid.lower()]
    if sonnets:
        return max(sonnets, key=lambda mid: tuple(int(n) for n in re.findall(r"\d+", mid)))
    if "default" in ids:
        return "default"
    return ids[0] if ids else "default"
