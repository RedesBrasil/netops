#!/usr/bin/env python3
"""Bootstrap de caminhos, segurança (Origin/Host + login por senha-mestra) e estado compartilhado da UI.

Tudo aqui é "infra" do servidor — sem regra de negócio. Importar ANTES de qualquer
`from lib...` para garantir que scripts/engine/ esteja no sys.path (mesmo padrão dos
outros scripts do NetOps: cli.py, inventory.py).
"""
from __future__ import annotations

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
BACKUPS_STORE = NETOPS_ROOT / "backups"   # configs coletados (populado pelo runner)
BACKUPS_RUNS = NETOPS_ROOT / "runs" / "backups"   # status/log das execucoes (Run)

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
    "vmware", "datacom", "linux", "fiberhome", "intelbras", "general",
)


# --------------------------------------------------------------------------- #
# Estado do servidor (modo read-only, flags de features, sessões de login)
# --------------------------------------------------------------------------- #
@dataclass
class ServerState:
    read_only: bool = False
    update_pending: bool = False
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
    # Sessões de login do console (sid -> {"exp": epoch, "ttl": int}). Em memória do processo:
    # vale só enquanto o servidor está no ar (uvicorn single-process). Ver routers/auth.py.
    auth_sessions: dict = field(default_factory=dict)


STATE = ServerState()


# --------------------------------------------------------------------------- #
# Sessão de login (senha-mestra -> sid). Token de transporte (acima) e login são
# camadas independentes: o sid só é emitido por routers/auth.py após verificar a senha.
# --------------------------------------------------------------------------- #
def create_auth_session(ttl: int) -> str:
    """Emite um sid aleatório com expiração agora+ttl (TTL deslizante em auth_session_valid)."""
    sid = os.urandom(24).hex()
    STATE.auth_sessions[sid] = {"exp": time.time() + ttl, "ttl": ttl}
    return sid


def auth_session_valid(sid: str | None) -> bool:
    """True se o sid existe e não expirou; renova a janela (TTL deslizante). Limpa expirados."""
    now = time.time()
    for k in [k for k, v in STATE.auth_sessions.items() if v["exp"] <= now]:
        STATE.auth_sessions.pop(k, None)
    if not sid:
        return False
    sess = STATE.auth_sessions.get(sid)
    if not sess:
        return False
    sess["exp"] = now + sess["ttl"]
    return True


def drop_auth_session(sid: str | None) -> None:
    if sid:
        STATE.auth_sessions.pop(sid, None)


def clear_auth_sessions() -> None:
    STATE.auth_sessions.clear()


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


def auth_required() -> bool:
    """O console exige login com senha sempre que houver cofre inicializado."""
    return vault_initialized()


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
