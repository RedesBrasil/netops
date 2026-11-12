#!/usr/bin/env python3
"""Ping avançado — testa conectividade e mede perda/latência.

Aceita um host do inventário (--host) ou um IP/nome direto (--target). Resume perda de
pacotes e RTT min/avg/max. Útil para o `tester` validar conectividade.

Uso:
    python3 scripts/tools/diagnostics/ping_advanced.py --host rt-core-01
    python3 scripts/tools/diagnostics/ping_advanced.py --target 8.8.8.8 --count 20 --size 1400
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto


def resolve_target(host: int | str | None, target: str | None) -> str:
    """Resolve o IP-alvo a partir de --host (inventário) ou --target (direto)."""
    if target:
        return target
    if host:
        from lib.inventory import load_inventory, resolve_host
        hosts_data, _ = load_inventory(include_credentials=False)
        resolved, _ = resolve_host(host, hosts_data, {}, decrypt=False)
        return resolved.get("mgmt_ip") or resolved.get("hostname")
    raise SystemExit("informe --host-id, --host ou --target")


def ping(target: str, count: int, interval: float, size: int) -> dict:
    """Executa ping e devolve um resumo estruturado."""
    cmd = ["ping", "-c", str(count), "-i", str(interval), "-s", str(size), target]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=count * interval + 30)
    out = proc.stdout

    loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    rtt = re.search(r"rtt [^=]+= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
    return {
        "target": target,
        "count": count,
        "packet_loss_pct": float(loss.group(1)) if loss else None,
        "rtt_ms": {
            "min": float(rtt.group(1)) if rtt else None,
            "avg": float(rtt.group(2)) if rtt else None,
            "max": float(rtt.group(3)) if rtt else None,
        },
        "reachable": bool(loss) and float(loss.group(1)) < 100,
        "raw": out.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping avançado com resumo de perda/latência.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help="ID inteiro do host no inventário")
    selection.add_argument("--host", help="Nome único ou alias legado do host")
    selection.add_argument("--target", help="IP ou nome direto")
    parser.add_argument("--count", type=int, default=10, help="Número de pacotes (padrão 10)")
    parser.add_argument("--interval", type=float, default=0.5, help="Intervalo em s (padrão 0.5)")
    parser.add_argument("--size", type=int, default=56, help="Tamanho do payload (padrão 56)")
    args = parser.parse_args()

    target = resolve_target(args.host_id if args.host_id is not None else args.host, args.target)
    try:
        result = ping(target, args.count, args.interval, args.size)
    except FileNotFoundError:
        return print("ERRO: comando 'ping' não encontrado no sistema.", file=sys.stderr) or 1
    except subprocess.TimeoutExpired:
        return print(f"ERRO: ping a {target} excedeu o tempo.", file=sys.stderr) or 1

    print(json.dumps({k: v for k, v in result.items() if k != "raw"}, indent=2, ensure_ascii=False))
    return 0 if result["reachable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
