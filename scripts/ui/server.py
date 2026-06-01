#!/usr/bin/env python3
"""Sobe o NetOps Console (CRUD web) — ferramenta de operador local e efêmera.

  cd /home/francisco/netops
  .venv/bin/python3 scripts/ui/server.py            # porta livre, abre o browser
  .venv/bin/python3 scripts/ui/server.py --port 8765 --no-browser
  .venv/bin/python3 scripts/ui/server.py --read-only

Segurança: bind em loopback (127.0.0.1) por padrão; recusa 0.0.0.0. Gera um token por
sessão e imprime/abre a URL já com ?token=... (o servidor exige o token em /api). O cofre
pode ser destrancado pela web (senha-mestra digitada na UI -> derive_key -> sessão); use
--no-vault-unlock para exigir o terminal (`python scripts/vault/cli.py unlock`).
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# scripts/ui no sys.path[0] quando rodado como script; garante scripts/ também.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import deps  # noqa: E402

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _free_port(host: str, preferred: int) -> int:
    """Usa a porta pedida se livre; senão pede uma efêmera ao SO."""
    for candidate in (preferred, 0):
        if candidate == 0:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, 0))
                return s.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, candidate))
                return candidate
            except OSError:
                continue
    return preferred


def main() -> int:
    parser = argparse.ArgumentParser(description="NetOps Console — CRUD web local.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind (só loopback; default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Porta preferida (default 8765; cai p/ livre)")
    parser.add_argument("--no-browser", action="store_true", help="Não abrir o navegador")
    parser.add_argument("--read-only", action="store_true", help="Desliga toda escrita (só CRUD de leitura)")
    parser.add_argument("--no-vault-unlock", action="store_true",
                        help="Desabilita destrancar o cofre pela web (a senha-mestra só pelo terminal)")
    parser.add_argument("--token", default=os.environ.get("NETOPS_UI_TOKEN", ""),
                        help="Token fixo (default: aleatório por sessão)")
    args = parser.parse_args()

    is_loopback = args.host in LOOPBACK
    if args.host == "0.0.0.0":
        sys.exit("ERRO: 0.0.0.0 recusado. Faça bind num IP específico (ex.: --host 192.0.2.10) ou 127.0.0.1.")

    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        sys.exit("ERRO: dependências da UI ausentes. Rode: .venv/bin/pip install -r requirements.txt")

    deps.STATE.token = args.token or os.urandom(16).hex()
    deps.STATE.read_only = args.read_only
    deps.STATE.allow_vault_unlock = not args.no_vault_unlock
    # O Host header precisa bater com o IP de bind (anti DNS-rebinding). Mantém loopback + o IP escolhido.
    deps.STATE.allowed_hosts = tuple({"127.0.0.1", "localhost", "::1", args.host})

    if not is_loopback:
        print("\n  AVISO DE SEGURANÇA: bind em endereço NÃO-loopback — o console fica acessível na rede.")
        print("  Protegido por token de sessão (na URL). Use apenas em rede CONFIÁVEL.")
        print("  Este servidor pode descriptografar credenciais e editar o inventário.")
        if deps.STATE.allow_vault_unlock:
            print("  ATENÇÃO: destrancar o cofre pela web envia a SENHA-MESTRA em TEXTO PURO por HTTP nesta rede.")
            print("  Use só atrás de túnel SSH/VPN, ou suba com --no-vault-unlock e destranque pelo terminal.")
        print()

    from app import create_app  # noqa: PLC0415  (importa depois de setar STATE)
    application = create_app()

    port = _free_port(args.host, args.port)
    url = f"http://{args.host}:{port}/?token={deps.STATE.token}"

    print("\n  NetOps Console")
    print(f"  -> {url}")
    if args.read_only:
        print("  (modo somente-leitura)")
    print("  Ctrl+C para encerrar.\n")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(application, host=args.host, port=port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
