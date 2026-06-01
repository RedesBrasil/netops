#!/usr/bin/env python3
"""Acesso à API nativa do MikroTik RouterOS via librouteros.

Para hosts MikroTik com `access.method: api` no inventário. A API retorna dados
estruturados (lista de dicts), melhor que parsear texto de CLI.

Uso:
    python scripts/access/api_mikrotik.py --host rt-core-01 --path /ip/service
    python scripts/access/api_mikrotik.py --host rt-core-01 --path /ip/firewall/filter --save
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.inventory import NETOPS_ROOT, load_inventory, resolve_host  # noqa: E402
from lib.transport import open_routeros_api  # noqa: E402


def query(host_name: str, paths: list[str]) -> dict[str, list]:
    """Consulta uma ou mais paths da API RouterOS. Retorna {path: [registros]}."""
    hosts_data, creds_data = load_inventory()
    host, cred = resolve_host(host_name, hosts_data, creds_data)
    if (host.get("access") or {}).get("method") != "api":
        print(f"AVISO: '{host_name}' não está marcado como method:api no inventário.", file=sys.stderr)

    conn = open_routeros_api(host, cred)
    results: dict[str, list] = {}
    try:
        for raw in paths:
            keys = [k for k in raw.strip("/").split("/") if k]
            results[raw] = [dict(item) for item in conn.path(*keys)]
    finally:
        conn.close()
    return results


def _save(host_name: str, results: dict[str, list]) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    out_dir = NETOPS_ROOT / "runs" / f"{ts}-api-collect" / "collected"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{host_name}.json"
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Consulta a API do MikroTik RouterOS.")
    parser.add_argument("--host", required=True, help="Nome do host MikroTik em network/hosts.yaml")
    parser.add_argument("--path", action="append", default=[], required=True,
                        help="Path da API, ex.: /ip/service (pode repetir)")
    parser.add_argument("--save", action="store_true", help="Salva a saída em runs/<id>/collected/")
    args = parser.parse_args()

    try:
        results = query(args.host, args.path)
    except Exception as exc:  # noqa: BLE001
        print(f"FALHA ao consultar a API de '{args.host}': {exc}", file=sys.stderr)
        return 1

    print(json.dumps(results, indent=2, ensure_ascii=False))
    if args.save:
        print(f"[salvo] {_save(args.host, results)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
