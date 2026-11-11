#!/usr/bin/env python3
"""Acesso Telnet a equipamentos legados via Netmiko.

Telnet é inseguro (texto puro) — use só onde o equipamento não suportar SSH, e registre
isso como achado de segurança. A lógica é a mesma do ssh.py, forçando o transporte Telnet.

Uso:
    python scripts/tools/access/telnet.py --host olt-legada-01 --command "show version"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()
from access.ssh import _canonical_host_id, _save, run_commands  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Roda comandos Telnet num host do inventário.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help="ID inteiro do host no inventário")
    selection.add_argument("--host", help="Nome único ou alias legado do host")
    parser.add_argument("--command", action="append", default=[], help="Comando (pode repetir)")
    parser.add_argument("--commands-file", help="Arquivo com um comando por linha")
    parser.add_argument("--save", action="store_true", help="Salva a saída em runs/<id>/collected/")
    args = parser.parse_args()
    host_ref = args.host_id if args.host_id is not None else args.host

    commands = list(args.command)
    if args.commands_file:
        commands += [ln.strip() for ln in Path(args.commands_file).read_text().splitlines() if ln.strip()]
    if not commands:
        parser.error("informe ao menos um --command ou --commands-file")

    print("AVISO: Telnet trafega em texto puro. Prefira SSH sempre que possível.", file=sys.stderr)
    try:
        host_ref = _canonical_host_id(host_ref)
        results = run_commands(host_ref, commands, force_method="telnet")
    except Exception as exc:  # noqa: BLE001
        print(f"FALHA ao conectar/coletar em '{host_ref}': {exc}", file=sys.stderr)
        return 1

    for cmd, output in results.items():
        print(f"### {cmd}\n{output}\n")
    if args.save:
        print(f"[salvo] {_save(host_ref, results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
