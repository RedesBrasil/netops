#!/usr/bin/env python3
"""Avaliação de segurança — confronta hosts contra o catálogo de checagens (checks.yaml).

Checagens tipo 'port'   : rodam um scan e detectam serviços inseguros expostos.
Checagens tipo 'config' : rodam regex sobre a configuração coletada (--config-file).

Uso:
    python scripts/analysis/security_assessment.py --host rt-core-01
    python scripts/analysis/security_assessment.py --all
    python scripts/analysis/security_assessment.py --host rt-core-01 \\
        --config-file runs/2026-05-18-1430-security-audit/collected/rt-core-01.txt
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagnostics.portscan import DEFAULT_PORTS, scan_nmap, scan_socket  # noqa: E402
from lib.inventory import load_inventory, resolve_host  # noqa: E402

CHECKS_FILE = Path(__file__).resolve().parent / "checks.yaml"


def load_checks() -> list[dict]:
    import yaml
    data = yaml.safe_load(CHECKS_FILE.read_text(encoding="utf-8")) or {}
    return data.get("checks", [])


def assess_host(name: str, host: dict, checks: list[dict], config_text: str | None) -> list[dict]:
    """Aplica todas as checagens a um host. Retorna a lista de achados."""
    findings: list[dict] = []
    target = host.get("mgmt_ip") or host.get("hostname")

    # --- Checagens por porta ---
    port_checks = [c for c in checks if c.get("tipo") == "port"]
    if port_checks:
        ports = sorted({c["porta"] for c in port_checks} | set(DEFAULT_PORTS))
        scan = scan_nmap(target, ports) if shutil.which("nmap") else scan_socket(target, ports)
        open_ports = {int(p["port"].split("/")[0]) for p in scan["open_ports"]}
        for c in port_checks:
            if c["porta"] in open_ports:
                findings.append(_finding(name, c, f"porta {c['porta']}/tcp aberta"))

    # --- Checagens por configuração ---
    config_checks = [c for c in checks if c.get("tipo") == "config"]
    if config_checks:
        if config_text is None:
            findings.append({"host": name, "id": "config-checks-skipped", "severidade": "INFO",
                             "titulo": "Checagens de config não executadas",
                             "evidencia": "nenhum --config-file informado"})
        else:
            for c in config_checks:
                m = re.search(c["padrao"], config_text)
                if m:
                    findings.append(_finding(name, c, f"trecho: '{m.group(0).strip()[:80]}'"))
    return findings


def _finding(host: str, check: dict, evidence: str) -> dict:
    return {
        "host": host,
        "id": check["id"],
        "titulo": check["titulo"],
        "severidade": check["severidade"],
        "evidencia": evidence,
        "descricao": check["descricao"],
        "referencia": check.get("referencia", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Avaliação de segurança de hosts do inventário.")
    parser.add_argument("--host", help="Avaliar um host específico")
    parser.add_argument("--all", action="store_true", help="Avaliar todos os hosts do inventário")
    parser.add_argument("--config-file", help="Arquivo de config coletada (habilita checks de config)")
    args = parser.parse_args()

    if not args.host and not args.all:
        parser.error("informe --host ou --all")

    hosts_data, creds_data = load_inventory()
    checks = load_checks()
    names = sorted((hosts_data.get("hosts") or {}).keys()) if args.all else [args.host]
    config_text = Path(args.config_file).read_text(encoding="utf-8", errors="ignore") if args.config_file else None

    all_findings: list[dict] = []
    for name in names:
        try:
            host, _ = resolve_host(name, hosts_data, creds_data)
            all_findings += assess_host(name, host, checks, config_text)
        except Exception as exc:  # noqa: BLE001
            all_findings.append({"host": name, "id": "assessment-error", "severidade": "INFO",
                                 "titulo": "Falha ao avaliar host", "evidencia": str(exc)})

    order = {"CRITICO": 0, "ALTO": 1, "MEDIO": 2, "BAIXO": 3, "INFO": 4}
    all_findings.sort(key=lambda f: order.get(f["severidade"], 9))
    print(json.dumps({"total": len(all_findings), "findings": all_findings},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
