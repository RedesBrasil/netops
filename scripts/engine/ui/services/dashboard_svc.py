#!/usr/bin/env python3
"""Painel: consumo do host (CPU/RAM/disco via /proc) e consumo de IA (transcripts do Claude Code).

Só leitura. O uso de IA vem dos `.jsonl` em ~/.claude/projects (cada resposta traz `usage`);
valores em USD são ESTIMATIVA (tabela de preços abaixo, calibrada com o `cost-state` do próprio CLI).
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import deps

# ---------- Host ----------
_cpu_prev: tuple[int, int] | None = None
_cpu_lock = threading.Lock()


def _cpu_times() -> tuple[int, int]:
    with open("/proc/stat", encoding="utf-8") as fh:
        p = [int(x) for x in fh.readline().split()[1:]]
    return sum(p), p[3] + (p[4] if len(p) > 4 else 0)   # total, idle+iowait


def _cpu_percent() -> float:
    global _cpu_prev
    with _cpu_lock:
        cur = _cpu_times()
        prev = _cpu_prev
        if prev is None or cur[0] == prev[0]:
            time.sleep(0.25)
            prev, cur = cur, _cpu_times()
        _cpu_prev = cur
    dt, di = cur[0] - prev[0], cur[1] - prev[1]
    return round(100.0 * (dt - di) / dt, 1) if dt > 0 else 0.0


def _meminfo() -> dict:
    m: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as fh:
        for line in fh:
            k, _, v = line.partition(":")
            m[k] = int(v.split()[0]) * 1024
    total = m.get("MemTotal", 0)
    avail = m.get("MemAvailable", m.get("MemFree", 0))
    st, sf = m.get("SwapTotal", 0), m.get("SwapFree", 0)
    return {"total": total, "used": total - avail, "percent": round(100 * (total - avail) / total, 1) if total else 0,
            "swap_total": st, "swap_used": st - sf}


def host_stats() -> dict:
    root = shutil.disk_usage(str(deps.NETOPS_ROOT))
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = []
    try:
        with open("/proc/uptime", encoding="utf-8") as fh:
            uptime = int(float(fh.read().split()[0]))
    except OSError:
        uptime = None
    return {
        "t": int(time.time()), "cpu": {"percent": _cpu_percent(), "cores": os.cpu_count() or 1, "load": load},
        "mem": _meminfo(),
        "disk": {"path": str(deps.NETOPS_ROOT), "total": root.total, "used": root.used,
                 "percent": round(100 * root.used / root.total, 1) if root.total else 0},
        "uptime": uptime,
    }


# ---------- IA ----------
# USD por 1M tokens: (entrada, saída, leitura de cache, escrita cache 5m, escrita cache 1h). Ajustado ao cost-state do CLI.
PRICES = {
    "claude-opus-5-5": (2.8, 14, 0.28, 3.5, 5.6),
    "claude-sonnet-5-5": (1.4, 7, 0.14, 1.75, 2.8),
    "claude-haiku-5-5": (0.1, 0.5, 0.01, 0.125, 0.2),
    "claude-opus-5": (5, 25, 0.5, 6.25, 10),
    "claude-sonnet-5": (2, 10, 0.2, 2.5, 4),
    "claude-opus-4": (15, 75, 1.5, 18.75, 30),
    "claude-sonnet-4": (3, 15, 0.3, 3.75, 6),
    "claude-haiku-4": (1, 5, 0.1, 1.25, 2),
}
FAMILY = {"opus": (5, 25, 0.5, 6.25, 10), "sonnet": (3, 15, 0.3, 3.75, 6), "haiku": (1, 5, 0.1, 1.25, 2)}
WEB_SEARCH_USD = 0.01


def _price(model: str) -> tuple:
    best = None
    for k in PRICES:
        if model.startswith(k) and (best is None or len(k) > len(best)):
            best = k
    if best:
        return PRICES[best]
    for fam, p in FAMILY.items():
        if fam in model:
            return p
    return (0, 0, 0, 0, 0)


def _cost(model: str, i: int, o: int, cr: int, c5: int, c1: int, ws: int) -> float:
    p = _price(model)
    return (i * p[0] + o * p[1] + cr * p[2] + c5 * p[3] + c1 * p[4]) / 1e6 + ws * WEB_SEARCH_USD


def _projects_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")) / "projects"


_cache: dict[str, tuple[float, int, dict]] = {}   # arquivo -> (mtime, size, dados)
_cache_lock = threading.Lock()


def _parse_file(path: Path) -> dict:
    msgs: dict[str, dict] = {}
    title, first, entry = None, None, None
    sid = path.stem
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"ai-title"' in line[:60]:
                try:
                    title = json.loads(line).get("aiTitle") or title
                except ValueError:
                    pass
                continue
            if '"usage"' not in line or '"type":"assistant"' not in line.replace('": "', '":'):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message") or {}
            u = m.get("usage")
            model = m.get("model") or ""
            if d.get("type") != "assistant" or not u or model.startswith("<"):
                continue
            entry = entry or d.get("entrypoint")
            cc = u.get("cache_creation") or {}
            c1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
            c5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
            tot_c = int(u.get("cache_creation_input_tokens") or 0)
            if tot_c > c1 + c5:
                c5 += tot_c - c1 - c5
            rec = {"ts": d.get("timestamp"), "model": model, "i": int(u.get("input_tokens") or 0),
                   "o": int(u.get("output_tokens") or 0), "cr": int(u.get("cache_read_input_tokens") or 0),
                   "c5": c5, "c1": c1, "ws": int((u.get("server_tool_use") or {}).get("web_search_requests") or 0)}
            key = m.get("id") or d.get("uuid") or str(len(msgs))
            old = msgs.get(key)
            if old is None or rec["o"] >= old["o"]:   # a mesma resposta aparece várias vezes (streaming): vale a última
                msgs[key] = rec
    out = []
    for r in msgs.values():
        try:
            ts = datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue
        r["ts"] = ts
        r["cost"] = _cost(r["model"], r["i"], r["o"], r["cr"], r["c5"], r["c1"], r["ws"])
        out.append(r)
    return {"sid": sid, "title": title, "entry": entry, "recs": out}


def _scheduled_sessions() -> dict[str, str]:
    """session_id -> nome da tarefa agendada (execuções de agente do scheduler)."""
    out: dict[str, str] = {}
    base = deps.RUNS_DIR / "schedules"
    if not base.is_dir():
        return out
    for f in base.glob("*/*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("session_id"):
            out[rec["session_id"]] = rec.get("task_name") or rec.get("task_id") or "tarefa agendada"
    return out


def _sessions() -> list[dict]:
    base = _projects_dir()
    seen = set()
    result = []
    if not base.is_dir():
        return result
    with _cache_lock:
        for proj in base.iterdir():
            if not proj.is_dir() or proj.name.startswith("-tmp") or proj.name.startswith("-var-tmp"):
                continue   # sobras de teste
            for f in proj.glob("*.jsonl"):
                try:
                    st = f.stat()
                except OSError:
                    continue
                k = str(f)
                seen.add(k)
                c = _cache.get(k)
                if not c or c[0] != st.st_mtime or c[1] != st.st_size:
                    try:
                        c = (st.st_mtime, st.st_size, _parse_file(f))
                    except OSError:
                        continue
                    _cache[k] = c
                result.append(c[2])
        for k in set(_cache) - seen:
            _cache.pop(k, None)
    return result


def ai_usage(days: int = 30, start: str | None = None, end: str | None = None, model: str | None = None,
             tz_offset_min: int = 0) -> dict:
    """Agrega o consumo no período. start/end = AAAA-MM-DD (dias locais, fuso do navegador)."""
    tz = timezone(timedelta(minutes=-tz_offset_min))   # JS getTimezoneOffset: positivo a oeste de UTC
    now = datetime.now(tz)
    if start:
        d0 = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=tz)
        d1 = (datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=tz) if end else now.replace(hour=0, minute=0, second=0, microsecond=0)) + timedelta(days=1)
    else:
        d1 = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        d0 = d1 - timedelta(days=max(1, min(days, 365)))
    t0, t1 = d0.timestamp(), d1.timestamp()
    sched = _scheduled_sessions()

    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0, "requests": 0}
    by_day: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_task: dict[str, dict] = {}
    models_all: set[str] = set()
    for s in _sessions():
        for r in s["recs"]:
            if not (t0 <= r["ts"] < t1):
                continue
            models_all.add(r["model"])
            if model and r["model"] != model:
                continue
            day = datetime.fromtimestamp(r["ts"], tz).strftime("%Y-%m-%d")
            cw = r["c5"] + r["c1"]
            tokens = r["i"] + r["o"] + r["cr"] + cw
            sid = s["sid"]
            tname = sched.get(sid)
            keys = ((by_day, day), (by_model, r["model"]), (by_task, sid))
            for bucket, key in keys:
                b = bucket.setdefault(key, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "tokens": 0,
                                            "cost": 0.0, "requests": 0})
                b["input"] += r["i"]; b["output"] += r["o"]; b["cache_read"] += r["cr"]; b["cache_write"] += cw
                b["tokens"] += tokens; b["cost"] += r["cost"]; b["requests"] += 1
                if bucket is by_task:
                    b.setdefault("title", tname or s["title"] or sid[:8])
                    b["origin"] = "agendada" if tname else "conversa"
                    b["last"] = max(b.get("last", 0), r["ts"])
                    b.setdefault("models", {})
                    b["models"][r["model"]] = b["models"].get(r["model"], 0) + tokens
            totals["input"] += r["i"]; totals["output"] += r["o"]; totals["cache_read"] += r["cr"]
            totals["cache_write"] += cw; totals["cost"] += r["cost"]; totals["requests"] += 1
    totals["tokens"] = totals["input"] + totals["output"] + totals["cache_read"] + totals["cache_write"]

    # preenche dias sem uso (gráfico contínuo)
    days_out = []
    cur = d0
    while cur < d1:
        k = cur.strftime("%Y-%m-%d")
        days_out.append({"day": k, **by_day.get(k, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                                                      "tokens": 0, "cost": 0.0, "requests": 0})})
        cur += timedelta(days=1)
    tasks = [{"id": k, **v, "models": sorted(v["models"], key=v["models"].get, reverse=True)} for k, v in by_task.items()]
    tasks.sort(key=lambda x: x["tokens"], reverse=True)
    return {"start": d0.strftime("%Y-%m-%d"), "end": (d1 - timedelta(days=1)).strftime("%Y-%m-%d"),
            "totals": totals, "days": days_out,
            "models": sorted(({"model": k, **v} for k, v in by_model.items()), key=lambda x: x["cost"], reverse=True),
            "tasks": tasks[:200], "available_models": sorted(models_all),
            "estimated": True}
