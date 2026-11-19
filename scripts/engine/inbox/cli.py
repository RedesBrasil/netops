#!/usr/bin/env python3
"""CLI da Central de Avisos do NetOps — scripts, tarefas agendadas e agentes publicam por aqui.

  cli.py add --title T [--kind info|alert|approval] [--severity info|warning|critical] [--body MD | --body-file F]
             [--dedupe-key K] [--expires-hours N] [--link "#hosts/2"] [--session-id UUID] [--telegram]
             [--on-approve-command "cmd"] [--on-reject-command "cmd"]
             [--on-approve-agent "prompt"] [--agent-permissions restricted|full] [--timeout 15]
  cli.py list [--view open|pending|unread|alerts|all|archived] [--limit 50]
  cli.py get <id>
  cli.py wait <id> [--timeout-min 60]       espera a decisão (exit 0 aprovado, 3 reprovado, 4 expirado/tempo)
  cli.py read <id>... | archive <id>...
  cli.py summary
  cli.py execute <id>                        (interno: roda a ação do pedido decidido)

Dentro de tarefa agendada, a origem (tarefa/execução) é preenchida sozinha. Saída sempre JSON.
Ver SKILL.md ao lado.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()

from inbox import actions, store  # noqa: E402


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_add(a, root) -> int:
    body = a.body or ""
    if a.body_file:
        body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file != "-" else sys.stdin.read()
    kind = a.kind
    action = reject = None
    if a.on_approve_command:
        action = {"type": "command", "command": a.on_approve_command, "timeout_min": a.timeout}
    elif a.on_approve_agent is not None:
        action = {"type": "agent", "prompt": a.on_approve_agent, "permissions": a.agent_permissions,
                  "timeout_min": a.timeout, "resume": bool(a.session_id)}
    if a.on_reject_command:
        reject = {"type": "command", "command": a.on_reject_command, "timeout_min": a.timeout}
    if (action or reject) and kind != "approval":
        kind = "approval"
    msg = {**actions._env_source(), "kind": kind, "severity": a.severity, "title": a.title, "body": body,
           "dedupe_key": a.dedupe_key, "link": a.link, "session_id": a.session_id,
           "action": action, "reject_action": reject,
           "expires_at": time.time() + a.expires_hours * 3600 if a.expires_hours else None}
    if a.source:
        msg["source"] = a.source
    rec = store.add({k: v for k, v in msg.items() if v not in (None, "")}, root)
    if a.telegram:
        rec["telegram_sent"] = actions.notify_telegram(rec)
    _out({"ok": True, "id": rec["id"], "kind": rec["kind"], "status": rec["status"],
          "occurrences": rec["occurrences"], "telegram_sent": rec.get("telegram_sent")})
    return 0


def cmd_wait(a, root) -> int:
    deadline = time.time() + a.timeout_min * 60
    while True:
        rec = store.get(a.id, root)
        if rec["status"] != "pending" or time.time() >= deadline:
            break
        time.sleep(5)
    _out({"id": rec["id"], "status": rec["status"], "decided_by": rec["decided_by"], "note": rec["decision_note"]})
    return {"approved": 0, "rejected": 3}.get(rec["status"], 4)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Central de Avisos do NetOps")
    ap.add_argument("--data-root", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="publica um aviso/alerta/pedido de aprovação")
    p.add_argument("--title", required=True)
    p.add_argument("--kind", choices=store.KINDS, default="info")
    p.add_argument("--severity", choices=store.SEVERITIES)
    p.add_argument("--body", default="")
    p.add_argument("--body-file", help="arquivo markdown (ou - p/ stdin)")
    p.add_argument("--dedupe-key")
    p.add_argument("--expires-hours", type=float)
    p.add_argument("--link")
    p.add_argument("--session-id")
    p.add_argument("--source")
    p.add_argument("--telegram", action="store_true", help="também avisa no Telegram (network/telegram.yaml)")
    p.add_argument("--on-approve-command")
    p.add_argument("--on-reject-command")
    p.add_argument("--on-approve-agent", help="prompt do agente que roda se aprovado (retoma --session-id se houver)")
    p.add_argument("--agent-permissions", choices=("restricted", "full"), default="restricted")
    p.add_argument("--timeout", type=int, default=15, help="minutos da ação")

    p = sub.add_parser("list")
    p.add_argument("--view", choices=store.VIEWS, default="open")
    p.add_argument("--limit", type=int, default=50)
    for name in ("get", "execute"):
        sub.add_parser(name).add_argument("id", type=int)
    p = sub.add_parser("wait")
    p.add_argument("id", type=int)
    p.add_argument("--timeout-min", type=float, default=60)
    for name in ("read", "archive"):
        sub.add_parser(name).add_argument("ids", type=int, nargs="+")
    sub.add_parser("summary")

    a = ap.parse_args(argv)
    root = a.data_root
    try:
        if a.cmd == "add":
            return cmd_add(a, root)
        if a.cmd == "list":
            _out({"items": store.list_messages(a.view, a.limit, root), "summary": store.summary(root)})
        elif a.cmd == "get":
            _out(store.get(a.id, root))
        elif a.cmd == "wait":
            return cmd_wait(a, root)
        elif a.cmd == "read":
            store.mark_read(a.ids, os.environ.get("NETOPS_USER", "cli"), root)
            _out({"ok": True, **store.summary(root)})
        elif a.cmd == "archive":
            _out({"ok": True, "archived": store.set_archived(a.ids, True, "cli", root)})
        elif a.cmd == "summary":
            _out(store.summary(root))
        elif a.cmd == "execute":
            _out(actions.execute(a.id, root))
    except store.InboxError as e:
        _out({"ok": False, "errors": e.errors})
        return 2
    except KeyError as e:
        _out({"ok": False, "error": str(e).strip("'\"")})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
