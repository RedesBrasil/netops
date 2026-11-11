#!/usr/bin/env python3
"""Modelo de script do NetOps. Copie esta pasta ao criar um script novo.

Padrão: argparse com --help claro, funciona offline, lê o inventário via lib/inventory.py.
"""
import argparse
import sys
from pathlib import Path

# Permite importar scripts/engine/lib/ de qualquer script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)


def main() -> int:
    parser = argparse.ArgumentParser(description="Descreva o que o script faz.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help="ID inteiro do host no inventário")
    selection.add_argument("--host", help="Hostname único ou alias legado do host")
    args = parser.parse_args()

    # from lib.inventory import load_inventory, resolve_host  # import preguiçoso
    host_reference = args.host_id if args.host_id is not None else args.host
    print(f"TODO: implementar. host={host_reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
