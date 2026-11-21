"""Private projects shared with users and access groups (services/project_acl.py, routers/projects.py).

Levels: view < participate < manage < owner. Not a member = 404 everywhere; admins included (they only reach
someone else's project through the audited override)."""
import asyncio
import os
from types import SimpleNamespace

import pytest

from test_multiuser import _bare, _bootstrap, _login, _mk_user

PW = "senha-forte-1"


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    from lib import vault
    monkeypatch.setattr(vault, "ARGON2_DEFAULTS", {"iterations": 1, "memory_cost": 1024, "lanes": 1, "length": 32})


@pytest.fixture()
def world(env, monkeypatch, tmp_path):
    """admin (owner) + another admin + a 'dev' group (claude.use + projects.files) with ana and bia."""
    import deps
    deps.STATE.enable_claude = True
    monkeypatch.setattr(deps, "files_enabled", lambda: True)
    admin = _bootstrap(env)
    r = admin.post("/api/access-groups", json={"name": "dev", "permissions": ["claude.use", "projects.files"]})
    assert r.status_code == 201, r.text
    _mk_user(admin, "ana", ["dev"])
    _mk_user(admin, "bia", ["dev"])
    _mk_user(admin, "adm2", ["admin"])
    pasta = tmp_path.parent / (tmp_path.name + "-proj")   # outside NETOPS_ROOT (= tmp_path)
    pasta.mkdir()
    (pasta / "leia.txt").write_text("oi")
    assert admin.post("/api/projects", json={"name": "Site", "path": str(pasta)}).status_code == 200
    clients = {"admin": admin}
    for u in ("ana", "bia", "adm2"):
        c = _bare()
        _login(c, u, PW)
        clients[u] = c
    return SimpleNamespace(c=clients, pasta=pasta)


def _share(c, users=(), groups=(), pid="site"):
    rev = c.get(f"/api/projects/{pid}/shares").json()["rev"]
    return c.put(f"/api/projects/{pid}/shares", json={
        "rev": rev, "users": [{"username": u, "level": lv} for u, lv in users],
        "groups": [{"name": g, "level": lv} for g, lv in groups]})


def _ids(c):
    return [p["id"] for p in c.get("/api/projects").json()["projects"]]


def test_private_by_default_even_for_other_admins(world):
    c = world.c
    assert _ids(c["admin"]) == ["site"]
    p = c["admin"].get("/api/projects/site").json()
    assert p["my_level"] == "owner" and p["owner"] == "admin" and p["shared"] == {"users": 0, "groups": 0}
    for who in ("ana", "adm2"):
        assert _ids(c[who]) == []
        assert c[who].get("/api/projects/site").status_code == 404
        assert c[who].get("/api/projects/site/sessions").status_code == 404
        assert c[who].get("/api/claude/sessions/x/messages", params={"project": "site"}).status_code == 404
        assert c[who].get("/api/files/info", params={"src": "project:site"}).status_code == 404
        assert c[who].get("/api/projects/site/shares").status_code == 404
        assert c[who].put("/api/projects/site/archived", json={"archived": True}).status_code == 404


def test_view_reads_but_does_not_write(world, monkeypatch):
    from services import claude_svc
    c = world.c
    assert _share(c["admin"], users=[("ana", "view")]).status_code == 200
    assert _ids(c["ana"]) == ["site"]
    assert c["ana"].get("/api/projects/site").json()["my_level"] == "view"
    monkeypatch.setattr(claude_svc, "list_project_sessions", lambda *a, **k: [{"id": "s1"}])
    assert [s["id"] for s in c["ana"].get("/api/projects/site/sessions").json()["sessions"]] == ["s1"]
    # files: read yes, write no
    assert c["ana"].get("/api/files/list", params={"src": "project:site", "path": str(world.pasta)}).status_code == 200
    r = c["ana"].post("/api/files/mkdir", json={"src": "project:site", "path": str(world.pasta / "nova")})
    assert r.status_code == 403 and r.json()["error"] == "project_level"
    # conversation actions need participate
    assert c["ana"].post("/api/claude/upload", params={"project": "site"},
                         files={"file": ("a.txt", b"x")}).status_code == 403
    assert c["ana"].put("/api/claude/sessions/s1/title", params={"project": "site"},
                        json={"title": "x"}).status_code == 403
    # managing needs manage
    assert c["ana"].get("/api/projects/site/shares").status_code == 403
    assert c["ana"].patch("/api/projects/site", json={"name": "Outro"}).status_code == 403
    assert c["ana"].delete("/api/projects/site").status_code == 403


def test_participate_writes_and_deletes_only_own_conversations(world, monkeypatch):
    import deps
    from lib import accessdb
    from services import claude_svc
    c = world.c
    _share(c["admin"], users=[("ana", "participate")])
    r = c["ana"].post("/api/files/mkdir", json={"src": "project:site", "path": str(world.pasta / "nova")})
    assert r.status_code == 200, r.text
    assert c["ana"].post("/api/claude/upload", params={"project": "site"},
                         files={"file": ("a.txt", b"x")}).status_code == 200
    gone = []
    monkeypatch.setattr(claude_svc, "delete_project_session", lambda sid, cwd: gone.append(sid))
    accessdb.set_claude_owner(deps.db_file(), "s-admin", "admin")
    accessdb.set_claude_owner(deps.db_file(), "s-ana", "ana")
    assert c["ana"].delete("/api/claude/sessions/s-admin", params={"project": "site"}).status_code == 403
    assert c["ana"].delete("/api/claude/sessions/s-ana", params={"project": "site"}).status_code == 204
    assert gone == ["s-ana"]
    assert c["ana"].get("/api/projects/site/shares").status_code == 403


def test_manage_shares_but_never_touches_the_owner(world):
    c = world.c
    _share(c["admin"], users=[("ana", "manage")])
    assert _share(c["ana"], users=[("ana", "manage"), ("bia", "view")]).status_code == 200
    assert _ids(c["bia"]) == ["site"]
    r = _share(c["ana"], users=[("ana", "manage"), ("bia", "owner")])
    assert r.status_code == 422 and r.json()["error"] == "bad_share"
    r = _share(c["ana"], users=[("admin", "view")])
    assert r.status_code == 422 and r.json()["error"] == "owner_share"
    assert c["ana"].put("/api/projects/site/owner", json={"username": "ana"}).status_code == 403
    assert c["ana"].patch("/api/projects/site", json={"name": "Novo"}).json()["name"] == "Novo"
    assert c["ana"].delete("/api/projects/site").status_code == 403


def test_group_share_and_highest_level_wins(world):
    c = world.c
    assert _share(c["admin"], users=[("ana", "manage")], groups=[("dev", "view")]).status_code == 200
    assert c["bia"].get("/api/projects/site").json()["my_level"] == "view"
    assert c["ana"].get("/api/projects/site").json()["my_level"] == "manage"
    eff = {e["username"]: e for e in c["admin"].get("/api/projects/site/shares").json()["effective"]}
    assert eff["admin"]["level"] == "owner"
    assert eff["ana"]["level"] == "manage" and set(eff["ana"]["via"]) == {"direct", "group:dev"}
    assert eff["bia"]["via"] == ["group:dev"]
    # leaving the group removes the access right away
    r = c["admin"].patch("/api/users/bia", json={"groups": []})
    assert r.status_code == 200, r.text
    assert c["bia"].get("/api/projects/site").status_code in (403, 404)


def test_deleted_user_and_group_do_not_leave_access_behind(world):
    c = world.c
    _share(c["admin"], users=[("ana", "participate")], groups=[("dev", "view")])
    assert c["admin"].delete("/api/users/ana").status_code == 204
    assert c["admin"].delete("/api/access-groups/dev").status_code == 204
    sh = c["admin"].get("/api/projects/site/shares").json()
    assert sh["users"] == [] and sh["groups"] == []
    # same username again: starts with nothing
    assert c["admin"].post("/api/access-groups", json={"name": "dev", "permissions": ["claude.use"]}).status_code == 201
    _mk_user(c["admin"], "ana", ["dev"])
    ana = _bare()
    _login(ana, "ana", PW)
    assert _ids(ana) == []


def test_removed_and_recreated_project_is_private_again(world):
    c = world.c
    _share(c["admin"], users=[("ana", "participate")])
    assert c["admin"].delete("/api/projects/site").status_code == 204
    assert c["admin"].post("/api/projects", json={"name": "Site", "path": str(world.pasta)}).status_code == 200
    assert _ids(c["ana"]) == []


def test_stale_rev_is_a_conflict(world):
    c = world.c
    rev = c["admin"].get("/api/projects/site/shares").json()["rev"]
    assert c["admin"].put("/api/projects/site/shares", json={"rev": rev, "users": [{"username": "ana", "level": "view"}]}).status_code == 200
    r = c["admin"].put("/api/projects/site/shares", json={"rev": rev, "users": []})
    assert r.status_code == 409


def test_transfer_ownership(world):
    c = world.c
    r = c["admin"].put("/api/projects/site/owner", json={"username": "ana", "keep": "participate"})
    assert r.status_code == 200, r.text
    assert c["ana"].get("/api/projects/site").json()["my_level"] == "owner"
    assert c["admin"].get("/api/projects/site").json()["my_level"] == "participate"
    assert c["ana"].delete("/api/projects/site").status_code == 204


def test_admin_override_is_audited(world):
    import deps
    from lib import accessdb
    c = world.c
    allp = c["adm2"].get("/api/projects", params={"all": "1"}).json()["projects"]
    assert [(p["id"], p["admin_view"], p["owner"]) for p in allp] == [("site", True, "admin")]
    assert c["ana"].get("/api/projects", params={"all": "1"}).json()["projects"] == []   # not admin: ignored
    assert c["adm2"].get("/api/projects/site").status_code == 404
    assert c["ana"].post("/api/projects/site/admin-access").status_code == 403
    r = c["adm2"].post("/api/projects/site/admin-access")
    assert r.status_code == 200
    p = c["adm2"].get("/api/projects/site").json()
    assert p["my_level"] == "owner" and p["admin_view"] is True and p["override_until"]
    assert _ids(c["adm2"]) == []    # the override never puts it in the sidebar
    acts = {a["action"] for a in accessdb.query_audit(deps.db_file(), username="adm2")["items"]}
    assert {"project_admin_list", "project_admin_override"} <= acts


def test_projects_create_permission_only_new_folder_in_default_base(world, monkeypatch, tmp_path):
    from lib import accessdb
    from services import projects_svc
    base = tmp_path.parent / (tmp_path.name + "-base")
    monkeypatch.setattr(projects_svc, "DEFAULT_BASE", str(base))
    assert "projects.create" in accessdb.GRANTABLE and "projects.manage" in accessdb.ADMIN_ONLY
    c = world.c
    assert c["ana"].post("/api/projects", json={"name": "Meu", "path": str(base), "new_folder": "meu"}).status_code == 403
    assert c["admin"].patch("/api/access-groups/dev", json={"permissions": ["claude.use", "projects.create"]}).status_code == 200
    r = c["ana"].post("/api/projects", json={"name": "Existente", "path": str(world.pasta)})
    assert r.status_code == 403 and r.json()["error"] == "create_new_only"
    r = c["ana"].post("/api/projects", json={"name": "Fora", "path": str(world.pasta), "new_folder": "x"})
    assert r.status_code == 403 and r.json()["error"] == "create_base_only"
    r = c["ana"].post("/api/projects", json={"name": "Meu", "path": str(base), "new_folder": "meu"})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == os.path.realpath(base / "meu") and r.json()["my_level"] == "owner"
    assert c["ana"].get("/api/projects/browse", params={"path": "/"}).status_code == 403
    assert c["ana"].get("/api/projects").json()["can_create"] is True
    assert _ids(c["admin"]) == ["site"]      # private to ana, also for the admin


def test_owner_migration_gives_old_projects_to_the_oldest_admin(env, tmp_path):
    import deps
    from lib import accessdb
    from services import project_acl, projects_svc
    pasta = tmp_path.parent / (tmp_path.name + "-old")
    pasta.mkdir()
    projects_svc.create("Velho", str(pasta))         # before any user existed: no owner
    deps.STATE.enable_claude = True
    admin = _bootstrap(env)
    assert accessdb.project_owner(deps.db_file(), "velho") in (None, "admin")
    assert _ids(admin) == ["velho"]
    assert accessdb.project_owner(deps.db_file(), "velho") == "admin"
    # later ownerless projects are NOT auto-assigned again
    accessdb.forget_project(deps.db_file(), "velho")
    project_acl._MIGRATED.clear()
    assert _ids(admin) == []


# --------------------------------------------------------------- live session identity
class _Client:
    def __init__(self):
        self.queries = []
        self.disconnected = False

    async def query(self, text):
        self.queries.append(text)

    async def disconnect(self):
        self.disconnected = True


class _WS:
    query_params = {}

    def __init__(self, inbox, user, readonly=False):
        self.inbox = list(inbox)
        self.state = SimpleNamespace(principal=SimpleNamespace(username=user), readonly=readonly)

    async def receive_json(self):
        from services import claude_svc
        if not self.inbox:
            raise claude_svc.WebSocketDisconnect()
        return self.inbox.pop(0)


def _live(user, cwd=None):
    from services import claude_svc
    s = claude_svc.ClaudeWebSession(user=user, persist=True, cwd=cwd)
    s.client, s._started, s.sid = _Client(), True, "sid-1"
    sent, launches = [], []

    async def capture(ev, only=None, skip=None):
        sent.append(ev)

    async def fake_start():
        launches.append({"user": s.user, "resume": s._resume, "netcap": s._netcap})
        s.client, s._started = _Client(), True
    s._send, s.start = capture, fake_start
    return s, sent, launches


def test_sender_identity_replaces_the_owner_identity(world):
    """Ana (dev group: read only on the network) continues the admin's conversation: the agent relaunches
    on the same conversation as ANA, with her network ceiling, never with the admin's."""
    from lib import accessdb
    import deps
    accessdb.update_group(deps.db_file(), "dev", net_perms=["read"])
    _share(world.c["admin"], users=[("ana", "participate")])

    async def check():
        s, sent, launches = _live("admin", cwd=str(world.pasta))
        assert s._netcap is None
        s._wss = [_WS([], "admin")]
        ws = _WS([{"type": "prompt", "text": "continua"}], "ana")
        await s._ws_pump(ws)
        assert launches == [{"user": "ana", "resume": "sid-1", "netcap": ["read"]}]
        assert s.user == "ana" and s.client.queries == ["continua"]
        assert {"type": "identity", "user": "ana", "name": "Ana"} in sent
        assert all(p in ["read"] for p in s._netperms)
    asyncio.run(check())


def test_other_sender_while_busy_waits_in_queue_and_runs_as_them(world):
    _share(world.c["admin"], users=[("ana", "participate")])

    async def check():
        s, sent, launches = _live("admin", cwd=str(world.pasta))
        s._busy = True
        await s._ws_pump(_WS([{"type": "prompt", "text": "minha vez"}], "ana"))
        assert s.client.queries == [] and s._queue[0]["user"] == "ana" and launches == []
        s._busy = False
        await s._after_turn(False)
        assert launches and launches[0]["user"] == "ana" and s.client.queries == ["minha vez"]
    asyncio.run(check())


def test_view_socket_cannot_send_and_revoked_member_is_blocked(world):
    _share(world.c["admin"], users=[("ana", "view"), ("bia", "participate")])

    async def check():
        s, sent, launches = _live("admin", cwd=str(world.pasta))
        await s._ws_pump(_WS([{"type": "prompt", "text": "oi"}, {"type": "interrupt"}], "ana", readonly=True))
        assert s.client.queries == [] and any(e.get("detail") == "read_only" for e in sent)
        # bia had participate, the owner removes her: the next prompt is refused
        _share(world.c["admin"], users=[("ana", "view")])
        ws = _WS([{"type": "prompt", "text": "ainda posso?"}], "bia")
        await s._ws_pump(ws)
        assert s.client.queries == [] and ws.state.readonly is True and launches == []
    asyncio.run(check())


def test_revalidate_closes_sockets_of_who_lost_access(world):
    from services import claude_svc
    _share(world.c["admin"], users=[("ana", "participate"), ("bia", "participate")])

    async def check():
        s, sent, _ = _live("admin", cwd=os.path.realpath(world.pasta))
        closed = []

        class W(_WS):
            async def close(self, code=None):
                closed.append((self.state.principal.username, code))
        wa, wb = W([], "ana"), W([], "bia")
        s._wss = [wa, wb]
        s._loop = asyncio.get_running_loop()
        claude_svc._LIVE["sid-1"] = s
        try:
            _share(world.c["admin"], users=[("ana", "view")])
            claude_svc.revalidate_project_access(os.path.realpath(world.pasta))
            await asyncio.sleep(0.05)
        finally:
            claude_svc._LIVE.pop("sid-1", None)
        assert wa.state.readonly is True and closed == [("bia", 4403)] and s._wss == [wa]
    asyncio.run(check())


def test_resume_note_keeps_the_last_sender(world):
    async def check():
        s, sent, _ = _live("ana", cwd=str(world.pasta))
        s._busy, s._tracked = True, True
        s._track()
        from services import claude_svc
        assert claude_svc._resume_load()["sid-1"]["user"] == "ana"
    asyncio.run(check())
