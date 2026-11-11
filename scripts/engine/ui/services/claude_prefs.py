#!/usr/bin/env python3
"""Preferências da aba Claude Code: padrões p/ conversas novas + último modelo/modo POR conversa.

Arquivo único `runs/claude/prefs.json` (só IDs de modelo/modo, nada sensível):
  {"default_model": "", "default_mode": "default",
   "sessions": {"<sid>": {"model": "...", "mode": "..."}}}
Vazio em default_model = padrão automático do catálogo (Sonnet mais recente).
"""
from __future__ import annotations

import json
import threading

import deps

_FILE = deps.RUNS_DIR / "claude" / "prefs.json"
_LOCK = threading.Lock()
_MODES = ("plan", "default", "acceptEdits", "dontAsk", "bypassPermissions")
_MAX_SESSIONS = 2000


def _load() -> dict:
    try:
        with _FILE.open(encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            d.setdefault("sessions", {})
            return d
    except (OSError, ValueError):
        pass
    return {"default_model": "", "default_mode": "default", "sessions": {}}


def _save(d: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    tmp.replace(_FILE)


def defaults() -> dict:
    with _LOCK:
        d = _load()
    mode = d.get("default_mode")
    return {"default_model": d.get("default_model") or "",
            "default_mode": mode if mode in _MODES else "default"}


def set_defaults(model: str | None, mode: str | None) -> dict:
    with _LOCK:
        d = _load()
        if model is not None:
            d["default_model"] = str(model)[:200]
        if mode is not None and mode in _MODES:
            d["default_mode"] = mode
        _save(d)
    return defaults()


def get_session(sid: str | None) -> dict:
    if not sid:
        return {}
    with _LOCK:
        return dict(_load()["sessions"].get(sid) or {})


def set_session(sid: str | None, *, model: str | None = None, mode: str | None = None) -> None:
    if not sid:
        return
    with _LOCK:
        d = _load()
        s = d["sessions"].setdefault(sid, {})
        if model:
            s["model"] = str(model)[:200]
        if mode in _MODES:
            s["mode"] = mode
        if len(d["sessions"]) > _MAX_SESSIONS:   # poda as mais antigas (ordem de inserção)
            for k in list(d["sessions"])[: len(d["sessions"]) - _MAX_SESSIONS]:
                d["sessions"].pop(k, None)
        _save(d)
