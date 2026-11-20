#!/usr/bin/env python3
"""Modelo de script do NetOps. Copie esta pasta ao criar um script novo.

Padrão: argparse com --help claro, funciona offline, lê o inventário via lib/inventory.py.
Textos visíveis passam por i18n.t("cli_<skill>.<key>") e vão para core/locales/<idioma>/cli_<skill>.json
(ver core/rules/i18n.md); o inglês é a fonte.
"""
import argparse
import sys
from pathlib import Path

# Permite importar scripts/engine/lib/ de qualquer script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # OBRIGATÓRIO: python3 do sistema -> re-executa no .venv (antes de libs externas)
from lib import i18n  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=i18n.t("cli_template.description"))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help=i18n.t("cli_template.help_host_id"))
    selection.add_argument("--host", help=i18n.t("cli_template.help_host"))
    args = parser.parse_args()

    # from lib.inventory import load_inventory, resolve_host  # import preguiçoso
    host_reference = args.host_id if args.host_id is not None else args.host
    print(i18n.t("cli_template.todo", host=host_reference))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
