#!/usr/bin/env python3
"""Scan de portas TCP — descobre serviços expostos num host.

Usa nmap se disponível (com detecção de versão); senão cai num scan TCP-connect via socket.
Aceita um host do inventário (--host) ou um IP direto (--target).

Uso:
    python3 scripts/tools/diagnostics/portscan.py --host rt-core-01
    python3 scripts/tools/diagnostics/portscan.py --target 10.0.0.1 --ports 22,80,443,8728
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto
from lib import i18n  # noqa: E402

# Portas de gerência/serviço comuns em redes e infra.
DEFAULT_PORTS = [21, 22, 23, 25, 53, 80, 161, 443, 445, 2000, 3389, 8080, 8291, 8728, 8729]


def resolve_target(host: int | str | None, target: str | None) -> str:
    if target:
        return target
    if host:
        from lib.inventory import load_inventory, resolve_host
        hosts_data, _ = load_inventory(include_credentials=False)
        resolved, _ = resolve_host(host, hosts_data, {}, decrypt=False)
        return resolved.get("mgmt_ip") or resolved.get("hostname")
    raise SystemExit(i18n.t("cli_diagnostics.target_required"))


def scan_nmap(target: str, ports: list[int]) -> dict:
    """Scan com nmap (detecção de versão)."""
    port_arg = ",".join(str(p) for p in ports)
    cmd = ["nmap", "-sV", "-Pn", "-p", port_arg, target]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    open_ports = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "/tcp" in line and "open" in line:
            parts = line.split()
            open_ports.append({"port": parts[0], "state": parts[1],
                               "service": parts[2] if len(parts) > 2 else "",
                               "version": " ".join(parts[3:]) if len(parts) > 3 else ""})
    return {"target": target, "tool": "nmap", "open_ports": open_ports, "raw": proc.stdout.strip()}


def scan_socket(target: str, ports: list[int]) -> dict:
    """Fallback: scan TCP-connect simples via socket (sem detecção de versão)."""
    open_ports = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.5)
            if sock.connect_ex((target, port)) == 0:
                try:
                    svc = socket.getservbyport(port)
                except OSError:
                    svc = ""
                open_ports.append({"port": f"{port}/tcp", "state": "open", "service": svc, "version": ""})
    return {"target": target, "tool": "socket", "open_ports": open_ports, "raw": ""}


def main() -> int:
    parser = argparse.ArgumentParser(description=i18n.t("cli_diagnostics.scan_description"))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help=i18n.t("cli_diagnostics.help_host_id"))
    selection.add_argument("--host", help=i18n.t("cli_diagnostics.help_host"))
    selection.add_argument("--target", help=i18n.t("cli_diagnostics.help_target"))
    parser.add_argument("--ports", help=i18n.t("cli_diagnostics.help_ports"))
    args = parser.parse_args()

    target = resolve_target(args.host_id if args.host_id is not None else args.host, args.target)
    ports = [int(p) for p in args.ports.split(",")] if args.ports else DEFAULT_PORTS

    try:
        result = scan_nmap(target, ports) if shutil.which("nmap") else scan_socket(target, ports)
    except subprocess.TimeoutExpired:
        print(i18n.t("cli_diagnostics.scan_timeout", target=target), file=sys.stderr)
        return 1

    if result["tool"] == "socket":
        print(i18n.t("cli_diagnostics.scan_no_nmap"), file=sys.stderr)
    print(json.dumps({k: v for k, v in result.items() if k != "raw"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
