#!/usr/bin/env python3
"""Tarefas agendadas do NetOps — cadastro, estado e a linha do cron.

Arquivos (todos sob a raiz de dados da instalação, git-ignorados):
  network/schedules.yaml          cadastro (o que rodar e quando) — editado pelo console e pelo cli.py
  runs/schedules/state.json       estado de execução (próxima/última, status, não lidas) — só o motor grava
  runs/schedules/<tarefa>/<run>.json|.log   cada execução
  /etc/cron.d/netops-scheduler    UMA linha `* * * * *` que chama `cli.py tick` (o despachante)

Por que um despachante e não uma linha de cron por tarefa: o servidor roda em UTC e o cron do
Debian não tem CRON_TZ; o despachante avalia cada expressão no fuso da tarefa, impede execução
sobreposta, faz "uma vez em data/hora" e "a cada N minutos" reais, e grava histórico.

Tipos (`kind`):
  script  determinístico — roda um comando/script; nenhuma IA envolvida.
  agent   não determinístico — um agente de IA (Claude Code, headless) executa o prompt.
  hybrid  script + agente — o script coleta, a saída vai no prompt do agente que analisa.
          Saída vazia do script (ou última linha `{"wakeAgent": false}`) = agente não é acionado.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from scheduler.cronexpr import CronError, CronExpr

NETOPS_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TZ = "America/Sao_Paulo"
KINDS = ("script", "agent", "hybrid")
KIND_LABELS = {"script": "Determinística / script", "agent": "Agente de IA", "hybrid": "Script + agente"}
NOTIFY = ("auto", "always", "failure", "never")
PERMISSIONS = ("restricted", "full")
SCHEDULE_TYPES = ("cron", "interval", "once")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
CRON_FILE_NAME = "netops-scheduler"      # /etc/cron.d não aceita ponto no nome
MAX_RUNS_PER_TASK = 50
GRACE_SECONDS = 3600                     # atraso máximo tolerado (cron parado) antes de pular o horário


class TaskError(ValueError):
    """Erro de validação: lista de {loc, msg} (mesmo formato do console)."""

    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(f"{e['loc']}: {e['msg']}" for e in errors))
        self.errors = errors


class RevConflict(RuntimeError):
    def __init__(self, current: str):
        super().__init__("o cadastro mudou desde a leitura — recarregue")
        self.current = current


# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #
def data_root(root: Path | str | None = None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(os.environ.get("NETOPS_UI_DATA_ROOT") or NETOPS_ROOT).resolve()


def tasks_file(root=None) -> Path:
    return data_root(root) / "network" / "schedules.yaml"


def runs_dir(root=None) -> Path:
    return data_root(root) / "runs" / "schedules"


def state_file(root=None) -> Path:
    return runs_dir(root) / "state.json"


def cron_file(root=None) -> Path:
    """Instalação real → /etc/cron.d. Raiz de dados isolada (testes) → arquivo dentro dela, nunca o real."""
    env = os.environ.get("NETOPS_SCHEDULER_CRON_FILE")
    if env:
        return Path(env)
    r = data_root(root)
    if r == NETOPS_ROOT.resolve():
        return Path("/etc/cron.d") / CRON_FILE_NAME
    return r / "runs" / "schedules" / ("cron.d-" + CRON_FILE_NAME)


# --------------------------------------------------------------------------- #
# I/O com trava
# --------------------------------------------------------------------------- #
def _atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, mode)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


@contextlib.contextmanager
def _flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _rev(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _empty() -> dict:
    return {"version": 1, "timezone": DEFAULT_TZ, "tasks": []}


def load(root=None) -> dict:
    """{config, rev}. Arquivo ausente => cadastro vazio."""
    p = tasks_file(root)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    cfg = yaml.safe_load(text) if text.strip() else None
    cfg = cfg if isinstance(cfg, dict) else _empty()
    cfg.setdefault("version", 1)
    cfg.setdefault("timezone", DEFAULT_TZ)
    cfg["tasks"] = [t for t in (cfg.get("tasks") or []) if isinstance(t, dict)]
    return {"config": cfg, "rev": _rev(text)}


def _dump(cfg: dict) -> str:
    head = ("# Tarefas agendadas do NetOps — editar pelo console (menu Tarefas agendadas) ou por\n"
            "# scripts/engine/scheduler/cli.py. Quem dispara é o cron (/etc/cron.d/netops-scheduler).\n")
    return head + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=100)


def _save(cfg: dict, expected: str | None, root=None) -> str:
    p = tasks_file(root)
    current = _rev(p.read_text(encoding="utf-8")) if p.exists() else _rev("")
    if expected and expected != current:
        raise RevConflict(current)
    text = _dump(cfg)
    _atomic_write(p, text, 0o600)
    return _rev(text)


def read_state(root=None) -> dict:
    try:
        st = json.loads(state_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault("tasks", {})
    st.setdefault("unread", [])
    return st


@contextlib.contextmanager
def edit_state(root=None):
    """Leitura-modificação-escrita do state.json sob flock (tick e runs concorrem)."""
    with _flock(runs_dir(root) / ".state.lock"):
        st = read_state(root)
        yield st
        _atomic_write(state_file(root), json.dumps(st, ensure_ascii=False, indent=1), 0o600)


# --------------------------------------------------------------------------- #
# Agendamento
# --------------------------------------------------------------------------- #
def tzinfo(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def _parse_at(value, tz: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00").replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def schedule_sig(task: dict, tz_name: str) -> str:
    return hashlib.sha256(json.dumps([task.get("schedule"), tz_name], sort_keys=True, default=str)
                          .encode()).hexdigest()[:16]


def next_run(task: dict, tz_name: str, after: datetime, last_run: datetime | None = None) -> datetime | None:
    """Próximo disparo depois de `after` (aware). None = não há mais (uma vez já passou)."""
    tz = tzinfo(tz_name)
    sch = task.get("schedule") or {}
    kind = sch.get("type", "cron")
    if kind == "cron":
        return CronExpr(sch.get("expr", "")).next_after(after.astimezone(tz))
    if kind == "interval":
        minutes = int(sch.get("minutes") or 0)
        base = last_run or after
        nxt = base + timedelta(minutes=minutes)
        return nxt if nxt > after else after + timedelta(minutes=minutes)
    if kind == "once":
        at = _parse_at(sch.get("at"), tz)
        return at if at > after else None
    return None


def describe_schedule(task: dict) -> str:
    sch = task.get("schedule") or {}
    t = sch.get("type", "cron")
    if t == "interval":
        m = int(sch.get("minutes") or 0)
        return f"a cada {m // 60} h" if m % 60 == 0 and m >= 60 else f"a cada {m} min"
    if t == "once":
        return "uma vez em " + str(sch.get("at"))
    return "cron " + str(sch.get("expr"))


def preview(task: dict, tz_name: str, count: int = 5) -> list[str]:
    out, cur = [], datetime.now(tzinfo(tz_name))
    last = None
    for _ in range(count):
        nxt = next_run(task, tz_name, cur, last)
        if not nxt:
            break
        out.append(nxt.astimezone(tzinfo(tz_name)).isoformat(timespec="minutes"))
        cur, last = nxt, nxt
    return out


# --------------------------------------------------------------------------- #
# Validação + CRUD
# --------------------------------------------------------------------------- #
def slugify(name: str) -> str:
    import unicodedata  # noqa: PLC0415
    s = unicodedata.normalize("NFD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50]
    return s or "tarefa"


def _clean(task: dict, tz_name: str) -> dict:
    """Valida e devolve a tarefa normalizada (só campos conhecidos)."""
    errs = []
    name = str(task.get("name") or "").strip()
    if not name:
        errs.append({"loc": "name", "msg": "dê um nome à tarefa"})
    kind = task.get("kind")
    if kind not in KINDS:
        errs.append({"loc": "kind", "msg": "tipo deve ser script, agent ou hybrid"})
    script = str(task.get("script") or "").strip()
    prompt = str(task.get("prompt") or "").strip()
    if kind in ("script", "hybrid") and not script:
        errs.append({"loc": "script", "msg": "informe o comando/script a executar"})
    if kind in ("agent", "hybrid") and not prompt:
        errs.append({"loc": "prompt", "msg": "descreva o que o agente deve fazer"})
    sch = dict(task.get("schedule") or {})
    st = sch.get("type", "cron")
    clean_sch: dict = {"type": st}
    if st == "cron":
        try:
            CronExpr(str(sch.get("expr") or ""))
            clean_sch["expr"] = str(sch.get("expr")).strip()
        except CronError as e:
            errs.append({"loc": "schedule/expr", "msg": str(e)})
    elif st == "interval":
        try:
            m = int(sch.get("minutes"))
            if not 1 <= m <= 60 * 24 * 31:
                raise ValueError
            clean_sch["minutes"] = m
        except (TypeError, ValueError):
            errs.append({"loc": "schedule/minutes", "msg": "intervalo em minutos (1 a 44640)"})
    elif st == "once":
        try:
            at = _parse_at(sch.get("at"), tzinfo(tz_name))
            clean_sch["at"] = at.astimezone(tzinfo(tz_name)).isoformat(timespec="minutes")
        except (TypeError, ValueError):
            errs.append({"loc": "schedule/at", "msg": "data/hora inválida (use AAAA-MM-DDTHH:MM)"})
    else:
        errs.append({"loc": "schedule/type", "msg": "tipo de agendamento deve ser cron, interval ou once"})
    notify = task.get("notify") or "auto"
    if notify not in NOTIFY:
        errs.append({"loc": "notify", "msg": "notificação deve ser auto, always, failure ou never"})
    agent = dict(task.get("agent") or {})
    perm = agent.get("permissions") or "restricted"
    if perm not in PERMISSIONS:
        errs.append({"loc": "agent/permissions", "msg": "permissões devem ser restricted ou full"})
    try:
        timeout = int(task.get("timeout_min") or 15)
        if not 1 <= timeout <= 24 * 60:
            raise ValueError
    except (TypeError, ValueError):
        errs.append({"loc": "timeout_min", "msg": "tempo limite em minutos (1 a 1440)"})
        timeout = 15
    if errs:
        raise TaskError(errs)
    out = {
        "id": task.get("id"),
        "name": name,
        "description": str(task.get("description") or "").strip(),
        "enabled": bool(task.get("enabled", True)),
        "kind": kind,
        "schedule": clean_sch,
        "timeout_min": timeout,
        "notify": notify,
    }
    if kind in ("script", "hybrid"):
        out["script"] = script
    if kind in ("agent", "hybrid"):
        out["prompt"] = prompt
        out["agent"] = {"permissions": perm, "model": str(agent.get("model") or "").strip()}
    for k in ("created_at", "created_by"):
        if task.get(k):
            out[k] = task[k]
    return out


def _lock(root=None):
    return _flock(runs_dir(root) / ".tasks.lock")


def get_task(task_id: str, root=None) -> dict:
    for t in load(root)["config"]["tasks"]:
        if t.get("id") == task_id:
            return t
    raise KeyError(f"tarefa '{task_id}' não existe")


def resolve(ref: str, root=None) -> dict:
    """Aceita id exato ou nome (sem distinção de caixa). Nome ambíguo é recusado."""
    tasks = load(root)["config"]["tasks"]
    for t in tasks:
        if t.get("id") == ref:
            return t
    hits = [t for t in tasks if str(t.get("name", "")).lower() == str(ref).lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise TaskError([{"loc": "id", "msg": f"nome '{ref}' é ambíguo — use o id"}])
    raise KeyError(f"tarefa '{ref}' não existe")


def create_task(task: dict, rev: str | None = None, root=None, created_by: str = "ui") -> dict:
    if os.environ.get("NETOPS_SCHEDULED_RUN") == "1":
        raise TaskError([{"loc": "id", "msg": "uma tarefa agendada não pode criar outras tarefas"}])
    with _lock(root):
        data = load(root)
        cfg = data["config"]
        ids = {t.get("id") for t in cfg["tasks"]}
        tid = str(task.get("id") or "").strip() or slugify(task.get("name", ""))
        if not ID_RE.match(tid):
            raise TaskError([{"loc": "id", "msg": "id: minúsculas, números e hífen"}])
        base, i = tid, 2
        while tid in ids:
            tid, i = f"{base}-{i}", i + 1
        clean = _clean({**task, "id": tid}, cfg["timezone"])
        clean["created_at"] = datetime.now(tzinfo(cfg["timezone"])).isoformat(timespec="seconds")
        clean["created_by"] = task.get("created_by") or created_by
        cfg["tasks"].append(clean)
        new_rev = _save(cfg, rev, root)
    install_cron(root)
    return {"task": clean, "rev": new_rev}


def update_task(task_id: str, patch: dict, rev: str | None = None, root=None) -> dict:
    with _lock(root):
        data = load(root)
        cfg = data["config"]
        for i, t in enumerate(cfg["tasks"]):
            if t.get("id") == task_id:
                merged = {**t, **{k: v for k, v in patch.items() if k != "id"}, "id": task_id}
                if "agent" in patch and isinstance(t.get("agent"), dict):
                    merged["agent"] = {**t["agent"], **(patch.get("agent") or {})}
                clean = _clean(merged, cfg["timezone"])
                cfg["tasks"][i] = clean
                new_rev = _save(cfg, rev, root)
                break
        else:
            raise KeyError(f"tarefa '{task_id}' não existe")
    install_cron(root)
    return {"task": clean, "rev": new_rev}


def delete_task(task_id: str, rev: str | None = None, root=None) -> dict:
    with _lock(root):
        cfg = load(root)["config"]
        n = len(cfg["tasks"])
        cfg["tasks"] = [t for t in cfg["tasks"] if t.get("id") != task_id]
        if len(cfg["tasks"]) == n:
            raise KeyError(f"tarefa '{task_id}' não existe")
        new_rev = _save(cfg, rev, root)
    with edit_state(root) as st:
        st["tasks"].pop(task_id, None)
        st["unread"] = [u for u in st["unread"] if not u.startswith(task_id + "/")]
    install_cron(root)
    return {"rev": new_rev}


def set_timezone(name: str, rev: str | None = None, root=None) -> dict:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise TaskError([{"loc": "timezone", "msg": f"fuso desconhecido: {name}"}])
    with _lock(root):
        cfg = load(root)["config"]
        cfg["timezone"] = name
        return {"rev": _save(cfg, rev, root)}


# --------------------------------------------------------------------------- #
# Cron do sistema (uma linha: o despachante)
# --------------------------------------------------------------------------- #
def _python() -> str:
    venv = NETOPS_ROOT / ".venv" / "bin" / "python3"
    return str(venv if venv.exists() else "/usr/bin/python3")


def cron_text(root=None) -> str:
    import pwd  # noqa: PLC0415
    user = pwd.getpwuid(os.getuid()).pw_name
    r = data_root(root)
    cli = NETOPS_ROOT / "scripts" / "engine" / "scheduler" / "cli.py"
    path = f"{Path.home()}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    return (
        "# Gerado pelo NetOps (scripts/engine/scheduler). NÃO edite à mão: use o console\n"
        "# (menu Tarefas agendadas) ou scripts/engine/scheduler/cli.py. As tarefas ficam em\n"
        f"# {tasks_file(root)}; este despachante roda a cada minuto e dispara as que venceram.\n"
        "SHELL=/bin/bash\n"
        f"PATH={path}\n"
        f"* * * * * {user} {_python()} {cli} --data-root {r} tick >> {runs_dir(root)}/tick.log 2>&1\n"
    )


def install_cron(root=None) -> dict:
    """Garante a linha do despachante (idempotente). Falha de permissão não derruba o cadastro."""
    p = cron_file(root)
    want = cron_text(root)
    try:
        # o `>> runs/schedules/tick.log` da linha falha (e o tick nem roda) sem a pasta
        runs_dir(root).mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_text(encoding="utf-8") != want:
            _atomic_write(p, want, 0o644)
        return {"installed": True, "file": str(p)}
    except OSError as e:
        return {"installed": False, "file": str(p), "error": str(e)}


def cron_status(root=None) -> dict:
    p = cron_file(root)
    st = read_state(root)
    daemon = None
    if p.parent == Path("/etc/cron.d"):
        import subprocess  # noqa: PLC0415
        try:
            daemon = subprocess.run(["systemctl", "is-active", "cron"], capture_output=True, text=True,
                                    timeout=5).stdout.strip() == "active"
        except (OSError, subprocess.SubprocessError):
            daemon = None
    last_tick = st.get("last_tick")
    return {
        "file": str(p),
        "installed": p.exists() and p.read_text(encoding="utf-8") == cron_text(root),
        "daemon_active": daemon,
        "last_tick": last_tick,
        "healthy": bool(last_tick and time.time() - last_tick < 180),
        "line": cron_text(root).strip().splitlines()[-1],
    }
