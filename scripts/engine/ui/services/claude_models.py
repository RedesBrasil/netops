#!/usr/bin/env python3
"""Catálogo do mesmo Claude Code usado pela aba, sem prompt nem leitura de segredos.

O handshake do SDK conhece os modelos do provider/gateway configurado. Consultar a
API pública da Anthropic ignora esse contexto e pode oferecer modelos sem acesso.
O cache semanal guarda só IDs/nomes; refresh manual força nova descoberta local.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

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

_SECRET_KEYS = ("AUTH_TOKEN", "API_KEY")


def _settings_files() -> list[Path]:
    """Mesma ordem de precedência do CLI (setting_sources=user, project, local)."""
    home = Path(os.path.expanduser("~")) / ".claude"
    project = deps.NETOPS_ROOT / ".claude"
    return [home / "settings.json", project / "settings.json", project / "settings.local.json"]


def _read_settings() -> list[dict]:
    out = []
    for path in _settings_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _account_keys(env) -> set:
    return {str(k) for k, v in (env or {}).items() if v not in (None, "")
            and (str(k).startswith("ANTHROPIC_") or k == "CLAUDE_CODE_OAUTH_TOKEN")} if isinstance(env, dict) else set()


def account_only_in_netops() -> bool:
    """True quando a conta/proxy do agente (`ANTHROPIC_*`, `CLAUDE_CODE_OAUTH_TOKEN`) está declarada SÓ nos
    settings do NetOps (`.claude/settings*.json`), e não no nível do usuário (`~/.claude/settings.json`)
    nem no ambiente do servidor.

    Projetos rodam em outra pasta e o CLI só lê os settings do usuário + os da pasta: nesse caso a sessão do
    projeto não acharia a conta. O console NÃO copia o token para o projeto (ele ficaria no `env` de um
    agente com shell numa pasta qualquer); avisa para mover o bloco `env` p/ o nível do usuário, como no
    VS Code. Só olha NOMES de chave, nunca valores.
    """
    files = _settings_files()
    def keys(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return _account_keys(data.get("env")) if isinstance(data, dict) else set()
    user = keys(files[0]) | _account_keys(dict(os.environ))
    netops = keys(files[1]) | keys(files[2])
    return bool(netops) and not user


def _picker() -> list[dict]:
    """`modelPicker` dos settings (gateway/proxy de terceiros): é o que o `/model` do CLI mostra.

    O handshake (`get_server_info`) NÃO inclui essas opções, então sem isto a aba só enxergava
    os apelidos embutidos (default/opus/sonnet/haiku) e nunca os modelos do proxy.
    Devolve [] se não houver; `replaceBuiltInOptions` vai na chave `_replace` do primeiro item.
    """
    options, replace = [], False
    for data in _read_settings():
        picker = data.get("modelPicker")
        if not isinstance(picker, dict) or not isinstance(picker.get("options"), list):
            continue
        options, replace = [], bool(picker.get("replaceBuiltInOptions"))   # o mais específico vence
        for opt in picker["options"]:
            if isinstance(opt, dict) and isinstance(opt.get("model"), str) and opt["model"]:
                options.append({"id": opt["model"], "name": opt.get("label") or opt["model"]})
    if options:
        options[0] = {**options[0], "_replace": replace}
    return options


def _fingerprint() -> str:
    """Impressão digital NÃO secreta da config de provedor/modelos.

    Se `ANTHROPIC_BASE_URL`, os `ANTHROPIC_*_MODEL` ou o `modelPicker` mudam, o catálogo em cache
    deixa de valer: antes ele durava 7 dias e seguia oferecendo ids que o novo provedor rejeita.
    """
    env = {k: v for k, v in os.environ.items() if k.startswith("ANTHROPIC_")}
    for data in _read_settings():
        if isinstance(data.get("env"), dict):
            env.update({k: str(v) for k, v in data["env"].items() if str(k).startswith("ANTHROPIC_")})
    env = {k: v for k, v in env.items() if not any(x in k for x in _SECRET_KEYS)}
    blob = json.dumps({"env": env, "picker": _picker()}, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _load_disk() -> dict | None:
    try:
        with _CACHE_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if (isinstance(data, dict) and data.get("source") == _CACHE_SOURCE
                and data.get("fp") == _fingerprint()
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
            json.dump({"source": _CACHE_SOURCE, "at": at, "fp": _fingerprint(), "models": models}, fh)
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
    picker = _picker()
    if picker:
        replace = picker[0].pop("_replace", False)
        extra = [m for m in picker if replace or m["id"] not in seen]
        out = extra if replace else out + extra
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
