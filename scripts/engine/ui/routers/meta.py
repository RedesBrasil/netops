#!/usr/bin/env python3
"""Endpoints de metadados: enums (do schema) e status do cofre (sem renovar o TTL)."""
from __future__ import annotations

import json
import os
from update.common import read_version

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import deps
from models import VaultUnlock

router = APIRouter(tags=["meta"])


@router.get("/meta/enums")
def enums() -> dict:
    """Valores de enum p/ os dropdowns da UI — derivados do schema (nunca hardcoded)."""
    schema = json.loads(deps.SCHEMA_FILE.read_text(encoding="utf-8"))
    node = schema["$defs"]["nodeFields"]["properties"]
    access = node["access"]["properties"]
    return {
        "vendor": node["vendor"]["enum"],
        "role": node["role"]["enum"],
        "method": access["method"]["enum"],
        "vendors_knowledge": list(deps.VENDORS),
    }


@router.get("/meta/icons")
def host_icons() -> dict:
    """Ícones locais disponíveis para o seletor de host."""
    from services import icons_svc
    return icons_svc.choices()

@router.get("/vault/status")
def vault_status() -> dict:
    """Estado do cofre. USA session_status() — NÃO renova o TTL deslizante.

    Estados: cache (com expires_in), env, locked, insecure.
    """
    from lib import vault_session  # noqa: PLC0415
    st = dict(vault_session.session_status())
    st["writable_secrets"] = st.get("state") in ("cache", "env")
    st["allow_unlock"] = deps.STATE.allow_vault_unlock
    if st.get("state") in ("locked", "insecure"):
        st["unlock_cmd"] = "cd /opt/netops && .venv/bin/python3 scripts/engine/vault/cli.py unlock"
    return st


@router.post("/vault/unlock")
def vault_unlock(body: VaultUnlock):
    """Destranca o cofre: deriva a chave da senha-mestra (Argon2id) e grava a sessão.

    É o MESMO caminho do `cli.py unlock` (derive_key -> verify_key -> set_session_key),
    então a sessão vale tanto para a UI quanto para os agentes/CLI. A senha-mestra é usada
    só aqui e descartada — nunca é gravada, logada nem devolvida. NÃO devolve plaintext.
    """
    if not deps.STATE.allow_vault_unlock:
        return JSONResponse(
            {"error": "unlock_disabled",
             "detail": "Destrancar pela web está desabilitado (--no-vault-unlock). Use o terminal."},
            status_code=403,
        )
    import yaml  # noqa: PLC0415
    from lib import vault, vault_session  # noqa: PLC0415

    if not deps.CREDS_FILE.exists():
        return JSONResponse(
            {"error": "vault_uninitialized", "detail": "credentials.yaml não existe.",
             "action": "python scripts/engine/vault/cli.py init"},
            status_code=409,
        )
    data = yaml.safe_load(deps.CREDS_FILE.read_text(encoding="utf-8")) or {}
    meta = vault.load_meta(data)  # VaultNotInitialized -> 409 (handler)
    try:
        key = vault.derive_key(body.master_password, meta)
        vault.verify_key(key, meta)  # VaultWrongKey se a senha estiver errada
    except vault.VaultWrongKey:
        return JSONResponse({"error": "vault_wrong_key", "detail": "Senha mestra incorreta."}, status_code=401)
    vault_session.set_session_key(key, body.ttl or vault_session.default_ttl())
    return vault_status()


@router.post("/vault/lock")
def vault_lock():
    """Tranca a sessão (apaga o cache da chave). Ação positiva de segurança."""
    from lib import vault_session  # noqa: PLC0415
    vault_session.clear_session()
    return vault_status()


@router.get("/config/meta")
def config_meta() -> dict:
    """Infos leves p/ o topo da UI: nome da rede + modo do servidor."""
    import yaml  # noqa: PLC0415
    from services import host_migration_svc
    network_name = "NetOps"
    if deps.PROJECT_CONFIG.exists():
        try:
            cfg = yaml.safe_load(deps.PROJECT_CONFIG.read_text(encoding="utf-8")) or {}
            network_name = ((cfg.get("project") or {}).get("network_name")) or network_name
        except Exception:
            pass
    return {
        "network_name": network_name,
        "version": read_version(deps.NETOPS_ROOT),
        "boot_id": os.environ.get("NETOPS_UPDATE_NONCE", ""),
        "read_only": deps.STATE.read_only,
        "isolated_data": deps.DATA_ROOT != deps.NETOPS_ROOT,
        "terminal_enabled": deps.STATE.enable_terminal,
        "claude_enabled": deps.STATE.enable_claude,
        "host_migration": host_migration_svc.status(),
    }
