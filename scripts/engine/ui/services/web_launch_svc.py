#!/usr/bin/env python3
"""Acessar → Web: abre a interface web de um host já autenticada (Proxmox, Zabbix, ...).

O cliente manda ID + método + porta (nunca IP/URL livre); o destino sai do inventário. A credencial é
resolvida AQUI (cofre destrancado) e o login roda no servidor via lib/web_login. O navegador recebe só
o `Handoff` (formulário a enviar para o host). Proxmox: ticket, não a senha. Zabbix: a senha vai ao
navegador (exceção em constitution.md §VII). Auditoria em runs/<ts>-web-<id>/launch.log, sem segredos.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import deps
from lib import i18n

from lib.terminal_access import TargetError, web_entries  # noqa: E402
from lib.web_login import APP_BY_VENDOR, WebLoginError, WebTarget, provider_for  # noqa: E402,F401
from services import host_term_svc


class LaunchError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "error"):
        super().__init__(message)
        self.status, self.code = status, code


def _audit(host: dict, entry: dict, result: str) -> None:
    try:
        now = datetime.now(timezone.utc)
        d = Path(deps.NETOPS_ROOT) / "runs" / f"{now:%Y%m%dT%H%M%SZ}-web-{host.get('id')}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "launch.log").write_text(
            f"{now.isoformat()} host={host.get('hostname')} ip={host.get('mgmt_ip')} "
            f"{entry['method']}:{entry['port']} app={entry.get('app') or '-'} -> {result}\n", encoding="utf-8")
    except OSError:
        pass


def _launch_sync(host_id: str, method: str | None, port: int | None) -> dict:
    try:
        host, entry, cred, note, locked = host_term_svc.resolve_target(host_id, method, port, entries_fn=web_entries)
    except TargetError as exc:
        raise LaunchError(str(exc), 404 if getattr(exc, "not_found", False) or "inventário" in str(exc) else 400,
                          "bad_target") from exc
    target = WebTarget(entry["method"], host["mgmt_ip"], entry["port"], entry.get("path") or "/")
    provider = provider_for(entry.get("app"))
    manual = {"mode": "open", "then_url": target.url, "then_delay_ms": 0}
    if provider is None:
        _audit(host, entry, "abre URL (app sem login automático)")
        return {**manual, "note": i18n.t("api_web_launch.no_autologin")}
    if locked:
        raise LaunchError(i18n.t("api_web_launch.vault_locked"), 423, "vault_locked")
    if not (cred.get("username") and cred.get("password")):
        _audit(host, entry, "abre URL (sem credencial)")
        return {**manual, "note": note or i18n.t("api_web_launch.no_credential")}
    try:
        handoff = provider.launch(target, cred["username"], cred["password"])
    except WebLoginError as exc:
        _audit(host, entry, f"FALHOU {exc.code}: {exc}")
        raise LaunchError(str(exc), 502 if exc.code == "unreachable" else 401 if exc.code == "auth" else 422, exc.code) from exc
    _audit(host, entry, f"ok mode={handoff.mode}")
    return {"mode": handoff.mode, "action": handoff.action, "fields": handoff.fields, "then_url": handoff.then_url,
            "then_delay_ms": handoff.then_delay_ms, "note": handoff.note, "host": host.get("hostname"), "app": provider.app}


async def launch(host_id: str, method: str | None, port: int | None) -> dict:
    return await asyncio.to_thread(_launch_sync, host_id, method, port)
