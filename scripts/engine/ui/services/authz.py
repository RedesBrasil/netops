#!/usr/bin/env python3
"""Autorização do console: quem é o usuário da requisição e o que ele pode fazer.

- Identidade: o sid (header `X-Netops-Session` / `?auth=` no WebSocket) aponta p/ um usuário no banco
  de acesso (lib/accessdb.py). Sem login exigido (sem cofre e sem usuários) = administrador local.
- Permissão por rota: tabela RULES (método + regex do caminho sem /api -> permissão). DEFAULT-DENY:
  rota sem regra só passa p/ admin, e o teste `test_every_route_is_mapped` reprova rota nova sem regra.
  `None` = qualquer usuário logado; "@router" = o próprio router decide (depende do corpo/da query).
- O grupo `admin` tem "*". Permissões `admin_only` (terminal/arquivos do servidor, config, updates,
  usuários, auditoria, editar scripts e tarefas agendadas — os dois rodam com a conta do servidor —
  e `server.admin`, a administração Local como root) não são concedíveis a outros grupos.

A aba Claude Code roda o agente com shell no servidor: liberar `claude.use` é decisão de confiança.
O teto de `net_perms` do grupo limita o que ela faz nos EQUIPAMENTOS (grade contra erro, não fronteira).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import deps
from lib import i18n
from lib import accessdb

ANY = None            # qualquer usuário logado
ROUTER = "@router"    # checado dentro do router

_R = re.compile
GET = frozenset({"GET", "HEAD"})
WRITE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALL = GET | WRITE

# (métodos, regex do caminho SEM o prefixo /api, permissão). Primeira regra que casa vence.
RULES: list[tuple[frozenset, re.Pattern, str | None]] = [
    # sessão / identidade / bootstrap da UI
    (ALL, _R(r"^/auth/"), ANY),
    # primeiro acesso: status e conclusão (exige o token de uso único); etapa root = só admin
    (GET, _R(r"^/setup/status$"), ANY),
    (WRITE, _R(r"^/setup/complete$"), ANY),
    (ALL, _R(r"^/setup/finish$"), "server.admin"),
    (GET, _R(r"^/config/meta$"), ANY),
    # traduções: lista de idiomas e catálogos (abertos: login e primeiro acesso usam); idioma da instalação = admin
    (GET, _R(r"^/i18n(/[A-Za-z_-]{2,20})?$"), ANY),
    (WRITE, _R(r"^/config/language$"), "config"),
    (GET, _R(r"^/meta/(enums|icons)$"), ANY),
    (GET, _R(r"^/vault/status$"), ANY),
    (WRITE, _R(r"^/vault/unlock$"), ANY),                     # exige a senha-mestra de qualquer jeito
    (WRITE, _R(r"^/vault/lock$"), "credentials.edit"),
    (GET, _R(r"^/updates/status$"), ANY),
    # GitHub DO PRÓPRIO usuário (Minha conta → GitHub); o de outro usuário cai em /users/ (users.manage)
    (ALL, _R(r"^/account/github(/|$)"), ANY),
    # inventário
    (GET, _R(r"^/(hosts|groups)(/|$)"), "hosts.view"),
    (WRITE, _R(r"^/hosts/[^/]+/web-launch$"), "host.web"),
    (WRITE, _R(r"^/(hosts|groups)(/|$)"), "hosts.edit"),
    (GET, _R(r"^/(topology|maps)(/|$)"), "hosts.view"),
    (WRITE, _R(r"^/(topology|maps)(/|$)"), "hosts.edit"),
    # Cofre de senhas (network/vault.yaml) — segredos que não são de host
    (GET, _R(r"^/vault/(catalog|items)(/|$)"), "vault.view"),
    (WRITE, _R(r"^/vault/items/[^/]+/reveal$"), "vault.reveal"),
    (WRITE, _R(r"^/vault/items(/|$)"), "vault.edit"),
    (WRITE, _R(r"^/vault/(fields|templates)(/|$)"), "vault.templates"),
    (GET, _R(r"^/credentials(/|$)"), "credentials.view"),
    (WRITE, _R(r"^/credentials(/|$)"), "credentials.edit"),
    # conhecimento / saída
    (GET, _R(r"^/(memory|knowledge|workflows|agents|reports|runs)(/|$)"), "knowledge.view"),
    (WRITE, _R(r"^/(memory|knowledge|workflows|agents)(/|$)"), "knowledge.edit"),
    (GET, _R(r"^/scripts(/|$)"), "scripts.view"),
    (WRITE, _R(r"^/scripts(/|$)"), "scripts.edit"),
    (GET, _R(r"^/backups(/|$)"), "backups.view"),
    (WRITE, _R(r"^/backups/[^/]+/run$"), "backups.run"),
    (WRITE, _R(r"^/backups(/|$)"), "backups.edit"),
    # tarefas agendadas (dono confere no router)
    (GET, _R(r"^/schedules(/|$)"), "schedules.view"),
    (WRITE, _R(r"^/schedules/notifications/read$"), "schedules.view"),
    (WRITE, _R(r"^/schedules/(timezone|cron/install)$"), "config"),
    (WRITE, _R(r"^/schedules/tasks/[^/]+/run$"), "schedules.run"),
    (WRITE, _R(r"^/schedules/tasks(/|$)"), "schedules.edit"),          # executa como root = só admin
    # Central de Avisos: ver/ler = inbox.view; arquivar/decidir = inbox.decide (pedido COM ação = só admin, no router)
    (GET, _R(r"^/inbox(/|$)"), "inbox.view"),
    (WRITE, _R(r"^/inbox/(read|[^/]+/unread)$"), "inbox.view"),
    (WRITE, _R(r"^/inbox/(archive|[^/]+/decision)$"), "inbox.decide"),
    # sistema
    (GET, _R(r"^/dashboard/"), "dashboard.view"),
    (ALL, _R(r"^/config$"), "config"),
    (GET, _R(r"^/web-access$"), "config"),
    (GET, _R(r"^/updates/(check)$"), "updates"),
    (WRITE, _R(r"^/updates/apply$"), "updates"),
    (ALL, _R(r"^/term$"), "server.terminal"),                  # WebSocket (checado em routers/terminal.py)
    (ALL, _R(r"^/term/host/"), "host.terminal"),               # WebSocket (routers/host_term.py)
    (ALL, _R(r"^/files/root/(status|open|close)$"), "server.admin"),  # modo root dos Arquivos (localadmin)
    (GET, _R(r"^/files/dl/"), ANY),                           # ticket de uso único (emitido já autorizado)
    (ALL, _R(r"^/files/"), ROUTER),                           # local = server.files; SFTP de host = host.files
    # IA / ditado
    (GET, _R(r"^/audio/config$"), "claude.use"),
    (WRITE, _R(r"^/audio/config$"), "config"),
    (WRITE, _R(r"^/audio/(transcribe|test)$"), "claude.use"),
    (WRITE, _R(r"^/claude/auth/logout$"), "config"),
    (ALL, _R(r"^/claude(/|$)"), "claude.use"),                # dono da conversa confere no router
    # Projetos (nome + pasta do servidor): cada projeto abre sessões do agente, que tem shell no servidor
    # na pasta escolhida — mesma confiança da aba Claude Code. O seletor de pasta só lista diretórios.
    # Escolher a pasta (navegar, criar, confiar, renomear, remover) = só admin; ver/usar = claude.use.
    # Ordem e arquivados são preferência de cada usuário (não mexem no registro).
    # Each project is private to its owner and shared per user/access group (services/project_acl): the router
    # checks the LEVEL in the project (view/participate/manage/owner) on top of claude.use. Creating = router
    # (projects.manage = any folder, projects.create = only a new folder in the default base).
    (WRITE, _R(r"^/projects/(order|[a-z0-9-]+/archived)$"), "claude.use"),
    (GET, _R(r"^/projects/browse$"), "projects.manage"),
    (WRITE, _R(r"^/projects$"), ROUTER),
    (ALL, _R(r"^/projects(/|$)"), "claude.use"),
    # administração de acesso
    (ALL, _R(r"^/(users|access-groups|access-catalog)(/|$)"), "users.manage"),
    (GET, _R(r"^/audit(/|$)"), "audit.view"),
]
UNMAPPED = "@unmapped"


def required_perm(method: str, path: str) -> str | None:
    """Permissão exigida por `METHOD /caminho` (sem /api). UNMAPPED = só admin."""
    m = (method or "GET").upper()
    for methods, rx, perm in RULES:
        if m in methods and rx.search(path):
            return perm
    return UNMAPPED


# --------------------------------------------------------------------------- #
@dataclass
class Principal:
    username: str
    display_name: str = ""
    groups: list = field(default_factory=list)
    permissions: set = field(default_factory=set)
    net_perms: list = field(default_factory=list)
    is_admin: bool = False
    must_change_password: bool = False
    legacy: bool = False      # modo senha-mestra (ainda sem usuários) ou console sem login

    def can(self, perm: str | None) -> bool:
        if perm is ANY:
            return True
        if self.is_admin:
            return True
        if perm in (UNMAPPED, ROUTER):
            return False
        return perm in self.permissions and perm not in accessdb.ADMIN_ONLY

    def public(self) -> dict:
        return {"username": self.username, "display_name": self.display_name or self.username,
                "groups": self.groups, "is_admin": self.is_admin,
                "permissions": sorted(self.permissions), "net_perms": list(self.net_perms),
                "must_change_password": self.must_change_password, "legacy": self.legacy}


def _admin(username: str, legacy: bool = True) -> Principal:
    return Principal(username=username, display_name=username, groups=[accessdb.ADMIN_GROUP],
                     permissions=set(accessdb.PERM_KEYS), net_perms=list(accessdb.NET_PERMS),
                     is_admin=True, legacy=legacy)


LOCAL_ADMIN_NAME = "local"


def principal_for_user(username: str | None) -> Principal | None:
    if not username:
        return None
    db = deps.db_file()
    eff = accessdb.effective(db, username)
    if eff is None:
        # Sem usuários cadastrados = modo senha-mestra: a sessão é do admin legado.
        return _admin(username) if not accessdb.has_users(db) else None
    return Principal(username=eff["username"], display_name=eff["display_name"], groups=eff["groups"],
                     permissions=set(eff["permissions"]), net_perms=eff["net_perms"],
                     is_admin=eff["is_admin"], must_change_password=eff["must_change_password"])


def principal_for_sid(sid: str | None) -> Principal | None:
    """Usuário do sid. Sem login exigido = administrador local (instalação sem cofre e sem usuários)."""
    if not deps.auth_required():
        # Primeiro acesso pendente (na rede, sem cofre/usuário): ninguém vira admin sem o assistente.
        return None if deps.setup_mode() else _admin(LOCAL_ADMIN_NAME)
    return principal_for_user(deps.auth_session_user(sid))


def request_principal(request) -> Principal:
    p = getattr(request.state, "principal", None)
    if p is None:
        p = principal_for_sid(request.headers.get("x-netops-session"))
    return p or Principal(username="")


class Forbidden(Exception):
    def __init__(self, perm: str, detail: str | None = None):
        super().__init__(detail or perm)
        self.perm = perm
        self.detail = detail or i18n.t("errors.forbidden_perm", perm=perm_label(perm))


def perm_label(perm: str) -> str:
    for p in accessdb.localized_permissions():
        if p["key"] == perm:
            return p["label"]
    from lib import i18n  # noqa: PLC0415
    return i18n.t("common.admins_only") if perm in (UNMAPPED, ROUTER) else str(perm)


def require(request, perm: str) -> Principal:
    p = request_principal(request)
    if not p.can(perm):
        raise Forbidden(perm)
    return p


def ws_principal(ws, perm: str | None) -> Principal | None:
    """WebSocket: o middleware http não cobre — valida sessão (?auth=) + permissão aqui."""
    p = principal_for_sid(ws.query_params.get("auth"))
    if p is None or p.must_change_password or not p.can(perm):
        return None
    return p


def net_perms_cap(username: str | None) -> list[str] | None:
    """Teto de permissões de rede da aba Claude p/ o usuário. None = sem teto (admin / sem login)."""
    if not username or not deps.auth_required():
        return None
    p = principal_for_user(username)
    if p is None:
        return []
    return None if p.is_admin else list(p.net_perms)


def client_ip(request) -> str:
    c = getattr(request, "client", None)
    return getattr(c, "host", "") or ""
