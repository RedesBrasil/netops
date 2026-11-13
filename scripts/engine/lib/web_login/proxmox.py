"""Proxmox VE: ticket pela API JSON; a aba recebe o ticket (NUNCA a senha) via POST em /api2/html/access/ticket.

O PVE responde 301 com `Set-Cookie: PVEAuthCookie` (path=/; secure) e a aba fica logada.
Um ticket válido é aceito como "senha" para renovar a sessão do mesmo usuário. 2FA não é suportado.
"""
from __future__ import annotations

from .base import Handoff, WebLoginError, WebTarget, post


class ProxmoxProvider:
    app = "proxmox"

    def launch(self, target: WebTarget, username: str, password: str) -> Handoff:
        user = username if "@" in username else f"{username}@pam"
        resp = post(f"{target.base}/api2/json/access/ticket", data={"username": user, "password": password})
        if resp.status_code in (401, 403):
            raise WebLoginError("Proxmox recusou a credencial (usuário/senha/realm)")
        if resp.status_code != 200:
            raise WebLoginError(f"Proxmox respondeu HTTP {resp.status_code}", "unreachable")
        try:
            data = resp.json()["data"]
            ticket = data["ticket"]
        except (ValueError, KeyError, TypeError) as exc:
            raise WebLoginError("resposta inesperada do Proxmox (não parece a API do PVE)", "unreachable") from exc
        if data.get("NeedTFA") or str(ticket).startswith("PVE:!tfa!"):
            raise WebLoginError("usuário com 2FA: login automático não suportado — entre manualmente", "unsupported")
        return Handoff(mode="form_post", action=f"{target.base}/api2/html/access/ticket",
                       fields={"username": user, "password": ticket},
                       then_url=target.base + "/", then_delay_ms=1500)
