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
    if cred.get("secret"):
        params["secret"] = cred["secret"]
    if cred.get("key_file"):
        params["use_keys"] = True
        params["key_file"] = cred["key_file"]
    return ConnectHandler(**params)


def open_napalm(host: dict, cred: dict):
    """Abre um driver NAPALM (coleta estruturada / compare_config). Levanta se não suportado."""
    driver_name = resolve_vendor(host.get("vendor")).get("napalm")
    if not driver_name:
        raise ValueError(f"NAPALM não suporta o fabricante '{host.get('vendor')}'")
    try:
        from napalm import get_network_driver
    except ImportError:
        sys.exit("ERRO: napalm não instalado. Rode: pip install -r requirements.txt")

    driver = get_network_driver(driver_name)
    dev = driver(
        hostname=host["mgmt_ip"],
        username=cred.get("username", ""),
        password=cred.get("password", ""),
        optional_args={"secret": cred.get("secret", ""), "port": (host.get("access") or {}).get("port", 22)},
    )
    dev.open()
    return dev


def open_routeros_api(host: dict, cred: dict):
    """Abre a API nativa do MikroTik RouterOS via librouteros."""
    try:
        import librouteros
    except ImportError:
        sys.exit("ERRO: librouteros não instalado. Rode: pip install -r requirements.txt")

    port = (host.get("access") or {}).get("port", 8728)
    return librouteros.connect(
        host=host["mgmt_ip"],
        username=cred.get("username", ""),
        password=cred.get("password", ""),
        port=port,
        timeout=DEFAULT_TIMEOUT,
    )


def get_connection(host: dict, cred: dict):
    """Despachante central. Retorna (tipo, conexão) — tipo ∈ {'api','cli'}."""
    method = (host.get("access") or {}).get("method", "ssh")
    vendor = (host.get("vendor") or "").lower()

    if method == "api":
        if vendor == "mikrotik":
            return "api", open_routeros_api(host, cred)
        raise ValueError(f"acesso API ainda não implementado para o fabricante '{vendor}'")
    if method in ("ssh", "telnet"):
        return "cli", open_cli(host, cred)
    if method == "winbox":
        raise ValueError("winbox não é automatizável — cadastre o host com method 'api' ou 'ssh'")
    raise ValueError(f"método de acesso desconhecido: '{method}'")
