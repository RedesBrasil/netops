#!/usr/bin/env python3
"""CLI das tarefas agendadas do NetOps — é por aqui que o agente de IA (aba Claude Code) agenda.

  cli.py list                                   tarefas + próxima/última execução
  cli.py show <id|nome>
  cli.py add --name N --kind script|agent|hybrid (--cron "0 9 * * *" | --every 30 | --at 2026-11-20T09:00)
             [--script "cmd"] [--prompt "texto"] [--notify auto|always|failure|never]
             [--permissions restricted|full] [--model M] [--timeout 15] [--description D] [--disabled]
  cli.py edit <id> [mesmos campos do add]
  cli.py rm <id> | enable <id> | disable <id> | run <id> (dispara agora, em segundo plano)
  cli.py runs [<id>] [--limit 20]  |  cli.py log <id> <run_id>
  cli.py install-cron | cli.py tick (chamado pelo cron) | cli.py preview --cron "..."

Saída em JSON (fácil de ler por IA e por scripts). Ver SKILL.md ao lado.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto

from scheduler import runner, store  # noqa: E402


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _schedule(a) -> dict | None:
    given = [x for x in (a.cron, a.every, a.at) if x not in (None, "")]
    if len(given) > 1:
        raise store.TaskError([{"loc": "schedule", "msg": "use só um de --cron, --every, --at"}])
    if a.cron:
        return {"type": "cron", "expr": a.cron}
    if a.every:
        return {"type": "interval", "minutes": int(a.every)}
    if a.at:
        return {"type": "once", "at": a.at}
    return None


def _fields(a, creating: bool) -> dict:
    f: dict = {}
    for k in ("name", "kind", "script", "prompt", "notify", "description"):
        v = getattr(a, k, None)
        if v is not None:
            f[k] = v
    if a.timeout is not None:
        f["timeout_min"] = a.timeout
    sch = _schedule(a)
    if sch:
        f["schedule"] = sch
    agent = {k: v for k, v in (("permissions", a.permissions), ("model", a.model),
                               ("github_as", getattr(a, "github_as", None))) if v is not None}
    if agent:
        f["agent"] = agent
    if a.disabled:
        f["enabled"] = False
    elif creating:
        f["enabled"] = True
    return f


def _add_fields(p) -> None:
    p.add_argument("--name")
    p.add_argument("--kind", choices=store.KINDS)
    p.add_argument("--cron", help='expressão de 5 campos, ex.: "0 9 * * 1-5" (fuso da tarefa)')
    p.add_argument("--every", type=int, help="a cada N minutos")
    p.add_argument("--at", help="uma vez: AAAA-MM-DDTHH:MM (fuso da tarefa)")
    p.add_argument("--script", help="comando/script (roda com bash, cwd = raiz do NetOps)")
    p.add_argument("--prompt", help="o que o agente deve fazer")
    p.add_argument("--notify", choices=store.NOTIFY)
    p.add_argument("--permissions", choices=store.PERMISSIONS)
    p.add_argument("--model")
    p.add_argument("--github-as", dest="github_as",
                   help="ID do usuário do console cuja conta do GitHub o agente usa (padrão: gh do servidor)")
    p.add_argument("--timeout", type=int, help="minutos (padrão 15)")
    p.add_argument("--description")
    p.add_argument("--disabled", action="store_true")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tarefas agendadas do NetOps")
    ap.add_argument("--data-root", help="raiz de dados (padrão: a instalação)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("show"); p.add_argument("ref")
    p = sub.add_parser("add"); _add_fields(p); p.add_argument("--id")
    p.add_argument("--created-by", default="chat")
    p = sub.add_parser("edit"); p.add_argument("ref"); _add_fields(p)
    p.add_argument("--enabled", action="store_true")
    for c in ("rm", "enable", "disable"):
        p = sub.add_parser(c); p.add_argument("ref")
    p = sub.add_parser("run"); p.add_argument("ref")
    p.add_argument("--run-id", help=argparse.SUPPRESS); p.add_argument("--trigger", default="manual",
                                                                       help=argparse.SUPPRESS)
    p = sub.add_parser("runs"); p.add_argument("ref", nargs="?"); p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("log"); p.add_argument("ref"); p.add_argument("run_id")
    sub.add_parser("install-cron")
    sub.add_parser("tick")
    p = sub.add_parser("preview"); p.add_argument("--cron"); p.add_argument("--every", type=int)
    p.add_argument("--at")
    a = ap.parse_args(argv)
    root = a.data_root

    try:
        if a.cmd == "tick":
            due = runner.tick(root)
            if due:
                print(f"{runner._now(store.load(root)['config'].get('timezone')).isoformat(timespec='seconds')} "
                      f"disparadas: {', '.join(due)}")
            return 0
        if a.cmd == "list":
            ov = runner.overview(root)
            tz = ov["timezone"]
            _out({"timezone": tz, "cron": ov["cron"], "unread": ov["unread"], "tasks": [{
                "id": t["id"], "name": t["name"], "kind": t["kind"], "kind_label": t["kind_label"],
                "enabled": t.get("enabled", True), "schedule": t["schedule_label"],
                "next_run": runner._iso(t["state"]["next_run_at"], tz),
                "last_run": runner._iso(t["state"]["last_run_at"], tz),
                "last_status": t["state"]["last_status"]} for t in ov["config"]["tasks"]]})
            return 0
        if a.cmd == "show":
            t = store.resolve(a.ref, root)
            tz = store.load(root)["config"]["timezone"]
            _out({**t, "next_runs": store.preview(t, tz)})
            return 0
        if a.cmd == "add":
            f = _fields(a, True)
            if a.id:
                f["id"] = a.id
            if "schedule" not in f:
                raise store.TaskError([{"loc": "schedule", "msg": "informe --cron, --every ou --at"}])
            r = store.create_task(f, root=root, created_by=a.created_by)
            tz = store.load(root)["config"]["timezone"]
            _out({"ok": True, "task": r["task"], "next_runs": store.preview(r["task"], tz),
                  "cron": store.cron_status(root)})
            return 0
        if a.cmd == "edit":
            t = store.resolve(a.ref, root)
            f = _fields(a, False)
            if a.enabled:
                f["enabled"] = True
            r = store.update_task(t["id"], f, root=root)
            _out({"ok": True, "task": r["task"]})
            return 0
        if a.cmd in ("enable", "disable"):
            t = store.resolve(a.ref, root)
            r = store.update_task(t["id"], {"enabled": a.cmd == "enable"}, root=root)
            _out({"ok": True, "task": r["task"]})
            return 0
        if a.cmd == "rm":
            t = store.resolve(a.ref, root)
            store.delete_task(t["id"], root=root)
            _out({"ok": True, "removed": t["id"]})
            return 0
        if a.cmd == "run":
            t = store.resolve(a.ref, root)
            if a.run_id:   # modo interno: o despachante já criou o run_id e o log
                rec = runner.run(t["id"], a.run_id, a.trigger, root)
                print(f"[{rec['status']}] {rec.get('error') or ''}".strip())
                return 0
            if os.environ.get("NETOPS_SCHEDULED_RUN") == "1":
                raise store.TaskError([{"loc": "run", "msg": "uma tarefa agendada não dispara outra"}])
            _out({"ok": True, "run_id": runner.run_now(t["id"], root)})
            return 0
        if a.cmd == "runs":
            tid = store.resolve(a.ref, root)["id"] if a.ref else None
            _out(runner.list_runs(root, tid, a.limit))
            return 0
        if a.cmd == "log":
            t = store.resolve(a.ref, root)
            _out(runner.read_run(t["id"], a.run_id, root))
            return 0
        if a.cmd == "install-cron":
            _out(store.install_cron(root))
            return 0
        if a.cmd == "preview":
            sch = _schedule(a)
            tz = store.load(root)["config"]["timezone"]
            _out({"timezone": tz, "next_runs": store.preview({"schedule": sch}, tz, 8)})
            return 0
    except store.TaskError as e:
        _out({"ok": False, "errors": e.errors})
        return 2
    except KeyError as e:
        _out({"ok": False, "errors": [{"loc": "id", "msg": str(e).strip("'\"")}]})
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
