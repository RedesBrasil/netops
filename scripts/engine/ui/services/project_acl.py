#!/usr/bin/env python3
"""Who can see and use each Project (private by default, shared with users and access groups).

Levels, in increasing order: view < participate < manage < owner (stored in runs/netops.db, table
`project_shares`, see lib/accessdb.py). The effective level of a user is the highest one among the direct
share and the shares of each of their access groups. The owner is the one who created the project.

- A project is PRIVATE to its owner by default, **admins included**: an admin who is not a member only sees
  it in "All projects (administration)" (`GET /projects?all=1`) and enters with an audited override that
  lasts OVERRIDE_TTL (`POST /projects/<id>/admin-access`).
- Without access the API answers 404 (it never reveals that the project exists); with access but a lower
  level than needed, 403.
- No login (local install without users) or master-password mode = everything, as before.
- `claude.use` is still required: without it nobody opens a project.

This is a CONSOLE boundary, not an OS one: the agent has a shell as the server account (see SKILL.md).
"""
from __future__ import annotations

import threading
import time

import deps
from lib import accessdb, i18n

LEVELS = accessdb.PROJECT_LEVELS
_RANK = {x: i for i, x in enumerate(LEVELS)}
OVERRIDE_TTL = 60 * 60
_OVERRIDES: dict[tuple[str, str], float] = {}
_LOCK = threading.Lock()
_MIGRATED: set[str] = set()
_MIGRATION_KEY = "projects_owner_migration"


class NoAccess(Exception):
    """Not a member (or the project does not exist) -> 404."""


class LowLevel(Exception):
    """Member, but the level is below what the action needs -> 403."""

    def __init__(self, need: str):
        super().__init__(need)
        self.need = need


def at_least(level: str | None, minimum: str) -> bool:
    return bool(level) and _RANK.get(level, -1) >= _RANK[minimum]


def _db():
    return deps.db_file()


def unrestricted(principal) -> bool:
    """No login / master-password mode: the only person is the local admin, nothing is filtered."""
    if not deps.auth_required():
        return True
    return bool(principal is not None and getattr(principal, "legacy", False))


def ensure_owners() -> None:
    """One-time migration: projects registered before sharing existed get the oldest active admin as owner.
    Runs once per database (flag in `meta`); later projects without an owner (owner account deleted) stay
    ownerless on purpose, so an admin decides who takes them over."""
    db = _db()
    key = str(db)
    if key in _MIGRATED:
        return
    try:
        if accessdb.meta_get(db, _MIGRATION_KEY):
            _MIGRATED.add(key)
            return
        if not accessdb.has_users(db):
            return   # no users yet: run when the first admin exists
        admin = accessdb.oldest_admin(db)
        if not admin:
            return
        from services import projects_svc  # noqa: PLC0415 (circular)
        owners = accessdb.project_owners(db)
        for p in projects_svc.registry():
            if p["id"] not in owners:
                accessdb.set_project_owner(db, p["id"], admin, actor="migration", keep_previous=None)
        accessdb.meta_set(db, _MIGRATION_KEY, str(int(time.time())))
        _MIGRATED.add(key)
    except Exception:  # noqa: BLE001 - never break the project list because of the migration
        pass


def _has_override(username: str, pid: str) -> bool:
    with _LOCK:
        exp = _OVERRIDES.get((username, pid))
        if exp is None:
            return False
        if exp < time.time():
            _OVERRIDES.pop((username, pid), None)
            return False
        return True


def grant_override(principal, pid: str) -> float:
    exp = time.time() + OVERRIDE_TTL
    with _LOCK:
        _OVERRIDES[(principal.username, pid)] = exp
    return exp


def override_expires(principal, pid: str) -> float | None:
    if principal is None or not _has_override(principal.username, pid):
        return None
    with _LOCK:
        return _OVERRIDES.get((principal.username, pid))


def drop_overrides(pid: str | None = None) -> None:
    with _LOCK:
        for k in [k for k in _OVERRIDES if pid is None or k[1] == pid]:
            _OVERRIDES.pop(k, None)


def levels_for(principal) -> dict[str, str]:
    """{project_id: level} of every project this person may open (override not included)."""
    ensure_owners()
    from services import projects_svc  # noqa: PLC0415
    if principal is None:
        return {}
    if unrestricted(principal):
        return {p["id"]: "owner" for p in projects_svc.registry()}
    if not principal.can("claude.use"):
        return {}
    return accessdb.project_levels_for(_db(), principal.username, principal.groups)


def level_for(principal, pid: str) -> str | None:
    if principal is None or not pid:
        return None
    if unrestricted(principal):
        from services import projects_svc  # noqa: PLC0415
        return "owner" if projects_svc.get(pid) else None
    lvl = levels_for(principal).get(pid)
    if lvl is None and principal.is_admin and _has_override(principal.username, pid):
        return "owner"
    return lvl


def level_for_username(username: str | None, pid: str) -> str | None:
    """Same as level_for, reading the user again from the database (live sessions, revocation)."""
    from services import authz  # noqa: PLC0415
    if not deps.auth_required():
        return "owner"
    p = authz.principal_for_user(username) if username else None
    return level_for(p, pid)


def require(principal, pid: str, minimum: str = "view") -> str:
    lvl = level_for(principal, pid)
    if lvl is None:
        raise NoAccess(pid)
    if not at_least(lvl, minimum):
        raise LowLevel(minimum)
    return lvl


def project_for_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    from services import projects_svc  # noqa: PLC0415
    for p in projects_svc.registry():
        if p["path"] == str(cwd):
            return p["id"]
    return None


def level_label(level: str) -> str:
    return i18n.t("api_projects.level_" + level)
