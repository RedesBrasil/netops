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

_FILE = deps.RUNS_DIR / "claude" / "projects.json"
_LOCK = threading.Lock()
_MAX_PROJECTS = 200
_MAX_NAME = 80
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RESERVED = {"new"}   # #projects/new é o formulário de criação
_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_BASE = "/opt/projetos"   # sugestão do formulário "criar pasta nova" (criada sob demanda)

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
        raise ProjectError("empty_name", "Dê um nome ao projeto.")
    return n


def _resolve_dir(path) -> str:
    raw = str(path or "").strip()
    if not raw or not os.path.isabs(raw):
        raise ProjectError("bad_path", "Informe o caminho absoluto da pasta (começa com /).")
    p = Path(raw)
    try:
        real = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ProjectError("path_not_found", "Essa pasta não existe no servidor.", 404)
    if not real.is_dir():
        raise ProjectError("not_a_dir", "O caminho informado não é uma pasta.")
    if not os.access(real, os.R_OK | os.X_OK):
        raise ProjectError("no_access", "O servidor não tem permissão para ler essa pasta.", 403)
    return str(real)


def _inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def deny_reason(real: str) -> str | None:
    """Motivo pelo qual a pasta (já resolvida, sem symlink) NÃO pode ser projeto; None = pode."""
    netops = str(Path(deps.NETOPS_ROOT).resolve())
    if _inside(real, netops):
        return "A pasta do NetOps (e o que está dentro dela) é da aba Claude Code. Escolha outra pasta."
    if _inside(netops, real):
        return "Essa pasta contém o NetOps. Escolha uma pasta que não inclua a instalação do NetOps."
    if real in _DENY_EXACT or any(_inside(real, d) for d in _DENY_TREE):
        return "Pasta do sistema não pode ser projeto. Use uma subpasta própria (ex.: " + DEFAULT_BASE + "/meu-projeto)."
    home = str(Path(os.path.expanduser("~")).resolve())
    if home != "/" and _inside(real, home) and real != home:
        first = real[len(home):].lstrip("/").split("/", 1)[0]
        if first.startswith("."):
            return "Pastas ocultas do usuário do servidor (~/.claude, ~/.ssh...) não podem ser projeto."
    if real == home:
        return "A pasta home do usuário do servidor não pode ser projeto. Use uma subpasta."
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
        raise ProjectError("bad_folder", "Nome de pasta inválido: use letras, números, ponto, hífen ou _ (sem / nem espaço).")
    raw_parent = str(parent or "").strip() or DEFAULT_BASE
    if os.path.isabs(raw_parent):
        raw_parent = os.path.normpath(raw_parent)   # "/opt/projetos/" == "/opt/projetos"
    if raw_parent == DEFAULT_BASE and not os.path.isdir(DEFAULT_BASE):
        os.makedirs(DEFAULT_BASE, mode=0o755, exist_ok=True)
    base = _resolve_dir(raw_parent)
    target = os.path.join(base, name)
    check_allowed(target)
    if os.path.lexists(target):
        raise ProjectError("exists", "Já existe algo com esse nome nessa pasta. Use “Pasta existente”.", 409)
    try:
        os.mkdir(target, 0o755)
    except OSError as e:
        raise ProjectError("mkdir_failed", f"Não foi possível criar a pasta: {e.strerror or e}.", 403)
    return str(Path(target).resolve())


def create(name, path, *, trust: bool = False, new_folder: str | None = None) -> dict:
    """Projeto numa pasta existente (`path`) ou numa pasta nova `new_folder` dentro de `path`.

    Pasta nova = confiável (vazia). Pasta existente sem config executável = confiável. Com config
    executável (.claude/settings*.json, .mcp.json) só fica confiável com `trust=True` (o admin viu a lista)."""
    clean = _clean_name(name)
    real = None   # pasta nova: validada e criada dentro do lock (_new_folder)
    if not new_folder:
        real = _resolve_dir(path)
        check_allowed(real)
    with _LOCK:
        items = _load()
        if len(items) >= _MAX_PROJECTS:
            raise ProjectError("too_many", "Limite de projetos atingido.")
        # Dois projetos na mesma pasta dividiriam as mesmas conversas.
        dup = next((p for p in items if real and p["path"] == real), None)
        if dup:
            raise ProjectError("duplicate_path", f"Essa pasta já é o projeto “{dup.get('name') or dup['id']}”.", 409)
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
    raise ProjectError("not_found", "Projeto não encontrado.", 404)


def set_trusted(pid: str, trusted: bool) -> dict:
    with _LOCK:
        items = _load()
        for p in items:
            if p["id"] == pid:
                p["trusted"] = bool(trusted)
                _save(items)
                return _public(p)
    raise ProjectError("not_found", "Projeto não encontrado.", 404)


def delete(pid: str) -> bool:
    """Remove só o registro. Pasta e conversas ficam intactas."""
    with _LOCK:
        items = _load()
        keep = [p for p in items if p["id"] != pid]
        if len(keep) == len(items):
            return False
        _save(keep)
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
        raise ProjectError("no_access", "Não foi possível listar essa pasta.", 403)
    dirs.sort(key=lambda d: d["name"].lower())
    parent = None if real == "/" else (os.path.dirname(real) or "/")
    # `allowed`/`reason`: o seletor desabilita "Usar esta pasta" onde o servidor recusaria.
    # `config`: o que a pasta traz (exec = vai pedir confiança).
    return {"path": real, "parent": parent, "dirs": dirs, "allowed": deny_reason(real) is None,
            "reason": deny_reason(real), "config": inspect(real)}
