#!/usr/bin/env python3
"""Monitor de lentidão do atendimento (WhatsBot-pro).

Mede sondas HTTP (incl. login e endpoints autenticados), mantém estado de incidente,
avisa no Telegram e, ao abrir incidente, dispara o agente investigador (investigate.py).

Uso: monitor.py [--cycles N] [--interval S] [--once] [--no-telegram] [--no-investigate]
Configuração: network/atendimento-monitor.yaml e network/telegram.yaml (ambos git-ignorados).
Só biblioteca padrão + PyYAML (já no .venv).
"""
from __future__ import annotations

import argparse, fcntl, json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "engine"))  # lib.i18n (stdlib only at import)
from lib import i18n  # noqa: E402  (no request context: messages follow NETOPS_LANG / instance language)
DATA = ROOT / "runs" / "atendimento-monitor"
STATE = DATA / "state.json"


def _yaml(p: Path) -> dict:
    import yaml
    return yaml.safe_load(p.read_text()) or {}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def http(url, method="GET", headers=None, body=None, timeout=20):
    """Retorna (status, segundos, bytes_lidos, corpo|None, erro|None). Mede até o último byte."""
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, time.perf_counter() - t0, len(raw), raw, None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, time.perf_counter() - t0, len(raw), raw, None
    except Exception as e:  # timeout, DNS, TLS, reset
        return 0, time.perf_counter() - t0, 0, None, f"{type(e).__name__}: {e}"[:200]


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"cycle": 0, "token": None, "bad": 0, "good": 0, "incident": None, "last_investigation": 0}


def save_state(s: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(STATE)


def login(cfg) -> tuple[str | None, tuple]:
    r = http(cfg["url"] + "/api/auth/login", "POST", body=cfg["login"], timeout=cfg["timeout_s"])
    tok = None
    if r[0] == 200 and r[3]:
        try:
            tok = json.loads(r[3])["data"]["token"]
        except Exception:
            pass
    return tok, r


def probe_cycle(cfg, st) -> dict:
    results = []
    st["cycle"] += 1
    do_login = st.get("token") is None or st["cycle"] % cfg["relogin_every_cycles"] == 0
    login_res = None
    if do_login:
        st["token"], login_res = login(cfg)
    for p in cfg["probes"]:
        if p.get("special") == "login":
            r = login_res
            if r is None:       # não logou neste ciclo: não conta
                continue
        else:
            hdr = {"Authorization": f"Bearer {st['token']}"} if p.get("auth", True) and st["token"] else {}
            r = http(cfg["url"] + p["path"], headers=hdr, timeout=cfg["timeout_s"])
            if r[0] == 401 and p.get("auth", True):       # token expirou: relogin e repete
                st["token"], _ = login(cfg)
                r = http(cfg["url"] + p["path"], headers={"Authorization": f"Bearer {st['token']}"}, timeout=cfg["timeout_s"])
        status, secs, size, _, err = r
        state = "fail" if (err or status == 0 or status >= 500 or (status >= 400 and p.get("auth", True) is False)
                           or (status in (401, 403, 404) and p.get("special") == "login")) \
            else ("slow" if secs > p["slow_s"] else "ok")
        if status in (401, 403) and p.get("auth", True) and not err:
            state = "fail"
        results.append({"probe": p["name"], "status": status, "s": round(secs, 3), "bytes": size,
                        "state": state, **({"error": err} if err else {})})
    return {"ts": now(), "cycle": st["cycle"], "results": results}


def classify(cfg, rec) -> str:
    fails = [r for r in rec["results"] if r["state"] == "fail"]
    slows = [r for r in rec["results"] if r["state"] == "slow"]
    if fails or len(slows) >= cfg["alert"]["slow_probes_min"]:
        return "bad"
    return "ok"


def summarize(rec) -> str:
    return ", ".join(f"{r['probe']}={r['s']:.2f}s" + ("" if r["state"] == "ok" else f"[{r['state'].upper()} {r['status'] or r.get('error','')}]")
                     for r in rec["results"])


def telegram(text: str) -> bool:
    try:
        tg = _yaml(ROOT / "network" / "telegram.yaml")
        body = urllib.parse.urlencode({"chat_id": tg["chat_id"], "text": text[:4000]}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage", data=body)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        print(i18n.t("cli_diagnostics.monitor_telegram_failed", error=type(e).__name__), file=sys.stderr)
        return False


def launch_investigation(cfg, st, rec) -> None:
    inv = cfg.get("investigate", {})
    if not inv.get("enabled"):
        return
    if time.time() - st.get("last_investigation", 0) < inv.get("cooldown_minutes", 30) * 60:
        return
    st["last_investigation"] = time.time()
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "pending.json").write_text(json.dumps({"incident": st["incident"], "last_cycle": rec, "created": now()}, indent=1))
    # a tarefa híbrida "Investigador — atendimento" (scheduler) consome pending.json e acorda o agente de IA


def handle(cfg, st, rec, verdict, notify, investigate) -> None:
    a = cfg["alert"]
    inc = st.get("incident")
    # Lentidão INTERMITENTE (engasgos curtos, ex.: event loop travando ~4 s/min): olha a taxa nos últimos N ciclos
    hist = (st.get("hist", []) + [any(r["state"] != "ok" and r["probe"] != "connected" for r in rec["results"])])[-a.get("window_cycles", 20):]
    st["hist"] = hist
    chronic = sum(hist) >= a.get("intermittent_min", 4)
    if verdict == "ok" and chronic and inc is None:
        verdict = "bad"; st["bad"] = max(st["bad"], a["bad_cycles_to_open"] - 1)   # abre já: padrão intermitente
        rec["intermittent"] = True
    elif verdict == "ok" and inc is not None and sum(hist) >= 2:
        verdict = "bad"                                                           # ainda instável: não fecha
    if verdict == "bad":
        st["bad"] += 1; st["good"] = 0
        if inc is None and st["bad"] >= a["bad_cycles_to_open"]:
            st["incident"] = {"start": now(), "start_ts": time.time(), "last_reminder": time.time(), "worst": {}}
            if notify:
                telegram((i18n.t("cli_diagnostics.monitor_alert_intermittent") if rec.get("intermittent") else i18n.t("cli_diagnostics.monitor_alert_slow")) + f"\n{cfg['url']}\n{summarize(rec)}\n"
                         + (i18n.t("cli_diagnostics.monitor_investigator_started") if investigate and cfg.get("investigate", {}).get("enabled") else ""))
            if investigate:
                launch_investigation(cfg, st, rec)
        elif inc is not None:
            if notify and time.time() - inc["last_reminder"] > a["reminder_minutes"] * 60:
                inc["last_reminder"] = time.time()
                telegram(i18n.t("cli_diagnostics.monitor_still_failing", since=inc["start"][11:16]) + f"\n{summarize(rec)}")
    else:
        st["good"] += 1; st["bad"] = 0
        if inc is not None and st["good"] >= a["good_cycles_to_close"]:
            mins = (time.time() - inc["start_ts"]) / 60
            st["incident"] = None
            if notify:
                telegram(i18n.t("cli_diagnostics.monitor_recovered", minutes=f"{mins:.0f}", start=inc["start"][11:16]) + f"\n{summarize(rec)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--once", action="store_true", help=i18n.t("cli_diagnostics.monitor_help_once"))
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--no-investigate", action="store_true")
    a = ap.parse_args()
    cfg = _yaml(ROOT / "network" / "atendimento-monitor.yaml")
    DATA.mkdir(parents=True, exist_ok=True)
    lock = open(DATA / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(i18n.t("cli_diagnostics.monitor_already_running")); return 0
    st = load_state()
    n = 1 if a.once else a.cycles
    for i in range(n):
        t0 = time.time()
        rec = probe_cycle(cfg, st)
        verdict = classify(cfg, rec)
        rec["verdict"] = verdict
        with open(DATA / f"metrics-{datetime.now():%Y%m%d}.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"{rec['ts']} {verdict.upper()} {summarize(rec)}")
        if not a.once:
            handle(cfg, st, rec, verdict, not a.no_telegram, not a.no_investigate)
        save_state(st)
        if i < n - 1:
            time.sleep(max(0, a.interval - (time.time() - t0)))
    # retenção: 14 dias de métricas
    for f in DATA.glob("metrics-*.jsonl"):
        if time.time() - f.stat().st_mtime > 14 * 86400:
            f.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
