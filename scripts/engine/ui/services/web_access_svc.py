#!/usr/bin/env python3
"""Firewall de acesso web do console: só IPs/redes cadastrados em `web_access` entram.

Config (core/config/project-config.yaml, tela Configuração → "Acesso web"):

    web_access:
      enabled: true
      allowed_networks: [10.0.0.0/8, 45.70.144.0/22, 2804:4368::/32]   # IP solto, rede v4 ou v6
      trusted_proxies: [10.8.200.4]   # proxy reverso à frente do console (lê o IP real do X-Forwarded-For)

Pontos que importam (incidente evitado em 15/11/2026):

* Atrás de proxy reverso o IP do socket é SEMPRE o do proxy. Se o proxy estiver numa rede liberada
  (ex.: 10.8.200.4 em 10.0.0.0/8) e o app olhasse só o socket, o mundo inteiro entraria. Por isso o
  IP do cliente vem do `X-Forwarded-For`, mas SÓ quando o socket é um `trusted_proxies`
  (ou loopback). De qualquer outro, o cabeçalho é ignorado (senão qualquer um forjaria o IP).
* No `X-Forwarded-For` vale a entrada mais à direita que não seja proxy confiável: as mais à
  esquerda são escritas pelo cliente.
* IP ilegível ⇒ negado (fail-closed). Loopback (o próprio servidor: start.sh, agendador) sempre entra.
* O arquivo é relido quando muda (mtime): ligar/desligar/editar vale na hora, sem reiniciar.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Iterable

import deps

log = logging.getLogger("netops.web_access")

# Redes liberadas quando a seção existe sem lista, e botão "Restaurar padrão" da tela.
# Topnet (AS267568): IPv4 45.70.144.0/22 e IPv6 2804:4368::/32 (RIPEstat + RDAP, 15/11/2026).
DEFAULT_NETWORKS: tuple[str, ...] = ("10.0.0.0/8", "45.70.144.0/22", "2804:4368::/32")

_LOOPBACK = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128"))
_FORWARDED_ENV = "NETOPS_UI_FORWARDED_ALLOW_IPS"

IPAddr = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNet = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    networks: tuple[IPNet, ...] = ()
    trusted: tuple[IPNet, ...] = ()       # proxies confiáveis (sem o loopback, que é implícito)


# --------------------------------------------------------------------------- #
# Parsing / validação
# --------------------------------------------------------------------------- #
def parse_ip(text: str | None) -> IPAddr | None:
    """IP de um socket/cabeçalho (aceita `[::1]`, `%scope`, IPv4-mapeado). Ilegível → None."""
    s = (text or "").strip().strip("[]")
    if not s:
        return None
    s = s.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def parse_network(text: str) -> IPNet:
    """`10.1.2.3` → /32, `2804::1` → /128, `10.0.0.0/8`, `2804:4368::/32`. Levanta ValueError."""
    s = str(text).strip()
    if not s:
        raise ValueError("entrada vazia")
    return ipaddress.ip_network(s, strict=False)


def _norm_list(items: Iterable, field: str, errors: list[dict]) -> list[str]:
    out: list[str] = []
    for raw in items or []:
        try:
            net = parse_network(str(raw))
        except ValueError:
            errors.append({"loc": f"web_access.{field}", "msg": f"'{raw}' não é IP nem rede válida (use 10.0.0.0/8, 192.0.2.7, 2804:4368::/32)"})
            continue
        s = str(net)
        if s not in out:
            out.append(s)
    return out


def _in(ip: IPAddr, nets: Iterable[IPNet]) -> bool:
    return any(ip.version == n.version and ip in n for n in nets)


# --------------------------------------------------------------------------- #
# Política (lida do project-config.yaml, cache por mtime)
# --------------------------------------------------------------------------- #
_cache: dict = {"key": None, "policy": Policy()}
_cache_lock = threading.Lock()


def _build(section: dict) -> Policy:
    errors: list[dict] = []
    networks = _norm_list(section.get("allowed_networks", list(DEFAULT_NETWORKS)), "allowed_networks", errors)
    trusted = _norm_list(section.get("trusted_proxies", []), "trusted_proxies", errors)
    if errors:
        raise ValueError("; ".join(e["msg"] for e in errors))
    return Policy(
        enabled=bool(section.get("enabled", False)),
        networks=tuple(ipaddress.ip_network(n) for n in networks),
        trusted=tuple(ipaddress.ip_network(n) for n in trusted),
    )


def load_policy() -> Policy:
    """Política vigente. Arquivo ilegível/inválido → mantém a última boa (ou desligada se nunca leu)."""
    path = deps.PROJECT_CONFIG
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return _cache["policy"]
    with _cache_lock:
        if _cache["key"] == key:
            return _cache["policy"]
        try:
            import yaml  # noqa: PLC0415
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            policy = _build(data.get("web_access") or {})
        except Exception:  # noqa: BLE001
            log.exception("web_access: config inválida em %s — mantendo a política anterior", path)
            _cache["key"] = key           # não relê/loga a cada request até o arquivo mudar
            return _cache["policy"]
        _cache.update(key=key, policy=policy)
        return policy


def validate_patch(patch: dict, client_ip: str | None) -> dict:
    """Valida/normaliza o `web_access` de um PUT /config e impede o auto-bloqueio.

    Devolve o dict canônico a gravar (só as chaves enviadas). Levanta `deps.ValidationFailed`.
    """
    if not isinstance(patch, dict):
        raise deps.ValidationFailed([{"loc": "web_access", "msg": "objeto esperado"}])
    errors: list[dict] = []
    out: dict = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "allowed_networks" in patch:
        out["allowed_networks"] = _norm_list(patch["allowed_networks"], "allowed_networks", errors)
    if "trusted_proxies" in patch:
        out["trusted_proxies"] = _norm_list(patch["trusted_proxies"], "trusted_proxies", errors)
    if errors:
        raise deps.ValidationFailed(errors)

    cur = load_policy()
    nets = [ipaddress.ip_network(n) for n in out["allowed_networks"]] if "allowed_networks" in out else list(cur.networks)
    enabled = out.get("enabled", cur.enabled)
    if enabled and not nets:
        raise deps.ValidationFailed([{"loc": "web_access.allowed_networks",
                                      "msg": "Com o acesso restrito ligado, cadastre ao menos uma rede."}])
    ip = parse_ip(client_ip)
    if enabled and (ip is None or not (_in(ip, _LOOPBACK) or _in(ip, nets))):
        raise deps.ValidationFailed([{"loc": "web_access.allowed_networks",
                                      "msg": f"Seu IP atual ({client_ip or 'desconhecido'}) ficaria bloqueado. Inclua-o (ou a rede dele) na lista."}])
    return out


# --------------------------------------------------------------------------- #
# IP real do cliente
# --------------------------------------------------------------------------- #
def _env_trusted() -> tuple[IPNet, ...]:
    out = []
    for item in os.environ.get(_FORWARDED_ENV, "").split(","):
        item = item.strip()
        if item and item != "*":
            try:
                out.append(parse_network(item))
            except ValueError:
                pass
    return tuple(out)


def _header_values(scope: dict, name: bytes) -> list[str]:
    return [v.decode("latin1") for k, v in scope.get("headers", []) if k == name]


def resolve_client(scope: dict, policy: Policy) -> IPAddr | None:
    """IP real do cliente; reescreve `scope["client"]` e `scope["scheme"]` quando o socket é proxy confiável.

    Desligado e sem `trusted_proxies`/env configurados mantém o comportamento antigo do console
    (confiava no proxy de qualquer origem para o esquema https), pois o IP não é usado p/ nada.
    """
    client = scope.get("client")
    peer = parse_ip(client[0]) if client else None
    if peer is None:
        return None
    trusted = _LOOPBACK + policy.trusted + _env_trusted()
    legacy_trust_all = (not policy.enabled and not policy.trusted
                        and os.environ.get(_FORWARDED_ENV, "*").strip() == "*")
    if not (legacy_trust_all or _in(peer, trusted)):
        return peer

    proto = (_header_values(scope, b"x-forwarded-proto") or [""])[-1].split(",")[0].strip().lower()
    if proto in {"http", "https", "ws", "wss"}:
        scope["scheme"] = proto.replace("http", "ws") if scope.get("type") == "websocket" else proto

    hops = [h.strip() for v in _header_values(scope, b"x-forwarded-for") for h in v.split(",") if h.strip()]
    if not hops:
        return peer
    chosen: IPAddr | None = None
    for raw in reversed(hops):                  # da direita (mais confiável) p/ a esquerda
        hop = parse_ip(raw)
        if hop is None:
            return None                         # lixo no cabeçalho → fail-closed
        chosen = hop
        if not _in(hop, trusted):
            break
    if chosen is not None:
        scope["client"] = (str(chosen), client[1] if len(client) > 1 else 0)
    return chosen


def is_allowed(ip: IPAddr | None, policy: Policy) -> bool:
    if not policy.enabled:
        return True
    if ip is None:
        return False
    return _in(ip, _LOOPBACK) or _in(ip, policy.networks)


# --------------------------------------------------------------------------- #
# Bloqueios recentes (RAM, desde o último restart) — p/ conferir o teste "por fora"
# --------------------------------------------------------------------------- #
_MAX_DENIED = 50
_denied: dict[str, dict] = {}


def record_denied(ip: IPAddr | None, path: str) -> None:
    key = str(ip) if ip else "desconhecido"
    now = time.time()
    entry = _denied.get(key)
    if entry is None:
        if len(_denied) >= _MAX_DENIED:
            _denied.pop(min(_denied, key=lambda k: _denied[k]["last"]))
        entry = _denied[key] = {"ip": key, "count": 0, "first": now}
        log.warning("web_access: acesso negado a %s (%s)", key, path[:80])
    entry.update(count=entry["count"] + 1, last=now, path=path[:120])


def recent_denied() -> list[dict]:
    return sorted(_denied.values(), key=lambda e: e["last"], reverse=True)


def status(client_ip: str | None) -> dict:
    p = load_policy()
    ip = parse_ip(client_ip)
    return {
        "enabled": p.enabled,
        "allowed_networks": [str(n) for n in p.networks],
        "trusted_proxies": [str(n) for n in p.trusted],
        "defaults": list(DEFAULT_NETWORKS),
        "client_ip": client_ip,
        "client_allowed": is_allowed(ip, Policy(True, p.networks, p.trusted)),
        "denied": recent_denied(),
    }
