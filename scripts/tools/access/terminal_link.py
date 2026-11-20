#!/usr/bin/env python3
"""Gera o link que ABRE o terminal web de um host numa janela nova do console (botão "⌨ Acessar").

Uso pelo agente na aba Claude Code: o usuário pede "abre a borda pra mim" -> ache o ID em
network/hosts.yaml, rode este script e cole a linha impressa NA RESPOSTA (como está). O chat
abre a janela sozinho (se o navegador permitir pop-ups) ou mostra o link para um clique.
O agente NÃO conecta em nada aqui: só gera o link; quem conecta é o humano, pelo console.

    python3 scripts/tools/access/terminal_link.py --host-id 2                 # método principal
    python3 scripts/tools/access/terminal_link.py --host-id 2 --method telnet # método específico
    python3 scripts/tools/access/terminal_link.py --host-id 2 --all           # um link por método
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # OBRIGATÓRIO: python3 do sistema -> re-executa no .venv (antes de libs externas)
from lib import i18n  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=i18n.t("cli_access.terminal_link_description"))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help=i18n.t("cli_access.help_host_id"))
    selection.add_argument("--host", help=i18n.t("cli_access.help_hostname"))
    parser.add_argument("--method", choices=["ssh", "telnet"], help=i18n.t("cli_access.help_method"))
    parser.add_argument("--port", type=int, help=i18n.t("cli_access.help_port"))
    parser.add_argument("--all", action="store_true", help=i18n.t("cli_access.help_all_links"))
    args = parser.parse_args()

    from lib.inventory import load_inventory, resolve_host  # noqa: PLC0415
    from lib.terminal_access import TargetError, access_entries, pick_entry, terminal_url  # noqa: PLC0415

    hosts_data, _ = load_inventory(include_credentials=False)
    ref = args.host_id if args.host_id is not None else args.host
    try:
        host, _ = resolve_host(ref, hosts_data, {}, decrypt=False)
    except Exception as exc:  # noqa: BLE001
        print(i18n.t("cli_access.terminal_host_not_found", host=ref, error=exc), file=sys.stderr)
        return 2
    entries = access_entries(host)
    if not entries:
        print(i18n.t("cli_access.terminal_no_ssh_telnet", host=host.get("id", ref),
                     method=(host.get("access") or {}).get("method")), file=sys.stderr)
        return 3
    if args.all:
        chosen = entries
    else:
        try:
            chosen = [pick_entry(entries, args.method, args.port)]
        except TargetError as exc:
            print(i18n.t("cli_access.terminal_pick_failed", error=exc,
                         entries=", ".join(f"{e['method']}:{e['port']}" for e in entries)), file=sys.stderr)
            return 3
    name = host.get("hostname") or host.get("id", ref)
    for entry in chosen:
        url = terminal_url(host.get("id", ref), entry)
        print(f"[{i18n.t('cli_access.terminal_link_label', name=name, method=entry['method'].upper(), port=entry['port'])}]({url})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
