#!/usr/bin/env python3
"""Projetos da aba Claude Code — nome + pasta do servidor, e as sessões de cada um.

Só HTTP e gate; a lógica vive em services/projects_svc.py (registro), services/project_acl.py (quem vê e
usa cada projeto) e claude_svc.py (sessões, sempre com `cwd` = pasta do projeto). Mesmo gate do router
claude: `--enable-claude`, e o middleware de app.py já barra escritas em `--read-only`.

Permissions:
- every route needs `claude.use` (services/authz.RULES) and then the LEVEL in the project (project_acl):
  view < participate < manage < owner. A project is private to its owner; sharing adds users and access
  groups. Not a member = 404 (the project's existence is not revealed).
- create = `projects.manage` (admin: any folder) or `projects.create` (only a new folder in the default base);
  trust/restricted mode and browsing server folders = `projects.manage` (admin only), as before.
- admin outside the project: `GET /projects?all=1` and `POST /projects/<id>/admin-access` (audited override).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import deps
from lib import accessdb, i18n
from routers.claude import _visible
from services import authz, claude_models, claude_svc, project_acl, projects_svc

router = APIRouter(tags=["projects"])


def _off():
    return JSONResponse({"error": "claude_disabled"}, status_code=403)


def _err(exc: projects_svc.ProjectError) -> JSONResponse:
    return JSONResponse({"error": exc.code, "detail": str(exc)}, status_code=exc.status)


def _acc_err(exc: accessdb.AccessError) -> JSONResponse:
    return JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=exc.status)


def _not_found() -> JSONResponse:
    return JSONResponse({"error": "project_not_found", "detail": i18n.t("api_common.project_not_found")}, status_code=404)


def _low(need: str) -> JSONResponse:
    return JSONResponse({"error": "project_level", "need": need,
                         "detail": i18n.t("api_projects.level_needed", level=project_acl.level_label(need))},
                        status_code=403)


def _principal(request: Request):
    return authz.request_principal(request)


def _user(request: Request) -> str:
    p = _principal(request)
    return (p.username if p else "") or ""


def _db():
    return deps.db_file()


def _audit(request: Request, action: str, pid: str, detail: str = "") -> None:
    try:
        accessdb.audit(_db(), action, username=_user(request), ip=authz.client_ip(request), target=pid, detail=detail)
    except Exception:  # noqa: BLE001
        pass


def _need(request: Request, pid: str, minimum: str):
    """Level of the requester in `pid`, or a JSONResponse (404/403) to return."""
    try:
        return project_acl.require(_principal(request), pid, minimum)
    except project_acl.NoAccess:
        return _not_found()
    except project_acl.LowLevel as e:
        return _low(e.need)


def _decorate(items: list[dict], request: Request) -> list[dict]:
    """owner / owner_name / share counts (one query each)."""
    db = _db()
    owners = accessdb.project_owners(db) if deps.auth_required() else {}
    names = accessdb.first_names(db, owners.values()) if owners else {}
    out = []
    for p in items:
        sh = accessdb.project_shares(db, p["id"]) if deps.auth_required() else {"users": [], "groups": []}
        o = owners.get(p["id"], "")
        out.append({**p, "owner": o, "owner_name": names.get(o, ""),
                    "shared": {"users": len(sh["users"]), "groups": len(sh["groups"])},
                    "ownerless": deps.auth_required() and not o})
    return out


def _with_level(p: dict, request: Request) -> dict:
    pr = _principal(request)
    lvl = project_acl.level_for(pr, p["id"])
    member = project_acl.levels_for(pr).get(p["id"])
    return {**_decorate([p], request)[0], "my_level": lvl,
            "admin_view": bool(lvl and not member),
            "override_until": project_acl.override_expires(pr, p["id"]) if not member else None}


@router.get("/projects")
def projects_list(request: Request, all: str = ""):  # noqa: A002 - query param name
    """Só os projetos que a pessoa pode abrir, na ordem dela e com `archived` dela.
    `?all=1` (admin) = todos, com `admin_view` nos que não foram compartilhados com ele (auditado)."""
    if not deps.STATE.enable_claude:
        return _off()
    pr = _principal(request)
    levels = project_acl.levels_for(pr)
    show_all = all in ("1", "true") and pr.is_admin and deps.auth_required()
    if show_all:
        _audit(request, "project_admin_list", "*")
        items = [{**p, "my_level": levels.get(p["id"]) or project_acl.level_for(pr, p["id"]),
                  "admin_view": p["id"] not in levels}
                 for p in projects_svc.list_for(_user(request))]
    else:
        items = projects_svc.list_for(_user(request), levels)
    return {"projects": _decorate(items, request),
            # conta do agente só nos settings do NetOps = sessões de projeto não a acham (ver claude_models)
            "account_warning": claude_models.account_only_in_netops(),
            # base sugerida p/ "criar pasta nova" (~/projects da conta do console); a UI não a fixa no código
            "default_base": projects_svc.DEFAULT_BASE,
            "can_create": pr.can("projects.manage") or pr.can("projects.create"),
            "can_pick_folder": pr.can("projects.manage")}


@router.post("/projects")
def projects_create(body: dict, request: Request):
    """projects.manage = any allowed folder; projects.create = only a new folder in the default base."""
    if not deps.STATE.enable_claude:
        return _off()
    pr = _principal(request)
    if not pr.username or not pr.can("claude.use"):
        raise authz.Forbidden("claude.use")
    full = pr.can("projects.manage")
    if not full and not pr.can("projects.create"):
        raise authz.Forbidden("projects.create")
    try:
        owner = pr.username if deps.auth_required() and not pr.legacy else None
        out = projects_svc.create(body.get("name"), body.get("path"), trust=bool(body.get("trust")) and full,
                                  new_folder=(body.get("new_folder") or None), owner=owner, restricted=not full)
    except projects_svc.ProjectError as e:
        return _err(e)
    _audit(request, "project_create", out["id"], out["path"])
    return {**out, "my_level": "owner"}


@router.put("/projects/order")
def projects_order(body: dict, request: Request):
    """Ordem da lista (arrastar e soltar) — preferência do usuário. body: {ids: [...]}"""
    if not deps.STATE.enable_claude:
        return _off()
    try:
        projects_svc.set_order(_user(request), body.get("ids"))
    except projects_svc.ProjectError as e:
        return _err(e)
    return {"projects": _decorate(projects_svc.list_for(_user(request), project_acl.levels_for(_principal(request))),
                                  request)}


@router.put("/projects/{pid}/archived")
def projects_archive(pid: str, body: dict, request: Request):
    """Arquiva/desarquiva SÓ para este usuário (some da barra lateral). body: {archived: bool}"""
    if not deps.STATE.enable_claude:
        return _off()
    lvl = _need(request, pid, "view")
    if isinstance(lvl, JSONResponse):
        return lvl
    try:
        return _with_level(projects_svc.set_archived(_user(request), pid, bool(body.get("archived"))), request)
    except projects_svc.ProjectError as e:
        return _err(e)


# Antes de /projects/{pid}: "browse" não pode ser lido como id de projeto.
@router.get("/projects/browse")
def projects_browse(path: str = "", hidden: bool = False):
    if not deps.STATE.enable_claude:
        return _off()
    try:
        return projects_svc.browse(path, hidden)
    except projects_svc.ProjectError as e:
        return _err(e)


@router.get("/projects/{pid}")
def projects_get(pid: str, request: Request):
    if not deps.STATE.enable_claude:
        return _off()
    lvl = _need(request, pid, "view")
    if isinstance(lvl, JSONResponse):
        return lvl
    p = next((x for x in projects_svc.list_for(_user(request)) if x["id"] == pid), None)
    return _with_level(p, request) if p else _not_found()


@router.patch("/projects/{pid}")
def projects_update(pid: str, body: dict, request: Request):
    """body: {name?} renomeia (manage); {trusted: bool} marca/desmarca a pasta como confiável (admin)."""
    if not deps.STATE.enable_claude:
        return _off()
    if "trusted" in body and not _principal(request).can("projects.manage"):
        raise authz.Forbidden("projects.manage")
    lvl = _need(request, pid, "manage" if "name" in body else "view")
    if isinstance(lvl, JSONResponse):
        return lvl
    try:
        out = None
        if "name" in body:
            out = projects_svc.rename(pid, body.get("name"))
            _audit(request, "project_rename", pid, out["name"])
        if "trusted" in body:
            out = projects_svc.set_trusted(pid, bool(body.get("trusted")))
            _audit(request, "project_trust", pid, "trusted" if out["trusted"] else "restricted")
        if out is None:
            return JSONResponse({"error": "nothing_to_update", "detail": i18n.t("api_common.nothing_to_update")}, status_code=400)
        return _with_level(out, request)
    except projects_svc.ProjectError as e:
        return _err(e)


@router.delete("/projects/{pid}", status_code=204)
def projects_delete(pid: str, request: Request):
    """Remove o registro (pasta e conversas ficam). Dono ou admin."""
    if not deps.STATE.enable_claude:
        return _off()
    pr = _principal(request)
    if not pr.is_admin:
        lvl = _need(request, pid, "owner")
        if isinstance(lvl, JSONResponse):
            return lvl
    cwd = projects_svc.path_of(pid)
    if not projects_svc.delete(pid):
        return _not_found()
    _audit(request, "project_delete", pid)
    claude_svc.revalidate_project_access(cwd)


@router.get("/projects/{pid}/sessions")
def projects_sessions(pid: str, request: Request):
    if not deps.STATE.enable_claude:
        return _off()
    lvl = _need(request, pid, "view")
    if isinstance(lvl, JSONResponse):
        return lvl
    cwd = projects_svc.path_of(pid)
    if not cwd:
        return _not_found()
    return {"sessions": _visible(request, claude_svc.list_project_sessions(cwd=cwd), everyone=True)}


@router.get("/projects/{pid}/sessions/search")
def projects_sessions_search(pid: str, request: Request, q: str = ""):
    if not deps.STATE.enable_claude:
        return _off()
    lvl = _need(request, pid, "view")
    if isinstance(lvl, JSONResponse):
        return lvl
    cwd = projects_svc.path_of(pid)
    if not cwd:
        return _not_found()
    return {"sessions": _visible(request, claude_svc.search_project_sessions(q, cwd=cwd), everyone=True)}


# ------------------------------------------------------------------ sharing
def _has_claude(perms) -> bool:
    return "*" in perms or "claude.use" in perms


def _shares_payload(pid: str) -> dict:
    db = _db()
    sh = accessdb.project_shares(db, pid)
    users = {u["username"]: u for u in accessdb.list_users(db)}
    groups = {g["name"]: g for g in accessdb.list_groups(db)}

    def user_info(name):
        u = users.get(name) or {}
        eff = accessdb.effective(db, name)
        return {"username": name, "display_name": u.get("display_name") or name,
                "disabled": bool(u.get("disabled")), "missing": not u,
                "has_claude": bool(eff and (eff["is_admin"] or "claude.use" in eff["permissions"]))}

    def name_of(x):
        return (users.get(x) or {}).get("display_name") or x if x else ""

    out_users = [{**user_info(x["username"]), "level": x["level"], "granted_by": x["granted_by"],
                  "granted_by_name": name_of(x["granted_by"]), "granted_at": x["granted_at"]} for x in sh["users"]]
    out_groups = []
    for x in sh["groups"]:
        g = groups.get(x["name"]) or {}
        out_groups.append({"name": x["name"], "description": g.get("description") or "",
                           "members": len(g.get("members") or []), "level": x["level"],
                           "has_claude": _has_claude(g.get("permissions") or []),
                           "granted_by": x["granted_by"], "granted_by_name": name_of(x["granted_by"]),
                           "granted_at": x["granted_at"]})
    # Effective access: every final user, the resulting level and where it comes from.
    rank = {v: i for i, v in enumerate(project_acl.LEVELS)}
    eff: dict[str, dict] = {}

    def add(name, level, via):
        e = eff.setdefault(name, {**user_info(name), "level": level, "via": []})
        e["via"].append(via)
        if rank[level] > rank[e["level"]]:
            e["level"] = level
    if sh["owner"]:
        add(sh["owner"], "owner", "owner")
    for x in sh["users"]:
        add(x["username"], x["level"], "direct")
    for x in sh["groups"]:
        for m in (groups.get(x["name"]) or {}).get("members") or []:
            add(m, x["level"], "group:" + x["name"])
    owner = sh["owner"]
    return {"rev": sh["rev"], "owner": ({**user_info(owner)} if owner else None),
            "users": out_users, "groups": out_groups,
            "effective": sorted(eff.values(), key=lambda e: (-rank[e["level"]], e["display_name"].lower()))}


@router.get("/projects/{pid}/shares")
def projects_shares(pid: str, request: Request):
    if not deps.STATE.enable_claude:
        return _off()
    lvl = _need(request, pid, "manage")
    if isinstance(lvl, JSONResponse):
        return lvl
    return {**_shares_payload(pid), "my_level": lvl}


@router.get("/projects/{pid}/shares/candidates")
def projects_share_candidates(pid: str, request: Request, q: str = ""):
    if not deps.STATE.enable_claude:
        return _off()
    lvl = _need(request, pid, "manage")
    if isinstance(lvl, JSONResponse):
        return lvl
    c = accessdb.share_candidates(_db(), q[:80])
    db = _db()
    for u in c["users"]:
        eff = accessdb.effective(db, u["username"])
        u["has_claude"] = bool(eff and (eff["is_admin"] or "claude.use" in eff["permissions"]))
    for g in c["groups"]:
        g["has_claude"] = _has_claude(g.pop("permissions", []))
    return c


def _fmt_changes(ch: dict) -> list[tuple[str, str]]:
    out = []
    for (kind, name), lvl in ch["added"]:
        out.append(("project_share_add", f"{kind}:{name}={lvl}"))
    for (kind, name), lvl in ch["removed"]:
        out.append(("project_share_remove", f"{kind}:{name} (was {lvl})"))
    for (kind, name), old, lvl in ch["changed"]:
        out.append(("project_share_level", f"{kind}:{name} {old}->{lvl}"))
    return out


@router.put("/projects/{pid}/shares")
def projects_shares_put(pid: str, body: dict, request: Request):
    """body: {rev, users: [{username, level}], groups: [{name, level}]} — replaces the whole list (not the owner).
    manage can grant up to manage; the owner is changed only by PUT /owner."""
    if not deps.STATE.enable_claude:
        return _off()
    if not deps.auth_required():
        return JSONResponse({"error": "sharing_needs_login", "detail": i18n.t("api_projects.sharing_needs_login")},
                            status_code=400)
    lvl = _need(request, pid, "manage")
    if isinstance(lvl, JSONResponse):
        return lvl
    try:
        ch = accessdb.replace_project_shares(_db(), pid, body.get("users") or [], body.get("groups") or [],
                                             actor=_user(request), rev=body.get("rev"))
    except accessdb.AccessError as e:
        return _acc_err(e)
    for action, detail in _fmt_changes(ch):
        _audit(request, action, pid, detail)
    cwd = projects_svc.path_of(pid)
    if cwd:
        claude_svc.revalidate_project_access(cwd)
    return {**_shares_payload(pid), "my_level": project_acl.level_for(_principal(request), pid)}


@router.put("/projects/{pid}/owner")
def projects_owner_put(pid: str, body: dict, request: Request):
    """Transfer ownership (owner or admin). body: {username, keep: "manage"|"participate"|"view"|"none"}"""
    if not deps.STATE.enable_claude:
        return _off()
    if not deps.auth_required():
        return JSONResponse({"error": "sharing_needs_login", "detail": i18n.t("api_projects.sharing_needs_login")},
                            status_code=400)
    pr = _principal(request)
    if not pr.is_admin:
        lvl = _need(request, pid, "owner")
        if isinstance(lvl, JSONResponse):
            return lvl
    elif not projects_svc.get(pid):
        return _not_found()
    keep = body.get("keep", "manage")
    keep = None if keep in (None, "none", "") else keep
    if keep not in (None, "view", "participate", "manage"):
        return JSONResponse({"error": "bad_share", "detail": i18n.t("lib_accessdb.bad_share")}, status_code=422)
    db = _db()
    prev = accessdb.project_owner(db, pid) or ""
    try:
        accessdb.set_project_owner(db, pid, body.get("username") or "", actor=pr.username, keep_previous=keep)
    except accessdb.AccessError as e:
        return _acc_err(e)
    _audit(request, "project_owner_transfer", pid, f"{prev or '-'} -> {accessdb.project_owner(db, pid)} (keep={keep})")
    cwd = projects_svc.path_of(pid)
    if cwd:
        claude_svc.revalidate_project_access(cwd)
    return {**_shares_payload(pid), "my_level": project_acl.level_for(pr, pid)}


@router.post("/projects/{pid}/admin-access")
def projects_admin_access(pid: str, request: Request):
    """Admin outside the project: full access for OVERRIDE_TTL, recorded in the audit log."""
    if not deps.STATE.enable_claude:
        return _off()
    pr = _principal(request)
    if not pr.is_admin:
        raise authz.Forbidden("server.admin")
    if not projects_svc.get(pid):
        return _not_found()
    exp = project_acl.grant_override(pr, pid)
    _audit(request, "project_admin_override", pid, f"until {int(exp)}")
    return {"id": pid, "until": exp}
