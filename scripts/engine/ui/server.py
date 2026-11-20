#!/usr/bin/env python3
"""Sobe o NetOps Console (CRUD web) — ferramenta de operador local e efêmera.

  cd /opt/netops
  .venv/bin/python3 scripts/engine/ui/server.py            # porta livre, abre o browser
  .venv/bin/python3 scripts/engine/ui/server.py --port 8765 --no-browser
  .venv/bin/python3 scripts/engine/ui/server.py --read-only

Segurança: bind em loopback (127.0.0.1) por padrão. O `start.sh` sobe com 0.0.0.0 = TODOS os IPs da
máquina (IPv4 e, se houver, IPv6 em `::`). Fora do loopback o acesso é protegido pelo LOGIN; sem cofre e
sem usuário, o console fica no modo de PRIMEIRO ACESSO (só o assistente #setup, com token de uso único)
em vez de ficar aberto. Mais a checagem de Host/Origin (anti DNS-rebinding/CSRF). O cofre pode ser destrancado pela web (senha-mestra
digitada na UI -> derive_key -> sessão); use --no-vault-unlock para exigir o terminal
(`python3 scripts/engine/vault/cli.py unlock`).
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# scripts/engine/ui no sys.path[0] quando rodado como script (p/ `import deps`, `from app`).
# deps.py cuida de pôr scripts/engine e scripts/tools no path (p/ `from lib`/`from docs`).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import deps  # noqa: E402
from lib import i18n  # noqa: E402

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
WILDCARD = {"0.0.0.0", "::", "*", ""}


def _bind_v4(host: str) -> str:
    """Endereço IPv4 de bind (curinga -> 0.0.0.0)."""
    return "0.0.0.0" if host in WILDCARD else host


def _listen_sockets(host: str, port: int) -> list[socket.socket] | None:
    """Curinga: um socket IPv4 em 0.0.0.0 e, se a máquina tiver IPv6, outro em :: (IPV6_V6ONLY,
    para o IP do cliente IPv4 não virar ::ffff:x — a allowlist de acesso web e a auditoria usam ele).
    Endereço específico: None (o uvicorn faz o bind)."""
    if host not in WILDCARD:
        return None
    socks = []
    s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s4.bind(("0.0.0.0", port))
    socks.append(s4)
    if socket.has_ipv6:
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.bind(("::", port))
            socks.append(s6)
        except OSError:
            try:
                s6.close()
            except Exception:  # noqa: BLE001
                pass
    for s in socks:
        s.listen(2048)
        s.set_inheritable(True)
    return socks


def _display_hosts(host: str) -> list[str]:
    """Endereços para mostrar nas URLs (curinga = cada IP da máquina, sem gravar a lista)."""
    if host not in WILDCARD:
        return [host]
    ips = sorted(deps.local_ips() - {"::1"}, key=lambda x: (":" in x, x != "127.0.0.1", x))
    return [f"[{i}]" if ":" in i else i for i in ips] or ["127.0.0.1"]


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


def _prepare_tls(host: str, https_port: int):
    """Gera/renova o certificado e confere a porta. Qualquer falha desliga só o HTTPS (nunca o console)."""
    try:
        from services import tls_svc  # noqa: PLC0415
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((_bind_v4(host), https_port))
        cert, key = tls_svc.ensure_cert(deps.DATA_ROOT / "runs" / "tls", host)
        shown = ", ".join(f"https://{h}:{https_port}/" for h in _display_hosts(host))
        print("\n  " + i18n.t("api_server.https_on", shown=shown))
        print("     " + i18n.t("api_server.cert_sha256", fingerprint=tls_svc.fingerprint(cert)))
        return cert, key
    except Exception as exc:  # noqa: BLE001
        print("\n  " + i18n.t("api_server.https_off", error=exc))
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=i18n.t("api_server.description"))
    parser.add_argument("--host", default="127.0.0.1",
                        help=i18n.t("api_server.help_host"))
    parser.add_argument("--port", type=int, default=8765, help=i18n.t("api_server.help_port"))
    parser.add_argument("--no-browser", action="store_true", help=i18n.t("api_server.help_no_browser"))
    parser.add_argument("--read-only", action="store_true", help=i18n.t("api_server.help_read_only"))
    parser.add_argument("--no-vault-unlock", action="store_true",
                        help=i18n.t("api_server.help_no_vault_unlock"))
    parser.add_argument("--enable-terminal", action="store_true",
                        help=i18n.t("api_server.help_terminal"))
    parser.add_argument("--enable-claude", action="store_true",
                        help=i18n.t("api_server.help_claude"))
    parser.add_argument("--enable-claude-persist", action="store_true",
                        help=i18n.t("api_server.help_claude_persist"))
    parser.add_argument("--claude-max-sessions", type=int, default=4,
                        help=i18n.t("api_server.help_max_sessions"))
    parser.add_argument("--claude-detach-grace", type=int, default=300,
                        help=i18n.t("api_server.help_detach_grace"))
    parser.add_argument("--claude-ask-timeout", type=int, default=180,
                        help=i18n.t("api_server.help_ask_timeout"))
    parser.add_argument("--https-port", type=int, default=None,
                        help=i18n.t("api_server.help_https_port"))
    args = parser.parse_args()

    is_loopback = args.host in LOOPBACK
    is_wildcard = args.host in WILDCARD
    if is_wildcard:
        args.host = "0.0.0.0"

    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        sys.exit(i18n.t("api_server.missing_deps"))

    deps.STATE.read_only = args.read_only
    deps.STATE.allow_vault_unlock = not args.no_vault_unlock
    deps.STATE.enable_terminal = args.enable_terminal and not args.read_only
    deps.STATE.enable_claude = args.enable_claude and not args.read_only
    deps.STATE.claude_persist = args.enable_claude_persist and deps.STATE.enable_claude
    deps.STATE.claude_max_sessions = max(1, args.claude_max_sessions)
    deps.STATE.claude_detach_grace = max(1, args.claude_detach_grace)
    deps.STATE.claude_ask_timeout = max(1, args.claude_ask_timeout)
    # O Host header precisa bater com o IP de bind (anti DNS-rebinding). Mantém loopback + o IP escolhido.
    deps.STATE.allowed_hosts = tuple({"127.0.0.1", "localhost", "::1", args.host} - {"0.0.0.0"})
    deps.STATE.bind_loopback = is_loopback
    deps.STATE.bind_wildcard = is_wildcard

    if deps.vault_initialized():
        print("\n  " + i18n.t("api_server.login_required"))
        if not deps.STATE.allow_vault_unlock:
            print("    " + i18n.t("api_server.no_vault_unlock"))
    elif deps.setup_mode():
        # No language chosen yet (that is part of the first access): print it in every complete language.
        langs = [i18n.default_lang()] if i18n.instance_language() else \
            [x["code"] for x in i18n.languages() if x["status"] == "complete"] or [i18n.default_lang()]
        for lang in langs:
            print("\n  " + i18n.t("api_server.setup_pending_1", lang))
            print("    " + i18n.t("api_server.setup_pending_2", lang))
        print("    python3 scripts/engine/users/cli.py setup-link")
    else:
        print("\n  " + i18n.t("api_server.no_vault_1"))
        print("    " + i18n.t("api_server.no_vault_2"))
        print("    " + i18n.t("api_server.no_vault_3"))

    if deps.STATE.enable_terminal:
        print("\n  " + i18n.t("api_server.terminal_on_1"))
        print("    " + i18n.t("api_server.terminal_on_2"))

    if deps.STATE.enable_claude:
        print("\n  " + i18n.t("api_server.claude_on_1"))
        print("    " + i18n.t("api_server.claude_on_2"))

    if deps.STATE.claude_persist:
        print("\n  " + i18n.t("api_server.persist_on_1"))
        print("    " + i18n.t("api_server.persist_on_2", max=deps.STATE.claude_max_sessions,
                                grace=deps.STATE.claude_detach_grace, ask=deps.STATE.claude_ask_timeout))
        print("    " + i18n.t("api_server.persist_on_3"))

    if not is_loopback:
        print("\n  " + i18n.t("api_server.net_warn_1"))
        print("  " + i18n.t("api_server.net_warn_2"))
        print("  " + i18n.t("api_server.net_warn_3"))
        if deps.STATE.allow_vault_unlock:
            print("  " + i18n.t("api_server.net_plain_1"))
            print("  " + i18n.t("api_server.net_plain_2"))
        if deps.STATE.enable_terminal:
            print("  " + i18n.t("api_server.net_term_1"))
            print("  " + i18n.t("api_server.net_term_2"))
        if deps.STATE.enable_claude:
            print("  " + i18n.t("api_server.net_claude_1"))
            print("  " + i18n.t("api_server.net_claude_2"))
        print()

    from app import create_app  # noqa: PLC0415  (importa depois de setar STATE)
    application = create_app()

    port = args.port if os.environ.get("NETOPS_UPDATE_MANAGED") == "1" else _free_port(_bind_v4(args.host), args.port)
    urls = [f"http://{h}:{port}/" for h in _display_hosts(args.host)]
    url = f"http://127.0.0.1:{port}/" if is_wildcard else urls[0]

    print("\n  NetOps Console" + ("  " + i18n.t("api_server.all_ips") if is_wildcard else ""))
    for u in urls:
        print(f"  -> {u}")
    if args.read_only:
        print("  " + i18n.t("api_server.read_only_mode"))
    print("  " + i18n.t("api_server.ctrl_c") + "\n")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    # Atrás de proxy reverso: X-Forwarded-For/Proto são tratados pelo próprio app (app._WebAccessGate →
    # services/web_access_svc.resolve_client), só de proxy confiável (web_access.trusted_proxies, loopback ou
    # NETOPS_UI_FORWARDED_ALLOW_IPS). NÃO usar proxy_headers do uvicorn: com "*" ele aceitava o IP de qualquer
    # origem (forjável) e apagava o IP real do socket, que a allowlist de acesso web precisa.
    https_port = args.https_port
    if https_port is None:
        env = os.environ.get("NETOPS_UI_HTTPS_PORT", "")
        https_port = int(env) if env.isdigit() else port + 1000
    tls = _prepare_tls(args.host, https_port) if https_port else None

    import asyncio  # noqa: PLC0415

    class _Secondary(uvicorn.Server):
        # Sinais ficam com o servidor HTTP principal; este só acompanha o should_exit dele.
        def capture_signals(self):
            import contextlib  # noqa: PLC0415
            return contextlib.nullcontext()

    main_socks = _listen_sockets(args.host, port)
    sec_socks = None
    if tls and is_wildcard:
        try:
            sec_socks = _listen_sockets(args.host, https_port)
        except OSError as exc:      # HTTPS nunca derruba o console
            print("  " + i18n.t("api_server.https_off_port", port=https_port, error=exc))
            tls = None

    async def _run() -> None:
        main_srv = uvicorn.Server(uvicorn.Config(application, host=args.host, port=port, log_level="info",
                                                 access_log=False, proxy_headers=False))
        sec_task = None
        sec_srv = None
        if tls:
            # Mesma app e MESMO event loop (serviços usam asyncio.get_event_loop). lifespan off: os
            # eventos de startup/shutdown já rodam no servidor principal. Falha aqui NUNCA derruba o HTTP.
            sec_srv = _Secondary(uvicorn.Config(application, host=args.host, port=https_port, log_level="info",
                                                access_log=False, proxy_headers=False, lifespan="off",
                                                ssl_certfile=str(tls[0]), ssl_keyfile=str(tls[1])))

            async def _sec() -> None:
                try:
                    await sec_srv.serve(sockets=sec_socks)
                except BaseException as exc:  # noqa: BLE001  (uvicorn faz sys.exit(1) se não conseguir bind)
                    print("  " + i18n.t("api_server.https_listener_ended", error=repr(exc)))
            sec_task = asyncio.create_task(_sec())
        try:
            await main_srv.serve(sockets=main_socks)
        finally:
            if sec_srv is not None:
                sec_srv.should_exit = True
                await sec_task

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
