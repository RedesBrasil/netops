#!/usr/bin/env python3
"""Lista de modelos disponíveis p/ a aba Claude Code — lida DINAMICAMENTE da API
(GET /v1/models) usando a credencial OAuth do MESMO store do agente (ver claude_auth).

Por que não hard-code: os nomes de modelo mudam por conta/época, e os ALIASES ("sonnet",
"opus") podem estar remapeados p/ variantes quebradas nesta conta (ex.: "sonnet" ->
"sonnet-failover[1m]", que o backend rejeita). Ler a lista real evita esse chute.

⚠ CUSTO/RATE LIMIT: chamar a API em excesso consome a cota da conta e pode gerar bloqueio
temporário (HTTP 429) que trava TODO o Claude Code. Por isso a releitura automática é no
MÁXIMO 1x/semana (cache persistido em disco); só o botão "Verificar modelos" força na hora.

⚠ SEGREDO: o access token OAuth é lido só p/ montar o header Authorization e NUNCA é
logado, impresso nem devolvido. Só saem daqui `id` + `name` (nome de exibição) dos modelos.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

import deps

_MODELS_URL = "https://api.anthropic.com/v1/models?limit=100"
_ANTHROPIC_BETA = "oauth-2025-04-20"       # header que a auth OAuth do Claude Code usa
_CACHE_TTL = 7 * 24 * 3600                  # 1 SEMANA — releitura automática no máximo 1x/semana
_CACHE_FILE = deps.RUNS_DIR / "claude" / "models-cache.json"
_cache: dict = {"at": 0.0, "models": None}  # espelho em memória do cache de disco

# Fallback mínimo — só entra em cena se a API falhar E nunca tivermos obtido a lista.
# Não é a fonte da verdade; é rede de segurança p/ o seletor não ficar vazio. São ids
# VERIFICADOS que funcionam nesta instalação.
_FALLBACK = [
    {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5"},
    {"id": "claude-opus-4-8", "name": "Claude Opus 4.8"},
    {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5"},
    {"id": "claude-fable-5", "name": "Claude Fable 5"},
]


def _token() -> str | None:
    """Access token OAuth do store do servidor ($HOME/.claude/.credentials.json). NUNCA logar."""
    path = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    found = {"tok": None}

    def walk(d):
        if found["tok"]:
            return
        if isinstance(d, dict):
            for k, v in d.items():
                if k.lower() in ("accesstoken", "access_token") and isinstance(v, str) and v:
                    found["tok"] = v
                    return
                walk(v)
        elif isinstance(d, list):
            for x in d:
                walk(x)

    walk(data)
    return found["tok"]


def _load_disk() -> dict | None:
    """Cache persistido {at, models} — sobrevive a restart (senão toda subida iria à API)."""
    try:
        with _CACHE_FILE.open(encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("models"), list) and d["models"]:
            return {"at": float(d.get("at") or 0.0), "models": d["models"]}
    except (OSError, ValueError):
        pass
    return None


def _save_disk(models: list[dict], at: float) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_FILE.open("w", encoding="utf-8") as fh:
            json.dump({"at": at, "models": models}, fh)
    except OSError:
        pass


def _fetch() -> list[dict] | None:
    tok = _token()
    if not tok:
        return None
    req = urllib.request.Request(_MODELS_URL)
    req.add_header("authorization", "Bearer " + tok)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("anthropic-beta", _ANTHROPIC_BETA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - URL https fixa
            data = json.load(r)
    except Exception:
        return None
    out = []
    for m in data.get("data", []):
        mid = m.get("id")
        if mid:
            out.append({"id": mid, "name": m.get("display_name") or mid})
    return out or None


def list_models(force: bool = False) -> list[dict]:
    """Modelos disponíveis (id + nome).

    Sem `force`: só vai à API se o cache (memória ou disco) tiver > _CACHE_TTL (1 semana).
    Com `force` (botão "Verificar modelos"): relê agora e regrava o cache.
    Qualquer falha cai no último cache bom; se nunca houve, no fallback estático.
    """
    now = time.time()

    # 1) memória fresca
    if not force and _cache["models"] is not None and (now - _cache["at"]) < _CACHE_TTL:
        return _cache["models"]

    # 2) disco fresco (hidrata a memória e evita ir à API a cada restart)
    if not force:
        disk = _load_disk()
        if disk and (now - disk["at"]) < _CACHE_TTL:
            _cache.update(disk)
            return disk["models"]

    # 3) precisa buscar na API
    models = _fetch()
    if models is None:
        # não sobrescreve um cache bom; usa o que houver, senão o fallback
        if _cache["models"] is not None:
            return _cache["models"]
        disk = _load_disk()
        return disk["models"] if disk else list(_FALLBACK)

    _cache["models"] = models
    _cache["at"] = now
    _save_disk(models, now)
    return models


def default_model(models: list[dict] | None = None) -> str:
    """Modelo padrão econômico. O usuário pediu Sonnet; escolhemos entre os DISPONÍVEIS,
    evitando o "sonnet" cru (remapeado p/ variante quebrada nesta conta) — prioriza o
    Sonnet 4.5 (verificado). Cai em qualquer sonnet, depois opus 4.8, depois o 1º da lista."""
    models = models if models is not None else list_models()
    ids = [m["id"] for m in models]

    def first(pred):
        return next((i for i in ids if pred(i)), None)

    return (
        first(lambda i: i.startswith("claude-sonnet-4-5"))
        or first(lambda i: "sonnet-4" in i)
        or first(lambda i: "sonnet" in i)
        or first(lambda i: i.startswith("claude-opus-4-8"))
        or (ids[0] if ids else "claude-sonnet-4-5")
    )
