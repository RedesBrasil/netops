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

# Vendors válidos (espelha PADRAO.md + schema). Usado p/ validar pastas de conhecimento.
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
    # Sessões de login do console (sha256(sid) -> {"exp": epoch}). Cache do arquivo
    # runs/.ui-auth-sessions.json (fonte da verdade, sobrevive a restart). Ver routers/auth.py.
    auth_sessions: dict = field(default_factory=dict)


STATE = ServerState()


# --------------------------------------------------------------------------- #
# Sessão de login (senha-mestra -> sid). Token de transporte (acima) e login são
# camadas independentes: o sid só é emitido por routers/auth.py após verificar a senha.
# --------------------------------------------------------------------------- #
AUTH_LOGIN_TTL_DEFAULT = 7 * 86400   # login vale 7 dias (absoluto), sobrevive a restart do backend
AUTH_SESSIONS_FILE: Path | None = None   # None = DATA_ROOT/runs/.ui-auth-sessions.json (resolvido na hora)


def _auth_sessions_file() -> Path:
    # Resolvido a cada uso (não no import): quem troca DATA_ROOT (testes, instalação temporária)
    # não pode gravar no arquivo de logins da instalação real. Sem isso a suíte de
    # testes sobrescrevia runs/.ui-auth-sessions.json e todo restart seguinte pedia login de novo.
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


def _read_auth_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)
            and isinstance(v.get("exp"), (int, float)) and v["exp"] > now} if isinstance(data, dict) else {}


def _update_auth_file(add: dict | None = None, drop: set | None = None, clear: bool = False) -> None:
    """Aplica só o DELTA (add/drop) sobre o que está no disco, sob flock, e ressincroniza a memória.

    Nunca despeja o dict em memória inteiro: outro processo (restart sobrepondo, CLI, testes) que
    tenha uma visão velha não consegue apagar logins que ele não conhece. Grava só o SHA-256 dos
    sids (nunca o sid) + expiração; 0600, atômico.
    """
    path = _auth_sessions_file()
    try:
        import fcntl  # noqa: PLC0415
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(path.with_suffix(".lock")), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            data = {} if clear else _read_auth_file(path)
            data.update(add or {})
            for k in drop or ():
                data.pop(k, None)
            tmp = path.with_suffix(f".tmp.{os.getpid()}")
            fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        finally:
            os.close(lock_fd)
    except OSError:
        data = {} if clear else dict(STATE.auth_sessions)
        data.update(add or {})
        for k in drop or ():
            data.pop(k, None)
    STATE.auth_sessions.clear()
    STATE.auth_sessions.update(data)


def load_auth_sessions() -> None:
    """Recarrega os logins ainda válidos (no arranque e quando um sid não é achado em memória)."""
    STATE.auth_sessions.update(_read_auth_file(_auth_sessions_file()))


def create_auth_session(ttl: int | None = None) -> str:
    """Emite um sid aleatório que expira em agora+ttl (absoluto) e persiste em disco."""
    sid = os.urandom(24).hex()
    _update_auth_file(add={_sid_key(sid): {"exp": time.time() + (ttl or login_ttl())}})
    return sid


def auth_session_valid(sid: str | None) -> bool:
    """True se o sid existe e não expirou. Se não estiver em memória, relê o disco (login feito
    por outro processo/instância continua valendo)."""
    if not sid:
        return False
    key = _sid_key(sid)
    now = time.time()
    entry = STATE.auth_sessions.get(key)
    if entry is None:
        disk = _read_auth_file(_auth_sessions_file())
        entry = disk.get(key)
        if entry is not None:
            STATE.auth_sessions[key] = entry
    if entry is None:
        return False
    if entry.get("exp", 0) <= now:
        _update_auth_file(drop={key})
        return False
    return True


def drop_auth_session(sid: str | None) -> None:
    if sid:
        _update_auth_file(drop={_sid_key(sid)})


def clear_auth_sessions() -> None:
    _update_auth_file(clear=True)


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
    """O console exige login com senha sempre que houver cofre inicializado."""
    return vault_initialized()


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

    def __init__(self, current_hash: str, detail: str = "arquivo modificado externamente"):
        self.current_hash = current_hash
        self.detail = detail
        super().__init__(detail)


class ValidationFailed(Exception):
    """Validação de schema/negócio falhou -> 422. `errors` no formato {loc, msg}."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(f"{len(errors)} erro(s) de validação")


class ReadOnlyMode(Exception):
    """Servidor subiu com --read-only e tentaram escrever -> 403."""
