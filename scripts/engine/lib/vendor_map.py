#!/usr/bin/env python3
"""Mapeamento de fabricante (vendor) -> drivers de acesso.

O campo `vendor` de cada host em network/hosts.yaml decide qual driver usar:
  - netmiko        : device_type do Netmiko para acesso SSH
  - netmiko_telnet : device_type do Netmiko para acesso Telnet (None se não houver)
  - napalm         : driver do NAPALM para coleta estruturada/diff (None se não suportado)
  - api            : biblioteca de API nativa (None se não houver)
  - notes          : observações operacionais

Para adicionar um fabricante novo: acrescente uma entrada aqui e registre-o no PADRAO.md.
"""
from __future__ import annotations

VENDOR_MAP: dict[str, dict] = {
    "mikrotik": {
        "netmiko": "mikrotik_routeros",
        "netmiko_telnet": "mikrotik_routeros_telnet",
        "napalm": None,
        "api": "librouteros",
        "notes": "API nativa na porta 8728 (8729 com TLS). Preferir API a SSH para MikroTik.",
    },
    "cisco": {
        "netmiko": "cisco_ios",
        "netmiko_telnet": "cisco_ios_telnet",
        "napalm": "ios",
        "api": None,
        "notes": "Para IOS-XE use cisco_xe; NX-OS use cisco_nxos. NAPALM 'ios' cobre IOS/IOS-XE.",
    },
    "huawei": {
        "netmiko": "huawei",
        "netmiko_telnet": "huawei_telnet",
        "napalm": None,
        "api": None,
        "notes": "VRP. Para VRPv8 use device_type huawei_vrpv8.",
    },
    "datacom": {
        "netmiko": "generic",
        "netmiko_telnet": "generic_telnet",
        "napalm": None,
        "api": None,
        "notes": "DmOS — sem device_type nativo no Netmiko; usa-se 'generic'. CLI parecida com Cisco.",
    },
    "unifi": {
        "netmiko": "ubiquiti_unifiswitch",
        "netmiko_telnet": None,
        "napalm": None,
        "api": "unifi_controller",
        "notes": "Switches UniFi via SSH. A controladora UniFi é gerida por API REST própria.",
    },
    "ubiquiti": {
        "netmiko": "ubiquiti_edgerouter",
        "netmiko_telnet": None,
        "napalm": None,
        "api": None,
        "notes": "EdgeRouter/EdgeOS. Para switches EdgeSwitch use ubiquiti_edge.",
    },
    "fiberhome": {
        "netmiko": "generic",
        "netmiko_telnet": "generic_telnet",
        "napalm": None,
        "api": None,
        "notes": "OLT — sem device_type nativo. Muitos modelos só por Telnet. Validar prompt.",
    },
    "intelbras": {
        "netmiko": "generic",
        "netmiko_telnet": "generic_telnet",
        "napalm": None,
        "api": None,
        "notes": "Switches/ONUs — sem device_type nativo. CLI varia por modelo.",
    },
    "linux": {
        "netmiko": "linux",
        "netmiko_telnet": None,
        "napalm": None,
        "api": None,
        "notes": "Servidores Linux e serviços. Preferir chave SSH a senha.",
    },
    "proxmox": {
        "netmiko": "linux",
        "netmiko_telnet": None,
        "napalm": None,
        "api": "proxmox_api",
        "notes": "Host Proxmox é Debian — acesso SSH como linux. Gestão via API PVE (proxmoxer).",
    },
    "vmware": {
        "netmiko": "linux",
        "netmiko_telnet": None,
        "napalm": None,
        "api": "vmware_api",
        "notes": "ESXi shell é limitado. Gestão real via vCenter API (pyvmomi).",
    },
    "other": {
        "netmiko": "generic",
        "netmiko_telnet": "generic_telnet",
        "napalm": None,
        "api": None,
        "notes": "Fabricante não mapeado — usa driver genérico do Netmiko.",
    },
}


def resolve_vendor(vendor: str | None) -> dict:
    """Retorna o mapeamento do fabricante; cai em 'other' se desconhecido."""
    key = (vendor or "other").lower()
    return VENDOR_MAP.get(key, VENDOR_MAP["other"])


def netmiko_device_type(vendor: str | None, method: str = "ssh") -> str:
    """device_type do Netmiko para o vendor e método (ssh|telnet)."""
    vmap = resolve_vendor(vendor)
    if method == "telnet":
        return vmap.get("netmiko_telnet") or vmap["netmiko"]
    return vmap["netmiko"]


if __name__ == "__main__":
    import json
    print(json.dumps(VENDOR_MAP, indent=2, ensure_ascii=False))
