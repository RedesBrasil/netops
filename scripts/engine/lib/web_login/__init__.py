#!/usr/bin/env python3
"""Login web automático por vendor/app — registro único usado pelo console (botão "Acessar → Web").

Cada app (proxmox, zabbix, ...) é um provedor em web_login/<app>.py com a interface de base.py.
Para suportar um app novo: crie o módulo, registre abaixo e declare `app: <nome>` no extra_access do
host (ou deixe o vendor casar, ver APP_BY_VENDOR). App sem provedor = só abre a URL (login manual).

Segurança: o login roda no SERVIDOR (credencial resolvida só lá). O navegador recebe apenas o
`Handoff` (formulário a enviar para o host). Ver constitution.md §VII (exceção Zabbix).
"""
from __future__ import annotations

from .base import Handoff, WebLoginError, WebLoginProvider, WebTarget  # noqa: F401
from .proxmox import ProxmoxProvider
from .zabbix import ZabbixProvider

REGISTRY: dict[str, WebLoginProvider] = {p.app: p for p in (ProxmoxProvider(), ZabbixProvider())}
APP_BY_VENDOR = {"proxmox": "proxmox"}      # vendor do host -> app, quando o extra_access não declara `app`


def provider_for(app: str | None) -> WebLoginProvider | None:
    return REGISTRY.get((app or "").lower())
