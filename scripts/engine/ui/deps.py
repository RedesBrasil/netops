#!/usr/bin/env python3
"""Bootstrap de caminhos, segurança (Origin/Host + login por senha-mestra) e estado compartilhado da UI.

Tudo aqui é "infra" do servidor — sem regra de negócio. Importar ANTES de qualquer
`from lib...` para garantir que scripts/engine/ esteja no sys.path (mesmo padrão dos
outros scripts do NetOps: cli.py, inventory.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# scripts/engine/ui/deps.py -> parents[1]=scripts/engine, parents[2]=scripts/, parents[3]=raiz
ENGINE_DIR = Path(__file__).resolve().parents[1]    # scripts/engine (motor: lib, vault, ui)
SCRIPTS_DIR = Path(__file__).resolve().parents[2]   # scripts/
NETOPS_ROOT = Path(__file__).resolve().parents[3]   # raiz do projeto
TOOLS_DIR = SCRIPTS_DIR / "tools"                    # scripts/tools (operacionais do usuário)
# engine/ no path p/ `from lib import ...`; tools/ p/ `from docs.topology_render import ...`.
for _p in (ENGINE_DIR, TOOLS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# --------------------------------------------------------------------------- #
# Caminhos canônicos (a UI só toca nestes arquivos)
# --------------------------------------------------------------------------- #
DATA_ROOT = Path(os.environ.get("NETOPS_UI_DATA_ROOT", str(NETOPS_ROOT))).resolve()
NETWORK_DIR = DATA_ROOT / "network"
HOSTS_FILE = NETWORK_DIR / "hosts.yaml"
CREDS_FILE = NETWORK_DIR / "credentials.yaml"
TOPOLOGY_FILE = NETWORK_DIR / "topology.yaml"
MAPS_FILE = NETWORK_DIR / "maps.yaml"
TOPOLOGY_MD = NETWORK_DIR / "topology.md"
BACKUPS_FILE = NETWORK_DIR / "backups.yaml"
BACKUPS_STORE = DATA_ROOT / "backups"   # mesmo inventário, inclusive em ambiente isolado
BACKUPS_RUNS = DATA_ROOT / "runs" / "backups"   # status/log das execucoes (Run)

CORE_DIR = NETOPS_ROOT / "core"
SCHEMA_FILE = CORE_DIR / "schemas" / "inventory.schema.json"
PROJECT_CONFIG = DATA_ROOT / "core" / "config" / "project-config.yaml"

# Translations (lib/i18n.py): the instance language is read from THIS data root (tests repoint DATA_ROOT).
from lib import i18n as _i18n  # noqa: E402
_i18n.set_data_root_provider(lambda: DATA_ROOT)

MEMORY_DIR = NETOPS_ROOT / "memory"
MEMORY_MD = MEMORY_DIR / "MEMORY.md"   # arquivo único de memória (ver core/rules/memory-protocol.md)

BEST_PRACTICES_DIR = NETOPS_ROOT / "best-practices"
BP_CATALOG = BEST_PRACTICES_DIR / "_catalog.yaml"
CONFIG_EXAMPLES_DIR = NETOPS_ROOT / "config-examples"
CE_INDEX = CONFIG_EXAMPLES_DIR / "_index.yaml"

WORKFLOWS_DIR = NETOPS_ROOT / "workflows"
AGENTS_DIR = NETOPS_ROOT / "agents"
REPORTS_DIR = NETOPS_ROOT / "reports"
RUNS_DIR = NETOPS_ROOT / "runs"

# Scripts operacionais (scripts/tools/): a UI gerencia SÓ estes — os scripts que o usuário
# cria/edita p/ acessar roteadores, diagnosticar, analisar. O motor (scripts/engine: lib,
# vault, ui) NÃO aparece. Só Python/Shell; sem execução. Ver routers/scripts.py.
SCRIPT_EXTS = (".py", ".sh")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Vendors válidos (espelha core/rules/standard.md + schema). Usado p/ validar pastas de conhecimento.
VENDORS = (
    "mikrotik", "unifi", "ubiquiti", "cisco", "huawei", "proxmox",
    "vmware", "datacom", "linux", "fiberhome", "intelbras", "zabbix", "general",
)


# --------------------------------------------------------------------------- #
# Estado do servidor (modo read-only, flags de features, sessões de login)
# --------------------------------------------------------------------------- #
@dataclass
class ServerState:
    read_only: bool = False
    update_pending: bool = False
    host_migration: dict = field(default_factory=lambda: {"phase": "not_checked", "required": False})
    active_writes: int = 0
    active_sessions: int = 0
    active_requests: int = 0
    allow_vault_unlock: bool = True
    enable_terminal: bool = False
    enable_claude: bool = False
    # Persistência da aba Claude: a sessão sobrevive à queda do socket (termina o turno;
    # re-anexa ao voltar). Default OFF (kill-switch). Os limites são ESTÁTICOS (estilo
    # CacheSize do Zabbix): alocados no arranque, previsíveis. Ver services/claude_svc.py.
    claude_persist: bool = False
    claude_max_sessions: int = 4      # teto de sessões desanexadas vivas (recusa ao estourar)
    claude_detach_grace: int = 300    # seg que uma sessão desanexada e OCIOSA sobrevive
    claude_ask_timeout: int = 180     # seg que uma pergunta sem resposta espera (desanexado) -> nega
    allowed_hosts: tuple[str, ...] = field(default_factory=lambda: ("127.0.0.1", "localhost"))
    # Endereço de escuta (server.py). Curinga (0.0.0.0/::) = todos os IPs da máquina: o Host aceito
    # sem login passa a ser qualquer IP local. Fora do loopback, sem cofre e sem usuário, o console
    # entra no modo de PRIMEIRO ACESSO (só o assistente #setup, com token) em vez de ficar aberto.
    bind_loopback: bool = True
    bind_wildcard: bool = False
    # LEGADO: as sessões de login agora vivem no SQLite (lib/accessdb.py); campo mantido p/ compat.
    auth_sessions: dict = field(default_factory=dict)


STATE = ServerState()


# --------------------------------------------------------------------------- #
# Sessão de login -> USUÁRIO. Fonte da verdade: banco de acesso SQLite (lib/accessdb.py,
# DATA_ROOT/runs/netops.db). Sem usuários cadastrados vale o modo antigo (senha-mestra = admin);
# o 1º login com a senha-mestra cria o usuário `admin` (routers/auth.py).
# --------------------------------------------------------------------------- #
AUTH_LOGIN_TTL_DEFAULT = 7 * 86400   # login vale 7 dias (absoluto), sobrevive a restart do backend
AUTH_SESSIONS_FILE: Path | None = None   # LEGADO (JSON de antes do SQLite): só lido na importação
DB_FILE: Path | None = None              # None = DATA_ROOT/runs/netops.db (resolvido na hora)
LEGACY_ADMIN = "admin"


def db_file() -> Path:
    # Resolvido a cada uso (não no import): quem troca DATA_ROOT (testes, instalação temporária)
    # nunca grava no banco da instalação real (lição do incidente de 11/11/2026 com o JSON de logins).
    return DB_FILE or (DATA_ROOT / "runs" / "netops.db")


def _auth_sessions_file() -> Path:
    return AUTH_SESSIONS_FILE or (DATA_ROOT / "runs" / ".ui-auth-sessions.json")


def _sid_key(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def login_ttl() -> int:
    """TTL do login do console (project-config.yaml -> ui.login_ttl_seconds; default 7 dias)."""
    try:
        import yaml  # noqa: PLC0415
        cfg = yaml.safe_load(PROJECT_CONFIG.read_text(encoding="utf-8")) or {}
        ttl = (cfg.get("ui") or {}).get("login_ttl_seconds")
        if isinstance(ttl, int) and ttl > 0:
            return ttl
    except Exception:
        pass
    return AUTH_LOGIN_TTL_DEFAULT


def load_auth_sessions() -> None:
    """Arranque: importa (uma vez) os logins do JSON legado p/ o SQLite, como o admin legado —
    quem estava logado antes da atualização continua logado."""
    from lib import accessdb  # noqa: PLC0415
    db = db_file()
    if accessdb.meta_get(db, "legacy_sessions_imported"):
        return
    try:
        data = json.loads(_auth_sessions_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    now = time.time()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("exp"), (int, float)) and v["exp"] > now:
                accessdb.import_session_hash(db, k, LEGACY_ADMIN, float(v["exp"]))
    accessdb.meta_set(db, "legacy_sessions_imported", str(int(now)))


def create_auth_session(ttl: int | None = None, user: str = LEGACY_ADMIN, *, ip: str = "",
                        user_agent: str = "") -> str:
    """Emite um sid aleatório do `user` que expira em agora+ttl (absoluto), persistido no SQLite."""
    from lib import accessdb  # noqa: PLC0415
    return accessdb.create_session(db_file(), user, ttl or login_ttl(), ip=ip, user_agent=user_agent)


def auth_session_user(sid: str | None) -> str | None:
    """Usuário dono do sid (válido, não expirado, usuário ativo) ou None."""
    if not sid:
        return None
    from lib import accessdb  # noqa: PLC0415
    return accessdb.session_user(db_file(), sid)


def auth_session_valid(sid: str | None) -> bool:
    return auth_session_user(sid) is not None


def drop_auth_session(sid: str | None) -> None:
    if sid:
        from lib import accessdb  # noqa: PLC0415
        accessdb.drop_session(db_file(), sid)


def clear_auth_sessions() -> None:
    from lib import accessdb  # noqa: PLC0415
    accessdb.clear_sessions(db_file())


def has_users() -> bool:
    from lib import accessdb  # noqa: PLC0415
    try:
        return accessdb.has_users(db_file())
    except Exception:
        return False


_vault_init_cache: dict = {}


def vault_initialized() -> bool:
    """True se credentials.yaml tem um bloco de cofre (kdf+verifier). Cacheado por (path, mtime),
    então pega um `init` feito com o servidor no ar e não re-parseia a cada request."""
    try:
        st = CREDS_FILE.stat()
    except OSError:
        return False
    key = (str(CREDS_FILE), st.st_mtime_ns)
    if key in _vault_init_cache:
        return _vault_init_cache[key]
    _vault_init_cache.clear()  # só guardamos a entrada corrente
    import yaml  # noqa: PLC0415
    from lib import vault  # noqa: PLC0415
    try:
        vault.load_meta(yaml.safe_load(CREDS_FILE.read_text(encoding="utf-8")) or {})
        ok = True
    except Exception:
        ok = False  # ausente/corrompido -> trata como sem cofre (fail-open p/ não travar o operador)
    _vault_init_cache[key] = ok
    return ok


def files_enabled() -> bool:
    """Gerenciador de arquivos (menu Arquivos + painel SFTP): mesmo nível de confiança do terminal web
    (acesso ao sistema como o usuário do servidor). Liga junto com o terminal; NETOPS_UI_FILES=0 desliga."""
    return (STATE.enable_terminal and not STATE.read_only
            and os.environ.get("NETOPS_UI_FILES", "1").strip().lower() not in ("0", "false", "no", "off"))


def auth_required() -> bool:
    """O console exige login sempre que houver cofre inicializado OU usuário cadastrado."""
    return vault_initialized() or has_users()


def setup_mode() -> bool:
    """Primeiro acesso pendente: sem cofre e sem usuário, escutando na rede (ou com token gerado).

    Nesse modo NADA abre sem login: só o assistente (/api/setup/*, que exige o token de uso único),
    o status e a meta. Loopback sem token (dev/testes) mantém o comportamento antigo (aberto).
    """
    if auth_required():
        return False
    from lib import setup_token  # noqa: PLC0415
    return (not STATE.bind_loopback) or setup_token.exists(DATA_ROOT)


_local_ips_cache: dict = {}


def local_ips() -> frozenset[str]:
    """IPs desta máquina (todas as interfaces), cacheado por 30 s. Usado com bind curinga."""
    now = time.monotonic()
    hit = _local_ips_cache.get("v")
    if hit and now - hit[0] < 30:
        return hit[1]
    ips = {"127.0.0.1", "::1"}
    try:
        import subprocess  # noqa: PLC0415
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout
        ips.update(x.strip().lower() for x in out.split() if x.strip())
    except Exception:  # noqa: BLE001
        pass
    val = frozenset(ips)
    _local_ips_cache["v"] = (now, val)
    return val


# --------------------------------------------------------------------------- #
# Política de Host/Origin (anti DNS-rebinding / CSRF) — compatível com proxy reverso
# --------------------------------------------------------------------------- #
def _hostname_of(host_header: str | None) -> str:
    """Hostname de um header Host (sem porta; aceita IPv6 `[::1]:8765`), em minúsculas."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[1:].split("]", 1)[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def _extra_allowed_hosts() -> tuple[str, ...]:
    """Hosts extras liberados (domínio do proxy) — `NETOPS_UI_ALLOWED_HOSTS=a.com,.b.com,*`."""
    raw = os.environ.get("NETOPS_UI_ALLOWED_HOSTS", "")
    return tuple(x.strip().lower() for x in raw.split(",") if x.strip())


def _hostname_allowed(hostname: str) -> bool:
    if not hostname:
        return False
    if hostname in STATE.allowed_hosts:
        return True
    if STATE.bind_wildcard and hostname in local_ips():
        return True
    for pat in _extra_allowed_hosts():
        if pat == "*" or hostname == pat or (pat.startswith(".") and hostname.endswith(pat)):
            return True
    return False


def host_origin_allowed(host_header: str | None, origin: str | None = None) -> bool:
    """Decide se um request (HTTP ou WebSocket) passa na checagem de Host/Origin.

    * Com **login ativo** (cofre inicializado) o gate real é a sessão: o token vai em header
      customizado/query (`X-Netops-Session`/`?auth=`), nunca em cookie ambiente — então CSRF/CSWSH
      não têm o que reaproveitar e um domínio atacante (rebinding) não tem o token. Aceita
      QUALQUER Host/Origin: é o que permite proxy reverso com qualquer domínio, que reescreva ou
      preserve o Host (Nginx, Traefik, Cloudflare, Caddy, HAProxy...).
    * **Sem login** (cofre não inicializado) o console está aberto, então Host/Origin são a única
      defesa: Host precisa ser loopback/IP de bind/`NETOPS_UI_ALLOWED_HOSTS`, e Origin, se
      presente, idem ou igual ao próprio Host (same-origin).
    """
    if auth_required():
        return True
    host = _hostname_of(host_header)
    if not _hostname_allowed(host):
        return False
    if origin:
        from urllib.parse import urlparse
        try:
            o = (urlparse(origin).hostname or "").lower()
        except ValueError:
            return False
        return bool(o) and (_hostname_allowed(o) or o == host)
    return True


# --------------------------------------------------------------------------- #
# Exceções de domínio (mapeadas p/ HTTP em app.py)
# --------------------------------------------------------------------------- #
class ConflictError(Exception):
    """Arquivo mudou no disco desde o GET (concorrência otimista) -> 409."""

    def __init__(self, current_hash: str, detail: str | None = None):
        detail = detail or _i18n.t("api_app.file_modified")
        self.current_hash = current_hash
        self.detail = detail
        super().__init__(detail)


class ValidationFailed(Exception):
    """Validação de schema/negócio falhou -> 422. `errors` no formato {loc, msg}."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(_i18n.t("api_app.validation_errors", n=len(errors)))


class ReadOnlyMode(Exception):
    """Servidor subiu com --read-only e tentaram escrever -> 403."""
