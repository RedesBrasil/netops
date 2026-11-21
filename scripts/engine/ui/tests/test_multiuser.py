"""Multiusuário: login por usuário, grupos de acesso, permissões por rota, keyslot do cofre,
auditoria, dono das conversas Claude e teto de permissões de rede.

Banco de acesso = SQLite isolado em tmp (conftest: deps.DB_FILE). Argon2 barato só nos testes.
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest
from fastapi.testclient import TestClient

MASTER = "senha-mestra-teste-123"


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    from lib import vault
    monkeypatch.setattr(vault, "ARGON2_DEFAULTS", {"iterations": 1, "memory_cost": 1024, "lanes": 1, "length": 32})


def _app():
    from app import create_app
    return create_app()


def _bare():
    return TestClient(_app(), base_url="http://127.0.0.1")


def _init_vault(env, master=MASTER):
    import yaml
    from lib import vault
    meta, _key = vault.build_meta(master)
    f = env / "network" / "credentials.yaml"
    data = yaml.safe_load(f.read_text()) if f.exists() else {}
    data = data or {}
    data["vault"] = meta
    f.write_text(yaml.safe_dump(data))
    import deps
    deps._vault_init_cache.clear()


def _mail(username):
    return username if "@" in username else f"{username}@teste.com.br"


def _login(c, username, password):
    """Login pelo E-MAIL (padrão). 'admin' migrado (sem e-mail) entra pelo ID."""
    body = {"username": username} if username == "admin" else {"email": _mail(username)}
    r = c.post("/api/auth/login", json={**body, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-Netops-Session"] = r.json()["auth_token"]
    return r.json()


def _bootstrap(env):
    """Cofre + 1º login com a senha-mestra -> cria o admin. Devolve cliente logado como admin."""
    _init_vault(env)
    c = _bare()
    r = c.post("/api/auth/login", json={"master_password": MASTER})
    assert r.status_code == 200, r.text
    assert r.json()["bootstrap"] is True
    c.headers["X-Netops-Session"] = r.json()["auth_token"]
    return c


def _mk_user(admin, username, groups, password="senha-forte-1", must_change=False):
    r = admin.post("/api/users", json={"email": _mail(username), "username": username, "password": password,
                                       "groups": groups, "must_change_password": must_change})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
def test_every_route_is_mapped_to_a_permission():
    """Default-deny: toda rota da API tem regra em services/authz.RULES (rota nova sem regra reprova)."""
    import routers
    from services import authz
    missing = []
    for m in pkgutil.iter_modules(routers.__path__):
        mod = importlib.import_module(f"routers.{m.name}")
        for r in getattr(mod, "router").routes:
            methods = sorted((getattr(r, "methods", None) or {"GET"}) - {"HEAD"})
            for meth in methods:
                path = r.path.replace("{", "x").replace("}", "")
                if authz.required_perm(meth, path) == authz.UNMAPPED:
                    missing.append(f"{meth} {r.path}")
    assert not missing, "rotas sem permissão mapeada em services/authz.RULES: " + ", ".join(missing)


def test_admin_only_permissions_cannot_be_granted(env):
    c = _bootstrap(env)
    r = c.post("/api/access-groups", json={"name": "esperto", "permissions": ["server.terminal"]})
    assert r.status_code == 422 and r.json()["error"] == "invalid_permission"
    r = c.post("/api/access-groups", json={"name": "esperto", "permissions": ["schedules.edit"]})
    assert r.status_code == 422


def test_bootstrap_admin_from_master_password_and_then_username_login(env):
    c = _bootstrap(env)
    me = c.get("/api/auth/me").json()
    assert me["username"] == "admin" and me["is_admin"] and me["multiuser"]
    st = _bare().get("/api/auth/status").json()
    assert st["multiuser"] and st["auth_required"]
    c2 = _bare()
    assert c2.post("/api/auth/login", json={"username": "admin", "password": "errada!!"}).status_code == 401
    _login(c2, "admin", MASTER)
    # compat: cliente antigo mandando só {master_password} = senha do admin
    assert _bare().post("/api/auth/login", json={"master_password": MASTER}).status_code == 200


def test_short_master_password_stays_legacy(env):
    _init_vault(env, master="curta")
    c = _bare()
    r = c.post("/api/auth/login", json={"master_password": "curta"})
    assert r.status_code == 200 and r.json()["bootstrap"] is False
    c.headers["X-Netops-Session"] = r.json()["auth_token"]
    me = c.get("/api/auth/me").json()
    assert me["is_admin"] and me["legacy"] and not me["multiuser"]
    assert c.get("/api/hosts").status_code == 200


def test_group_permissions_enforced_per_route(env):
    admin = _bootstrap(env)
    _mk_user(admin, "leitor", ["leitura"])
    c = _bare()
    _login(c, "leitor", "senha-forte-1")
    assert c.get("/api/hosts").status_code == 200
    r = c.post("/api/hosts", json={"hostname": "X"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden" and r.json()["perm"] == "hosts.edit"
    assert c.get("/api/credentials").status_code == 403
    assert c.get("/api/config").status_code == 403
    assert c.get("/api/users").status_code == 403
    assert c.get("/api/audit").status_code == 403
    me = c.get("/api/auth/me").json()
    assert not me["is_admin"] and "hosts.view" in me["permissions"] and me["net_perms"] == ["read"]


def test_files_permission_depends_on_source(env):
    import deps
    deps.STATE.enable_terminal = True
    admin = _bootstrap(env)
    _mk_user(admin, "op", ["operador"])
    c = _bare()
    _login(c, "op", "senha-forte-1")
    r = c.get("/api/files/info")                         # local = servidor -> só admin
    assert r.status_code == 403 and r.json()["perm"] == "server.files"
    r = c.post("/api/files/mkdir", json={"src": "local", "path": "/tmp/x"})
    assert r.status_code == 403
    r = c.get("/api/files/info", params={"src": "token-sftp-inexistente"})   # SFTP de host -> host.files
    assert r.status_code != 403
    assert admin.get("/api/files/info").status_code == 200


def test_disabled_user_and_session_revocation(env):
    admin = _bootstrap(env)
    u = _mk_user(admin, "joao", ["leitura"])
    c = _bare()
    _login(c, "joao", "senha-forte-1")
    assert c.get("/api/hosts").status_code == 200
    r = admin.patch("/api/users/joao", json={"disabled": True}, headers={"If-Match": u["rev"]})
    assert r.status_code == 200
    assert c.get("/api/hosts").status_code == 401        # sessão derrubada
    assert _bare().post("/api/auth/login", json={"email": "joao@teste.com.br", "password": "senha-forte-1"}).status_code == 401


def test_rev_conflict_on_user_update(env):
    admin = _bootstrap(env)
    u = _mk_user(admin, "maria", ["leitura"])
    assert admin.patch("/api/users/maria", json={"display_name": "M"}, headers={"If-Match": u["rev"]}).status_code == 200
    r = admin.patch("/api/users/maria", json={"display_name": "M2"}, headers={"If-Match": u["rev"]})
    assert r.status_code == 409


def test_last_admin_and_self_protections(env):
    admin = _bootstrap(env)
    assert admin.delete("/api/users/admin").status_code == 422                    # não apaga a si mesmo
    r = admin.patch("/api/users/admin", json={"groups": ["leitura"]})
    assert r.status_code == 422                                                    # não se rebaixa
    assert admin.patch("/api/users/admin", json={"disabled": True}).status_code == 422
    assert admin.delete("/api/access-groups/admin").status_code == 422             # grupo fixo
    _mk_user(admin, "chefe", ["admin"])
    chefe = _bare()
    _login(chefe, "chefe", "senha-forte-1")
    assert chefe.delete("/api/users/admin").status_code == 204                     # sobra o chefe
    r = chefe.patch("/api/access-groups/admin", json={"members": []})
    assert r.status_code == 422                                                    # não esvazia o admin


def test_must_change_password_flow(env):
    admin = _bootstrap(env)
    _mk_user(admin, "novo", ["leitura"], password="provisoria1", must_change=True)
    c = _bare()
    _login(c, "novo", "provisoria1")
    r = c.get("/api/hosts")
    assert r.status_code == 403 and r.json()["error"] == "password_change_required"
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/password", json={"current_password": "errada", "new_password": "nova-senha-9"}).status_code == 401
    assert c.post("/api/auth/password", json={"current_password": "provisoria1", "new_password": "curta"}).status_code == 422
    assert c.post("/api/auth/password", json={"current_password": "provisoria1", "new_password": "nova-senha-9"}).status_code == 200
    assert c.get("/api/hosts").status_code == 200                                  # sessão atual mantida
    _login(_bare(), "novo", "nova-senha-9")


def test_login_throttle(env):
    admin = _bootstrap(env)
    _mk_user(admin, "alvo", ["leitura"])
    c = _bare()
    codes = [c.post("/api/auth/login", json={"email": "alvo@teste.com.br", "password": "x" * 9}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and 429 in codes[5:]
    r = c.post("/api/auth/login", json={"email": "alvo@teste.com.br", "password": "senha-forte-1"})
    assert r.status_code == 429                                                   # até a senha certa espera


def test_keyslot_unlocks_vault_for_user_and_survives_master_rotation(env):
    from lib import vault, vault_session
    admin = _bootstrap(env)                       # cofre destrancado pelo bootstrap
    _mk_user(admin, "op", ["operador"])           # criado com o cofre aberto -> já tem slot
    assert admin.get("/api/users/op").json()["vault_slot"] is True
    vault_session.clear_session()
    assert vault_session.session_status()["state"] == "locked"
    r = _bare().post("/api/auth/login", json={"email": "op@teste.com.br", "password": "senha-forte-1"})
    assert r.json()["vault"] == "unlocked"
    assert vault_session.session_status()["state"] == "cache"
    # Senha-mestra trocada: slot velho não abre; com o cofre aberto, o login refaz o slot.
    vault_session.clear_session()
    _init_vault(env, master="outra-mestra-456")
    r = _bare().post("/api/auth/login", json={"email": "op@teste.com.br", "password": "senha-forte-1"})
    assert r.json()["vault"] == "no_slot"
    import yaml
    import deps
    meta = vault.load_meta(yaml.safe_load(deps.CREDS_FILE.read_text()))
    vault_session.set_session_key(vault.derive_key("outra-mestra-456", meta))
    r = _bare().post("/api/auth/login", json={"email": "op@teste.com.br", "password": "senha-forte-1"})
    assert r.json()["vault"] == "slot_created"
    vault_session.clear_session()
    r = _bare().post("/api/auth/login", json={"email": "op@teste.com.br", "password": "senha-forte-1"})
    assert r.json()["vault"] == "unlocked"


def test_audit_records_logins_and_writes(env):
    admin = _bootstrap(env)
    _mk_user(admin, "leitor", ["leitura"])
    c = _bare()
    c.post("/api/auth/login", json={"email": "leitor@teste.com.br", "password": "errada-123"})
    _login(c, "leitor", "senha-forte-1")
    c.post("/api/hosts", json={"hostname": "X"})          # 403, mas auditado
    a = admin.get("/api/audit").json()
    actions = [(i["action"], i["username"]) for i in a["items"]]
    assert ("bootstrap_admin", "admin") in actions
    assert ("user_created", "admin") in actions
    assert ("login_failed", "leitor") in actions and ("login", "leitor") in actions
    api = [i for i in a["items"] if i["action"] == "api" and i["username"] == "leitor"]
    assert api and api[0]["status"] == 403 and api[0]["path"] == "/api/hosts"
    only = admin.get("/api/audit", params={"user": "leitor"}).json()
    assert only["items"] and all(i["username"] == "leitor" for i in only["items"])


def test_terminal_websockets_respect_permissions(env):
    import deps
    from starlette.websockets import WebSocketDisconnect
    deps.STATE.enable_terminal = True
    admin = _bootstrap(env)
    _mk_user(admin, "op", ["operador"])
    c = _bare()
    sid = _login(c, "op", "senha-forte-1")["auth_token"]
    with pytest.raises(WebSocketDisconnect) as exc:     # terminal do SERVIDOR: só admin
        with c.websocket_connect(f"/api/term?auth={sid}") as ws:
            ws.receive_bytes()
    assert exc.value.code == 4403
    _mk_user(admin, "leitor", ["leitura"])
    sid2 = _login(_bare(), "leitor", "senha-forte-1")["auth_token"]
    with pytest.raises(WebSocketDisconnect) as exc:     # terminal de HOST sem host.terminal
        with c.websocket_connect(f"/api/term/host/1?auth={sid2}") as ws:
            ws.receive_bytes()
    assert exc.value.code == 4403


def test_claude_sessions_filtered_by_owner(env, monkeypatch):
    import deps
    from lib import accessdb
    from services import claude_svc
    deps.STATE.enable_claude = True
    admin = _bootstrap(env)
    _mk_user(admin, "op", ["operador"])
    _mk_user(admin, "op2", ["operador"])
    fake = [{"id": "s-admin"}, {"id": "s-op"}, {"id": "s-velha"}]
    monkeypatch.setattr(claude_svc, "list_project_sessions", lambda *a, **k: list(fake))
    monkeypatch.setattr(claude_svc, "project_session_exists", lambda sid, cwd=None: True)
    monkeypatch.setattr(claude_svc, "session_items", lambda sid, cwd=None: [])
    accessdb.set_claude_owner(deps.db_file(), "s-admin", "admin")
    accessdb.set_claude_owner(deps.db_file(), "s-op", "op")
    op = _bare()
    _login(op, "op", "senha-forte-1")
    assert [s["id"] for s in op.get("/api/claude/sessions").json()["sessions"]] == ["s-op"]
    assert {s["id"] for s in admin.get("/api/claude/sessions").json()["sessions"]} == {"s-admin", "s-op", "s-velha"}
    assert op.get("/api/claude/sessions/s-op/messages").status_code == 200
    assert op.get("/api/claude/sessions/s-admin/messages").status_code == 403
    assert op.get("/api/claude/sessions/s-velha").status_code == 403   # sem dono = anterior ao multiusuário
    op2 = _bare()
    _login(op2, "op2", "senha-forte-1")
    assert op2.put("/api/claude/sessions/s-op/title", json={"title": "x"}).status_code == 403
    leitor_grp = admin.post("/api/access-groups", json={"name": "sem-ia", "permissions": ["hosts.view"]})
    assert leitor_grp.status_code == 201
    _mk_user(admin, "semia", ["sem-ia"])
    c = _bare()
    _login(c, "semia", "senha-forte-1")
    assert c.get("/api/claude/sessions").status_code == 403


def test_projects_follow_claude_permission_and_owner_filter(env, monkeypatch, tmp_path):
    """Projetos abrem sessões do agente (shell no servidor, na pasta escolhida): mesma permissão da aba
    Claude (`claude.use`) e o mesmo filtro por dono — o operador só vê as sessões dele no projeto."""
    import deps
    from lib import accessdb
    from services import claude_svc
    deps.STATE.enable_claude = True
    admin = _bootstrap(env)
    _mk_user(admin, "op", ["operador"])
    pasta = tmp_path.parent / (tmp_path.name + "-proj")   # fora do NETOPS_ROOT (= tmp_path)
    pasta.mkdir()
    assert admin.post("/api/projects", json={"name": "Site", "path": str(pasta)}).status_code == 200
    # escolher pasta / criar / confiar / remover = só admin (projects.manage); o operador só usa
    op0 = _bare()
    _login(op0, "op", "senha-forte-1")
    # private by default: the operator does not even see it until the owner shares it
    assert op0.get("/api/projects").json()["projects"] == []
    assert op0.get("/api/projects/site").status_code == 404
    rev = admin.get("/api/projects/site/shares").json()["rev"]
    r = admin.put("/api/projects/site/shares", json={"rev": rev, "users": [{"username": "op", "level": "participate"}]})
    assert r.status_code == 200, r.text
    assert [x["id"] for x in op0.get("/api/projects").json()["projects"]] == ["site"]
    assert op0.get("/api/projects/site").status_code == 200
    assert op0.get("/api/projects/browse", params={"path": "/"}).status_code == 403
    assert op0.post("/api/projects", json={"name": "x", "path": str(pasta)}).status_code == 403
    assert op0.patch("/api/projects/site", json={"trusted": True}).status_code == 403
    assert op0.delete("/api/projects/site").status_code == 403
    # ordem/arquivar = preferência do próprio usuário (claude.use); não afeta o admin
    assert op0.put("/api/projects/order", json={"ids": ["site"]}).status_code == 200
    assert op0.put("/api/projects/site/archived", json={"archived": True}).json()["archived"] is True
    assert admin.get("/api/projects/site").json()["archived"] is False
    # arquivos da pasta do projeto = projects.files (o grupo operador não tem; admin tem)
    monkeypatch.setattr(deps, "files_enabled", lambda: True)
    assert op0.get("/api/files/info", params={"src": "project:site"}).status_code == 403
    assert admin.get("/api/files/info", params={"src": "project:site"}).status_code == 200
    fake = [{"id": "s-admin"}, {"id": "s-op"}, {"id": "s-velha"}]
    monkeypatch.setattr(claude_svc, "list_project_sessions", lambda *a, **k: list(fake))
    accessdb.set_claude_owner(deps.db_file(), "s-admin", "admin")
    accessdb.set_claude_owner(deps.db_file(), "s-op", "op")
    op = _bare()
    _login(op, "op", "senha-forte-1")
    # members see every conversation of the project (not only their own)
    assert {x["id"] for x in op.get("/api/projects/site/sessions").json()["sessions"]} == {"s-admin", "s-op", "s-velha"}
    assert {x["id"] for x in admin.get("/api/projects/site/sessions").json()["sessions"]} == {"s-admin", "s-op", "s-velha"}
    # sem claude.use: nem lista, nem cria, nem navega nas pastas do servidor
    assert admin.post("/api/access-groups", json={"name": "sem-ia", "permissions": ["hosts.view"]}).status_code == 201
    _mk_user(admin, "semia", ["sem-ia"])
    c = _bare()
    _login(c, "semia", "senha-forte-1")
    assert c.get("/api/projects").status_code == 403
    assert c.get("/api/projects/browse", params={"path": "/"}).status_code == 403
    assert c.post("/api/projects", json={"name": "x", "path": str(pasta)}).status_code == 403
    assert c.get("/api/projects/site/sessions").status_code == 403

def test_claude_netperms_capped_by_group(env):
    import deps
    from services import claude_svc
    admin = _bootstrap(env)
    _mk_user(admin, "leitor", ["leitura"])
    s = claude_svc.ClaudeWebSession(user="leitor", persist=True)
    assert s._netcap == ["read"]
    assert s._capped(["read", "create", "edit", "delete"]) == ["read"]
    s_admin = claude_svc.ClaudeWebSession(user="admin", persist=True)
    assert s_admin._netcap is None
    assert s_admin._capped(None) == ["read", "create", "edit", "delete"]


def test_no_login_console_is_local_admin(env):
    """Sem cofre e sem usuários (instalação de teste/E2E): console aberto como antes."""
    c = _bare()
    assert c.get("/api/hosts").status_code == 200
    me = c.get("/api/auth/me").json()
    assert me["is_admin"] and me["legacy"]


def test_snapshot_is_consistent_copy(env, tmp_path):
    import sqlite3
    import deps
    from lib import accessdb
    _bootstrap(env)
    out = accessdb.snapshot(deps.db_file(), tmp_path / "snap" / "netops.db")
    conn = sqlite3.connect(out)
    assert conn.execute("SELECT username FROM users").fetchall() == [("admin",)]
    conn.close()



# --------------------------------------------------------------------------- #
# Login por E-MAIL
# --------------------------------------------------------------------------- #
def test_login_by_email_case_insensitive_and_by_internal_id(env):
    admin = _bootstrap(env)
    r = admin.post("/api/users", json={"email": "Joao.Silva@Empresa.com.br", "password": "senha-forte-1",
                                       "groups": ["leitura"], "must_change_password": False})
    assert r.status_code == 201
    u = r.json()
    assert u["email"] == "joao.silva@empresa.com.br" and u["username"] == "joao.silva"   # ID derivado
    for login in ("joao.silva@empresa.com.br", "JOAO.SILVA@EMPRESA.COM.BR", "joao.silva"):
        body = {"email": login} if "@" in login else {"username": login}
        assert _bare().post("/api/auth/login", json={**body, "password": "senha-forte-1"}).status_code == 200, login
    assert _bare().post("/api/auth/login", json={"email": "outro@empresa.com.br", "password": "senha-forte-1"}).status_code == 401
    me = _login(_bare(), "joao.silva@empresa.com.br", "senha-forte-1")["user"]
    assert me["username"] == "joao.silva"


def test_email_required_unique_and_valid(env):
    admin = _bootstrap(env)
    ok = {"password": "senha-forte-1", "groups": ["leitura"]}
    assert admin.post("/api/users", json={**ok}).status_code == 422                       # sem e-mail
    r = admin.post("/api/users", json={**ok, "email": "nao-e-email"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_email"
    assert admin.post("/api/users", json={**ok, "email": "ana@x.com"}).status_code == 201
    r = admin.post("/api/users", json={**ok, "email": "ANA@x.com"})
    assert r.status_code == 409                                                           # duplicado (maiúsc.)
    r = admin.post("/api/users", json={**ok, "email": "ana@outro.com"})
    assert r.status_code == 201 and r.json()["username"] == "ana-2"                        # ID sem colisão


def test_change_email_keeps_id_and_history(env):
    admin = _bootstrap(env)
    u = _mk_user(admin, "maria", ["leitura"])
    r = admin.patch("/api/users/maria", json={"email": "maria.nova@x.com"}, headers={"If-Match": u["rev"]})
    assert r.status_code == 200 and r.json()["username"] == "maria"
    assert _bare().post("/api/auth/login", json={"email": "maria.nova@x.com", "password": "senha-forte-1"}).status_code == 200
    assert _bare().post("/api/auth/login", json={"email": "maria@teste.com.br", "password": "senha-forte-1"}).status_code == 401
    _mk_user(admin, "pedro", ["leitura"])
    r = admin.patch("/api/users/pedro", json={"email": "maria.nova@x.com"})
    assert r.status_code == 409


def test_bootstrap_with_email_sets_admin_login(env):
    _init_vault(env)
    r = _bare().post("/api/auth/login", json={"email": "Chefe@Empresa.com", "master_password": MASTER})
    assert r.status_code == 200 and r.json()["bootstrap"] is True
    r = _bare().post("/api/auth/login", json={"email": "chefe@empresa.com", "password": MASTER})
    assert r.status_code == 200 and r.json()["user"]["username"] == "admin" and r.json()["user"]["is_admin"]


def test_schema_v1_db_migrates_emails_to_lowercase_unique(env):
    import sqlite3
    import deps
    from lib import accessdb
    _bootstrap(env)
    db = deps.db_file()
    conn = sqlite3.connect(db)
    conn.execute("DROP INDEX IF EXISTS users_email")
    conn.execute("UPDATE users SET email=' Admin@X.COM ' WHERE username='admin'")
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()
    accessdb._initialized.clear()
    assert accessdb.login_username(db, "admin@x.com") == "admin"
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == accessdb.SCHEMA_VERSION
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='users_email'").fetchone()
    conn.close()


def test_banco_existente_sem_claude_msg_authors_ganha_a_tabela(tmp_path):
    """Bug 2.6.1→2.6.2: a tabela entrou só no _SCHEMA_V1; banco já em v2 nunca a recebia e apagar
    conversa dava 'no such table'. Agora é tabela aditiva, criada em todo banco sem subir o user_version."""
    import sqlite3
    from lib import accessdb
    db = tmp_path / "netops.db"
    with accessdb.connect(db) as c:              # cria o banco atual (v2)
        c.execute("SELECT 1")
    raw = sqlite3.connect(db)
    raw.execute("DROP TABLE claude_msg_authors")  # = instalação criada antes da tabela
    raw.commit(); raw.close()
    accessdb._initialized.clear()                 # novo processo (o console reiniciado)
    accessdb.set_claude_owner(db, "s1", "ana")
    accessdb.record_claude_msg_author(db, "s1", "ana", "oi")
    assert accessdb.claude_msg_authors(db, "s1") == [("oi", "ana")]
    accessdb.forget_claude_owner(db, "s1")        # apagar conversa: não pode dar 'no such table'
    assert accessdb.claude_msg_authors(db, "s1") == []
    with sqlite3.connect(db) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == accessdb.SCHEMA_VERSION
