#!/usr/bin/env python3
"""Banco de acesso do NetOps (SQLite): usuários, grupos de acesso, sessões de login, auditoria.

Por que SQLite aqui e arquivo no resto: isto é ESTADO DO SISTEMA (escrito a cada login/request por
vários processos, precisa de transação e de consulta), não contexto do agente. O que a IA lê e edita
(inventário, skills, memória, workflows) continua em arquivo. Ver
reports/20261116-plano-multiusuario-grupos-acesso.md.

Arquivo: <DATA_ROOT>/runs/netops.db (git-ignorado, 0600, modo WAL). Nunca copie o .db com o console
no ar: use `snapshot()` (API de backup do SQLite) — `scripts/engine/users/cli.py snapshot <destino>`.

Login = E-MAIL (único, minúsculo). `username` é o ID interno estável (derivado do e-mail; usado na
auditoria, no dono das conversas e no CLI) — trocar o e-mail não quebra o histórico.

Senha de usuário: o MESMO esquema do cofre (lib/vault.build_meta: Argon2id + verifier). A chave
derivada da senha do usuário também embrulha a chave do cofre ("keyslot"), então o login de cada
usuário destranca o cofre sem ninguém conhecer a senha-mestra. A senha nunca é gravada.

API (todas recebem `db` = caminho do arquivo):
  usuários:  has_users, list_users, get_user, create_user, update_user, set_password, delete_user,
             verify_password, set_vault_slot, unwrap_vault_slot, active_admins
  grupos:    list_groups, get_group, create_group, update_group, delete_group
  efetivo:   effective(db, username) -> {"permissions": set, "net_perms": list, "is_admin": bool, ...}
  sessões:   create_session, session_user, drop_session, drop_user_sessions, clear_sessions, list_sessions
  throttle:  login_wait, login_failed, login_ok
  auditoria: audit, query_audit, prune_audit
  claude:    set_claude_owner, claude_owner, claude_owners
  backup:    snapshot
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from lib import i18n

SCHEMA_VERSION = 2
ADMIN_GROUP = "admin"
NET_PERMS = ("read", "create", "edit", "delete")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GROUPNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
PASSWORD_MIN = 8

# Catálogo de permissões (fonte única; services/authz.py mapeia rota -> permissão).
# admin_only = só o grupo admin ("*") tem; não aparece no editor de grupos.
PERMISSIONS: list[dict] = [
    {"key": "hosts.view", "label": "Ver hosts, grupos de host e mapas", "area": "Inventário"},
    {"key": "hosts.edit", "label": "Editar hosts, grupos de host, mapas e topologia", "area": "Inventário"},
    {"key": "credentials.view", "label": "Ver credenciais (nunca o segredo)", "area": "Inventário"},
    {"key": "credentials.edit", "label": "Criar/editar credenciais e trancar o cofre", "area": "Inventário"},
    {"key": "vault.view", "label": "Ver o Cofre de senhas (campos em texto; segredos mascarados)", "area": "Inventário"},
    {"key": "vault.reveal", "label": "Revelar/copiar segredos do Cofre de senhas (cofre destrancado)", "area": "Inventário"},
    {"key": "vault.use", "label": "Usar segredos do Cofre de senhas em comandos e na IA, sem ver o valor (nvault://, cofre destrancado)", "area": "Inventário"},
    {"key": "vault.edit", "label": "Criar/editar/excluir itens do Cofre de senhas", "area": "Inventário"},
    {"key": "vault.templates", "label": "Gerenciar templates e campos do Cofre de senhas", "area": "Inventário"},
    {"key": "knowledge.view", "label": "Ver memória, boas práticas, workflows, agentes, relatórios e execuções", "area": "Conhecimento"},
    {"key": "knowledge.edit", "label": "Editar memória, boas práticas, workflows e agentes", "area": "Conhecimento"},
    {"key": "scripts.view", "label": "Ver scripts / skills", "area": "Conhecimento"},
    {"key": "scripts.edit", "label": "Editar scripts / skills (código que roda com a conta do servidor)", "area": "Administração", "admin_only": True},
    {"key": "backups.view", "label": "Ver backups de equipamentos", "area": "Operação"},
    {"key": "backups.run", "label": "Disparar backup agora", "area": "Operação"},
    {"key": "backups.edit", "label": "Configurar backups e apagar arquivos de backup", "area": "Operação"},
    {"key": "schedules.view", "label": "Ver tarefas agendadas", "area": "Operação"},
    {"key": "schedules.run", "label": "Rodar agora uma tarefa agendada existente", "area": "Operação"},
    {"key": "schedules.edit", "label": "Criar/editar tarefas agendadas (rodam com a conta do servidor)", "area": "Administração", "admin_only": True},
    {"key": "inbox.view", "label": "Ver a Central de Avisos (alertas, avisos e pedidos de aprovação)", "area": "Operação"},
    {"key": "inbox.decide", "label": "Aprovar/reprovar pedidos e arquivar avisos (pedido que roda ação no servidor = só admin)", "area": "Operação"},
    {"key": "dashboard.view", "label": "Ver o Painel (servidor e uso de IA)", "area": "Operação"},
    {"key": "host.terminal", "label": "Terminal SSH/Telnet dos hosts", "area": "Acesso a equipamento"},
    {"key": "host.files", "label": "Arquivos (SFTP) dos hosts", "area": "Acesso a equipamento"},
    {"key": "host.web", "label": "Abrir a web do host com login automático", "area": "Acesso a equipamento"},
    {"key": "claude.use", "label": "Usar a aba Claude Code (limitada pelas permissões de rede do grupo)", "area": "IA"},
    {"key": "projects.files", "label": "Arquivos dos Projetos (ver/editar só dentro da pasta de cada projeto)", "area": "IA"},
    {"key": "projects.create", "label": "Criar Projetos numa pasta nova da base padrão (quem cria vira dono)", "area": "IA"},
    {"key": "projects.manage", "label": "Criar/remover Projetos e escolher a pasta do servidor onde o agente roda", "area": "Administração", "admin_only": True},
    {"key": "server.terminal", "label": "Terminal do servidor NetOps", "area": "Administração", "admin_only": True},
    {"key": "server.files", "label": "Arquivos do servidor NetOps", "area": "Administração", "admin_only": True},
    {"key": "server.admin", "label": "Administração Local (root) deste servidor — host Local e Arquivos como root", "area": "Administração", "admin_only": True},
    {"key": "config", "label": "Configuração do console, acesso web, conta Claude e ditado", "area": "Administração", "admin_only": True},
    {"key": "updates", "label": "Atualizar o NetOps", "area": "Administração", "admin_only": True},
    {"key": "users.manage", "label": "Usuários e grupos de acesso", "area": "Administração", "admin_only": True},
    {"key": "audit.view", "label": "Auditoria", "area": "Administração", "admin_only": True},
]
PERM_KEYS = {p["key"] for p in PERMISSIONS}

_AREA_KEYS = {"Inventário": "area_inventory", "Conhecimento": "area_knowledge", "Administração": "area_administration",
              "Operação": "area_operations", "Acesso a equipamento": "area_device_access", "IA": "area_ai"}


def localized_permissions(lang: str | None = None) -> list[dict]:
    """PERMISSIONS with label/area in the requested (or current) language (core/locales/*/perm.json)."""
    from lib import i18n  # noqa: PLC0415
    out = []
    for p in PERMISSIONS:
        q = dict(p)
        lbl = i18n.t("perm." + p["key"], lang)
        q["label"] = p["label"] if lbl == "perm." + p["key"] else lbl
        ak = _AREA_KEYS.get(p["area"])
        if ak:
            area = i18n.t("perm." + ak, lang)
            q["area"] = p["area"] if area == "perm." + ak else area
        out.append(q)
    return out
ADMIN_ONLY = {p["key"] for p in PERMISSIONS if p.get("admin_only")}
GRANTABLE = PERM_KEYS - ADMIN_ONLY

# Grupos criados na primeira abertura do banco (só o admin é fixo; os outros são sugestões editáveis).
DEFAULT_GROUPS = [
    {"name": ADMIN_GROUP, "description": "Administradores: acesso total ao console e ao servidor.",
     "builtin": True, "permissions": ["*"], "net_perms": list(NET_PERMS)},
    {"name": "operador", "description": "Operação de rede: acessa equipamentos, roda backups e usa a IA.",
     "builtin": False, "net_perms": ["read", "create", "edit"],
     "permissions": ["hosts.view", "credentials.view", "vault.view", "vault.reveal", "vault.use", "knowledge.view", "knowledge.edit", "scripts.view",
                     "backups.view", "backups.run", "schedules.view", "schedules.run", "inbox.view", "inbox.decide", "dashboard.view",
                     "host.terminal", "host.files", "host.web", "claude.use"]},
    {"name": "leitura", "description": "Somente consulta: inventário, conhecimento, backups e tarefas.",
     "builtin": False, "net_perms": ["read"],
     "permissions": ["hosts.view", "knowledge.view", "scripts.view", "backups.view", "schedules.view",
                     "inbox.view", "dashboard.view"]},
]

# Throttle de login: a partir de THROTTLE_FREE falhas seguidas, espera crescente (cap THROTTLE_MAX s).
THROTTLE_FREE = 5
THROTTLE_BASE = 15
THROTTLE_MAX = 15 * 60
THROTTLE_FORGET = 24 * 3600
SESSION_TOUCH_EVERY = 60


class AccessError(Exception):
    """Erro de domínio (vira 4xx no console). `code` é estável p/ o front."""

    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


class Conflict(AccessError):
    def __init__(self, detail: str | None = None):
        super().__init__("conflict", detail or i18n.t("lib_accessdb.conflict"), 409)


class NotFound(AccessError):
    def __init__(self, detail: str):
        super().__init__("not_found", detail, 404)


class WrongPassword(AccessError):
    def __init__(self):
        super().__init__("bad_credentials", i18n.t("lib_accessdb.bad_credentials"), 401)


# --------------------------------------------------------------------------- #
# Conexão + migração
# --------------------------------------------------------------------------- #
_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY,
  display_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  pw TEXT NOT NULL,
  vault_slot TEXT,
  disabled INTEGER NOT NULL DEFAULT 0,
  must_change INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  created_by TEXT NOT NULL DEFAULT '',
  updated_at REAL NOT NULL,
  pw_changed_at REAL,
  last_login REAL,
  last_ip TEXT NOT NULL DEFAULT '',
  rev INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS access_groups(
  name TEXT PRIMARY KEY,
  description TEXT NOT NULL DEFAULT '',
  builtin INTEGER NOT NULL DEFAULT 0,
  permissions TEXT NOT NULL DEFAULT '[]',
  net_perms TEXT NOT NULL DEFAULT '["read"]',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS user_groups(
  username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  group_name TEXT NOT NULL REFERENCES access_groups(name) ON DELETE CASCADE,
  PRIMARY KEY(username, group_name)
);
CREATE TABLE IF NOT EXISTS sessions(
  sid_hash TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  created_at REAL NOT NULL,
  exp REAL NOT NULL,
  last_seen REAL NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(username);
CREATE TABLE IF NOT EXISTS login_failures(
  key TEXT PRIMARY KEY,
  failures INTEGER NOT NULL,
  last_fail REAL NOT NULL,
  locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  username TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  method TEXT NOT NULL DEFAULT '',
  path TEXT NOT NULL DEFAULT '',
  target TEXT NOT NULL DEFAULT '',
  status INTEGER,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS audit_user_ts ON audit(username, ts);
CREATE TABLE IF NOT EXISTS claude_owners(
  session_id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS claude_owners_user ON claude_owners(username);
CREATE TABLE IF NOT EXISTS claude_msg_authors(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  username TEXT NOT NULL,
  text TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS claude_msg_authors_sid ON claude_msg_authors(session_id, id);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

# Tabelas ADITIVAS (só acrescentam; versão antiga do NetOps as ignora): criadas em TODO banco, qualquer que seja o
# user_version. Entrar só no _SCHEMA_V1 não basta: banco já em v1/v2 nunca roda o V1 de novo (bug 2.6.1→: a tabela
# claude_msg_authors faltava em instalação existente e apagar conversa dava "no such table"). Não sobe o
# SCHEMA_VERSION de propósito: subir faria a versão anterior recusar o banco (db_too_new) num downgrade.
_ADDITIVE = (
    """CREATE TABLE IF NOT EXISTS claude_msg_authors(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  username TEXT NOT NULL,
  text TEXT NOT NULL,
  ts REAL NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS claude_msg_authors_sid ON claude_msg_authors(session_id, id)",
    # Project sharing (owner + users/groups with a level). FK with CASCADE: deleting a user/group (also via the
    # CLI) removes its access, so re-creating the same username never inherits old access.
    """CREATE TABLE IF NOT EXISTS project_shares(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  username TEXT REFERENCES users(username) ON DELETE CASCADE,
  group_name TEXT REFERENCES access_groups(name) ON DELETE CASCADE,
  level TEXT NOT NULL CHECK(level IN ('view','participate','manage','owner')),
  granted_by TEXT NOT NULL DEFAULT '',
  granted_at REAL NOT NULL,
  CHECK ((username IS NULL) <> (group_name IS NULL)),
  CHECK (level <> 'owner' OR username IS NOT NULL)
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS project_shares_user ON project_shares(project_id, username) WHERE username IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS project_shares_group ON project_shares(project_id, group_name) WHERE group_name IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS project_shares_owner ON project_shares(project_id) WHERE level = 'owner'",
    "CREATE TABLE IF NOT EXISTS project_meta(project_id TEXT PRIMARY KEY, rev INTEGER NOT NULL DEFAULT 1)",
)

_init_lock = threading.Lock()
_initialized: set[tuple] = set()


def _ident(path: Path) -> tuple:
    try:
        st = path.stat()
        return (str(path), st.st_ino, st.st_dev)
    except OSError:
        return (str(path), None, None)


def _raw_connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure(path: Path) -> None:
    """Cria (0600) e migra o banco uma vez por processo/arquivo."""
    key = _ident(path)
    if key in _initialized and key[1] is not None:
        return
    with _init_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd = os.open(str(path), os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        conn = _raw_connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            if ver < 1:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    # executescript faria COMMIT implícito; um statement por vez fica na transação.
                    for stmt in _SCHEMA_V1.split(";"):
                        if stmt.strip():
                            conn.execute(stmt)
                    now = time.time()
                    for g in DEFAULT_GROUPS:
                        conn.execute(
                            "INSERT OR IGNORE INTO access_groups(name, description, builtin, permissions, net_perms,"
                            " created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                            (g["name"], g["description"], int(g["builtin"]), json.dumps(g["permissions"]),
                             json.dumps(g["net_perms"]), now, now))
                    conn.execute("PRAGMA user_version=1")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                ver = 1
            if ver < 2:
                # v2: login por E-MAIL — e-mail normalizado (minúsculo) e único quando preenchido.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute("UPDATE users SET email=lower(trim(email))")
                    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email) WHERE email<>''")
                    conn.execute("PRAGMA user_version=2")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            elif ver > SCHEMA_VERSION:
                raise AccessError("db_too_new", i18n.t("lib_accessdb.db_too_new", ver=ver, current=SCHEMA_VERSION), 500)
            for stmt in _ADDITIVE:
                conn.execute(stmt)
        finally:
            conn.close()
        _initialized.add(_ident(path))


@contextmanager
def connect(db: Path | str, write: bool = False):
    """Conexão curta (uma por operação). write=True abre BEGIN IMMEDIATE (trava de escrita do SQLite)."""
    path = Path(db)
    _ensure(path)
    conn = _raw_connect(path)
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
        else:
            yield conn
    finally:
        conn.close()


def _j(text, default):
    try:
        v = json.loads(text) if text else default
    except ValueError:
        return default
    return v


# --------------------------------------------------------------------------- #
# Senha (mesmo esquema do cofre) + keyslot da chave do cofre
# --------------------------------------------------------------------------- #
def _vault():
    from lib import vault  # noqa: PLC0415
    return vault


def check_password_policy(password: str) -> None:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN:
        raise AccessError("weak_password", i18n.t("lib_accessdb.weak_password", min=PASSWORD_MIN), 422)


def _hash_password(password: str) -> tuple[str, bytes]:
    meta, key = _vault().build_meta(password)
    return json.dumps(meta), key


def _check(pw_json: str, password: str) -> bytes:
    """Devolve a chave derivada da senha (KEK) ou levanta WrongPassword."""
    v = _vault()
    meta = _j(pw_json, {})
    try:
        key = v.derive_key(password, meta)
        v.verify_key(key, meta)
    except Exception as exc:  # VaultWrongKey / meta corrompida
        raise WrongPassword() from exc
    return key


def wrap_vault_key(kek: bytes, vault_key: bytes) -> str:
    v = _vault()
    from lib import vault_session  # noqa: PLC0415
    return v.encrypt_value(kek, vault_session.encode_key(vault_key))


def unwrap_vault_key(kek: bytes, slot: str) -> bytes:
    v = _vault()
    from lib import vault_session  # noqa: PLC0415
    return vault_session.decode_key(v.decrypt_value(kek, slot))


# --------------------------------------------------------------------------- #
# Usuários
# --------------------------------------------------------------------------- #
def norm_username(username: str) -> str:
    u = (username or "").strip().lower()
    if not USERNAME_RE.match(u):
        raise AccessError("invalid_username",
                          i18n.t("lib_accessdb.invalid_username"), 422)
    return u


def norm_email(email: str | None, required: bool = False) -> str:
    e = (email or "").strip().lower()
    if not e:
        if required:
            raise AccessError("email_required", i18n.t("lib_accessdb.email_required"), 422)
        return ""
    if len(e) > 120 or not EMAIL_RE.match(e):
        raise AccessError("invalid_email", i18n.t("lib_accessdb.invalid_email", email=email), 422)
    return e


def _email_taken(conn, email: str, exclude: str | None = None) -> bool:
    if not email:
        return False
    r = conn.execute("SELECT username FROM users WHERE email=?", (email,)).fetchone()
    return bool(r) and r[0] != exclude


def _derive_username(conn, email: str) -> str:
    """ID interno estável a partir do e-mail (joao.silva@x.com -> joao.silva; repetido -> joao.silva-2)."""
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0].lower()).strip("._-")[:28] or "usuario"
    if len(base) < 2 or not base[0].isalnum():
        base = ("u" + base)[:28]
    cand, i = base, 2
    while conn.execute("SELECT 1 FROM users WHERE username=?", (cand,)).fetchone():
        cand, i = f"{base}-{i}", i + 1
    return cand


def _login_row(conn, identifier: str):
    """Linha do usuário pelo LOGIN: e-mail (padrão) ou o ID interno (admin migrado, CLI, scripts)."""
    ident = (identifier or "").strip().lower()
    if not ident:
        return None
    if "@" in ident:
        return conn.execute("SELECT * FROM users WHERE email=?", (ident,)).fetchone()
    return _user_row(conn, ident)


def login_username(db, identifier: str) -> str | None:
    with connect(db) as c:
        row = _login_row(c, identifier)
        return row["username"] if row else None


def _user_row(conn, username: str):
    return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def _groups_of(conn, username: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT group_name FROM user_groups WHERE username=? ORDER BY group_name", (username,))]


def _public_user(conn, row) -> dict:
    now = time.time()
    sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE username=? AND exp>?",
                            (row["username"], now)).fetchone()[0]
    return {
        "username": row["username"], "display_name": row["display_name"], "email": row["email"],
        "groups": _groups_of(conn, row["username"]), "disabled": bool(row["disabled"]),
        "must_change_password": bool(row["must_change"]), "vault_slot": bool(row["vault_slot"]),
        "created_at": row["created_at"], "created_by": row["created_by"], "updated_at": row["updated_at"],
        "password_changed_at": row["pw_changed_at"], "last_login": row["last_login"], "last_ip": row["last_ip"],
        "sessions": sessions, "rev": str(row["rev"]),
    }


def has_users(db) -> bool:
    with connect(db) as c:
        return c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def list_users(db) -> list[dict]:
    with connect(db) as c:
        return [_public_user(c, r) for r in c.execute("SELECT * FROM users ORDER BY username")]


def get_user(db, username: str) -> dict | None:
    with connect(db) as c:
        row = _user_row(c, (username or "").strip().lower())
        return _public_user(c, row) if row else None


def _admins_active(conn, exclude: str | None = None) -> int:
    q = ("SELECT COUNT(*) FROM users u JOIN user_groups g ON g.username=u.username "
         "WHERE g.group_name=? AND u.disabled=0")
    args: list = [ADMIN_GROUP]
    if exclude:
        q += " AND u.username<>?"
        args.append(exclude)
    return conn.execute(q, args).fetchone()[0]


def active_admins(db) -> int:
    with connect(db) as c:
        return _admins_active(c)


def _set_groups(conn, username: str, groups) -> None:
    groups = sorted({str(g).strip().lower() for g in (groups or []) if str(g).strip()})
    for g in groups:
        if not conn.execute("SELECT 1 FROM access_groups WHERE name=?", (g,)).fetchone():
            raise AccessError("unknown_group", i18n.t("lib_accessdb.unknown_group", group=g), 422)
    conn.execute("DELETE FROM user_groups WHERE username=?", (username,))
    conn.executemany("INSERT INTO user_groups(username, group_name) VALUES(?,?)", [(username, g) for g in groups])


def create_user(db, username: str | None, password: str, *, display_name: str = "", email: str = "",
                groups=(), must_change: bool = False, created_by: str = "",
                vault_key: bytes | None = None, require_email: bool = False) -> dict:
    """Login = e-mail. `username` (ID interno) é opcional: sem ele, deriva do e-mail."""
    email = norm_email(email, required=require_email or not username)
    username = norm_username(username) if username else None
    check_password_policy(password)
    pw_json, kek = _hash_password(password)
    slot = wrap_vault_key(kek, vault_key) if vault_key else None
    now = time.time()
    with connect(db, write=True) as c:
        if _email_taken(c, email):
            raise AccessError("exists", i18n.t("lib_accessdb.email_exists", email=email), 409)
        if username is None:
            username = _derive_username(c, email)
        if _user_row(c, username):
            raise AccessError("exists", i18n.t("lib_accessdb.user_exists", username=username), 409)
        first = c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
        groups = list(groups or [])
        if first and ADMIN_GROUP not in groups:
            raise AccessError("first_must_be_admin", i18n.t("lib_accessdb.first_must_be_admin"), 422)
        c.execute("INSERT INTO users(username, display_name, email, pw, vault_slot, must_change, created_at,"
                  " created_by, updated_at, pw_changed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (username, (display_name or "").strip()[:80], email, pw_json, slot,
                   int(bool(must_change)), now, created_by or "", now, now))
        _set_groups(c, username, groups)
        return _public_user(c, _user_row(c, username))


def update_user(db, username: str, *, rev: str | None = None, actor: str = "", **fields) -> dict:
    """Campos: display_name, email, groups, disabled, must_change_password. Protege o último admin."""
    username = (username or "").strip().lower()
    with connect(db, write=True) as c:
        row = _user_row(c, username)
        if not row:
            raise NotFound(i18n.t("lib_accessdb.user_not_found", username=username))
        if rev is not None and str(rev) != str(row["rev"]):
            raise Conflict()
        sets, args = [], []
        if fields.get("display_name") is not None:
            sets.append("display_name=?")
            args.append(str(fields["display_name"]).strip()[:80])
        if fields.get("email") is not None:
            email = norm_email(fields["email"], required=True)
            if _email_taken(c, email, exclude=username):
                raise AccessError("exists", i18n.t("lib_accessdb.email_exists", email=email), 409)
            sets.append("email=?")
            args.append(email)
        if fields.get("disabled") is not None:
            if fields["disabled"] and actor and actor == username:
                raise AccessError("self_disable", i18n.t("lib_accessdb.self_disable"), 422)
            sets.append("disabled=?")
            args.append(int(bool(fields["disabled"])))
        if fields.get("must_change_password") is not None:
            sets.append("must_change=?")
            args.append(int(bool(fields["must_change_password"])))
        if fields.get("groups") is not None:
            if actor and actor == username and ADMIN_GROUP in _groups_of(c, username) \
                    and ADMIN_GROUP not in fields["groups"]:
                raise AccessError("self_demote", i18n.t("lib_accessdb.self_demote"), 422)
            _set_groups(c, username, fields["groups"])
        sets += ["updated_at=?", "rev=rev+1"]
        args += [time.time(), username]
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE username=?", args)
        if _admins_active(c) == 0 and c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise AccessError("last_admin", i18n.t("lib_accessdb.last_admin"), 422)
        if fields.get("disabled"):
            c.execute("DELETE FROM sessions WHERE username=?", (username,))
            c.execute("UPDATE users SET vault_slot=NULL WHERE username=?", (username,))
        return _public_user(c, _user_row(c, username))


def set_password(db, username: str, password: str, *, must_change: bool | None = None,
                 vault_key: bytes | None = None, keep_sid_hash: str | None = None) -> dict:
    """Troca a senha, derruba as sessões (menos `keep_sid_hash`) e reembrulha o keyslot se houver chave."""
    username = (username or "").strip().lower()
    check_password_policy(password)
    pw_json, kek = _hash_password(password)
    slot = wrap_vault_key(kek, vault_key) if vault_key else None
    now = time.time()
    with connect(db, write=True) as c:
        if not _user_row(c, username):
            raise NotFound(i18n.t("lib_accessdb.user_not_found", username=username))
        mc = "must_change" if must_change is None else str(int(bool(must_change)))
        c.execute(f"UPDATE users SET pw=?, vault_slot=?, must_change={mc}, pw_changed_at=?, updated_at=?,"
                  " rev=rev+1 WHERE username=?", (pw_json, slot, now, now, username))
        if keep_sid_hash:
            c.execute("DELETE FROM sessions WHERE username=? AND sid_hash<>?", (username, keep_sid_hash))
        else:
            c.execute("DELETE FROM sessions WHERE username=?", (username,))
        return _public_user(c, _user_row(c, username))


def delete_user(db, username: str, *, actor: str = "") -> None:
    username = (username or "").strip().lower()
    if actor and actor == username:
        raise AccessError("self_delete", i18n.t("lib_accessdb.self_delete"), 422)
    with connect(db, write=True) as c:
        if not _user_row(c, username):
            raise NotFound(i18n.t("lib_accessdb.user_not_found", username=username))
        c.execute("DELETE FROM users WHERE username=?", (username,))
        c.execute("DELETE FROM sessions WHERE username=?", (username,))
        if _admins_active(c) == 0 and c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise AccessError("last_admin", i18n.t("lib_accessdb.last_admin"), 422)


def verify_password(db, login: str, password: str) -> tuple[dict, bytes]:
    """(usuário público, KEK) ou WrongPassword. `login` = e-mail (ou o ID interno). Usuário desativado
    também é recusado (mesma mensagem: não revela se o login existe)."""
    with connect(db) as c:
        row = _login_row(c, login)
        if not row:
            # Tempo parecido com o caminho real (não revela se o usuário existe).
            _check(json.dumps(_dummy_meta()), password + "x") if password else None
            raise WrongPassword()
        kek = _check(row["pw"], password)
        if row["disabled"]:
            raise WrongPassword()
        return _public_user(c, row), kek


_DUMMY: dict = {}


def _dummy_meta() -> dict:
    if not _DUMMY:
        meta, _ = _vault().build_meta(secrets.token_hex(8))
        _DUMMY.update(meta)
    return _DUMMY


def record_login(db, username: str, ip: str) -> None:
    with connect(db, write=True) as c:
        c.execute("UPDATE users SET last_login=?, last_ip=? WHERE username=?", (time.time(), ip or "", username))


def get_vault_slot(db, username: str) -> str | None:
    with connect(db) as c:
        row = c.execute("SELECT vault_slot FROM users WHERE username=?", (username,)).fetchone()
        return row[0] if row else None


def set_vault_slot(db, username: str, kek: bytes | None, vault_key: bytes | None) -> None:
    slot = wrap_vault_key(kek, vault_key) if (kek and vault_key) else None
    with connect(db, write=True) as c:
        c.execute("UPDATE users SET vault_slot=? WHERE username=?", (slot, username))


def unwrap_vault_slot(slot: str | None, kek: bytes) -> bytes | None:
    if not slot:
        return None
    try:
        return unwrap_vault_key(kek, slot)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Grupos de acesso
# --------------------------------------------------------------------------- #
def _norm_perms(perms) -> list[str]:
    out = sorted({str(p) for p in (perms or [])})
    bad = [p for p in out if p not in GRANTABLE]
    if bad:
        raise AccessError("invalid_permission", i18n.t("lib_accessdb.invalid_permission", perms=", ".join(bad)), 422)
    return out


def _norm_net(perms) -> list[str]:
    out = [p for p in NET_PERMS if p in set(perms or [])]
    return out


def _public_group(conn, row) -> dict:
    members = [r[0] for r in conn.execute(
        "SELECT username FROM user_groups WHERE group_name=? ORDER BY username", (row["name"],))]
    return {"name": row["name"], "description": row["description"], "builtin": bool(row["builtin"]),
            "permissions": _j(row["permissions"], []), "net_perms": _j(row["net_perms"], []),
            "members": members, "created_at": row["created_at"], "updated_at": row["updated_at"],
            "rev": str(row["rev"])}


def list_groups(db) -> list[dict]:
    with connect(db) as c:
        return [_public_group(c, r) for r in c.execute(
            "SELECT * FROM access_groups ORDER BY builtin DESC, name")]


def get_group(db, name: str) -> dict | None:
    with connect(db) as c:
        row = c.execute("SELECT * FROM access_groups WHERE name=?", ((name or "").lower(),)).fetchone()
        return _public_group(c, row) if row else None


def create_group(db, name: str, *, description: str = "", permissions=(), net_perms=("read",)) -> dict:
    name = (name or "").strip().lower()
    if not GROUPNAME_RE.match(name):
        raise AccessError("invalid_name", i18n.t("lib_accessdb.invalid_group_name"), 422)
    perms, net = _norm_perms(permissions), _norm_net(net_perms)
    now = time.time()
    with connect(db, write=True) as c:
        if c.execute("SELECT 1 FROM access_groups WHERE name=?", (name,)).fetchone():
            raise AccessError("exists", i18n.t("lib_accessdb.group_exists", name=name), 409)
        c.execute("INSERT INTO access_groups(name, description, permissions, net_perms, created_at, updated_at)"
                  " VALUES(?,?,?,?,?,?)", (name, (description or "").strip()[:200], json.dumps(perms),
                                         json.dumps(net), now, now))
        return _public_group(c, c.execute("SELECT * FROM access_groups WHERE name=?", (name,)).fetchone())


def update_group(db, name: str, *, rev: str | None = None, description=None, permissions=None,
                 net_perms=None, members=None, actor: str = "") -> dict:
    name = (name or "").strip().lower()
    with connect(db, write=True) as c:
        row = c.execute("SELECT * FROM access_groups WHERE name=?", (name,)).fetchone()
        if not row:
            raise NotFound(i18n.t("lib_accessdb.group_not_found", name=name))
        if rev is not None and str(rev) != str(row["rev"]):
            raise Conflict()
        builtin = bool(row["builtin"])
        sets, args = [], []
        if description is not None:
            sets.append("description=?")
            args.append(str(description).strip()[:200])
        if permissions is not None and not builtin:
            sets.append("permissions=?")
            args.append(json.dumps(_norm_perms(permissions)))
        if net_perms is not None and not builtin:
            sets.append("net_perms=?")
            args.append(json.dumps(_norm_net(net_perms)))
        sets += ["updated_at=?", "rev=rev+1"]
        args += [time.time(), name]
        c.execute(f"UPDATE access_groups SET {', '.join(sets)} WHERE name=?", args)
        if members is not None:
            members = sorted({str(m).strip().lower() for m in members if str(m).strip()})
            for m in members:
                if not _user_row(c, m):
                    raise AccessError("unknown_user", i18n.t("lib_accessdb.unknown_user", username=m), 422)
            if name == ADMIN_GROUP and actor and actor not in members and \
                    c.execute("SELECT 1 FROM user_groups WHERE username=? AND group_name=?", (actor, name)).fetchone():
                raise AccessError("self_demote", i18n.t("lib_accessdb.self_demote"), 422)
            c.execute("DELETE FROM user_groups WHERE group_name=?", (name,))
            c.executemany("INSERT INTO user_groups(username, group_name) VALUES(?,?)", [(m, name) for m in members])
            if _admins_active(c) == 0 and c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise AccessError("last_admin", i18n.t("lib_accessdb.last_admin"), 422)
        return _public_group(c, c.execute("SELECT * FROM access_groups WHERE name=?", (name,)).fetchone())


def delete_group(db, name: str) -> None:
    name = (name or "").strip().lower()
    with connect(db, write=True) as c:
        row = c.execute("SELECT * FROM access_groups WHERE name=?", (name,)).fetchone()
        if not row:
            raise NotFound(i18n.t("lib_accessdb.group_not_found", name=name))
        if row["builtin"]:
            raise AccessError("builtin", i18n.t("lib_accessdb.builtin_group"), 422)
        c.execute("DELETE FROM access_groups WHERE name=?", (name,))


def effective(db, username: str) -> dict | None:
    """Permissões efetivas (união dos grupos). None = usuário inexistente/desativado."""
    with connect(db) as c:
        row = _user_row(c, (username or "").lower())
        if not row or row["disabled"]:
            return None
        perms: set[str] = set()
        net: set[str] = set()
        groups = []
        for g in c.execute("SELECT a.* FROM access_groups a JOIN user_groups ug ON ug.group_name=a.name "
                           "WHERE ug.username=? ORDER BY a.name", (row["username"],)):
            groups.append(g["name"])
            perms.update(_j(g["permissions"], []))
            net.update(_j(g["net_perms"], []))
        is_admin = "*" in perms
        return {"username": row["username"], "display_name": row["display_name"] or row["username"],
                "groups": groups, "is_admin": is_admin,
                "permissions": set(PERM_KEYS) if is_admin else (perms & GRANTABLE),
                "net_perms": list(NET_PERMS) if is_admin else [p for p in NET_PERMS if p in net],
                "must_change_password": bool(row["must_change"]), "vault_slot": bool(row["vault_slot"])}


# --------------------------------------------------------------------------- #
# Sessões de login
# --------------------------------------------------------------------------- #
def sid_hash(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def create_session(db, username: str, ttl: int, *, ip: str = "", user_agent: str = "") -> str:
    sid = os.urandom(24).hex()
    now = time.time()
    with connect(db, write=True) as c:
        c.execute("DELETE FROM sessions WHERE exp<=?", (now,))
        c.execute("INSERT INTO sessions(sid_hash, username, created_at, exp, last_seen, ip, user_agent)"
                  " VALUES(?,?,?,?,?,?,?)", (sid_hash(sid), username, now, now + int(ttl), now, ip or "",
                                             (user_agent or "")[:200]))
    return sid


def import_session_hash(db, key: str, username: str, exp: float) -> None:
    with connect(db, write=True) as c:
        now = time.time()
        c.execute("INSERT OR IGNORE INTO sessions(sid_hash, username, created_at, exp, last_seen)"
                  " VALUES(?,?,?,?,?)", (key, username, now, exp, now))


def session_user(db, sid: str | None) -> str | None:
    """Usuário dono do sid (válido, não expirado, usuário ativo). Sem usuários cadastrados (modo
    senha-mestra) a sessão vale para o dono gravado nela (o admin legado)."""
    if not sid:
        return None
    key = sid_hash(sid)
    now = time.time()
    with connect(db) as c:
        row = c.execute("SELECT username, exp, last_seen FROM sessions WHERE sid_hash=?", (key,)).fetchone()
        if not row:
            return None
        if row["exp"] <= now:
            expired = True
        else:
            expired = False
            any_user = c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
            if any_user:
                u = c.execute("SELECT disabled FROM users WHERE username=?", (row["username"],)).fetchone()
                if not u or u["disabled"]:
                    return None
            touch = now - (row["last_seen"] or 0) > SESSION_TOUCH_EVERY
    if expired:
        drop_session_hash(db, key)
        return None
    if touch:
        try:
            with connect(db, write=True) as c:
                c.execute("UPDATE sessions SET last_seen=? WHERE sid_hash=?", (now, key))
        except sqlite3.OperationalError:
            pass   # banco ocupado: o carimbo de "visto por último" fica p/ a próxima
    return row["username"]


def drop_session_hash(db, key: str) -> None:
    with connect(db, write=True) as c:
        c.execute("DELETE FROM sessions WHERE sid_hash=?", (key,))


def drop_session(db, sid: str | None) -> None:
    if sid:
        drop_session_hash(db, sid_hash(sid))


def drop_user_sessions(db, username: str) -> int:
    with connect(db, write=True) as c:
        return c.execute("DELETE FROM sessions WHERE username=?", (username,)).rowcount


def clear_sessions(db) -> None:
    with connect(db, write=True) as c:
        c.execute("DELETE FROM sessions")


def list_sessions(db, username: str | None = None) -> list[dict]:
    now = time.time()
    q, args = "SELECT * FROM sessions WHERE exp>?", [now]
    if username:
        q += " AND username=?"
        args.append(username)
    with connect(db) as c:
        return [{"id": r["sid_hash"][:16], "username": r["username"], "created_at": r["created_at"],
                 "exp": r["exp"], "last_seen": r["last_seen"], "ip": r["ip"], "user_agent": r["user_agent"]}
                for r in c.execute(q + " ORDER BY last_seen DESC", args)]


def drop_session_prefix(db, username: str, prefix: str) -> int:
    if not prefix or len(prefix) < 8:
        return 0
    with connect(db, write=True) as c:
        return c.execute("DELETE FROM sessions WHERE username=? AND substr(sid_hash,1,?)=?",
                         (username, len(prefix), prefix)).rowcount


# --------------------------------------------------------------------------- #
# Throttle de login
# --------------------------------------------------------------------------- #
def _throttle_keys(username: str, ip: str) -> list[str]:
    return [f"u:{(username or '').lower()}|{ip or '?'}", f"ip:{ip or '?'}"]


def login_wait(db, username: str, ip: str) -> int:
    """Segundos que ainda faltam para poder tentar de novo (0 = pode)."""
    now = time.time()
    with connect(db) as c:
        wait = 0.0
        for k in _throttle_keys(username, ip):
            r = c.execute("SELECT locked_until FROM login_failures WHERE key=?", (k,)).fetchone()
            if r and r[0] > now:
                wait = max(wait, r[0] - now)
        return int(wait + 0.999)


def login_failed(db, username: str, ip: str) -> None:
    now = time.time()
    with connect(db, write=True) as c:
        c.execute("DELETE FROM login_failures WHERE last_fail<?", (now - THROTTLE_FORGET,))
        for i, k in enumerate(_throttle_keys(username, ip)):
            free = THROTTLE_FREE if i == 0 else THROTTLE_FREE * 4   # por IP (qualquer usuário) tolera mais
            r = c.execute("SELECT failures FROM login_failures WHERE key=?", (k,)).fetchone()
            n = (r[0] if r else 0) + 1
            locked = now + min(THROTTLE_MAX, THROTTLE_BASE * 2 ** (n - free)) if n >= free else 0
            c.execute("INSERT INTO login_failures(key, failures, last_fail, locked_until) VALUES(?,?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET failures=excluded.failures, last_fail=excluded.last_fail,"
                      " locked_until=excluded.locked_until", (k, n, now, locked))


def login_ok(db, username: str, ip: str) -> None:
    with connect(db, write=True) as c:
        c.execute("DELETE FROM login_failures WHERE key=?", (_throttle_keys(username, ip)[0],))


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #
def audit(db, action: str, *, username: str = "", ip: str = "", method: str = "", path: str = "",
          target: str = "", status: int | None = None, detail: str = "") -> None:
    try:
        with connect(db, write=True) as c:
            c.execute("INSERT INTO audit(ts, username, ip, action, method, path, target, status, detail)"
                      " VALUES(?,?,?,?,?,?,?,?,?)", (time.time(), username or "", ip or "", action, method,
                                                     path[:300], str(target)[:200], status, str(detail)[:500]))
    except Exception:
        pass   # auditoria nunca derruba a operação


def query_audit(db, *, username: str = "", action: str = "", q: str = "", since: float | None = None,
                until: float | None = None, limit: int = 200, offset: int = 0) -> dict:
    where, args = [], []
    if username:
        where.append("username=?")
        args.append(username)
    if action:
        where.append("action=?")
        args.append(action)
    if q:
        where.append("(path LIKE ? OR target LIKE ? OR detail LIKE ? OR ip LIKE ?)")
        args += [f"%{q}%"] * 4
    if since:
        where.append("ts>=?")
        args.append(float(since))
    if until:
        where.append("ts<?")
        args.append(float(until))
    w = (" WHERE " + " AND ".join(where)) if where else ""
    limit = max(1, min(1000, int(limit)))
    with connect(db) as c:
        total = c.execute("SELECT COUNT(*) FROM audit" + w, args).fetchone()[0]
        rows = c.execute("SELECT * FROM audit" + w + " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                         args + [limit, max(0, int(offset))]).fetchall()
        actions = [r[0] for r in c.execute("SELECT DISTINCT action FROM audit ORDER BY action")]
        users = [r[0] for r in c.execute("SELECT DISTINCT username FROM audit WHERE username<>'' ORDER BY username")]
    return {"total": total, "items": [dict(r) for r in rows], "actions": actions, "users": users}


def prune_audit(db, keep_days: int = 365) -> int:
    with connect(db, write=True) as c:
        return c.execute("DELETE FROM audit WHERE ts<?", (time.time() - keep_days * 86400,)).rowcount


# --------------------------------------------------------------------------- #
# Dono das conversas da aba Claude
# --------------------------------------------------------------------------- #
def set_claude_owner(db, session_id: str, username: str, *, overwrite: bool = False) -> None:
    if not session_id or not username:
        return
    with connect(db, write=True) as c:
        verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
        c.execute(f"{verb} INTO claude_owners(session_id, username, created_at) VALUES(?,?,?)",
                  (session_id, username, time.time()))


def claude_owner(db, session_id: str) -> str | None:
    with connect(db) as c:
        r = c.execute("SELECT username FROM claude_owners WHERE session_id=?", (session_id,)).fetchone()
        return r[0] if r else None


def claude_owners(db) -> dict[str, str]:
    with connect(db) as c:
        return {r[0]: r[1] for r in c.execute("SELECT session_id, username FROM claude_owners")}


def forget_claude_owner(db, session_id: str) -> None:
    with connect(db, write=True) as c:
        c.execute("DELETE FROM claude_owners WHERE session_id=?", (session_id,))
        c.execute("DELETE FROM claude_msg_authors WHERE session_id=?", (session_id,))


def record_claude_msg_author(db, session_id: str, username: str, text: str) -> None:
    """Registra QUEM enviou uma mensagem da conversa (uma sessão pode ter mais de uma pessoa)."""
    if not session_id or not username or not (text or "").strip():
        return
    with connect(db, write=True) as c:
        c.execute("INSERT INTO claude_msg_authors(session_id, username, text, ts) VALUES(?,?,?,?)",
                  (session_id, username, text.strip(), time.time()))


def claude_msg_authors(db, session_id: str) -> list[tuple[str, str]]:
    """[(texto, username)] na ordem de envio."""
    with connect(db) as c:
        return [(r[0], r[1]) for r in c.execute(
            "SELECT text, username FROM claude_msg_authors WHERE session_id=? ORDER BY id", (session_id,))]


def first_names(db, usernames) -> dict[str, str]:
    """username -> PRIMEIRO nome (display_name; sem ele, a parte local do e-mail/username)."""
    out: dict[str, str] = {}
    with connect(db) as c:
        for u in {x for x in usernames if x}:
            r = c.execute("SELECT display_name FROM users WHERE username=?", (u,)).fetchone()
            dn = ((r[0] if r else "") or "").strip()
            if dn:
                out[u] = dn.split()[0]
            else:
                parts = u.split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").split()
                out[u] = (parts[0] if parts else u).capitalize()
    return out


# --------------------------------------------------------------------------- #
# Project sharing (the project registry itself stays in runs/claude/projects.json)
# --------------------------------------------------------------------------- #
PROJECT_LEVELS = ("view", "participate", "manage", "owner")


def project_owner(db, pid: str) -> str | None:
    with connect(db) as c:
        r = c.execute("SELECT username FROM project_shares WHERE project_id=? AND level='owner'", (pid,)).fetchone()
        return r[0] if r else None


def project_owners(db) -> dict[str, str]:
    with connect(db) as c:
        return {r[0]: r[1] for r in c.execute("SELECT project_id, username FROM project_shares WHERE level='owner'")}


def project_rev(db, pid: str) -> int:
    with connect(db) as c:
        r = c.execute("SELECT rev FROM project_meta WHERE project_id=?", (pid,)).fetchone()
        return int(r[0]) if r else 1


def _bump_project_rev(c, pid: str) -> None:
    c.execute("INSERT INTO project_meta(project_id, rev) VALUES(?, 2) "
              "ON CONFLICT(project_id) DO UPDATE SET rev = rev + 1", (pid,))


def project_shares(db, pid: str) -> dict:
    """{owner, users: [{username, level, granted_by, granted_at}], groups: [{name, level, ...}], rev}"""
    with connect(db) as c:
        rows = c.execute("SELECT * FROM project_shares WHERE project_id=? ORDER BY id", (pid,)).fetchall()
        r = c.execute("SELECT rev FROM project_meta WHERE project_id=?", (pid,)).fetchone()
    owner, users, groups = None, [], []
    for x in rows:
        if x["level"] == "owner":
            owner = x["username"]
        elif x["username"]:
            users.append({"username": x["username"], "level": x["level"], "granted_by": x["granted_by"],
                          "granted_at": x["granted_at"]})
        else:
            groups.append({"name": x["group_name"], "level": x["level"], "granted_by": x["granted_by"],
                           "granted_at": x["granted_at"]})
    return {"owner": owner, "users": users, "groups": groups, "rev": int(r[0]) if r else 1}


def set_project_owner(db, pid: str, username: str, *, actor: str = "", keep_previous: str | None = "manage") -> None:
    """Set the owner (transfer). The previous owner becomes `keep_previous` (None = leaves the project)."""
    username = (username or "").strip().lower()
    with connect(db, write=True) as c:
        if not _user_row(c, username):
            raise NotFound(i18n.t("lib_accessdb.user_not_found", username=username))
        now = time.time()
        prev = c.execute("SELECT username FROM project_shares WHERE project_id=? AND level='owner'", (pid,)).fetchone()
        c.execute("DELETE FROM project_shares WHERE project_id=? AND level='owner'", (pid,))
        c.execute("DELETE FROM project_shares WHERE project_id=? AND username=?", (pid, username))
        c.execute("INSERT INTO project_shares(project_id, username, level, granted_by, granted_at) VALUES(?,?,?,?,?)",
                  (pid, username, "owner", actor, now))
        if prev and prev[0] != username and keep_previous in ("view", "participate", "manage"):
            c.execute("INSERT INTO project_shares(project_id, username, level, granted_by, granted_at) VALUES(?,?,?,?,?)",
                      (pid, prev[0], keep_previous, actor, now))
        _bump_project_rev(c, pid)


def replace_project_shares(db, pid: str, users, groups, *, actor: str = "", rev: int | None = None,
                           max_level: str = "manage") -> dict:
    """Replace the WHOLE share list (except the owner) in one transaction. A stale `rev` = conflict (409).
    users = [{username, level}], groups = [{name, level}]. Returns {added, removed, changed, rev} for the audit."""
    allowed = PROJECT_LEVELS[:PROJECT_LEVELS.index(max_level) + 1]
    allowed = tuple(x for x in allowed if x != "owner")
    want_u: dict[str, str] = {}
    want_g: dict[str, str] = {}
    for kind, items, dest in (("user", users, want_u), ("group", groups, want_g)):
        for it in items or []:
            if not isinstance(it, dict):
                raise AccessError("bad_share", i18n.t("lib_accessdb.bad_share"), 422)
            key = str(it.get("username" if kind == "user" else "name") or "").strip().lower()
            lvl = it.get("level")
            if not key or lvl not in allowed:
                raise AccessError("bad_share", i18n.t("lib_accessdb.bad_share"), 422)
            if key in dest:
                raise AccessError("duplicate_share", i18n.t("lib_accessdb.duplicate_share", name=key), 422)
            dest[key] = lvl
    with connect(db, write=True) as c:
        r = c.execute("SELECT rev FROM project_meta WHERE project_id=?", (pid,)).fetchone()
        cur_rev = int(r[0]) if r else 1
        if rev is not None and int(rev) != cur_rev:
            raise Conflict(i18n.t("lib_accessdb.share_conflict"))
        owner = c.execute("SELECT username FROM project_shares WHERE project_id=? AND level='owner'", (pid,)).fetchone()
        owner = owner[0] if owner else None
        if owner and owner in want_u:
            raise AccessError("owner_share", i18n.t("lib_accessdb.owner_share"), 422)
        for u in want_u:
            if not _user_row(c, u):
                raise NotFound(i18n.t("lib_accessdb.user_not_found", username=u))
        for g in want_g:
            if not c.execute("SELECT 1 FROM access_groups WHERE name=?", (g,)).fetchone():
                raise NotFound(i18n.t("lib_accessdb.group_not_found", name=g))
        old = {("user", x["username"]) if x["username"] else ("group", x["group_name"]): x["level"]
               for x in c.execute("SELECT * FROM project_shares WHERE project_id=? AND level<>'owner'", (pid,))}
        new = {**{("user", k): v for k, v in want_u.items()}, **{("group", k): v for k, v in want_g.items()}}
        if old == new:
            return {"added": [], "removed": [], "changed": [], "rev": cur_rev}
        now = time.time()
        added = [(k, v) for k, v in new.items() if k not in old]
        removed = [(k, old[k]) for k in old if k not in new]
        changed = [(k, old[k], v) for k, v in new.items() if k in old and old[k] != v]
        for (kind, name), _lvl in removed:
            col = "username" if kind == "user" else "group_name"
            c.execute(f"DELETE FROM project_shares WHERE project_id=? AND {col}=? AND level<>'owner'", (pid, name))
        for (kind, name), _o, lvl in changed:
            col = "username" if kind == "user" else "group_name"
            c.execute(f"UPDATE project_shares SET level=?, granted_by=?, granted_at=? WHERE project_id=? AND {col}=?",
                      (lvl, actor, now, pid, name))
        for (kind, name), lvl in added:
            col = "username" if kind == "user" else "group_name"
            c.execute(f"INSERT INTO project_shares(project_id, {col}, level, granted_by, granted_at) VALUES(?,?,?,?,?)",
                      (pid, name, lvl, actor, now))
        _bump_project_rev(c, pid)
        r = c.execute("SELECT rev FROM project_meta WHERE project_id=?", (pid,)).fetchone()
    return {"added": added, "removed": removed, "changed": changed, "rev": int(r[0])}


def project_levels_for(db, username: str, groups) -> dict[str, str]:
    """{project_id: highest level} of the user (direct or through any of their groups)."""
    groups = [g for g in (groups or []) if g]
    rank = {x: i for i, x in enumerate(PROJECT_LEVELS)}
    out: dict[str, str] = {}
    q = "SELECT project_id, level FROM project_shares WHERE username=?"
    args: list = [username or ""]
    if groups:
        q += " OR group_name IN (%s)" % ",".join("?" * len(groups))
        args += groups
    with connect(db) as c:
        for pid, lvl in c.execute(q, args):
            if pid not in out or rank[lvl] > rank[out[pid]]:
                out[pid] = lvl
    return out


def forget_project(db, pid: str) -> None:
    with connect(db, write=True) as c:
        c.execute("DELETE FROM project_shares WHERE project_id=?", (pid,))
        c.execute("DELETE FROM project_meta WHERE project_id=?", (pid,))


def share_candidates(db, q: str = "", limit: int = 50) -> dict:
    """ACTIVE users (no e-mail) and groups for the share picker."""
    like = f"%{(q or '').strip().lower()}%"
    with connect(db) as c:
        users = [{"username": r["username"], "display_name": r["display_name"] or r["username"],
                  "groups": _groups_of(c, r["username"])}
                 for r in c.execute("SELECT username, display_name FROM users WHERE disabled=0 AND "
                                    "(lower(username) LIKE ? OR lower(display_name) LIKE ?) ORDER BY lower(display_name), "
                                    "username LIMIT ?", (like, like, limit))]
        groups = [{"name": r["name"], "description": r["description"],
                   "permissions": _j(r["permissions"], []),
                   "members": c.execute("SELECT COUNT(*) FROM user_groups WHERE group_name=?", (r["name"],)).fetchone()[0]}
                  for r in c.execute("SELECT * FROM access_groups WHERE lower(name) LIKE ? OR lower(description) LIKE ? "
                                     "ORDER BY name LIMIT ?", (like, like, limit))]
    return {"users": users, "groups": groups}


def oldest_admin(db) -> str | None:
    with connect(db) as c:
        r = c.execute("SELECT u.username FROM users u JOIN user_groups ug ON ug.username=u.username "
                      "WHERE ug.group_name=? AND u.disabled=0 ORDER BY u.created_at, u.username LIMIT 1",
                      (ADMIN_GROUP,)).fetchone()
        return r[0] if r else None


# --------------------------------------------------------------------------- #
# Meta + backup
# --------------------------------------------------------------------------- #
def meta_get(db, key: str) -> str | None:
    with connect(db) as c:
        r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None


def meta_set(db, key: str, value: str) -> None:
    with connect(db, write=True) as c:
        c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))


def snapshot(db, dest: Path | str) -> Path:
    """Cópia consistente do banco (API de backup do SQLite) — segura com o console no ar."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp.{os.getpid()}")
    if tmp.exists():
        tmp.unlink()
    with connect(db) as src:
        fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        os.close(fd)
        out = sqlite3.connect(str(tmp))
        try:
            src.backup(out)
        finally:
            out.close()
    os.replace(tmp, dest)
    return dest
