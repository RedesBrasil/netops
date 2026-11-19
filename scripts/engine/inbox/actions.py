#!/usr/bin/env python3
"""Central de Avisos — integração com as tarefas agendadas e execução da ação de um pedido decidido.

- `ingest_agent_output(text, ...)`: o agente de uma tarefa (que em modo restrito não tem shell) publica
  avisos/pedidos escrevendo blocos ```netops-inbox {json}``` na resposta; aqui viram mensagens.
- `post_schedule_run(task, rec)`: a execução de tarefa que "notifica" vira mensagem na Central.
- `spawn(id, decision)` / `execute(...)`: ao aprovar/reprovar um pedido com ação, roda a ação num
  processo destacado (comando, ou o agente RETOMANDO a mesma sessão com a decisão do humano).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from inbox import store

BLOCK_RE = re.compile(r"```netops-inbox[^\n]*\n(.*?)```", re.S)

AGENT_HINT = """Central de Avisos (alertas e pedidos de aprovação para o humano):
- Para ALERTAR ou PEDIR APROVAÇÃO, inclua na resposta um bloco de código com a linguagem `netops-inbox` contendo JSON
  (um objeto ou uma lista). Campos: kind ("alert" | "approval" | "info"), severity ("info" | "warning" | "critical"),
  title (curto), body (markdown: o que achou, evidência, o que propõe), dedupe_key (opcional: mesmo achado recorrente
  = mesma chave, não duplica).
- Pedido de aprovação = kind "approval". Você NÃO executa a ação proposta agora: descreva no body exatamente o que
  será feito. Se aprovado, a sua sessão é retomada com a decisão do humano para continuar. Opcional:
  "action": {"type": "agent", "prompt": "o que fazer se aprovado", "permissions": "restricted" | "full"}
  (use "full" só se a continuação precisar de shell/escrita, ex.: apagar arquivos). Sem "action", a sessão é
  retomada com permissões restritas.
- Exemplo:
```netops-inbox
{"kind": "approval", "severity": "warning", "title": "Apagar 12 arquivos temporários (3,1 GB) em /var/tmp",
 "body": "Lista:\\n- /var/tmp/a.tar (2 GB, 40 dias)\\n...", "action": {"type": "agent", "permissions": "full",
 "prompt": "Apague exatamente os arquivos listados e confirme o espaço liberado."}}
```
- Depois de publicar os blocos, se não houver mais nada a dizer, a resposta pode ser só os blocos."""


# --------------------------------------------------------------------------- #
# Blocos ```netops-inbox``` na resposta do agente
# --------------------------------------------------------------------------- #
def parse_blocks(text: str) -> tuple[list[dict], str, list[str]]:
    """(mensagens, texto sem os blocos, erros de parse)."""
    msgs, errors = [], []

    def take(m):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except ValueError as e:
            errors.append(f"bloco netops-inbox com JSON inválido: {e}")
            return m.group(0)
        items = data if isinstance(data, list) else [data]
        good = [x for x in items if isinstance(x, dict)]
        msgs.extend(good)
        return "\n".join(f"→ enviado à Central de Avisos: {x.get('title') or '(sem título)'}" for x in good)

    rest = BLOCK_RE.sub(take, text or "")
    return msgs, rest.strip(), errors


def ingest_agent_output(text: str, *, task: dict | None = None, run_id: str | None = None,
                        session_id: str | None = None, root=None) -> tuple[list[dict], str]:
    """Cria as mensagens dos blocos. Devolve (mensagens criadas, texto restante p/ a notificação)."""
    msgs, rest, errors = parse_blocks(text)
    created = []
    task = task or {}
    for m in msgs:
        base = {
            "source": "schedule" if task.get("id") else "agent",
            "source_label": task.get("name"),
            "task_id": task.get("id"), "run_id": run_id, "session_id": session_id,
            "link": f"#schedules/runs/{task['id']}/{run_id}" if task.get("id") and run_id else None,
        }
        if m.get("kind") == "approval" and not m.get("action") and session_id:
            # sem ação explícita: aprovar retoma a mesma sessão do agente (permissões restritas)
            m = {**m, "action": {"type": "agent", "resume": True, "permissions": "restricted"}}
        try:
            rec = store.add({**base, **{k: v for k, v in m.items() if k in (
                "kind", "severity", "title", "body", "dedupe_key", "action", "reject_action", "expires_at")}}, root)
            created.append(rec)
            if m.get("telegram"):
                notify_telegram(rec)
        except store.InboxError as e:
            errors.append(f"aviso inválido ({m.get('title') or '?'}): {e}")
    if errors:
        rest = (rest + "\n\n" if rest else "") + "\n".join(f"⚠ {e}" for e in errors)
    return created, rest


def post_schedule_run(task: dict, rec: dict, root=None) -> dict | None:
    """Execução de tarefa agendada que notifica → mensagem na Central (falha repetida agrupa)."""
    status = rec.get("status")
    failed = status in ("error", "timeout")
    name = task.get("name") or task.get("id")
    if failed:
        title = f"Tarefa “{name}” falhou" + (f": {rec['error']}" if rec.get("error") else "")
        tail = (rec.get("agent_output") or rec.get("script_output") or "").strip()
        body = (f"**Erro:** {rec.get('error') or status}\n\n" + (f"```\n{tail[-3000:]}\n```" if tail else "")).strip()
    else:
        text = (rec.get("agent_output") or rec.get("script_output") or "").strip()
        first = next((ln.strip(" #*") for ln in text.splitlines() if ln.strip()), "")
        title = f"{name}: {first}" if first else f"Tarefa “{name}” concluída"
        body = text if rec.get("agent_output") else (f"```\n{text[-6000:]}\n```" if text else "")
    try:
        return store.add({
            "kind": "alert" if failed else "info", "severity": "warning" if failed else "info",
            "title": title[:store.TITLE_MAX], "body": body,
            "source": "schedule", "source_label": name, "task_id": task.get("id"), "run_id": rec.get("run_id"),
            "session_id": rec.get("session_id"), "link": f"#schedules/runs/{task.get('id')}/{rec.get('run_id')}",
            "dedupe_key": f"schedule-fail:{task.get('id')}" if failed else None,
        }, root)
    except store.InboxError:
        return None


def notify_telegram(rec: dict) -> bool:
    """Empurrão opcional no Telegram (network/telegram.yaml). Nunca derruba quem chamou."""
    try:
        from scheduler import runner  # noqa: PLC0415
        icon = {"approval": "🟡 Aprovação pendente", "alert": "🔴 Alerta", "info": "ℹ️ Aviso"}.get(rec["kind"], "Aviso")
        return runner._telegram(f"{icon} — Central de Avisos #{rec['id']}\n\n{rec['title']}\n\nAbra o console para ver.")
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Ação do pedido decidido
# --------------------------------------------------------------------------- #
def spawn(mid: int, root=None) -> None:
    """Roda a ação num processo destacado (o request do console não espera)."""
    rec = store.get(mid, root)
    act = rec["action"] if rec["status"] == "approved" else rec["reject_action"] if rec["status"] == "rejected" else None
    if not act:
        return
    store.set_result(mid, {"state": "queued", "decision": rec["status"], "queued_at": time.time()}, root=root)
    cli = Path(__file__).resolve().parent / "cli.py"
    logd = store.data_root(root) / "runs" / "inbox"
    logd.mkdir(parents=True, exist_ok=True)
    with open(logd / f"{int(mid)}.log", "ab") as log:
        subprocess.Popen([sys.executable, str(cli), "--data-root", str(store.data_root(root)), "execute", str(int(mid))],
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                         cwd=str(store.data_root(root)))


def decision_prompt(rec: dict, act: dict) -> str:
    verb = "APROVOU" if rec["status"] == "approved" else "REPROVOU"
    parts = [f"[NetOps — Central de Avisos] O usuário {rec.get('decided_by') or '?'} {verb} o pedido "
             f"#{rec['id']}: “{rec['title']}”."]
    if rec.get("decision_note"):
        parts.append(f"Observação do usuário: {rec['decision_note']}")
    if act.get("prompt"):
        parts.append(act["prompt"])
    elif rec["status"] == "approved":
        parts.append("Prossiga exatamente com o que foi proposto no pedido (nada além disso) e reporte o resultado.")
    else:
        parts.append("Não execute o que foi proposto. Registre a decisão e encerre.")
    if not (act.get("resume", True) and rec.get("session_id")):
        parts.append("## Pedido original\n" + (rec.get("body") or "(sem detalhes)"))
    return "\n\n".join(parts)


def execute(mid: int, root=None) -> dict:
    """Executa a ação do pedido decidido (chamado pelo processo destacado do `spawn`)."""
    from scheduler import runner  # noqa: PLC0415 — reaproveita ambiente, timeout e linha do `claude`
    rec = store.get(mid, root)
    act = rec["action"] if rec["status"] == "approved" else rec["reject_action"] if rec["status"] == "rejected" else None
    if not act:
        return {"state": "done", "status": "skipped", "error": "sem ação para esta decisão"}
    res = {"state": "running", "decision": rec["status"], "type": act["type"], "started_at": time.time()}
    store.set_result(mid, res, root=root)
    env = runner._env(rec.get("task_id") or "inbox", f"inbox-{mid}")
    env.update(NETOPS_INBOX_ID=str(mid), NETOPS_INBOX_DECISION=rec["status"],
               NETOPS_INBOX_DECIDED_BY=rec.get("decided_by") or "", NETOPS_INBOX_NOTE=rec.get("decision_note") or "")
    timeout = int(act.get("timeout_min") or 15) * 60
    try:
        if act["type"] == "command":
            code, out, tout = runner._run_proc(act["command"], env=env, cwd=str(store.data_root(root)),
                                               timeout=timeout, shell=True)
            res.update(exit_code=code, output=out)
            res["status"] = "timeout" if tout else ("ok" if code == 0 else "error")
            if code not in (0, None) and not tout:
                res["error"] = f"comando saiu com código {code}"
        else:
            if not runner.claude_bin():
                raise RuntimeError("binário `claude` não encontrado no PATH")
            task = {"agent": {"permissions": act.get("permissions") or "restricted", "model": act.get("model")}}
            cmd = runner.agent_command(task, decision_prompt(rec, act))
            if act.get("resume", True) and rec.get("session_id"):
                cmd += ["--resume", rec["session_id"]]
            code, out, tout = runner._run_proc(cmd, env={**env, "IS_SANDBOX": "1"}, cwd=str(store.NETOPS_ROOT),
                                               timeout=timeout)
            text, meta = out, {}
            try:
                meta = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
                text = meta.get("result") or ""
            except (ValueError, IndexError):
                meta = {}
            sid = meta.get("session_id") or rec.get("session_id")
            created, rest = ingest_agent_output(text, task={"id": rec.get("task_id"), "name": rec.get("source_label")}
                                                if rec.get("task_id") else None, run_id=rec.get("run_id"),
                                                session_id=sid, root=root)
            res.update(output=rest or text.strip(), session_id=sid, cost_usd=meta.get("total_cost_usd"),
                       followups=[c["id"] for c in created])
            if tout:
                res.update(status="timeout", error=f"agente passou de {timeout // 60} min")
            elif code != 0 or meta.get("is_error"):
                res.update(status="error", error=meta.get("subtype") or f"claude saiu com código {code}")
                if not text.strip():
                    res["output"] = out.strip()[-4000:]
            elif text.strip().startswith("[FALHA]"):
                res.update(status="error", error="o agente reportou falha")
            else:
                res["status"] = "ok"
    except Exception as e:  # noqa: BLE001
        res.update(status="error", error=f"{type(e).__name__}: {e}")
    res.update(state="done", finished_at=time.time())
    if isinstance(res.get("output"), str) and len(res["output"]) > 60_000:
        res["output"] = res["output"][:30_000] + "\n…[truncado]…\n" + res["output"][-30_000:]
    store.set_result(mid, res, unread=True, root=root)
    return res


def _env_source() -> dict:
    """Origem automática p/ quem chama o CLI: tarefa agendada, aba Claude ou script."""
    if os.environ.get("NETOPS_SCHEDULED_TASK"):
        tid, rid = os.environ["NETOPS_SCHEDULED_TASK"], os.environ.get("NETOPS_SCHEDULED_RUN_ID")
        name = None
        try:
            from scheduler import store as sstore  # noqa: PLC0415
            name = sstore.get_task(tid).get("name")
        except Exception:  # noqa: BLE001
            pass
        out = {"source": "schedule", "task_id": tid, "source_label": name or tid}
        if rid and not rid.startswith("inbox-"):
            out.update(run_id=rid, link=f"#schedules/runs/{tid}/{rid}")
        return out
    if os.environ.get("NETOPS_USER"):
        return {"source": "chat", "source_label": f"aba Claude ({os.environ['NETOPS_USER']})"}
    return {"source": "script"}
