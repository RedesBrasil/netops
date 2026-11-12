#!/usr/bin/env python3
"""Gera network/topology.md (diagrama Mermaid) a partir de topology.yaml + hosts.yaml.

O `documenter` roda este script após qualquer mudança de topologia. O diagrama Mermaid
renderiza direto no GitHub e nas IDEs.

Uso:
    python3 scripts/tools/docs/topology_render.py            # gera network/topology.md
    python3 scripts/tools/docs/topology_render.py --stdout   # só imprime, não grava
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from html import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto
from lib.host_identity import host_index, resolve_reference  # noqa: E402
from lib.inventory import resolve_host  # noqa: E402
from lib.inventory_lock import ensure_migration_complete, inventory_lock  # noqa: E402

NETOPS_ROOT = Path(__file__).resolve().parents[3]
HOSTS_FILE = NETOPS_ROOT / "network" / "hosts.yaml"
TOPO_FILE = NETOPS_ROOT / "network" / "topology.yaml"
OUT_FILE = NETOPS_ROOT / "network" / "topology.md"


def _resolved_hosts(hosts_data: dict) -> dict[int | str, dict]:
    """Resolve cada host com a herança de grupo (vendor/role podem vir do grupo)."""
    out = {}
    for host_id in host_index(hosts_data):
        host, _ = resolve_host(host_id, hosts_data, {}, decrypt=False)
        out[host_id] = host
    return out


def render(hosts_data: dict, topo_data: dict) -> str:
    hosts = _resolved_hosts(hosts_data)
    links = topo_data.get("links") or []
    segments = topo_data.get("segments") or []
    node_ids = {hid: f"host_{hid}" if isinstance(hid, int) else f"legacy_{str(hid).encode().hex()}"
                for hid in hosts}

    lines = [
        "# Topologia da Rede",
        "",
        "> Arquivo **gerado** por `scripts/tools/docs/topology_render.py`. Não edite à mão.",
        "",
        "```mermaid",
        "graph TD",
    ]
    # Nós
    for host_id, host in hosts.items():
        vendor = host.get("vendor", "?")
        role = host.get("role", "?")
        label = escape(str(host.get("hostname") or host_id), quote=True)
        details = escape(f"{vendor} · {role}", quote=True)
        lines.append(f'    {node_ids[host_id]}["{label}<br/>{details}"]')
    lines.append("")
    # Arestas
    missing = set()

    def endpoint_node(reference):
        try:
            return node_ids[resolve_reference(reference, hosts_data)]
        except (KeyError, ValueError):
            # Um enlace inconsistente continua visível para diagnóstico, sem cadastrar host.
            node_id = "missing_" + f"{type(reference).__name__}:{reference}".encode().hex()
            if node_id not in missing:
                label = escape(str(reference if reference is not None else "?"), quote=True)
                lines.append(f'    {node_id}["{label}<br/>host ausente"]')
                missing.add(node_id)
            return node_id

    for link in links:
        a = endpoint_node((link.get("a") or {}).get("host"))
        b = endpoint_node((link.get("b") or {}).get("host"))
        label = escape(" ".join(str(x) for x in (link.get("speed"), link.get("media")) if x), quote=True)
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

    with inventory_lock(HOSTS_FILE.parent):
        ensure_migration_complete(HOSTS_FILE.parent)
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
