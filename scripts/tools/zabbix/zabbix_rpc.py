#!/usr/bin/env python3
"""Chamada JSON-RPC generica na API do Zabbix, usando a credencial do inventario.

O token e resolvido internamente (cofre) e NUNCA e impresso. Uso:
  python3 scripts/tools/zabbix/zabbix_rpc.py --host-id 1 --method host.get --params '{"output":["hostid","host"]}'
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()
import requests  # noqa: E402
from lib import i18n  # noqa: E402
from lib.inventory import load_inventory, resolve_host  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host-id", type=int, required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--params", default="{}")
    a = ap.parse_args()
    hosts, creds = load_inventory()
    host, cred = resolve_host(a.host_id, hosts, creds)
    token = next((cred[k] for k in ("token", "api_token", "secret", "password") if cred.get(k)), None)
    if not token:
        sys.exit(i18n.t("cli_zabbix.no_token"))
    site = host.get("site") or f"http://{host['mgmt_ip']}/zabbix"
    url = site.rstrip("/") + "/api_jsonrpc.php"
    body = {"jsonrpc": "2.0", "method": a.method, "params": json.loads(a.params), "id": 1}
    headers = {"Content-Type": "application/json-rpc"}
    if a.method != "apiinfo.version":
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(url, json=body, headers=headers, timeout=20).json()
    print(json.dumps(r.get("result", r.get("error")), ensure_ascii=False, indent=1))
    return 1 if "error" in r else 0


if __name__ == "__main__":
    sys.exit(main())
