#!/usr/bin/env python3
"""Métodos de terminal (SSH/Telnet) de um host — regra ÚNICA usada pelo console e pelo agente.

  access_entries(host) -> [{method, port, credential}]  principal + extra_access, só ssh/telnet,
                          sem duplicata método+porta; extra sem credential herda a do host.
  pick_entry(entries, method, port)                       escolhe (sem porta = o 1º do método).
  terminal_url(host_id, entry)                            '#hostterm/<id>?method=..&port=..' (janela do console)
  web_entries(host) -> [{method, port, credential, app, path}]  http/https (principal + extra_access);
                          `app` = extra.app, senão pelo vendor (web_login.APP_BY_VENDOR), senão "" (só abre a URL).

Espelho em JS: static/js/pages/host-term.js (terminalEntries) — mudar os dois juntos.
"""
from __future__ import annotations

TERMINAL_METHODS = ("ssh", "telnet")
DEFAULT_PORTS = {"ssh": 22, "telnet": 23}


class TargetError(Exception):
    """Host/método inválido para o terminal."""


def access_entries(host: dict) -> list[dict]:
    principal = host.get("access") or {}
    items = [{"method": principal.get("method") or "ssh", "port": principal.get("port"),
              "credential": host.get("credential")}]
    for extra in host.get("extra_access") or []:
        if isinstance(extra, dict):
            items.append({"method": extra.get("method"), "port": extra.get("port"),
                          "credential": extra.get("credential") or host.get("credential")})
    out, seen = [], set()
    for item in items:
        method = str(item["method"] or "").lower()
        if method not in TERMINAL_METHODS:
            continue
        try:
            port = int(item["port"] or DEFAULT_PORTS[method])
        except (TypeError, ValueError):
            port = DEFAULT_PORTS[method]
        if (method, port) in seen:
            continue
        seen.add((method, port))
        out.append({"method": method, "port": port, "credential": item["credential"]})
    return out


def pick_entry(entries: list[dict], method: str | None, port: int | None) -> dict:
    method = (method or "").lower() or None
    for entry in entries:
        if (method is None or entry["method"] == method) and (port is None or entry["port"] == port):
            return entry
    raise TargetError(f"método {method or '?'}{':' + str(port) if port else ''} não está cadastrado neste host")


def terminal_url(host_id, entry: dict) -> str:
    return f"#hostterm/{host_id}?method={entry['method']}&port={entry['port']}"


WEB_METHODS = ("http", "https")
WEB_DEFAULT_PORTS = {"http": 80, "https": 443}


def web_entries(host: dict) -> list[dict]:
    from lib.web_login import APP_BY_VENDOR  # noqa: PLC0415
    principal = host.get("access") or {}
    items = [{"method": principal.get("method"), "port": principal.get("port"),
              "credential": host.get("credential")}]
    for extra in host.get("extra_access") or []:
        if isinstance(extra, dict):
            items.append({**extra, "credential": extra.get("credential") or host.get("credential")})
    default_app = APP_BY_VENDOR.get(str(host.get("vendor") or "").lower(), "")
    out, seen = [], set()
    for item in items:
        method = str(item.get("method") or "").lower()
        if method not in WEB_METHODS:
            continue
        try:
            port = int(item.get("port") or WEB_DEFAULT_PORTS[method])
        except (TypeError, ValueError):
            port = WEB_DEFAULT_PORTS[method]
        if (method, port) in seen:
            continue
        seen.add((method, port))
        path = str(item.get("path") or "/")
        out.append({"method": method, "port": port, "credential": item.get("credential"),
                    "app": str(item.get("app") or default_app or "").lower(), "path": path})
    return out
