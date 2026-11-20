#!/usr/bin/env python3
"""Login do console por USUÁRIO + senha (banco de acesso SQLite, lib/accessdb.py).

Modos:
- **Sem usuários cadastrados** (instalação antiga): login com a senha-mestra do cofre, como sempre.
  O 1º login bem-sucedido cria o usuário `admin` (grupo admin, com o e-mail informado na tela) com essa
  senha e um keyslot do cofre —
  a partir daí o console é multiusuário.
- **Com usuários**: `{email, password}` (o login é o E-MAIL; `username`=ID interno ainda aceito). Se o usuário tem keyslot, o login também destranca o
  cofre (a chave do cofre fica embrulhada pela senha dele). Sem keyslot, ele é criado sozinho
  quando o usuário entra com o cofre já destrancado (usuário novo, troca de senha-mestra).

Senhas nunca são gravadas, logadas nem devolvidas. Throttle por usuário+IP e por IP.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import deps
from lib import i18n
from lib import accessdb
from services import authz

router = APIRouter(tags=["auth"])

SESSION_HEADER = "x-netops-session"


class LoginBody(BaseModel):
    model_config = {"extra": "forbid"}
    email: Optional[str] = Field(default=None, max_length=120)          # login padrão
    username: Optional[str] = Field(default=None, max_length=120)       # ID interno (ou e-mail) — compat
    password: Optional[str] = Field(default=None, max_length=1024)
    master_password: Optional[str] = Field(default=None, max_length=1024)   # modo legado
    ttl: Optional[int] = Field(default=None, ge=30, le=86400)              # TTL do cofre destrancado


class PasswordChange(BaseModel):
    model_config = {"extra": "forbid"}
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _vault_meta():
    """Bloco `vault:` do credentials.yaml (None = sem cofre)."""
    if not deps.vault_initialized():
        return None
    import yaml  # noqa: PLC0415
    from lib import vault  # noqa: PLC0415
    data = yaml.safe_load(deps.CREDS_FILE.read_text(encoding="utf-8")) or {}
    return vault.load_meta(data)


def _open_vault_key(meta) -> bytes | None:
    """Chave do cofre JÁ destrancado (sessão), validada contra o verifier atual. Não pede senha."""
    if meta is None:
        return None
    from lib import vault, vault_session  # noqa: PLC0415
    try:
        key = vault_session.get_session_key()
        vault.verify_key(key, meta)
        return key
    except Exception:
        return None


def _unlock_with_slot(username: str, kek: bytes, ttl: int | None) -> str:
    """Destranca o cofre pelo keyslot do usuário (ou cria o slot se o cofre já estiver aberto).
    Retorna o estado: 'unlocked' | 'already' | 'slot_created' | 'no_slot' | 'no_vault' | 'disabled'."""
    meta = _vault_meta()
    if meta is None:
        return "no_vault"
    from lib import vault, vault_session  # noqa: PLC0415
    db = deps.db_file()
    key = accessdb.unwrap_vault_slot(accessdb.get_vault_slot(db, username), kek)
    if key is not None:
        try:
            vault.verify_key(key, meta)
        except Exception:
            key = None          # senha-mestra trocada depois do slot: slot velho
    if key is not None:
        if not deps.STATE.allow_vault_unlock:
            return "disabled"
        vault_session.set_session_key(key, ttl or vault_session.default_ttl())
        return "unlocked"
    open_key = _open_vault_key(meta)
    if open_key is not None:
        accessdb.set_vault_slot(db, username, kek, open_key)
        return "slot_created"
    accessdb.set_vault_slot(db, username, None, None)
    return "no_slot"


@router.get("/auth/status")
def auth_status(request: Request) -> dict:
    """Estado do gate de login — alcançável sem sessão (allow-list do middleware)."""
    return {
        "auth_required": deps.auth_required(),
        "authenticated": deps.auth_session_valid(request.headers.get(SESSION_HEADER)) or (
            not deps.auth_required() and not deps.setup_mode()),
        "vault_initialized": deps.vault_initialized(),
        "multiuser": deps.has_users(),
        "setup_required": deps.setup_mode(),
    }


@router.post("/auth/login")
def auth_login(body: LoginBody, request: Request):
    db = deps.db_file()
    ip = _ip(request)
    ua = request.headers.get("user-agent", "")
    if not deps.auth_required():
        return JSONResponse({"error": "no_auth", "detail": i18n.t("api_auth.no_auth")}, status_code=400)

    if deps.has_users():
        login = (body.email or body.username or "").strip().lower()
        password = body.password or ""
        if not login and body.master_password:
            # Compat: clientes antigos (scripts/testes) mandam só {master_password} = senha do admin migrado.
            login, password = deps.LEGACY_ADMIN, body.master_password
        if not login or not password:
            return JSONResponse({"error": "bad_credentials", "detail": i18n.t("api_auth.email_password_required")}, status_code=401)
        wait = accessdb.login_wait(db, login, ip)
        if wait:
            return JSONResponse({"error": "throttled", "retry_after": wait,
                                 "detail": i18n.t("api_auth.throttled", wait=wait)},
                                status_code=429, headers={"Retry-After": str(wait)})
        try:
            user, kek = accessdb.verify_password(db, login, password)
        except accessdb.WrongPassword:
            accessdb.login_failed(db, login, ip)
            accessdb.audit(db, "login_failed", username=accessdb.login_username(db, login) or "", ip=ip,
                           target=login, detail=ua[:120])
            return JSONResponse({"error": "bad_credentials", "detail": i18n.t("api_auth.bad_credentials")}, status_code=401)
        accessdb.login_ok(db, login, ip)
        username = user["username"]
        vault_state = _unlock_with_slot(username, kek, body.ttl)
        sid = deps.create_auth_session(user=username, ip=ip, user_agent=ua)
        accessdb.record_login(db, username, ip)
        accessdb.audit(db, "login", username=username, ip=ip, detail=f"cofre: {vault_state}")
        return {"auth_token": sid, "user": authz.principal_for_user(username).public(), "vault": vault_state}

    # ---- modo legado: senha-mestra; o 1º login vira o usuário admin ----
    from lib import vault, vault_session  # noqa: PLC0415
    secret = body.master_password or body.password or ""
    if not secret:
        return JSONResponse({"error": "bad_password", "detail": i18n.t("api_auth.master_password_required")}, status_code=401)
    wait = accessdb.login_wait(db, deps.LEGACY_ADMIN, ip)
    if wait:
        return JSONResponse({"error": "throttled", "retry_after": wait,
                             "detail": i18n.t("api_auth.throttled", wait=wait)},
                            status_code=429, headers={"Retry-After": str(wait)})
    meta = _vault_meta()   # VaultNotInitialized -> 409 (handler em app.py)
    if meta is None:
        return JSONResponse({"error": "vault_uninitialized", "detail": i18n.t("api_auth.vault_uninitialized")}, status_code=409)
    try:
        key = vault.derive_key(secret, meta)
        vault.verify_key(key, meta)
    except vault.VaultWrongKey:
        accessdb.login_failed(db, deps.LEGACY_ADMIN, ip)
        accessdb.audit(db, "login_failed", username=deps.LEGACY_ADMIN, ip=ip, detail="senha-mestra")
        return JSONResponse({"error": "bad_password", "detail": i18n.t("api_auth.wrong_master_password")}, status_code=401)
    accessdb.login_ok(db, deps.LEGACY_ADMIN, ip)
    created = False
    try:
        accessdb.create_user(db, deps.LEGACY_ADMIN, secret, display_name="Administrador",
                             email=body.email or "", groups=[accessdb.ADMIN_GROUP],
                             created_by="migração (senha-mestra)", vault_key=key)
        created = True
    except accessdb.AccessError as exc:
        # Senha-mestra curta demais p/ a política: segue no modo legado (o admin cria o usuário na tela).
        if exc.code == "invalid_email":
            return JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=422)
        if exc.code not in ("weak_password", "exists"):
            raise
    if deps.STATE.allow_vault_unlock:
        vault_session.set_session_key(key, body.ttl or vault_session.default_ttl())
    sid = deps.create_auth_session(user=deps.LEGACY_ADMIN, ip=ip, user_agent=ua)
    if created:
        accessdb.record_login(db, deps.LEGACY_ADMIN, ip)
    accessdb.audit(db, "bootstrap_admin" if created else "login", username=deps.LEGACY_ADMIN, ip=ip,
                   detail="1º login: usuário admin criado com a senha-mestra" if created else "senha-mestra (legado)")
    p = authz.principal_for_user(deps.LEGACY_ADMIN)
    return {"auth_token": sid, "user": p.public() if p else None, "vault": "unlocked", "bootstrap": created}


@router.post("/auth/logout")
def auth_logout(request: Request) -> dict:
    """Encerra a sessão de login. NÃO tranca o cofre (lock é ação explícita)."""
    sid = request.headers.get(SESSION_HEADER)
    user = deps.auth_session_user(sid)
    deps.drop_auth_session(sid)
    if user:
        accessdb.audit(deps.db_file(), "logout", username=user, ip=_ip(request))
    return {"ok": True}


@router.get("/auth/me")
def auth_me(request: Request) -> dict:
    """Quem sou eu + o que posso (o front esconde menus/botões com isto; o backend é quem bloqueia)."""
    p = authz.request_principal(request)
    out = p.public()
    out["multiuser"] = deps.has_users()
    out["catalog"] = accessdb.localized_permissions()
    from lib import i18n  # noqa: PLC0415
    from routers.i18n import user_locale  # noqa: PLC0415
    out["locale"] = "" if p.legacy else user_locale(p.username)
    out["instance_language"] = i18n.instance_language(deps.DATA_ROOT)
    if deps.has_users() and not p.legacy:
        u = accessdb.get_user(deps.db_file(), p.username)
        if u:
            out.update(email=u["email"], last_login=u["last_login"], vault_slot=u["vault_slot"],
                       password_changed_at=u["password_changed_at"])
            from lib import github_identity as ghid  # noqa: PLC0415
            out["github_login"] = (ghid.get_meta(deps.DATA_ROOT, p.username) or {}).get("login") or ""
    return out


@router.post("/auth/password")
def auth_password(body: PasswordChange, request: Request):
    """Troca a PRÓPRIA senha. Mantém esta sessão, derruba as outras e reembrulha o keyslot."""
    db = deps.db_file()
    p = authz.request_principal(request)
    if not deps.has_users() or p.legacy:
        return JSONResponse({"error": "no_user", "detail": i18n.t("api_auth.no_user")}, status_code=409)
    ip = _ip(request)
    try:
        _user, old_kek = accessdb.verify_password(db, p.username, body.current_password)
    except accessdb.WrongPassword:
        accessdb.login_failed(db, p.username, ip)
        return JSONResponse({"error": "bad_credentials", "detail": i18n.t("api_auth.wrong_current_password")}, status_code=401)
    if body.new_password == body.current_password:
        return JSONResponse({"error": "same_password", "detail": i18n.t("api_auth.same_password")},
                            status_code=422)
    meta = _vault_meta()
    vault_key = accessdb.unwrap_vault_slot(accessdb.get_vault_slot(db, p.username), old_kek) or _open_vault_key(meta)
    if vault_key is not None and meta is not None:
        from lib import vault  # noqa: PLC0415
        try:
            vault.verify_key(vault_key, meta)
        except Exception:
            vault_key = None
    sid = request.headers.get(SESSION_HEADER) or ""
    accessdb.set_password(db, p.username, body.new_password, must_change=False, vault_key=vault_key,
                          keep_sid_hash=accessdb.sid_hash(sid) if sid else None)
    accessdb.audit(db, "password_changed", username=p.username, ip=ip, target=p.username)
    return {"ok": True, "vault_slot": vault_key is not None}
