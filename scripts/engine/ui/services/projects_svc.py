#!/usr/bin/env python3
"""Projetos da aba Claude Code: nome + pasta do servidor.

Arquivo único `runs/claude/projects.json` (nome, caminho e confiança; nada sensível):
  {"projects": [{"id": "meu-site", "name": "Meu site", "path": "/srv/meu-site", "trusted": true, "created": 1760000000}]}

Segurança (modelo do VS Code):
- **Conta do agente** fica no nível do usuário do servidor (`~/.claude/`), como num VS Code: o CLI a lê de
  qualquer pasta. Nenhum token é copiado para o ambiente da sessão do projeto.
- **Confiança na pasta (Workspace Trust):** pasta com config executável (`.claude/settings*.json` = hooks/env/
  statusLine/apiKeyHelper, `.mcp.json` = servidores MCP) só carrega essa config se o admin marcar o projeto como
  confiável. Não confiável = **modo restrito**: o agente roda só com os settings do usuário (setting_sources=user).
  Pasta nova criada pelo console nasce confiável (está vazia).
- **Pastas proibidas:** raiz e diretórios do sistema, o NetOps (pasta, dentro ou acima dela) e pastas ocultas do home
  (`~/.claude`, `~/.ssh`...). Ver `check_allowed`.
- Criar/renomear/remover/confiar e navegar nas pastas = `projects.manage` (só admin); usar = `claude.use`.

As conversas NÃO são guardadas aqui. O Claude Code já separa os transcripts por pasta
(~/.claude/projects/<pasta>/), então "sessões do projeto" = as sessões daquela pasta
(`directory=` do SDK, ver claude_svc). Remover um projeto só apaga o registro: nunca a pasta
nem as conversas.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import deps
from lib import i18n

_FILE = deps.RUNS_DIR / "claude" / "projects.json"
# Preferências POR USUÁRIO do console (ordem e arquivados): {"<username>": {"order": [ids], "archived": [ids]}}.
# Separado do registro: arquivar/reordenar é gosto de cada um e não exige projects.manage.
_PREFS_FILE = deps.RUNS_DIR / "claude" / "projects-prefs.json"
_LOCK = threading.Lock()
_MAX_PROJECTS = 200
_MAX_NAME = 80
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RESERVED = {"new"}   # #projects/new é o formulário de criação
_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# Base padrão de "criar pasta nova" = ~/projects da CONTA DO CONSOLE (layout 2: /var/lib/netops/projects).
# No HOME a conta sempre consegue criar a pasta sozinha, sem root e sem passo do instalador; /opt/<x> exigia
# root e quebrava em instalação migrada/atualizada. Projetos já cadastrados em outra pasta continuam valendo.
DEFAULT_BASE = os.path.join(os.path.expanduser("~"), "projects")

# Diretórios do sistema: nunca são projeto (nem eles, nem nada dentro deles).
_DENY_TREE = ("/proc", "/sys", "/dev", "/run", "/boot", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32",
              "/lib64", "/libx32", "/snap", "/var/lib", "/var/log", "/var/spool", "/var/cache", "/var/backups",
              "/var/mail", "/lost+found")
# Só a própria pasta é proibida (subpastas podem: /opt/meu-app, /srv/site, /home/ana/proj).
_DENY_EXACT = ("/", "/home", "/root", "/opt", "/srv", "/var", "/tmp", "/var/tmp", "/mnt", "/media", "/var/www")
# Config que EXECUTA algo ou muda o provedor do agente ao abrir a pasta (exige confiança).
_EXEC_CONFIG = (".claude/settings.json", ".claude/settings.local.json", ".mcp.json")
# Instruções/extensões do agente (texto; listadas para o admin saber o que vai entrar no contexto).
_INFO_CONFIG = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", ".claude/agents", ".claude/commands", ".claude/skills")


class ProjectError(Exception):
    """Erro de validação com código estável (a UI mostra `detail`)."""

    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code = code
        self.status = status


def valid_id(pid: str) -> bool:
    return isinstance(pid, str) and bool(_SLUG_RE.match(pid)) and pid not in _RESERVED


def _load() -> list[dict]:
    try:
        with _FILE.open(encoding="utf-8") as fh:
            d = json.load(fh)
        items = d.get("projects") if isinstance(d, dict) else None
        if isinstance(items, list):
            return [p for p in items if isinstance(p, dict) and valid_id(p.get("id")) and p.get("path")]
    except (OSError, ValueError):
        pass
    return []


def _save(items: list[dict]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump({"projects": items}, fh, ensure_ascii=False, indent=1)
    tmp.replace(_FILE)


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48].strip("-")
    return s or "projeto"


def _clean_name(name) -> str:
    n = " ".join(str(name or "").split())[:_MAX_NAME]
    if not n:
        raise ProjectError("empty_name", i18n.t("api_projects.empty_name"))
    return n


def _resolve_dir(path, deny_first: bool = False) -> str:
    raw = str(path or "").strip()
    if not raw or not os.path.isabs(raw):
        raise ProjectError("bad_path", i18n.t("api_projects.bad_path"))
    p = Path(raw)
    try:
        real = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ProjectError("path_not_found", i18n.t("api_projects.path_not_found"), 404)
    if not real.is_dir():
        raise ProjectError("not_a_dir", i18n.t("api_projects.not_a_dir"))
    if deny_first:  # pasta do sistema é recusada pelo motivo certo mesmo quando a conta nem consegue lê-la
        check_allowed(str(real))
    if not os.access(real, os.R_OK | os.X_OK):
        raise ProjectError("no_access", i18n.t("api_projects.no_access"), 403)
    return str(real)


def _inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def deny_reason(real: str) -> str | None:
    """Motivo pelo qual a pasta (já resolvida, sem symlink) NÃO pode ser projeto; None = pode."""
    netops = str(Path(deps.NETOPS_ROOT).resolve())
    if _inside(real, netops):
        return i18n.t("api_projects.deny_netops")
    if _inside(netops, real):
        return i18n.t("api_projects.deny_contains_netops")
    home = str(Path(os.path.expanduser("~")).resolve())
    if real == home:
        return i18n.t("api_projects.deny_home")
    if home != "/" and _inside(real, home):
        first = real[len(home):].lstrip("/").split("/", 1)[0]
        if first.startswith("."):
            return i18n.t("api_projects.deny_hidden")
        # Subpasta visível do HOME da conta do console: pode, mesmo com o HOME dentro de /var/lib
        # (layout 2: /var/lib/netops). É onde fica a base padrão (DEFAULT_BASE).
        return None
    if real in _DENY_EXACT or any(_inside(real, d) for d in _DENY_TREE):
        return i18n.t("api_projects.deny_system", example=os.path.join(DEFAULT_BASE, "my-project"))
    return None


def check_allowed(real: str) -> None:
    why = deny_reason(real)
    if why:
        raise ProjectError("forbidden_path", why, 403)


def inspect(real: str) -> dict:
    """O que a pasta traz para o agente: `exec` (exige confiança) e `info` (só instruções)."""
    found = lambda names: [n for n in names if os.path.exists(os.path.join(real, n))]
    return {"exec": found(_EXEC_CONFIG), "info": found(_INFO_CONFIG)}


def _public(p: dict) -> dict:
    exists = os.path.isdir(p["path"])
    cfg = inspect(p["path"]) if exists else {"exec": [], "info": []}
    return {"id": p["id"], "name": p.get("name") or p["id"], "path": p["path"],
            "created": p.get("created") or 0, "exists": exists,
            "trusted": bool(p.get("trusted")), "config": cfg}


def list_projects() -> list[dict]:
    with _LOCK:
        items = _load()
    return [_public(p) for p in sorted(items, key=lambda x: (x.get("name") or "").lower())]


# ------------------------------------------------------------------ preferências por usuário
def _prefs_all() -> dict:
    try:
        with _PREFS_FILE.open(encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _prefs_save(d: dict) -> None:
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PREFS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    tmp.replace(_PREFS_FILE)


def _user_prefs(d: dict, user: str) -> dict:
    u = d.get(user or "")
    u = u if isinstance(u, dict) else {}
    ids = lambda k: [x for x in (u.get(k) or []) if isinstance(x, str) and valid_id(x)]
    return {"order": ids("order"), "archived": ids("archived")}


def list_for(user: str) -> list[dict]:
    """Projetos na ordem do usuário (arrastar e soltar) com `archived` dele. Projeto sem posição
    salva (novo) vai para o fim, em ordem alfabética."""
    with _LOCK:
        up = _user_prefs(_prefs_all(), user)
    pos = {pid: i for i, pid in enumerate(up["order"])}
    arch = set(up["archived"])
    items = list_projects()   # já em ordem alfabética: desempate estável
    items.sort(key=lambda p: pos.get(p["id"], len(pos)))
    return [{**p, "archived": p["id"] in arch} for p in items]


def set_order(user: str, ids) -> list[dict]:
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise ProjectError("bad_order", i18n.t("api_projects.bad_order"))
    known = {p["id"] for p in list_projects()}
    seen, order = set(), []
    for x in ids:
        if x in known and x not in seen:
            seen.add(x)
            order.append(x)
    with _LOCK:
        d = _prefs_all()
        up = _user_prefs(d, user)
        up["order"] = order
        d[user or ""] = up
        _prefs_save(d)
    return list_for(user)


def set_archived(user: str, pid: str, archived: bool) -> dict:
    if not get(pid):
        raise ProjectError("not_found", i18n.t("api_common.project_not_found"), 404)
    with _LOCK:
        d = _prefs_all()
        up = _user_prefs(d, user)
        arch = [x for x in up["archived"] if x != pid]
        if archived:
            arch.append(pid)
        up["archived"] = arch
        d[user or ""] = up
        _prefs_save(d)
    return next(p for p in list_for(user) if p["id"] == pid)


def get(pid: str) -> dict | None:
    if not valid_id(pid):
        return None
    with _LOCK:
        items = _load()
    for p in items:
        if p["id"] == pid:
            return _public(p)
    return None


def path_of(pid: str) -> str | None:
    """Pasta do projeto, só se ainda existir E continuar permitida (o agente nunca roda numa pasta que sumiu,
    nem numa que virou proibida, ex.: registro editado à mão apontando p/ /etc)."""
    p = get(pid)
    if not p or not p["exists"]:
        return None
    try:
        real = str(Path(p["path"]).resolve(strict=True))
    except (OSError, RuntimeError):
        return None
    return real if deny_reason(real) is None else None


def is_trusted(path: str | None) -> bool:
    """A pasta é de um projeto marcado como confiável? Desconhecida/removida = NÃO (modo restrito).
    Lido a cada início de sessão (inclusive a retomada pós-restart): revogar vale na próxima sessão."""
    if not path:
        return False
    with _LOCK:
        items = _load()
    return any(p["path"] == str(path) and p.get("trusted") for p in items)


def _new_folder(parent, folder) -> str:
    """Cria `parent/folder` (pasta nova e vazia), como o "Nova pasta" do VS Code. Devolve o caminho real."""
    name = str(folder or "").strip()
    if not _FOLDER_RE.match(name) or name in (".", ".."):
        raise ProjectError("bad_folder", i18n.t("api_projects.bad_folder"))
    raw_parent = str(parent or "").strip() or DEFAULT_BASE
    if os.path.isabs(raw_parent):
        raw_parent = os.path.normpath(raw_parent)   # "~/projects/" == "~/projects"
    if raw_parent == os.path.normpath(DEFAULT_BASE) and not os.path.isdir(DEFAULT_BASE):
        try:
            os.makedirs(DEFAULT_BASE, mode=0o750, exist_ok=True)
        except OSError as e:
            raise ProjectError("mkdir_failed", i18n.t("api_projects.mkdir_failed", error=e.strerror or e), 403)
    base = _resolve_dir(raw_parent)
    target = os.path.join(base, name)
    check_allowed(target)
    if os.path.lexists(target):
        raise ProjectError("exists", i18n.t("api_projects.exists"), 409)
    try:
        os.mkdir(target, 0o755)
    except OSError as e:
        raise ProjectError("mkdir_failed", i18n.t("api_projects.mkdir_failed", error=e.strerror or e), 403)
    return str(Path(target).resolve())


def create(name, path, *, trust: bool = False, new_folder: str | None = None) -> dict:
    """Projeto numa pasta existente (`path`) ou numa pasta nova `new_folder` dentro de `path`.

    Pasta nova = confiável (vazia). Pasta existente sem config executável = confiável. Com config
    executável (.claude/settings*.json, .mcp.json) só fica confiável com `trust=True` (o admin viu a lista)."""
    clean = _clean_name(name)
    real = None   # pasta nova: validada e criada dentro do lock (_new_folder)
    if not new_folder:
        real = _resolve_dir(path, deny_first=True)
    with _LOCK:
        items = _load()
        if len(items) >= _MAX_PROJECTS:
            raise ProjectError("too_many", i18n.t("api_projects.too_many"))
        # Dois projetos na mesma pasta dividiriam as mesmas conversas.
        dup = next((p for p in items if real and p["path"] == real), None)
        if dup:
            raise ProjectError("duplicate_path", i18n.t("api_projects.duplicate_path", name=dup.get("name") or dup["id"]), 409)
        if new_folder:
            real = _new_folder(path, new_folder)
            trusted = True
        else:
            trusted = bool(trust) or not inspect(real)["exec"]
        base = _slug(clean)
        if base in _RESERVED:
            base += "-1"
        taken = {p["id"] for p in items}
        pid, n = base, 1
        while pid in taken or pid in _RESERVED:
            n += 1
            pid = f"{base[:60]}-{n}"
        item = {"id": pid, "name": clean, "path": real, "trusted": trusted, "created": int(time.time())}
        items.append(item)
        _save(items)
    return _public(item)


def rename(pid: str, name) -> dict:
    clean = _clean_name(name)
    with _LOCK:
        items = _load()
        for p in items:
            if p["id"] == pid:
                p["name"] = clean
                _save(items)
                return _public(p)
    raise ProjectError("not_found", i18n.t("api_common.project_not_found"), 404)


def set_trusted(pid: str, trusted: bool) -> dict:
    with _LOCK:
        items = _load()
        for p in items:
            if p["id"] == pid:
                p["trusted"] = bool(trusted)
                _save(items)
                return _public(p)
    raise ProjectError("not_found", i18n.t("api_common.project_not_found"), 404)


def delete(pid: str) -> bool:
    """Remove só o registro. Pasta e conversas ficam intactas."""
    with _LOCK:
        items = _load()
        keep = [p for p in items if p["id"] != pid]
        if len(keep) == len(items):
            return False
        _save(keep)
        # some da ordem/arquivados de todos (um projeto novo com o mesmo id não herda a posição)
        d = _prefs_all()
        if d:
            for u in list(d):
                up = _user_prefs(d, u)
                d[u] = {k: [x for x in v if x != pid] for k, v in up.items()}
            _prefs_save(d)
    return True


def browse(path: str | None = None, hidden: bool = False) -> dict:
    """Subpastas de `path` (padrão: home do usuário do servidor) para o seletor de pasta."""
    raw = (path or "").strip() or os.path.expanduser("~") or "/"
    real = _resolve_dir(raw)
    dirs: list[dict] = []
    try:
        with os.scandir(real) as it:
            for e in it:
                if not hidden and e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=True):
                        dirs.append({"name": e.name, "path": os.path.join(real, e.name)})
                except OSError:
                    continue
    except OSError:
        raise ProjectError("no_access", i18n.t("api_projects.list_failed"), 403)
    dirs.sort(key=lambda d: d["name"].lower())
    parent = None if real == "/" else (os.path.dirname(real) or "/")
    # `allowed`/`reason`: o seletor desabilita "Usar esta pasta" onde o servidor recusaria.
    # `config`: o que a pasta traz (exec = vai pedir confiança).
    return {"path": real, "parent": parent, "dirs": dirs, "allowed": deny_reason(real) is None,
            "reason": deny_reason(real), "config": inspect(real)}
