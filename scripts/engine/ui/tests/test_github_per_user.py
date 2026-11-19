"""GitHub por usuário: cada usuário do console conecta a própria conta e o agente dele usa só ela.

`gh` falso (script em tmp) emula /user, /user/emails, auth login --with-token e logout gravando
hosts.yml no GH_CONFIG_DIR — nada fala com o GitHub de verdade.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from test_multiuser import _bare, _bootstrap, _fast_kdf, _login, _mk_user  # noqa: F401  (fixture autouse)

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
cfg = os.environ.get("GH_CONFIG_DIR", "")
hosts = os.path.join(cfg, "hosts.yml")
a = sys.argv[1:]
def token():
    try:
        return open(hosts).read().split("oauth_token: ", 1)[1].split()[0]
    except Exception:
        return ""
if a[:2] == ["auth", "login"] and "--with-token" in a:
    t = sys.stdin.read().strip()
    if not t.startswith("ghp_ok"):
        print("error validating token", file=sys.stderr); sys.exit(1)
    os.makedirs(cfg, exist_ok=True)
    open(hosts, "w").write("github.com:\n    oauth_token: %s\n    user: u\n" % t)
    sys.exit(0)
if a[:2] == ["auth", "logout"]:
    sys.exit(0)
if a[:2] == ["auth", "git-credential"]:
    t = token()
    if t:
        print("username=x-access-token\npassword=" + t)
    sys.exit(0)
if a and a[0] == "api":
    t = token()
    if not t:
        print("HTTP 401: Requires authentication", file=sys.stderr); sys.exit(1)
    login = t.split("_")[2]
    if "-i" in a:
        print("HTTP/2.0 200 OK\nX-Oauth-Scopes: repo, read:org, workflow, user:email\n\n{}"); sys.exit(0)
    if a[-1] == "/user":
        print(json.dumps({"login": login, "name": login.title() + " Silva", "id": 4242, "avatar_url": "https://x/y?v=4"}))
    elif a[-1] == "/user/emails":
        print(json.dumps([{"email": login + "@empresa.com", "verified": True}, {"email": "nao@x.com", "verified": False}]))
    sys.exit(0)
sys.exit(2)
'''


@pytest.fixture()
def fake_gh(tmp_path, monkeypatch):
    from lib import github_identity
    p = tmp_path / "bin" / "gh"
    p.parent.mkdir()
    p.write_text(FAKE_GH)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(github_identity, "gh_bin", lambda: str(p))
    return p


def _users(env):
    admin = _bootstrap(env)
    _mk_user(admin, "joao", ["operador"])
    _mk_user(admin, "maria", ["operador"])
    joao, maria = _bare(), _bare()
    _login(joao, "joao", "senha-forte-1")
    _login(maria, "maria", "senha-forte-1")
    return admin, joao, maria


# --------------------------------------------------------------------------- #
def test_connect_with_token_status_email_and_disconnect(env, fake_gh):
    _admin, joao, maria = _users(env)
    assert joao.get("/api/account/github").json()["connected"] is False
    r = joao.post("/api/account/github/token", json={"token": "ghp_ok_joaogh"})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["connected"] and st["login"] == "joaogh" and st["method"] == "token"
    assert st["email"] == "4242+joaogh@users.noreply.github.com"
    assert "nao@x.com" not in st["emails"] and "joaogh@empresa.com" in st["emails"]
    assert "token" not in json.dumps(st).replace("\"method\": \"token\"", "")   # nunca devolve o token
    # pasta privada e fora de qualquer outra
    d = env / "runs" / "users" / "joao" / "gh"
    assert (d / "hosts.yml").exists() and stat.S_IMODE(d.stat().st_mode) == 0o700
    # maria não vê o GitHub do joão
    assert maria.get("/api/account/github").json()["connected"] is False
    # e-mail: só um dos verificados
    assert joao.put("/api/account/github/email", json={"email": "nao@x.com"}).status_code == 422
    assert joao.put("/api/account/github/email", json={"email": "joaogh@empresa.com"}).json()["email"] == "joaogh@empresa.com"
    assert joao.get("/api/auth/me").json()["github_login"] == "joaogh"
    # token recusado não deixa lixo
    assert maria.post("/api/account/github/token", json={"token": "ghp_ruim_xxxxx"}).status_code == 401
    assert not (env / "runs" / "users" / "maria" / "gh" / "hosts.yml").exists()
    # desconectar
    assert joao.delete("/api/account/github").json()["connected"] is False
    assert not (d / "hosts.yml").exists()


def test_admin_sees_and_revokes_and_delete_user_purges(env, fake_gh):
    admin, joao, maria = _users(env)
    joao.post("/api/account/github/token", json={"token": "ghp_ok_joaogh"})
    rows = {u["username"]: u for u in admin.get("/api/users").json()["users"]}
    assert rows["joao"]["github_login"] == "joaogh" and rows["maria"]["github_login"] == ""
    assert maria.get("/api/users/joao/github").status_code == 403           # só admin
    assert maria.delete("/api/users/joao/github").status_code == 403
    assert admin.get("/api/users/joao/github").json()["login"] == "joaogh"
    assert admin.delete("/api/users/joao/github").json()["connected"] is False
    joao.post("/api/account/github/token", json={"token": "ghp_ok_joaogh"})
    assert admin.delete("/api/users/joao").status_code == 204
    assert not (env / "runs" / "users" / "joao").exists()
    items = admin.get("/api/audit?limit=500").json()["items"]
    actions = {e["action"] for e in items}
    assert {"github_connected", "github_revoked"} <= actions
    assert "ghp_ok" not in json.dumps(items)                                  # token nunca na auditoria


def test_legacy_mode_has_no_per_user_github(env, fake_gh):
    c = _bare()   # sem cofre e sem usuários = admin local
    assert c.get("/api/account/github").json() == {"connected": False, "multiuser": False, "gh_available": True}
    assert c.post("/api/account/github/token", json={"token": "ghp_ok_xxxxxxxx"}).status_code == 409


def test_agent_env_is_per_user_and_never_server_account(env, fake_gh, monkeypatch):
    from lib import github_identity as ghid
    from services import claude_svc
    _admin, joao, _maria = _users(env)
    joao.post("/api/account/github/token", json={"token": "ghp_ok_joaogh"})
    monkeypatch.setenv("GH_TOKEN", "ghp_DO_SERVIDOR")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_DO_SERVIDOR")

    def env_of(user):
        s = claude_svc.ClaudeWebSession(user=user)
        return ghid.apply_env({**os.environ, "NETOPS_USER": user}, s._compute_github_env()), s

    ej, sj = env_of("joao")
    assert ej["GH_CONFIG_DIR"] == str(env / "runs" / "users" / "joao" / "gh")
    assert ej["GIT_AUTHOR_NAME"] == "Joaogh Silva" and ej["GIT_COMMITTER_EMAIL"] == "4242+joaogh@users.noreply.github.com"
    assert "GH_TOKEN" not in ej and "GITHUB_TOKEN" not in ej
    assert ej["GIT_TERMINAL_PROMPT"] == "0" and ej["NETOPS_GITHUB_LOGIN"] == "joaogh"
    assert "@joaogh" in sj._github_context()
    assert sj._github_guarded() is True                       # operador: guarda ligada

    em, sm = env_of("maria")                                  # não conectou -> pasta VAZIA
    assert em["GH_CONFIG_DIR"].endswith("runs/users/_sem-github/gh")
    assert not os.listdir(em["GH_CONFIG_DIR"])
    assert em["GIT_AUTHOR_EMAIL"] == "maria@teste.com.br" and em["NETOPS_GITHUB_LOGIN"] == ""
    assert "NÃO conectou" in sm._github_context()

    ea, sa = env_of("admin")
    assert sa._github_guarded() is False                      # admin = root no servidor: sem guarda

    # git de verdade: o credential helper do ambiente entrega o token DO JOÃO, e nada p/ a maria.
    def cred(e):
        p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, env={**e, "HOME": str(env)}, timeout=20)
        return p.stdout
    assert "password=ghp_ok_joaogh" in cred(ej)
    assert "password=" not in cred(em)


def test_legacy_session_env_unchanged(env, fake_gh):
    from services import claude_svc
    s = claude_svc.ClaudeWebSession(user="local")
    assert s._compute_github_env() == {} and s._github_guarded() is False


@pytest.mark.parametrize("cmd", [
    "cat /root/.config/gh/hosts.yml", "ls runs/users/", "gh auth token", "gh auth status --show-token",
    "GH_CONFIG_DIR=/tmp/x gh repo list", "unset GH_CONFIG_DIR; gh api user", "env -u GH_TOKEN gh api user",
    "env -i bash -c 'gh api user'", "git config --global credential.helper store",
    "git -c user.name=Fulano commit -m x", "git commit --author='Outro <o@x>' -m x", "export GITHUB_TOKEN=abc",
])
def test_guard_blocks(cmd):
    from lib import github_identity
    assert github_identity.guard_check(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "git status", "git commit -m 'fix: x'", "git push origin main", "gh pr create --fill", "gh api repos/a/b",
    "python3 scripts/tools/access/session.py exec --host-id 2 --command '/ip address print'",
    "cat network/hosts.yaml",
])
def test_guard_allows(cmd):
    from lib import github_identity
    assert github_identity.guard_check(cmd) is None, cmd


def test_scheduler_github_as(env, fake_gh, tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    engine = Path(__file__).resolve().parents[2]
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    from scheduler import runner, store
    monkeypatch.setenv("GH_TOKEN", "ghp_DO_SERVIDOR")
    base = {"GH_TOKEN": "ghp_DO_SERVIDOR", "PATH": os.environ["PATH"]}
    assert runner._github_env({"agent": {}}, base, env) == base                   # padrão = como antes
    e = runner._github_env({"agent": {"github_as": "joao"}}, base, env)
    assert "GH_TOKEN" not in e and e["GH_CONFIG_DIR"].endswith("_sem-github/gh")  # sem conta = sem GitHub
    task = {"name": "t", "kind": "agent", "prompt": "oi", "schedule": {"type": "interval", "minutes": 5},
            "agent": {"permissions": "restricted", "github_as": "Joao"}}
    assert store._clean(task, "America/Sao_Paulo")["agent"]["github_as"] == "joao"
    bad = {**task, "agent": {"github_as": "../root"}}
    with pytest.raises(store.TaskError):
        store._clean(bad, "America/Sao_Paulo")
