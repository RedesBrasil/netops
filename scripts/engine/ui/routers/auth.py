#!/usr/bin/env python3
"""Login do console com a senha-mestra do cofre (sessão própria, em memória do processo).

A senha-mestra é verificada pelo MESMO caminho do cofre (derive_key + verify_key) e nunca é
gravada, logada nem devolvida. No sucesso cria uma sessão de login (sid aleatório, header
`X-Netops-Session`) e — se o servidor permitir (sem --no-vault-unlock) — destranca o cofre na
mesma ação. O gate que exige o sid em todo /api vive no middleware de app.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import deps
from models import VaultUnlock

router = APIRouter(tags=["auth"])

SESSION_HEADER = "x-netops-session"


@router.get("/auth/status")
def auth_status(request: Request) -> dict:
    """Estado do gate de login — alcançável só com o token (allow-list do middleware)."""
    return {
        "auth_required": deps.auth_required(),
        "authenticated": deps.auth_session_valid(request.headers.get(SESSION_HEADER)),
        "vault_initialized": deps.vault_initialized(),
    }


@router.post("/auth/login")
def auth_login(body: VaultUnlock):
    """Verifica a senha-mestra e emite uma sessão de login. Também destranca o cofre."""
    if not deps.auth_required():
        return JSONResponse(
            {"error": "no_auth", "detail": "Cofre não inicializado — não há login a fazer."},
            status_code=400,
        )
    import yaml  # noqa: PLC0415
    from lib import vault, vault_session  # noqa: PLC0415

    data = yaml.safe_load(deps.CREDS_FILE.read_text(encoding="utf-8")) or {}
    meta = vault.load_meta(data)  # VaultNotInitialized -> 409 (handler em app.py)
    try:
        key = vault.derive_key(body.master_password, meta)
        vault.verify_key(key, meta)
    except vault.VaultWrongKey:
        return JSONResponse({"error": "bad_password", "detail": "Senha mestra incorreta."}, status_code=401)
    sid = deps.create_auth_session()  # login: 7 dias, persistido (sobrevive a restart)
    if deps.STATE.allow_vault_unlock:
        vault_session.set_session_key(key, body.ttl or vault_session.default_ttl())  # mesma sessão da CLI/agentes
    return {"auth_token": sid}


@router.post("/auth/logout")
def auth_logout(request: Request) -> dict:
    """Encerra a sessão de login. NÃO tranca o cofre (lock é ação explícita, na aba Terminal)."""
    deps.drop_auth_session(request.headers.get(SESSION_HEADER))
    return {"ok": True}
