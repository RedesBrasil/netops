#!/usr/bin/env python3
"""Central de Avisos — armazenamento das mensagens (SQLite em runs/inbox.db).

Uma mensagem é um de três tipos (`kind`):
  info      — informação ("backup concluído com 2 avisos")
  alert     — alerta que merece atenção (severity warning|critical)
  approval  — pedido de aprovação: fica `pending` até alguém aprovar/reprovar (ou expirar).
              Pode trazer uma AÇÃO que roda ao aprovar (`action`) e/ou ao reprovar (`reject_action`):
                {"type": "command", "command": "...", "timeout_min": 15}
                {"type": "agent", "prompt": "...", "resume": true, "permissions": "restricted|full"}
              A ação roda como o usuário do console (root) — por isso só admin decide pedido com ação.

Quem escreve: tarefas agendadas (runner), scripts e agentes via `inbox/cli.py`, o agente das tarefas
via bloco ```netops-inbox``` na resposta. Quem lê/decide: o console (menu e sino do topo).
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path

from lib import i18n

NETOPS_ROOT = Path(__file__).resolve().parents[3]

KINDS = ("info", "alert", "approval")
SEVERITIES = ("info", "warning", "critical")
STATUSES = ("pending", "approved", "rejected", "expired")
ACTION_TYPES = ("command", "agent")
TITLE_MAX = 200
BODY_MAX = 30_000
KEEP_ARCHIVED_DAYS = 90
MAX_MESSAGES = 5000

_COLS = ("id", "created_at", "updated_at", "kind", "severity", "title", "body", "source", "source_label",
         "task_id", "run_id", "session_id", "link", "dedupe_key", "occurrences", "status", "expires_at",
         "action", "reject_action", "decided_by", "decided_at", "decision_note", "result", "read_at",
         "read_by", "archived")
_JSON_COLS = ("action", "reject_action", "result")

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'script',
  source_label TEXT,
  task_id TEXT, run_id TEXT, session_id TEXT, link TEXT,
  dedupe_key TEXT,
  occurrences INTEGER NOT NULL DEFAULT 1,
  status TEXT,
  expires_at REAL,
  action TEXT, reject_action TEXT,
  decided_by TEXT, decided_at REAL, decision_note TEXT,
  result TEXT,
  read_at REAL, read_by TEXT,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_inbox_open ON messages(archived, read_at, status);
CREATE INDEX IF NOT EXISTS ix_inbox_dedupe ON messages(dedupe_key);
CREATE INDEX IF NOT EXISTS ix_inbox_run ON messages(task_id, run_id);
"""


class InboxError(ValueError):
    """Dado inválido (validação). `errors` = [{"loc", "msg"}] como no resto do console."""

    def __init__(self, errors):
        super().__init__("; ".join(f"{e['loc']}: {e['msg']}" for e in errors))
        self.errors = errors


class NotPending(Exception):
    """Decisão sobre pedido que não está mais pendente (outro operador decidiu, ou expirou)."""


# --------------------------------------------------------------------------- #
def data_root(root=None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(os.environ.get("NETOPS_UI_DATA_ROOT") or NETOPS_ROOT).resolve()


def db_path(root=None) -> Path:
    return data_root(root) / "runs" / "inbox.db"


@contextlib.contextmanager
def _db(root=None):
    p = db_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    con = sqlite3.connect(str(p), timeout=15)
    try:
        if new:
            os.chmod(p, 0o600)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=15000")
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = {k: r[k] for k in r.keys()}
    for k in _JSON_COLS:
        try:
            d[k] = json.loads(d[k]) if d[k] else None
        except ValueError:
            d[k] = None
    d["archived"] = bool(d["archived"])
    d["unread"] = d["read_at"] is None
    d["actionable"] = bool(d["action"] or d["reject_action"])
    return d


def _expire(con, now: float) -> None:
    con.execute("UPDATE messages SET status='expired', updated_at=? "
                "WHERE status='pending' AND expires_at IS NOT NULL AND expires_at < ?", (now, now))


# --------------------------------------------------------------------------- #
# Validação
# --------------------------------------------------------------------------- #
def _validate_action(a, loc: str, errors: list) -> dict | None:
    if a in (None, "", {}):
        return None
    if not isinstance(a, dict):
        errors.append({"loc": loc, "msg": i18n.t("lib_inbox.action_not_object")})
        return None
    t = a.get("type")
    if t not in ACTION_TYPES:
        errors.append({"loc": f"{loc}/type", "msg": i18n.t("lib_inbox.use_one_of", options=', '.join(ACTION_TYPES))})
        return None
    out: dict = {"type": t}
    if t == "command":
        cmd = str(a.get("command") or "").strip()
        if not cmd:
            errors.append({"loc": f"{loc}/command", "msg": i18n.t("lib_inbox.empty_command")})
        out["command"] = cmd
    else:
        out["prompt"] = str(a.get("prompt") or "").strip()
        out["resume"] = a.get("resume", True) is not False
        perm = a.get("permissions") or "restricted"
        if perm not in ("restricted", "full"):
            errors.append({"loc": f"{loc}/permissions", "msg": i18n.t("lib_inbox.use_restricted_full")})
        out["permissions"] = perm
        if a.get("model"):
            out["model"] = str(a["model"])
    try:
        tmo = int(a.get("timeout_min") or 15)
    except (TypeError, ValueError):
        tmo = 15
    out["timeout_min"] = min(max(tmo, 1), 240)
    if a.get("label"):
        out["label"] = str(a["label"])[:120]
    return out


def _clean(msg: dict) -> dict:
    errors: list = []
    kind = msg.get("kind") or "info"
    if kind not in KINDS:
        errors.append({"loc": "kind", "msg": i18n.t("lib_inbox.use_one_of", options=', '.join(KINDS))})
    sev = msg.get("severity") or ("info" if kind == "info" else "warning")
    if sev not in SEVERITIES:
        errors.append({"loc": "severity", "msg": i18n.t("lib_inbox.use_one_of", options=', '.join(SEVERITIES))})
    title = " ".join(str(msg.get("title") or "").split())
    if not title:
        errors.append({"loc": "title", "msg": i18n.t("lib_inbox.title_required")})
    body = str(msg.get("body") or "")
    action = _validate_action(msg.get("action"), "action", errors)
    reject_action = _validate_action(msg.get("reject_action"), "reject_action", errors)
    if (action or reject_action) and kind != "approval":
        errors.append({"loc": "action", "msg": i18n.t("lib_inbox.action_only_approval")})
    if action and action["type"] == "agent" and not (action.get("prompt") or msg.get("session_id")):
        errors.append({"loc": "action/prompt", "msg": i18n.t("lib_inbox.agent_action_needs_prompt")})
    expires_at = msg.get("expires_at")
    if expires_at not in (None, ""):
        try:
            expires_at = float(expires_at)
        except (TypeError, ValueError):
            errors.append({"loc": "expires_at", "msg": i18n.t("lib_inbox.invalid_timestamp")})
    else:
        expires_at = None
    if errors:
        raise InboxError(errors)
    return {
        "kind": kind, "severity": sev, "title": title[:TITLE_MAX],
        "body": body if len(body) <= BODY_MAX else body[:BODY_MAX] + "\n\n…[truncado]",
        "source": str(msg.get("source") or "script")[:40],
        "source_label": (str(msg["source_label"])[:120] if msg.get("source_label") else None),
        "task_id": msg.get("task_id") or None, "run_id": msg.get("run_id") or None,
        "session_id": msg.get("session_id") or None,
        "link": (str(msg["link"])[:500] if msg.get("link") else None),
        "dedupe_key": (str(msg["dedupe_key"])[:200] if msg.get("dedupe_key") else None),
        "status": "pending" if kind == "approval" else None,
        "expires_at": expires_at if kind == "approval" else None,
        "action": json.dumps(action, ensure_ascii=False) if action else None,
        "reject_action": json.dumps(reject_action, ensure_ascii=False) if reject_action else None,
    }


# --------------------------------------------------------------------------- #
# Escrita
# --------------------------------------------------------------------------- #
def add(msg: dict, root=None) -> dict:
    """Cria a mensagem (ou atualiza a aberta com o mesmo `dedupe_key`). Devolve o registro."""
    c = _clean(msg)
    now = time.time()
    with _db(root) as con:
        if c["dedupe_key"]:
            hit = con.execute("SELECT id FROM messages WHERE dedupe_key=? AND archived=0 AND "
                              "(status IS NULL OR status='pending') ORDER BY id DESC LIMIT 1",
                              (c["dedupe_key"],)).fetchone()
            if hit:
                con.execute("UPDATE messages SET title=?, body=?, severity=?, updated_at=?, occurrences=occurrences+1,"
                            " read_at=NULL, read_by=NULL, run_id=COALESCE(?, run_id), session_id=COALESCE(?, session_id),"
                            " link=COALESCE(?, link) WHERE id=?",
                            (c["title"], c["body"], c["severity"], now, c["run_id"], c["session_id"], c["link"], hit["id"]))
                return _row(con.execute("SELECT * FROM messages WHERE id=?", (hit["id"],)).fetchone())
        cols = ["created_at", "updated_at", *c.keys()]
        cur = con.execute(f"INSERT INTO messages ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                          (now, now, *c.values()))
        mid = cur.lastrowid
        _prune(con, now)
        return _row(con.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone())


def _prune(con, now: float) -> None:
    con.execute("DELETE FROM messages WHERE archived=1 AND updated_at < ?", (now - KEEP_ARCHIVED_DAYS * 86400,))
    n = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if n > MAX_MESSAGES:   # descarta as mais antigas já resolvidas (nunca pedido pendente)
        con.execute("DELETE FROM messages WHERE id IN (SELECT id FROM messages WHERE (status IS NULL OR status!='pending')"
                    " ORDER BY archived DESC, id ASC LIMIT ?)", (n - MAX_MESSAGES,))


def mark_read(ids: list[int] | None, user: str = "", root=None) -> list[tuple[str, str]]:
    """ids=None marca todas. Devolve os (tarefa, execução) afetados (p/ sincronizar com as tarefas agendadas)."""
    now = time.time()
    with _db(root) as con:
        if ids is None:
            rows = con.execute("SELECT id, task_id, run_id FROM messages WHERE read_at IS NULL").fetchall()
        else:
            ids = [int(i) for i in ids][:1000]
            if not ids:
                return []
            rows = con.execute(f"SELECT id, task_id, run_id FROM messages WHERE read_at IS NULL AND id IN "
                               f"({', '.join('?' * len(ids))})", ids).fetchall()
        con.executemany("UPDATE messages SET read_at=?, read_by=? WHERE id=?", [(now, user or None, r["id"]) for r in rows])
    runs = [(r["task_id"], r["run_id"]) for r in rows if r["task_id"] and r["run_id"]]
    _sync_schedule_read(runs, root)
    return runs


def _sync_schedule_read(runs: list[tuple[str, str]], root=None) -> None:
    """Lida aqui = lida também no histórico de execuções das tarefas agendadas."""
    if not runs:
        return
    try:
        from scheduler import store as sstore  # noqa: PLC0415
        keys = {f"{t}/{r}" for t, r in runs}
        with sstore.edit_state(root) as st:
            st["unread"] = [u for u in st["unread"] if u not in keys]
    except Exception:  # noqa: BLE001 — sincronização nunca derruba a leitura
        pass


def mark_read_runs(keys: list[str] | None, root=None) -> None:
    """Chamado pelas tarefas agendadas ao marcar execuções como lidas (keys=None = todas)."""
    now = time.time()
    with _db(root) as con:
        if keys is None:
            con.execute("UPDATE messages SET read_at=? WHERE read_at IS NULL AND run_id IS NOT NULL", (now,))
            return
        for k in keys:
            t, _, r = str(k).partition("/")
            con.execute("UPDATE messages SET read_at=? WHERE read_at IS NULL AND task_id=? AND run_id=?", (now, t, r))


def mark_unread(mid: int, root=None) -> dict:
    with _db(root) as con:
        con.execute("UPDATE messages SET read_at=NULL, read_by=NULL WHERE id=?", (int(mid),))
        return _require(con, mid)


def set_archived(ids: list[int], archived: bool = True, user: str = "", root=None) -> int:
    """Arquivar = sai da caixa (some do contador). Pedido pendente não arquiva: decida primeiro."""
    now = time.time()
    ids = [int(i) for i in ids][:1000]
    if not ids:
        return 0
    with _db(root) as con:
        q = f"id IN ({', '.join('?' * len(ids))})"
        if archived:
            cur = con.execute(f"UPDATE messages SET archived=1, updated_at=?, read_at=COALESCE(read_at, ?),"
                              f" read_by=COALESCE(read_by, ?) WHERE {q} AND (status IS NULL OR status!='pending')",
                              (now, now, user or None, *ids))
        else:
            cur = con.execute(f"UPDATE messages SET archived=0, updated_at=? WHERE {q}", (now, *ids))
        return cur.rowcount


def archive_read(user: str = "", root=None) -> int:
    """Arquiva tudo que já foi lido e não está pendente (limpar a caixa)."""
    with _db(root) as con:
        cur = con.execute("UPDATE messages SET archived=1, updated_at=? WHERE archived=0 AND read_at IS NOT NULL "
                          "AND (status IS NULL OR status!='pending')", (time.time(),))
        return cur.rowcount


def decide(mid: int, decision: str, user: str, note: str = "", root=None) -> dict:
    """approve|reject atômico: só o primeiro a decidir vence. Devolve o registro já decidido."""
    if decision not in ("approve", "reject"):
        raise InboxError([{"loc": "decision", "msg": i18n.t("lib_inbox.use_approve_reject")}])
    now = time.time()
    status = "approved" if decision == "approve" else "rejected"
    with _db(root) as con:
        _expire(con, now)
        cur = con.execute("UPDATE messages SET status=?, decided_by=?, decided_at=?, decision_note=?, updated_at=?,"
                          " read_at=COALESCE(read_at, ?), read_by=COALESCE(read_by, ?)"
                          " WHERE id=? AND kind='approval' AND status='pending'",
                          (status, user or None, now, (note or "").strip()[:4000] or None, now, now, user or None, int(mid)))
        rec = _require(con, mid)
        if cur.rowcount == 0:
            raise NotPending(i18n.t("lib_inbox.not_pending", id=mid, status=rec.get('status') or rec['kind']))
        return rec


def set_result(mid: int, result: dict, unread: bool = False, root=None) -> None:
    with _db(root) as con:
        if unread:   # resultado da ação chegou: volta a aparecer no sino
            con.execute("UPDATE messages SET result=?, updated_at=?, read_at=NULL, read_by=NULL WHERE id=?",
                        (json.dumps(result, ensure_ascii=False), time.time(), int(mid)))
        else:
            con.execute("UPDATE messages SET result=?, updated_at=? WHERE id=?",
                        (json.dumps(result, ensure_ascii=False), time.time(), int(mid)))


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #
def _require(con, mid) -> dict:
    r = _row(con.execute("SELECT * FROM messages WHERE id=?", (int(mid),)).fetchone())
    if r is None:
        raise KeyError(i18n.t("lib_inbox.not_found", id=mid))
    return r


def get(mid: int, root=None) -> dict:
    with _db(root) as con:
        _expire(con, time.time())
        return _require(con, mid)


VIEWS = ("open", "pending", "unread", "alerts", "all", "archived")


def list_messages(view: str = "open", limit: int = 500, root=None) -> list[dict]:
    """open = caixa (não arquivadas); pending = pedidos aguardando; unread; alerts; all; archived."""
    where = {
        "open": "archived=0",
        "pending": "status='pending'",
        "unread": "archived=0 AND read_at IS NULL",
        "alerts": "archived=0 AND kind='alert'",
        "all": "1=1",
        "archived": "archived=1",
    }.get(view, "archived=0")
    with _db(root) as con:
        _expire(con, time.time())
        rows = con.execute(f"SELECT * FROM messages WHERE {where} ORDER BY "
                           f"(status='pending') DESC, updated_at DESC LIMIT ?", (min(max(int(limit), 1), 2000),)).fetchall()
    out = []
    for r in rows:
        d = _row(r)
        d["body_excerpt"] = " ".join((d.pop("body") or "").split())[:240]
        out.append(d)
    return out


def summary(root=None) -> dict:
    """Contadores do sino: badge = não lidas ∪ pedidos pendentes (pendente conta até ser decidido)."""
    with _db(root) as con:
        _expire(con, time.time())
        r = con.execute("""SELECT
            SUM(CASE WHEN archived=0 AND read_at IS NULL THEN 1 ELSE 0 END) AS unread,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN archived=0 AND (read_at IS NULL OR status='pending') THEN 1 ELSE 0 END) AS badge,
            SUM(CASE WHEN archived=0 AND read_at IS NULL AND severity='critical' THEN 1 ELSE 0 END) AS critical
            FROM messages""").fetchone()
    return {k: int(r[k] or 0) for k in ("unread", "pending", "badge", "critical")}
