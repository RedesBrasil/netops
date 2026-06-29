#!/usr/bin/env python3
"""Gera network/topology.md (diagrama Mermaid) a partir de topology.yaml + hosts.yaml.

O `documenter` roda este script após qualquer mudança de topologia. O diagrama Mermaid
renderiza direto no GitHub e nas IDEs.

Uso:
    python scripts/tools/docs/topology_render.py            # gera network/topology.md
    python scripts/tools/docs/topology_render.py --stdout   # só imprime, não grava
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

NETOPS_ROOT = Path(__file__).resolve().parents[3]
HOSTS_FILE = NETOPS_ROOT / "network" / "hosts.yaml"
TOPO_FILE = NETOPS_ROOT / "network" / "topology.yaml"
OUT_FILE = NETOPS_ROOT / "network" / "topology.md"


def _resolved_hosts(hosts_data: dict) -> dict[str, dict]:
    """Resolve cada host com a herança de grupo (vendor/role podem vir do grupo)."""
    groups = hosts_data.get("groups") or {}
    out = {}
    for name, host in (hosts_data.get("hosts") or {}).items():
        group = groups.get(host.get("group"), {})
        out[name] = {**group, **host}
    return out


def render(hosts_data: dict, topo_data: dict) -> str:
    hosts = _resolved_hosts(hosts_data)
    links = topo_data.get("links") or []
    segments = topo_data.get("segments") or []

    lines = [
        "# Topologia da Rede",
        "",
        "> Arquivo **gerado** por `scripts/tools/docs/topology_render.py`. Não edite à mão.",
        "",
        "```mermaid",
        "graph TD",
    ]
    # Nós
    for name, host in sorted(hosts.items()):
        vendor = host.get("vendor", "?")
        role = host.get("role", "?")
        lines.append(f'    {name}["{name}<br/>{vendor} · {role}"]')
    lines.append("")
    # Arestas
    for link in links:
        a = (link.get("a") or {}).get("host", "?")
        b = (link.get("b") or {}).get("host", "?")
        label = " ".join(str(x) for x in (link.get("speed"), link.get("media")) if x)
        if label:
            lines.append(f'    {a} ---|"{label}"| {b}')
        else:
            lines.append(f"    {a} --- {b}")
    lines.append("```")
    lines.append("")

    # Segmentos lógicos
    if segments:
        lines += ["## Segmentos lógicos", "", "| Segmento | VLAN | Sub-rede |", "|----------|------|----------|"]
        for seg in segments:
            lines.append(f"| {seg.get('name','')} | {seg.get('vlan','')} | {seg.get('subnet','')} |")
        lines.append("")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"_Gerado em: {ts} — {len(hosts)} host(s), {len(links)} enlace(s)._")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera o diagrama de topologia em Mermaid.")
    parser.add_argument("--stdout", action="store_true", help="Imprime no terminal, não grava o arquivo")
    args = parser.parse_args()

    try:
        import yaml
    except ImportError:
        print("ERRO: PyYAML não instalado. Rode: pip install -r requirements.txt", file=sys.stderr)
        return 1

    if not HOSTS_FILE.exists() or not TOPO_FILE.exists():
        print("ERRO: network/hosts.yaml e/ou network/topology.yaml não encontrados.", file=sys.stderr)
        return 1

    hosts_data = yaml.safe_load(HOSTS_FILE.read_text(encoding="utf-8")) or {}
    topo_data = yaml.safe_load(TOPO_FILE.read_text(encoding="utf-8")) or {}
    content = render(hosts_data, topo_data)

    if args.stdout:
        print(content)
    else:
        OUT_FILE.write_text(content, encoding="utf-8")
        print(f"[gerado] {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
