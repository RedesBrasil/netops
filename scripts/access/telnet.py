#!/usr/bin/env python3
"""Acesso Telnet a equipamentos legados via Netmiko.

Telnet é inseguro (texto puro) — use só onde o equipamento não suportar SSH, e registre
isso como achado de segurança. A lógica é a mesma do ssh.py, forçando o transporte Telnet.

Uso:
    python scripts/access/telnet.py --host olt-legada-01 --command "show version"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from access.ssh import _save, run_commands  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Roda comandos Telnet num host do inventário.")
    parser.add_argument("--host", required=True, help="Nome do host em network/hosts.yaml")
    parser.add_argument("--command", action="append", default=[], help="Comando (pode repetir)")
    parser.add_argument("--commands-file", help="Arquivo com um comando por linha")
    parser.add_argument("--save", action="store_true", help="Salva a saída em runs/<id>/collected/")
    args = parser.parse_args()

    commands = list(args.command)
    if args.commands_file:
        commands += [ln.strip() for ln in Path(args.commands_file).read_text().splitlines() if ln.strip()]
    if not commands:
        parser.error("informe ao menos um --command ou --commands-file")

    print("AVISO: Telnet trafega em texto puro. Prefira SSH sempre que possível.", file=sys.stderr)
    try:
        results = run_commands(args.host, commands, force_method="telnet")
    except Exception as exc:  # noqa: BLE001
        print(f"FALHA ao conectar/coletar em '{args.host}': {exc}", file=sys.stderr)
        return 1

    for cmd, output in results.items():
        print(f"### {cmd}\n{output}\n")
    if args.save:
        print(f"[salvo] {_save(args.host, results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
