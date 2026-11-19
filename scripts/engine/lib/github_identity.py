#!/usr/bin/env python3
"""GitHub POR USUÁRIO do console: cada pessoa usa a própria conta no agente (aba Claude / Projetos).

Problema que resolve: o agente roda como root com HOME=/root, então todo mundo herdava o `gh` do
servidor (`/root/.config/gh`) e a identidade fixa do `.git/config`. Agora, no modo multiusuário,
cada conversa nasce com o ambiente do usuário que a abriu:

  GH_CONFIG_DIR       = <DATA_ROOT>/runs/users/<username>/gh   (login do `gh` DELE; git-ignorado, 0700)
  GIT_AUTHOR_*/GIT_COMMITTER_*  = nome/e-mail dele (do GitHub; sem GitHub, os do cadastro do console)
  GIT_CONFIG_COUNT/KEY/VALUE    = credential helper do github.com -> `gh auth git-credential` (lê o GH_CONFIG_DIR)
  GIT_TERMINAL_PROMPT=0         = sem conta, o push FALHA na hora (nunca cai na conta do servidor)
  GH_TOKEN/GITHUB_TOKEN herdados = REMOVIDOS

Usuário sem GitHub conectado aponta para uma pasta VAZIA (`runs/users/_sem-github/gh`): `gh` e `git push`
respondem "não autenticado" — nunca a conta do servidor. Modo sem usuários (instalação de um usuário só)
não muda nada (`env_for` devolve {} e o comportamento antigo vale).

O servidor (atualizador, backup completo) continua usando o `gh` do root, fora do agente.

Segredo: o token fica SÓ no hosts.yml do `gh` dentro da pasta do usuário. Este módulo nunca o lê,
imprime nem devolve; os metadados exibidos (login, nome, e-mail) ficam em `github.json` ao lado.
⚠ Limite: o agente roda como root, então a separação é LÓGICA (guarda no hook do claude_svc), não do
sistema operacional. Ver scripts/engine/users/SKILL.md ("GitHub por usuário").
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")   # espelha accessdb.USERNAME_RE
NONE_DIR_NAME = "_sem-github"          # pasta vazia de quem não conectou (não colide: "_" não é inicial válida)
META_FILE = "github.json"
SCOPES = ("repo", "read:org", "workflow", "user:email")
TOKEN_ENV_KEYS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
_TIMEOUT = 30


class GitHubError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


# --------------------------------------------------------------------------- #
# Pastas
# --------------------------------------------------------------------------- #
def users_root(data_root: Path | str) -> Path:
    return Path(data_root) / "runs" / "users"


def _check_user(username: str) -> str:
    u = (username or "").strip().lower()
    if not USERNAME_RE.match(u):
        raise GitHubError("invalid_username", f"Usuário inválido: {username!r}", 422)
    return u


def _mkdir_private(path: Path) -> Path:
    """mkdir -p + 0700 em toda a cadeia de runs/users/ até `path` (nada fora dela)."""
    path.mkdir(parents=True, exist_ok=True)
    for p in [path, *path.parents]:
        if not (p.name == "users" and p.parent.name == "runs") and "users" not in [q.name for q in p.parents]:
            break   # fora de runs/users: nunca mexe
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass
        if p.name == "users" and p.parent.name == "runs":
            break
    return path


def user_base(data_root, username: str) -> Path:
    return users_root(data_root) / _check_user(username)


def gh_dir(data_root, username: str, create: bool = True) -> Path:
    """GH_CONFIG_DIR do usuário (criado 0700)."""
    d = user_base(data_root, username) / "gh"
    return _mkdir_private(d) if create else d


def empty_gh_dir(data_root) -> Path:
    """GH_CONFIG_DIR de quem não conectou: vazio de propósito. Se algo gravar nele, é limpo."""
    d = users_root(data_root) / NONE_DIR_NAME / "gh"
    _mkdir_private(d)
    for child in d.iterdir():
        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
    return d


def gh_bin() -> str | None:
    return shutil.which("gh") or next((p for p in ("/usr/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), None)


# --------------------------------------------------------------------------- #
# Metadados (sem segredo)
# --------------------------------------------------------------------------- #
def get_meta(data_root, username: str) -> dict | None:
    try:
        f = user_base(data_root, username) / META_FILE
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, GitHubError):
        return None
    return data if isinstance(data, dict) and data.get("login") else None


def _write_meta(data_root, username: str, meta: dict) -> None:
    base = _mkdir_private(user_base(data_root, username))
    fd, tmp = tempfile.mkstemp(prefix=".github-", dir=str(base))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, base / META_FILE)


def noreply_email(gh_id, login: str) -> str:
    return f"{gh_id}+{login}@users.noreply.github.com" if gh_id else f"{login}@users.noreply.github.com"


def public(meta: dict | None) -> dict:
    """O que a UI vê (nunca token)."""
    if not meta:
        return {"connected": False}
    keys = ("login", "name", "id", "avatar_url", "email", "emails", "scopes", "connected_at", "method")
    return {"connected": True, **{k: meta.get(k) for k in keys}}


# --------------------------------------------------------------------------- #
# gh com o GH_CONFIG_DIR do usuário
# --------------------------------------------------------------------------- #
def base_env(cfg_dir: Path, data_root) -> dict:
    """Ambiente p/ rodar `gh` em nome do usuário: sem token herdado, sem tocar o ~/.gitconfig do root."""
    env = {k: v for k, v in os.environ.items() if k not in TOKEN_ENV_KEYS}
    env.update(GH_CONFIG_DIR=str(cfg_dir), GH_PROMPT_DISABLED="1", GH_PAGER="cat", NO_COLOR="1",
               GH_NO_UPDATE_NOTIFIER="1", GH_BROWSER="true", BROWSER="true", TERM="dumb",
               # `gh auth login` configura o credential helper no gitconfig GLOBAL: isola num arquivo da pasta.
               GIT_CONFIG_GLOBAL=str(cfg_dir / "gitconfig"))
    env.pop("GH_DEBUG", None)
    return env


def _gh(args: list[str], cfg_dir: Path, data_root, stdin: str | None = None,
        timeout: int = _TIMEOUT) -> subprocess.CompletedProcess:
    gh = gh_bin()
    if not gh:
        raise GitHubError("gh_missing", "GitHub CLI (gh) não está instalado no servidor.", 500)
    try:
        return subprocess.run(  # noqa: S603 - argv fixo, sem shell
            [gh, *args], env=base_env(cfg_dir, data_root), input=stdin, capture_output=True, text=True,
            timeout=timeout, cwd=str(cfg_dir))
    except (OSError, subprocess.SubprocessError) as e:
        raise GitHubError("gh_failed", f"Falha ao executar gh: {type(e).__name__}", 502) from e


def _api_json(path: str, cfg_dir: Path, data_root):
    p = _gh(["api", "--hostname", "github.com", path], cfg_dir, data_root)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


def _scopes(cfg_dir: Path, data_root) -> list[str]:
    p = _gh(["api", "--hostname", "github.com", "-i", "/user"], cfg_dir, data_root)
    for line in (p.stdout or "").splitlines():
        if line.lower().startswith("x-oauth-scopes:"):
            return [s.strip() for s in line.split(":", 1)[1].split(",") if s.strip()]
    return []


def refresh(data_root, username: str, method: str = "", keep_email: bool = True) -> dict:
    """Lê do GitHub quem é a conta logada na pasta do usuário e grava github.json. Sem login = erro."""
    cfg = gh_dir(data_root, username)
    user = _api_json("/user", cfg, data_root)
    if not isinstance(user, dict) or not user.get("login"):
        raise GitHubError("not_logged", "O GitHub não confirmou o login (token inválido ou sem acesso).", 401)
    emails = _api_json("/user/emails", cfg, data_root)
    verified = [e["email"] for e in (emails or []) if isinstance(e, dict) and e.get("verified") and e.get("email")]
    old = get_meta(data_root, username) or {}
    noreply = noreply_email(user.get("id"), user["login"])
    choices = list(dict.fromkeys([noreply, *verified]))
    email = old.get("email") if keep_email and old.get("login") == user["login"] and old.get("email") in choices else noreply
    meta = {"login": user["login"], "name": user.get("name") or user["login"], "id": user.get("id"),
            "avatar_url": user.get("avatar_url") or "", "email": email, "emails": choices,
            "scopes": _scopes(cfg, data_root),
            "connected_at": old.get("connected_at") if old.get("login") == user["login"] else time.time(),
            "method": method or old.get("method") or "device"}
    _write_meta(data_root, username, meta)
    return meta


def login_with_token(data_root, username: str, token: str) -> dict:
    """Alternativa ao login pelo navegador: token pessoal (PAT). Vai por stdin, nunca por argv/log."""
    token = (token or "").strip()
    if not token or len(token) > 400 or any(c.isspace() for c in token):
        raise GitHubError("invalid_token", "Token inválido.", 422)
    cfg = gh_dir(data_root, username)
    p = _gh(["auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--with-token",
             "--insecure-storage"],   # token no hosts.yml da pasta do usuário, nunca no chaveiro do sistema
            cfg, data_root, stdin=token + "\n")
    if p.returncode != 0:
        _wipe_gh(cfg)
        raise GitHubError("login_failed", "O GitHub recusou o token (confira validade e permissões).", 401)
    try:
        return refresh(data_root, username, method="token", keep_email=False)
    except GitHubError:
        _wipe_gh(cfg)
        raise


def set_email(data_root, username: str, email: str) -> dict:
    meta = get_meta(data_root, username)
    if not meta:
        raise GitHubError("not_connected", "Conecte o GitHub antes.", 409)
    if email not in (meta.get("emails") or []):
        raise GitHubError("invalid_email", "Escolha um dos e-mails verificados da sua conta do GitHub.", 422)
    meta["email"] = email
    _write_meta(data_root, username, meta)
    return meta


def _wipe_gh(cfg: Path) -> None:
    shutil.rmtree(cfg, ignore_errors=True)


def disconnect(data_root, username: str) -> bool:
    """Desloga (best-effort: o token OAuth continua válido no GitHub até o usuário revogar lá) e apaga tudo."""
    base = user_base(data_root, username)
    had = (base / META_FILE).exists() or (base / "gh" / "hosts.yml").exists()
    cfg = base / "gh"
    if (cfg / "hosts.yml").exists() and gh_bin():
        try:
            _gh(["auth", "logout", "--hostname", "github.com"], cfg, data_root, stdin="y\n", timeout=15)
        except GitHubError:
            pass
    _wipe_gh(cfg)
    try:
        (base / META_FILE).unlink()
    except OSError:
        pass
    return had


def purge_user(data_root, username: str) -> None:
    """Usuário apagado do console: some a pasta inteira dele."""
    try:
        disconnect(data_root, username)
        shutil.rmtree(user_base(data_root, username), ignore_errors=True)
    except GitHubError:
        pass


# --------------------------------------------------------------------------- #
# Ambiente do agente
# --------------------------------------------------------------------------- #
def git_helper_env(gh: str | None) -> dict:
    """Credential helper do github.com por variável (vale sobre qualquer gitconfig): zera a lista e usa o gh."""
    helper = f"!{gh} auth git-credential" if gh else ""
    env = {"GIT_CONFIG_COUNT": "4",
           "GIT_CONFIG_KEY_0": "credential.https://github.com.helper", "GIT_CONFIG_VALUE_0": "",
           "GIT_CONFIG_KEY_1": "credential.https://gist.github.com.helper", "GIT_CONFIG_VALUE_1": ""}
    if helper:
        env.update(GIT_CONFIG_KEY_2="credential.https://github.com.helper", GIT_CONFIG_VALUE_2=helper,
                   GIT_CONFIG_KEY_3="credential.https://gist.github.com.helper", GIT_CONFIG_VALUE_3=helper)
    else:
        env["GIT_CONFIG_COUNT"] = "2"
    return env


def env_for(data_root, username: str | None, *, multiuser: bool, fallback_name: str = "",
            fallback_email: str = "") -> dict:
    """Variáveis que entram no ambiente do agente do usuário. {} = modo antigo (sem usuários)."""
    if not multiuser or not username:
        return {}
    try:
        meta = get_meta(data_root, username)
        cfg = gh_dir(data_root, username, create=False) if meta else None
        if meta and not (cfg / "hosts.yml").exists():
            meta = None
    except GitHubError:
        meta = None
    if meta:
        cfg_dir, name, email = cfg, meta.get("name") or meta["login"], meta.get("email") or noreply_email(meta.get("id"), meta["login"])
    else:
        cfg_dir, name, email = empty_gh_dir(data_root), fallback_name or username, fallback_email or f"{username}@netops.local"
    env = {"GH_CONFIG_DIR": str(cfg_dir), "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
           "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
           "NETOPS_GITHUB_LOGIN": meta["login"] if meta else ""}
    env.update(git_helper_env(gh_bin()))
    return env


def apply_env(base: dict, extra: dict) -> dict:
    """Junta o ambiente herdado com o do usuário. Com `extra` (multiusuário), tira tokens herdados."""
    if not extra:
        return dict(base)
    out = {k: v for k, v in base.items() if k not in TOKEN_ENV_KEYS}
    out.update(extra)
    return out


# --------------------------------------------------------------------------- #
# Guarda (best-effort) contra o agente pegar o GitHub de outra pessoa / do servidor
# --------------------------------------------------------------------------- #
_GUARD_PATTERNS = [
    (re.compile(r"\.config/gh\b"), "a configuração do gh do servidor"),
    (re.compile(r"runs/users\b|/users/[^/\s]+/gh\b|hosts\.yml"), "pastas de login do GitHub dos usuários"),
    (re.compile(r"\bgh\s+auth\s+(token|login|logout|switch|refresh|setup-git)\b"), "comandos de login do gh"),
    (re.compile(r"--show-token"), "exibir o token"),
    (re.compile(r"\b(GH_CONFIG_DIR|GH_TOKEN|GITHUB_TOKEN|GH_ENTERPRISE_TOKEN|GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+|GLOBAL))\b"),
     "variáveis da conta do GitHub"),
    (re.compile(r"\benv\s+(-[a-zA-Z]*i\b|--ignore-environment|-u\b|--unset)"), "limpar o ambiente da conta"),
    (re.compile(r"\bgit\b[^\n|;&]*\bconfig\b[^\n|;&]*\b(credential|user\.(name|email))"), "trocar credencial/identidade do git"),
    (re.compile(r"\bgit\b[^\n|;&]*-c\s+(credential|user\.)"), "trocar credencial/identidade do git"),
    (re.compile(r"\bgit\b[^\n|;&]*--author\b"), "commitar em nome de outra pessoa"),
]


def guard_check(text: str) -> str | None:
    """Motivo do bloqueio, ou None. Texto = comando Bash ou caminho/padrão de ferramenta de arquivo."""
    for rx, what in _GUARD_PATTERNS:
        if rx.search(text or ""):
            return what
    return None
