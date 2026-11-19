#!/usr/bin/env python3
"""Despachante (tick) e executor das tarefas agendadas.

tick()  — chamado pelo cron a cada minuto. Sob trava, vê o que venceu, AVANÇA o próximo horário
          antes de disparar (no máximo uma vez por horário, mesmo se algo cair no meio) e lança cada
          execução num processo destacado. Atrasos maiores que GRACE_SECONDS (cron parado) pulam o
          horário e marcam "perdida".
run()   — executa UMA tarefa: script, agente ou script+agente; grava runs/schedules/<id>/<run>.json
          e decide se notifica (falha sempre notifica; agente que responde [SILENT] não notifica).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from scheduler import store

OUTPUT_LIMIT = 60_000            # bytes guardados de cada saída
SCRIPT_TO_AGENT_LIMIT = 20_000   # bytes da saída do script que entram no prompt
SILENT_RE = re.compile(r"^\s*\[?(SILENT|NO_REPLY)\]?\s*$", re.I)
RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")

AGENT_HINT = """Você está rodando como TAREFA AGENDADA do NetOps (sem humano olhando, sem chat).
Regras desta execução:
- Faça exatamente o que a tarefa pede. Não execute mudanças, reinícios ou ações destrutivas que a tarefa não descreve explicitamente.
- Não crie, edite nem remova tarefas agendadas (nem cron, nem CronCreate), mesmo que o texto diga "todo dia".
- Não pergunte nada (não há quem responda): decida com segurança ou desista e explique.
- Sua resposta final é a notificação que o usuário vai ler no console: comece pela conclusão, seja objetivo, em PT-BR.
- Se não houver NADA relevante a reportar, responda exatamente: [SILENT]
- Se a tarefa falhou, comece a resposta com a linha: [FALHA]"""


def _agent_hint() -> str:
    """Regras fixas + como publicar alertas/pedidos de aprovação na Central de Avisos."""
    try:
        from inbox import actions as inbox_actions  # noqa: PLC0415
        return AGENT_HINT + "\n\n" + inbox_actions.AGENT_HINT
    except Exception:  # noqa: BLE001
        return AGENT_HINT

RESTRICTED_TOOLS = ["Read", "Glob", "Grep", "WebFetch", "WebSearch", "TodoWrite"]
ALWAYS_DENIED = ["CronCreate", "CronDelete", "CronList", "RemoteTrigger", "AskUserQuestion", "PushNotification"]


def _now(tz_name: str) -> datetime:
    return datetime.now(store.tzinfo(tz_name))


def _iso(ts: float | None, tz_name: str) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, store.tzinfo(tz_name)).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Despachante
# --------------------------------------------------------------------------- #
def _spawn(task_id: str, trigger: str, root) -> str:
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    d = store.runs_dir(root) / task_id
    d.mkdir(parents=True, exist_ok=True)
    cli = Path(__file__).resolve().parent / "cli.py"
    with open(d / f"{run_id}.log", "ab") as log:
        subprocess.Popen(
            [sys.executable, str(cli), "--data-root", str(store.data_root(root)), "run", task_id,
             "--run-id", run_id, "--trigger", trigger],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            cwd=str(store.data_root(root)),
        )
    return run_id


def compute_due(cfg: dict, st: dict, now: datetime) -> list[str]:
    """Atualiza st['tasks'][id]['next_run_at'] e devolve os ids a disparar agora (puro, testável)."""
    tz_name = cfg.get("timezone") or store.DEFAULT_TZ
    due = []
    ids = set()
    for task in cfg.get("tasks") or []:
        tid = task.get("id")
        ids.add(tid)
        ts = st["tasks"].setdefault(tid, {})
        sig = store.schedule_sig(task, tz_name)
        if not task.get("enabled", True):
            ts["next_run_at"] = None
            ts["sig"] = None
            continue
        last = datetime.fromtimestamp(ts["last_run_at"], now.tzinfo) if ts.get("last_run_at") else None
        if ts.get("sig") != sig or ts.get("next_run_at") is None and not ts.get("completed"):
            # Agenda nova/alterada (ou religada): o próximo horário conta a partir de agora.
            ts["sig"] = sig
            ts["completed"] = False
            try:
                nxt = store.next_run(task, tz_name, now.replace(second=0, microsecond=0) if
                                     (task.get("schedule") or {}).get("type") == "cron" else now, None)
            except Exception as e:  # noqa: BLE001
                ts["next_run_at"], ts["error"] = None, f"agenda inválida: {e}"
                continue
            if task["schedule"].get("type") == "cron" and nxt is not None:
                # o minuto corrente também vale (salvou 09:00:10 uma tarefa das 09:00 → roda já)
                from scheduler.cronexpr import CronExpr  # noqa: PLC0415
                cur = now.replace(second=0, microsecond=0)
                if CronExpr(task["schedule"]["expr"]).matches(cur.astimezone(store.tzinfo(tz_name))):
                    nxt = cur
            ts["next_run_at"] = nxt.timestamp() if nxt else None
            if nxt is None:
                ts["completed"] = True
        nra = ts.get("next_run_at")
        if nra is None or nra > now.timestamp():
            continue
        late = now.timestamp() - nra
        stype = (task.get("schedule") or {}).get("type")
        nxt = store.next_run(task, tz_name, now, last if stype == "interval" else None)
        ts["next_run_at"] = nxt.timestamp() if nxt else None
        if stype == "once":
            ts["completed"] = True
        if late > store.GRACE_SECONDS:
            ts["last_status"] = "missed"
            ts["missed_at"] = nra
            continue
        due.append(tid)
    for gone in set(st["tasks"]) - ids:
        st["tasks"].pop(gone, None)
    return due


def tick(root=None) -> list[str]:
    lock_path = store.runs_dir(root) / ".tick.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        cfg = store.load(root)["config"]
        now = _now(cfg.get("timezone"))
        with store.edit_state(root) as st:
            due = compute_due(cfg, st, now)
            st["last_tick"] = time.time()
        for tid in due:
            _spawn(tid, "schedule", root)
        _sweep_task_keys(cfg, root)
        return due


def _sweep_task_keys(cfg: dict, root=None) -> None:
    """Pasta de chave sem tarefa (tarefa apagada editando o YAML na mão) é removida."""
    ids = {t.get("id") for t in cfg.get("tasks", [])}
    if not ids:
        return
    try:
        from lib import taskkeys
        taskkeys.sweep(store.data_root(root), ids)
    except Exception:
        pass


def run_now(task_id: str, root=None) -> str:
    store.get_task(task_id, root)   # KeyError se não existe
    return _spawn(task_id, "manual", root)


# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #
def _env(task_id: str, run_id: str) -> dict:
    env = dict(os.environ)
    home = str(Path.home())
    extra = [str(store.NETOPS_ROOT / ".venv" / "bin"), f"{home}/.local/bin"]
    env["PATH"] = ":".join(extra + [env.get("PATH") or "/usr/local/bin:/usr/bin:/bin"])
    env["NETOPS_SCHEDULED_RUN"] = "1"
    env["NETOPS_SCHEDULED_TASK"] = task_id
    env["NETOPS_SCHEDULED_RUN_ID"] = run_id
    # cofre: o cache da chave mora em /run/user/<uid>/netops (mesmo do console/CLI)
    run_user = f"/run/user/{os.getuid()}"
    if not env.get("XDG_RUNTIME_DIR") and os.path.isdir(run_user):
        env["XDG_RUNTIME_DIR"] = run_user
    return env


def _run_proc(cmd, *, env, cwd, timeout: int, shell: bool = False) -> tuple[int | None, str, bool]:
    """(exit_code, saída combinada truncada, estourou_tempo). Mata o grupo inteiro no timeout."""
    proc = subprocess.Popen(cmd, shell=shell, executable="/bin/bash" if shell else None, cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        with _suppress():
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            with _suppress():
                os.killpg(proc.pid, signal.SIGKILL)
            out, _ = proc.communicate()
        timed_out = True
    text = (out or b"").decode("utf-8", errors="replace")
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT // 2] + "\n…[saída truncada]…\n" + text[-OUTPUT_LIMIT // 2:]
    return proc.returncode, text, timed_out


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return exc[0] is not None and issubclass(exc[0], (ProcessLookupError, PermissionError, OSError))


def claude_bin() -> str | None:
    return shutil.which("claude") or next(
        (p for p in (f"{Path.home()}/.local/bin/claude", "/usr/local/bin/claude", "/usr/bin/claude")
         if os.path.exists(p)), None)


def _github_env(task: dict, env: dict, root=None) -> dict:
    """agent.github_as = usuário do console: o agente usa o GitHub DELE (sem conta conectada = sem GitHub,
    nunca o do servidor). Vazio = comportamento antigo (gh do servidor)."""
    user = ((task.get("agent") or {}).get("github_as") or "").strip()
    if not user:
        return env
    from lib import github_identity  # noqa: PLC0415
    return github_identity.apply_env(env, github_identity.env_for(store.data_root(root), user, multiuser=True))


def agent_command(task: dict, prompt: str) -> list[str]:
    agent = task.get("agent") or {}
    cmd = [claude_bin() or "claude", "-p", prompt, "--output-format", "json",
           "--append-system-prompt", _agent_hint(), "--disallowedTools", *ALWAYS_DENIED]
    if agent.get("permissions") == "full":
        cmd += ["--dangerously-skip-permissions"]
    else:
        cmd += ["--allowedTools", *RESTRICTED_TOOLS,
                "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit"]
    if agent.get("model"):
        cmd += ["--model", agent["model"]]
    return cmd


def build_prompt(task: dict, tz_name: str, script_output: str | None) -> str:
    parts = [f"[Tarefa agendada: {task.get('name')} (id {task.get('id')}) — "
             f"execução em {_now(tz_name).isoformat(timespec='minutes')}]"]
    if script_output is not None:
        out = script_output
        if len(out) > SCRIPT_TO_AGENT_LIMIT:
            out = out[-SCRIPT_TO_AGENT_LIMIT:]
        parts.append("## Saída do script (coletada antes de você)\n```\n" + out.strip() + "\n```")
    parts.append("## Tarefa\n" + task.get("prompt", ""))
    return "\n\n".join(parts)


def is_silent(text: str) -> bool:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    if not lines:
        return True
    return bool(SILENT_RE.match(lines[0]) or SILENT_RE.match(lines[-1]))


def wake_agent(script_output: str) -> bool:
    lines = [ln for ln in (script_output or "").strip().splitlines() if ln.strip()]
    if not lines:
        return False
    try:
        last = json.loads(lines[-1])
        if isinstance(last, dict) and last.get("wakeAgent") is False:
            return False
    except ValueError:
        pass
    return True


def should_notify(task: dict, status: str, silent: bool) -> bool:
    mode = task.get("notify") or "auto"
    if mode == "never":
        return False
    if status in ("error", "timeout"):
        return True
    if mode == "failure":
        return False
    if mode == "always":
        return True
    # auto: script só avisa em falha; agente avisa salvo [SILENT]
    return task.get("kind") != "script" and status == "ok" and not silent


def _write_run(root, rec: dict) -> None:
    store._atomic_write(store.runs_dir(root) / rec["task_id"] / f"{rec['run_id']}.json",
                        json.dumps(rec, ensure_ascii=False, indent=1), 0o600)


AUTH_FAIL_RE = re.compile(
    r"Failed to authenticate|OAuth session expired|authentication_error|Invalid API key|Please run /login|"
    r"could not be refreshed", re.I)
AUTH_ALERT_COOLDOWN = 3600       # no máx. 1 alerta de login por hora e por tarefa
MAX_FAILED_RUNS_KEPT = 200       # execuções com erro/timeout ficam bem mais tempo que as ok


def is_auth_failure(text: str) -> bool:
    return bool(AUTH_FAIL_RE.search(text or ""))


def _telegram(text: str) -> bool:
    """Alerta curto no Telegram (network/telegram.yaml). Nunca derruba a execução."""
    try:
        import urllib.parse
        import urllib.request
        import yaml
        tg = yaml.safe_load((store.NETOPS_ROOT / "network" / "telegram.yaml").read_text()) or {}
        body = urllib.parse.urlencode({"chat_id": tg["chat_id"], "text": text[:1000]}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage", data=body)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _alert_auth_failure(task: dict, rec: dict, root) -> None:
    with store.edit_state(root) as st:
        ts = st["tasks"].setdefault(task["id"], {})
        if time.time() - (ts.get("auth_alert_at") or 0) < AUTH_ALERT_COOLDOWN:
            return
        ts["auth_alert_at"] = time.time()
    hora = _now(store.load(root)["config"].get("timezone") or store.DEFAULT_TZ).strftime("%d/%m %H:%M")
    _telegram(f"⚠️ Tarefa agendada NÃO rodou: login do Claude expirou\n\n"
              f"Tarefa: {task.get('name')} ({hora})\n"
              f"O agente não iniciou, então a análise desta execução se perdeu.\n\n"
              f"Corrigir: fazer /login na aba Claude do console.")


def _prune(task_id: str, root) -> None:
    """Mantém as MAX_RUNS_PER_TASK execuções mais recentes e, além disso, as últimas
    MAX_FAILED_RUNS_KEPT com erro/timeout (para dar para diagnosticar falhas antigas)."""
    d = store.runs_dir(root) / task_id
    runs = sorted(d.glob("*.json"))
    old = runs[:-store.MAX_RUNS_PER_TASK]
    failed = []
    for p in old:
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("status") in ("error", "timeout"):
                failed.append(p)
        except (OSError, ValueError):
            pass
    keep = set(failed[-MAX_FAILED_RUNS_KEPT:])
    gone = set()
    for p in old:
        if p in keep:
            continue
        gone.add(f"{task_id}/{p.stem}")
        for f in (p, p.with_suffix(".log")):
            with _suppress():
                f.unlink()
    if gone:   # execução apagada não pode continuar "não lida" (badge fantasma no menu)
        with store.edit_state(root) as st:
            st["unread"] = [u for u in st["unread"] if u not in gone]


def run(task_id: str, run_id: str, trigger: str = "manual", root=None) -> dict:
    cfg = store.load(root)["config"]
    tz_name = cfg.get("timezone") or store.DEFAULT_TZ
    task = store.get_task(task_id, root)
    rec = {"run_id": run_id, "task_id": task_id, "task_name": task.get("name"), "kind": task.get("kind"),
           "trigger": trigger, "state": "running", "status": None, "started_at": time.time(),
           "finished_at": None, "script": task.get("script"), "exit_code": None, "script_output": None,
           "agent_output": None, "agent_skipped": None, "session_id": None, "cost_usd": None,
           "silent": False, "notified": False, "error": None}
    lock = store.runs_dir(root) / task_id / ".running.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        rec.update(state="done", status="skipped", finished_at=time.time(),
                   error="a execução anterior ainda não terminou")
        _write_run(root, rec)
        _finish_state(task, rec, root, notify=False)
        return rec
    with store.edit_state(root) as st:
        st["tasks"].setdefault(task_id, {}).update(running=run_id, running_since=rec["started_at"])
    _write_run(root, rec)
    env = _env(task_id, run_id)
    cwd = str(store.data_root(root))
    timeout = int(task.get("timeout_min") or 15) * 60
    deadline = time.time() + timeout
    try:
        script_out = None
        if task["kind"] in ("script", "hybrid"):
            code, script_out, tout = _run_proc(task["script"], env=env, cwd=cwd, timeout=timeout, shell=True)
            rec.update(exit_code=code, script_output=script_out)
            if tout:
                rec.update(status="timeout", error=f"script passou de {timeout // 60} min")
            elif code != 0:
                rec.update(status="error", error=f"script saiu com código {code}")
            elif task["kind"] == "script":
                rec["status"] = "ok"
            elif not wake_agent(script_out):
                rec.update(status="ok", agent_skipped="saída vazia do script — agente não acionado",
                           silent=True)
            _write_run(root, rec)
        if task["kind"] == "agent" or (task["kind"] == "hybrid" and rec["status"] is None):
            if not claude_bin():
                raise RuntimeError("binário `claude` não encontrado no PATH")
            prompt = build_prompt(task, tz_name, script_out if task["kind"] == "hybrid" else None)
            left = max(60, int(deadline - time.time()))
            code, out, tout = _run_proc(agent_command(task, prompt), env=_github_env(task, {**env, "IS_SANDBOX": "1"}, root),
                                        cwd=str(store.NETOPS_ROOT), timeout=left)
            text, meta = out, {}
            try:
                meta = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
                text = meta.get("result") or ""
            except (ValueError, IndexError):
                meta = {}
            rec.update(agent_output=text.strip(), session_id=meta.get("session_id"),
                       cost_usd=meta.get("total_cost_usd"))
            if code == 0 and not tout and text.strip():
                text = _ingest_inbox(task, rec, text, root)
            if tout:
                rec.update(status="timeout", error=f"agente passou do tempo limite ({timeout // 60} min)")
            elif code != 0 or meta.get("is_error"):
                rec.update(status="error", error=(meta.get("subtype") or f"claude saiu com código {code}"))
                if not text.strip():
                    rec["agent_output"] = out.strip()[-4000:]
                if is_auth_failure(text) or is_auth_failure(out):
                    rec.update(error="login do Claude expirado (OAuth) — o agente não iniciou",
                               auth_failure=True)
            elif text.strip().startswith("[FALHA]"):
                rec.update(status="error", error="o agente reportou falha")
            else:
                rec.update(status="ok", silent=is_silent(text) or bool(rec.get("inbox_only")))
    except Exception as e:  # noqa: BLE001
        rec.update(status="error", error=f"{type(e).__name__}: {e}")
    rec.update(state="done", finished_at=time.time())
    rec["notified"] = should_notify(task, rec["status"], rec["silent"])
    _write_run(root, rec)
    if rec["notified"]:
        try:   # a notificação também vai para a Central de Avisos (sino do console)
            from inbox import actions as inbox_actions  # noqa: PLC0415
            inbox_actions.post_schedule_run(task, rec, root)
        except Exception:  # noqa: BLE001 — Central nunca derruba a execução
            pass
    _finish_state(task, rec, root, notify=rec["notified"])
    if rec.get("auth_failure"):
        try:
            _alert_auth_failure(task, rec, root)
        except Exception:  # noqa: BLE001 — alerta nunca derruba a execução
            pass
    _prune(task_id, root)
    fcntl.flock(fh, fcntl.LOCK_UN)
    fh.close()
    return rec


def _ingest_inbox(task: dict, rec: dict, text: str, root) -> str:
    """Blocos ```netops-inbox``` da resposta viram avisos/pedidos na Central. Devolve o texto restante.

    Se o agente publicou algo, a execução em si não gera outra notificação (o aviso já está lá),
    salvo se sobrou texto relevante fora dos blocos."""
    try:
        from inbox import actions as inbox_actions  # noqa: PLC0415
        created, rest = inbox_actions.ingest_agent_output(text, task=task, run_id=rec["run_id"],
                                                          session_id=rec.get("session_id"), root=root)
    except Exception as e:  # noqa: BLE001
        rec["inbox_error"] = f"{type(e).__name__}: {e}"
        return text
    if created:
        rec["inbox_ids"] = [c["id"] for c in created]
        rec["agent_output"] = rest
        if is_silent(rest) or all(ln.startswith("→ enviado à Central") for ln in rest.splitlines() if ln.strip()):
            rec["inbox_only"] = True
    return rest if created else text


def _finish_state(task: dict, rec: dict, root, notify: bool) -> None:
    with store.edit_state(root) as st:
        ts = st["tasks"].setdefault(task["id"], {})
        if ts.get("running") == rec["run_id"]:
            ts.pop("running", None)
            ts.pop("running_since", None)
        ts.update(last_run_at=rec["started_at"], last_status=rec["status"], last_run_id=rec["run_id"],
                  last_silent=rec["silent"])
        ts["failures"] = (ts.get("failures") or 0) + 1 if rec["status"] in ("error", "timeout") else 0
        key = f"{task['id']}/{rec['run_id']}"
        if notify and key not in st["unread"]:
            st["unread"].append(key)
            st["unread"] = st["unread"][-200:]


# --------------------------------------------------------------------------- #
# Leitura (console / CLI)
# --------------------------------------------------------------------------- #
def _summary(rec: dict) -> dict:
    keep = ("run_id", "task_id", "task_name", "kind", "trigger", "state", "status", "started_at",
            "finished_at", "silent", "notified", "error", "agent_skipped", "session_id", "cost_usd", "inbox_ids")
    out = {k: rec.get(k) for k in keep}
    text = rec.get("agent_output") or rec.get("script_output") or ""
    out["excerpt"] = text.strip()[:240]
    return out


def list_runs(root=None, task_id: str | None = None, limit: int = 300) -> list[dict]:
    base = store.runs_dir(root)
    if not base.exists():
        return []
    unread = set(store.read_state(root)["unread"])
    items = []
    dirs = [base / task_id] if task_id else [d for d in base.iterdir() if d.is_dir()]
    for d in dirs:
        for p in d.glob("*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            s = _summary(rec)
            s["unread"] = f"{rec.get('task_id')}/{rec.get('run_id')}" in unread
            items.append(s)
    items.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return items[:limit]


def read_run(task_id: str, run_id: str, root=None) -> dict:
    if not store.ID_RE.match(task_id or "") or not RUN_ID_RE.match(run_id or ""):
        raise KeyError("execução inválida")
    p = store.runs_dir(root) / task_id / f"{run_id}.json"
    if not p.exists():
        raise KeyError(f"execução '{task_id}/{run_id}' não encontrada")
    rec = json.loads(p.read_text(encoding="utf-8"))
    log = p.with_suffix(".log")
    rec["log"] = log.read_text(encoding="utf-8", errors="replace")[-20_000:] if log.exists() else ""
    rec["unread"] = f"{task_id}/{run_id}" in store.read_state(root)["unread"]
    return rec


def mark_read(keys: list[str] | None, root=None) -> int:
    """keys=None marca tudo. Devolve quantas continuam não lidas."""
    with store.edit_state(root) as st:
        st["unread"] = [] if keys is None else [u for u in st["unread"] if u not in set(keys)]
        left = len(st["unread"])
    try:   # lida aqui = lida também na Central de Avisos
        from inbox import store as inbox_store  # noqa: PLC0415
        inbox_store.mark_read_runs(keys, root)
    except Exception:  # noqa: BLE001
        pass
    return left


def overview(root=None) -> dict:
    """Cadastro + estado por tarefa (próxima/última) + saúde do cron — o que a lista mostra."""
    data = store.load(root)
    cfg = data["config"]
    tz_name = cfg.get("timezone") or store.DEFAULT_TZ
    st = store.read_state(root)
    tasks = []
    now = _now(tz_name)
    for t in cfg["tasks"]:
        ts = dict(st["tasks"].get(t.get("id")) or {})
        nra = ts.get("next_run_at")
        if t.get("enabled", True) and (ts.get("sig") != store.schedule_sig(t, tz_name) or nra is None) \
                and not ts.get("completed"):
            try:   # ainda não passou pelo tick: mostra a previsão
                n = store.next_run(t, tz_name, now)
                nra = n.timestamp() if n else None
            except Exception:  # noqa: BLE001
                nra = None
        tasks.append({**t, "kind_label": store.KIND_LABELS.get(t.get("kind"), t.get("kind")),
                      "schedule_label": store.describe_schedule(t),
                      "state": {"next_run_at": nra if t.get("enabled", True) else None,
                                "last_run_at": ts.get("last_run_at"), "last_status": ts.get("last_status"),
                                "last_run_id": ts.get("last_run_id"), "running": ts.get("running"),
                                "failures": ts.get("failures") or 0, "completed": bool(ts.get("completed"))}})
    return {"config": {**cfg, "tasks": tasks}, "rev": data["rev"], "timezone": tz_name,
            "unread": len(st["unread"]), "cron": store.cron_status(root)}
