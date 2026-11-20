"""Zabbix (frontend 6/7): o login é um <form> POST em index.php (name/password/enter), sem token CSRF.

EXCEÇÃO À CONSTITUIÇÃO (§VII, autorizada em 13/11/2026): não há como gravar o cookie `zbx_session`
(assinado com HMAC) de fora; então a SENHA vai ao navegador do operador, uma vez, na resposta de
um clique explícito (no-store), e é enviada direto ao Zabbix. Antes disso o servidor valida a credencial
para não abrir a tela de erro do Zabbix. MFA (index_mfa.php) não é suportado.
"""
from __future__ import annotations

import requests

from lib import i18n

from .base import TIMEOUT, Handoff, WebLoginError, WebTarget, post


class ZabbixProvider:
    app = "zabbix"

    @staticmethod
    def _root(target: WebTarget) -> str:
        path = target.path.rstrip("/")
        if path.endswith(".php"):
            path = path.rsplit("/", 1)[0]
        return target.base + path

    def launch(self, target: WebTarget, username: str, password: str) -> Handoff:
        root = self._root(target)
        fields = {"name": username, "password": password, "autologin": "1", "enter": "Sign in"}
        resp = post(f"{root}/index.php", data=fields, allow_redirects=False)
        location = resp.headers.get("Location", "")
        if resp.status_code in (301, 302, 303) and "index_mfa" in location:
            raise WebLoginError(i18n.t("lib_web_login.zabbix_mfa"), "unsupported")
        if not (resp.status_code in (301, 302, 303) and "zbx_session" in {c.name for c in resp.cookies}):
            if resp.status_code == 200 and "incorrect" in resp.text.lower():
                raise WebLoginError(i18n.t("lib_web_login.zabbix_rejected"))
            raise WebLoginError(i18n.t("lib_web_login.zabbix_no_session", status=resp.status_code, path=target.path),
                                "unreachable")
        # sessão de validação descartada (o navegador cria a sua própria no POST abaixo)
        try:
            requests.get(f"{root}/index.php?reconnect=1", cookies=resp.cookies, verify=False,
                         timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException:
            pass
        return Handoff(mode="form_post", action=f"{root}/index.php", fields=fields,
                       note=i18n.t("lib_web_login.zabbix_http_note")
                       if target.scheme == "http" else "")
