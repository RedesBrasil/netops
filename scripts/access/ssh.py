#!/usr/bin/env python3
"""Acesso SSH a equipamentos de rede via Netmiko (camada padrão multi-fabricante).

Roda comandos num host do inventário e mostra/salva a saída. Comandos de coleta devem ser
read-only — ver core/rules/connection-safety.md.

Uso:
    python scripts/access/ssh.py --host rt-dist-01 --command "/system/resource/print"
    python scripts/access/ssh.py --host sw-access-01 --commands-file cmds.txt --save
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()
from lib.inventory import NETOPS_ROOT, load_inventory, resolve_host  # noqa: E402
from lib.transport import open_cli  # noqa: E402


def run_commands(host_name: str, commands: list[str], force_method: str = "ssh") -> dict[str, str]:
    """Conecta no host via CLI e executa os comandos. Retorna {comando: saída}."""
    hosts_data, creds_data = load_inventory()
    host, cred = resolve_host(host_name, hosts_data, creds_data)
    host.setdefault("access", {})["method"] = force_method

    conn = open_cli(host, cred)
    results: dict[str, str] = {}
    try:
        if cred.get("secret"):
            try:
                conn.enable()
            except Exception:  # noqa: BLE001  — nem todo device tem modo enable
                pass
        for cmd in commands:
            results[cmd] = conn.send_command(cmd, read_timeout=30)
    finally:
        conn.disconnect()
    return results


def _save(host_name: str, results: dict[str, str]) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    out_dir = NETOPS_ROOT / "runs" / f"{ts}-ssh-collect" / "collected"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{host_name}.txt"
    with out_file.open("w", encoding="utf-8") as fh:
        for cmd, output in results.items():
            fh.write(f"### {cmd}\n{output}\n\n")
    return out_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Roda comandos SSH num host do inventário.")
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

    try:
        results = run_commands(args.host, commands)
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
