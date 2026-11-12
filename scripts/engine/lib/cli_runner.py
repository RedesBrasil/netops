#!/usr/bin/env python3
"""Execução CLI em lote (biblioteca): conecta, roda N comandos, desconecta.

Uso interno do motor (backup do console, backup antes de mudança, api_mikrotik). Para o
humano/IA acessar um equipamento, o caminho é SEMPRE `scripts/tools/access/session.py`
(`run` para um lote, `open`/`exec`/`close` para interativo) — não há mais ssh.py/telnet.py.

A credencial é resolvida aqui dentro e nunca é devolvida a quem chama.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.inventory import load_inventory, resolve_host  # noqa: E402
from lib.transport import open_cli  # noqa: E402


def canonical_host_id(host_ref: int | str) -> int | str:
    """Resolve ID/nome/alias para a identidade canônica, sem ler credenciais."""
    hosts_data, _ = load_inventory(include_credentials=False)
    host, _ = resolve_host(host_ref, hosts_data, {}, decrypt=False)
    return host.get("id", host["name"])


def run_commands(host_ref: int | str, commands: list[str], force_method: str = "ssh",
                 *, read_timeout: int = 30) -> dict[str, str]:
    """Conecta no host via CLI (ssh|telnet) e executa os comandos. Retorna {comando: saída}."""
    hosts_data, creds_data = load_inventory()
    host, cred = resolve_host(host_ref, hosts_data, creds_data)
    access = host.setdefault("access", {})
    if access.get("method") != force_method:
        access.pop("port", None)                  # porta do cadastro é do outro protocolo (ex.: SSH 64777 ≠ Telnet 23)
    access["method"] = force_method

    conn = open_cli(host, cred)
    results: dict[str, str] = {}
    try:
        if cred.get("secret"):
            try:
                conn.enable()
            except Exception:  # noqa: BLE001  — nem todo device tem modo enable
                pass
        for cmd in commands:
            results[cmd] = conn.send_command(cmd, read_timeout=read_timeout)
    finally:
        conn.disconnect()
    return results
