#!/usr/bin/env python3
"""Avaliação de segurança — confronta hosts contra o catálogo de checagens (checks.yaml).

Checks of type 'port'   : run a scan and detect insecure exposed services.
Checks of type 'config' : run a regex on the collected configuration (--config-file).

Uso:
    python3 scripts/tools/analysis/security_assessment.py --host rt-core-01
    python3 scripts/tools/analysis/security_assessment.py --all
    python3 scripts/tools/analysis/security_assessment.py --host rt-core-01 \\
        --config-file runs/2026-05-18-1430-security-audit/collected/rt-core-01.txt
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto
from lib import i18n  # noqa: E402
from diagnostics.portscan import DEFAULT_PORTS, scan_nmap, scan_socket  # noqa: E402
from lib.inventory import list_hosts, load_inventory, resolve_host  # noqa: E402

CHECKS_FILE = Path(__file__).resolve().parent / "checks.yaml"


LEGACY_KEYS = {"titulo": "title", "severidade": "severity", "tipo": "type", "porta": "port", "padrao": "pattern",
               "descricao": "description", "referencia": "reference"}
LEGACY_SEVERITY = {"CRITICO": "CRITICAL", "ALTO": "HIGH", "MEDIO": "MEDIUM", "BAIXO": "LOW"}
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def normalize_check(check: dict) -> dict:
    """English keys/severities; customized catalogs with the legacy Portuguese keys keep working."""
    out = {}
    for k, v in (check or {}).items():
        out.setdefault(LEGACY_KEYS.get(k, k), v)
    sev = str(out.get("severity", "INFO")).upper()
    out["severity"] = LEGACY_SEVERITY.get(sev, sev)
    return out


def load_checks() -> list[dict]:
    import yaml
    data = yaml.safe_load(CHECKS_FILE.read_text(encoding="utf-8")) or {}
    return [normalize_check(c) for c in data.get("checks", [])]


def assess_host(name: int | str, host: dict, checks: list[dict], config_text: str | None) -> list[dict]:
    """Aplica todas as checagens a um host. Retorna a lista de achados."""
    findings: list[dict] = []
    target = host.get("mgmt_ip") or host.get("hostname")
    checks = [normalize_check(c) for c in checks]

    # --- Checagens por porta ---
    port_checks = [c for c in checks if c.get("type") == "port"]
    if port_checks:
        ports = sorted({c["port"] for c in port_checks} | set(DEFAULT_PORTS))
        scan = scan_nmap(target, ports) if shutil.which("nmap") else scan_socket(target, ports)
        open_ports = {int(p["port"].split("/")[0]) for p in scan["open_ports"]}
        for c in port_checks:
            if c["port"] in open_ports:
                findings.append(_finding(name, c, i18n.t("cli_analysis.port_open", port=c["port"])))

    # --- Checagens por configuração ---
    config_checks = [c for c in checks if c.get("type") == "config"]
    if config_checks:
        if config_text is None:
            findings.append({"host": name, "id": "config-checks-skipped", "severity": "INFO",
                             "title": i18n.t("cli_analysis.config_checks_skipped"),
                             "evidence": i18n.t("cli_analysis.no_config_file")})
        else:
            for c in config_checks:
                m = re.search(c["pattern"], config_text)
                if m:
                    findings.append(_finding(name, c, i18n.t("cli_analysis.config_match", excerpt=m.group(0).strip()[:80])))
    return findings


def _finding(host: int | str, check: dict, evidence: str) -> dict:
    return {
        "host": host,
        "id": check["id"],
        "title": check.get("title", check["id"]),
        "severity": check.get("severity", "INFO"),
        "evidence": evidence,
        "description": check.get("description", ""),
        "reference": check.get("reference", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=i18n.t("cli_analysis.security_description"))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--host-id", type=int, help=i18n.t("cli_analysis.help_host_id"))
    selection.add_argument("--host", help=i18n.t("cli_analysis.help_host"))
    selection.add_argument("--all", action="store_true", help=i18n.t("cli_analysis.help_all"))
    parser.add_argument("--config-file", help=i18n.t("cli_analysis.help_config_file"))
    args = parser.parse_args()

    hosts_data, _ = load_inventory(include_credentials=False)
    checks = load_checks()
    names = list_hosts(hosts_data) if args.all else [args.host_id if args.host_id is not None else args.host]
    config_text = Path(args.config_file).read_text(encoding="utf-8", errors="ignore") if args.config_file else None

    all_findings: list[dict] = []
    for name in names:
        try:
            host, _ = resolve_host(name, hosts_data, {}, decrypt=False)
            all_findings += assess_host(host.get("id", host["name"]), host, checks, config_text)
        except Exception as exc:  # noqa: BLE001
            all_findings.append({"host": name, "id": "assessment-error", "severity": "INFO",
                                 "title": i18n.t("cli_analysis.assessment_failed"), "evidence": str(exc)})

    all_findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    print(json.dumps({"total": len(all_findings), "findings": all_findings},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
