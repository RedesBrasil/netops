#!/usr/bin/env python3
"""Fábrica de conexões do NetOps.

Decide e abre o transporte certo para cada host, conforme o método de acesso e o fabricante:
  - method=api  + vendor=mikrotik -> librouteros (API RouterOS)
  - method=ssh/telnet              -> Netmiko (camada padrão multi-fabricante)
  - NAPALM                         -> sob demanda, para coleta estruturada/diff

As bibliotecas de rede são importadas de forma PREGUIÇOSA — este módulo importa sem elas
instaladas (permite rodar --help offline).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.vendor_map import netmiko_device_type, resolve_vendor  # noqa: E402

DEFAULT_TIMEOUT = 20


def open_cli(host: dict, cred: dict):
    """Abre uma sessão CLI via Netmiko (SSH ou Telnet, conforme host['access']['method'])."""
    try:
        from netmiko import ConnectHandler
    except ImportError:
        sys.exit("ERRO: netmiko não instalado. Rode: pip install -r requirements.txt")

    method = (host.get("access") or {}).get("method", "ssh")
    params = {
        "device_type": netmiko_device_type(host.get("vendor"), method),
        "host": host["mgmt_ip"],
        "port": (host.get("access") or {}).get("port", 23 if method == "telnet" else 22),
        "username": cred.get("username", ""),
        "password": cred.get("password", ""),
        "timeout": DEFAULT_TIMEOUT,
        "fast_cli": False,
    }
    if method == "telnet" and (host.get("vendor") or "").lower() == "mikrotik":
        # RouterOS/telnet: sem "+ct" ele consulta o terminal (ANSI) e derruba a conexão
        if "+" not in params["username"]:
            params["username"] += "+ct"
    if cred.get("secret"):
        params["secret"] = cred["secret"]
    if cred.get("key_file"):
        params["use_keys"] = True
        params["key_file"] = cred["key_file"]
    if method == "telnet" and (host.get("vendor") or "").lower() == "mikrotik":
        return _routeros_telnet_class()(**{**params, "device_type": "mikrotik_routeros_telnet"})
    return ConnectHandler(**params)


def _routeros_telnet_class():
    """mikrotik_routeros sobre Telnet. O 'generic_telnet' do Netmiko é de terminal-server (não faz
    login) e o RouterOS exige CR+LF no Enter; a negociação de opções o telnetlib já responde."""
    from netmiko.ssh_dispatcher import CLASS_MAPPER
    base = CLASS_MAPPER["mikrotik_routeros"]

    class RouterOSTelnet(base):
        def write_channel(self, out_data):
            if isinstance(out_data, str) and out_data.endswith("\r"):
                out_data += "\n"
            return super().write_channel(out_data)

    return RouterOSTelnet
