#!/usr/bin/env python3
"""Traceroute avançado — mapeia o caminho de rede até um destino.

Aceita um host do inventário (--host) ou um IP/nome direto (--target). Tenta traceroute,
depois tracepath, depois mtr — o primeiro disponível. Útil para troubleshooting de caminho.

Uso:
    python3 scripts/tools/diagnostics/traceroute_advanced.py --host srv-web-01
    python3 scripts/tools/diagnostics/traceroute_advanced.py --target 1.1.1.1 --max-hops 20
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto


def resolve_target(host: int | str | None, target: str | None) -> str:
    if target:
        return target
    if host:
        from lib.inventory import load_inventory, resolve_host
        hosts_data, _ = load_inventory(include_credentials=False)
        resolved, _ = resolve_host(host, hosts_data, {}, decrypt=False)
        return resolved.get("mgmt_ip") or resolved.get("hostname")
    raise SystemExit("informe --host-id, --host ou --target")


def trace(target: str, max_hops: int) -> str:
    """Roda a primeira ferramenta de traceroute disponível."""
    candidates = [
        ["traceroute", "-n", "-w", "2", "-q", "1", "-m", str(max_hops), target],
        ["tracepath", "-n", "-m", str(max_hops), target],
        ["mtr", "-n", "-r", "-c", "5", "-m", str(max_hops), target],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max_hops * 5 + 30)
            return f"$ {' '.join(cmd)}\n{proc.stdout}{proc.stderr}"
    raise FileNotFoundError("nenhuma ferramenta de traceroute encontrada (traceroute/tracepath/mtr)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Traceroute avançado (traceroute/tracepath/mtr).")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help="ID inteiro do host no inventário")
    selection.add_argument("--host", help="Nome único ou alias legado do host")
    selection.add_argument("--target", help="IP ou nome direto")
    parser.add_argument("--max-hops", type=int, default=30, help="Máximo de saltos (padrão 30)")
    args = parser.parse_args()

    target = resolve_target(args.host_id if args.host_id is not None else args.host, args.target)
    try:
        print(trace(target, args.max_hops))
    except FileNotFoundError as exc:
        print(f"ERRO: {exc}. Instale com: sudo apt install traceroute", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"ERRO: traceroute a {target} excedeu o tempo.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
