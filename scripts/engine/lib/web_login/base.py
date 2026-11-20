"""Contrato dos provedores de login web."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import requests
import urllib3

from lib import i18n

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)   # equipamentos de gerência: cert autoassinado
TIMEOUT = 10


class WebLoginError(Exception):
    """Falha de login/alcance. `code` -> 'auth' | 'unreachable' | 'unsupported'."""

    def __init__(self, message: str, code: str = "auth"):
        super().__init__(message)
        self.code = code


@dataclass
class WebTarget:
    scheme: str
    ip: str
    port: int
    path: str = "/"

    @property
    def base(self) -> str:
        host = f"[{self.ip}]" if ":" in self.ip else self.ip
        return f"{self.scheme}://{host}:{self.port}"

    @property
    def url(self) -> str:
        return self.base + (self.path if self.path.startswith("/") else "/" + self.path)


@dataclass
class Handoff:
    """O que o navegador faz para abrir a aba já logada.

    mode 'form_post': envia <form method=POST action target=aba> com `fields` (top-level, o cookie
    é gravado pelo próprio host). `then_url`: depois de `then_delay_ms` a aba vai para essa URL.
    mode 'open': só abre `then_url` (login manual)."""
    mode: str
    action: str = ""
    fields: dict = field(default_factory=dict)
    then_url: str = ""
    then_delay_ms: int = 0
    note: str = ""


class WebLoginProvider(Protocol):
    app: str

    def launch(self, target: WebTarget, username: str, password: str) -> Handoff:
        """Autentica no servidor (bloqueante, ≤10 s) e devolve o Handoff. Levanta WebLoginError."""


def post(url: str, **kw) -> requests.Response:
    try:
        return requests.post(url, verify=False, timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise WebLoginError(i18n.t("lib_web_login.connect_failed", url=url.split('/api2')[0].split('/index')[0], error=type(exc).__name__),
                            "unreachable") from exc
