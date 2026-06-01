#!/usr/bin/env python3
"""Modelo de script do NetOps. Copie esta pasta ao criar um script novo.

Padrão: argparse com --help claro, funciona offline, lê o inventário via lib/inventory.py.
"""
import argparse
import sys
from pathlib import Path

# Permite importar scripts/lib/ de qualquer script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Descreva o que o script faz.")
    parser.add_argument("--host", help="Nome do host em network/hosts.yaml")
    args = parser.parse_args()

    # from lib.inventory import load_inventory, resolve_host  # import preguiçoso
    print(f"TODO: implementar. host={args.host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
