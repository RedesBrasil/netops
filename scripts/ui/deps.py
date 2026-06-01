#!/usr/bin/env python3
"""Bootstrap de caminhos, segurança (token + Origin/Host) e estado compartilhado da UI.

Tudo aqui é "infra" do servidor — sem regra de negócio. Importar ANTES de qualquer
`from lib...` para garantir que scripts/ esteja no sys.path (mesmo padrão dos outros
scripts do NetOps: cli.py, inventory.py).
"""
from __future__ import annotations

import hmac
import sys
from dataclasses import dataclass, field
from pathlib import Path

# scripts/ui/deps.py -> parents[1] == scripts/   (p/ `from lib import ...`, `from docs import ...`)
# scripts/ui/deps.py -> parents[2] == raiz do projeto
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
NETOPS_ROOT = Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# --------------------------------------------------------------------------- #
# Caminhos canônicos (a UI só toca nestes arquivos)
# --------------------------------------------------------------------------- #
NETWORK_DIR = NETOPS_ROOT / "network"
HOSTS_FILE = NETWORK_DIR / "hosts.yaml"
CREDS_FILE = NETWORK_DIR / "credentials.yaml"
TOPOLOGY_FILE = NETWORK_DIR / "topology.yaml"
TOPOLOGY_MD = NETWORK_DIR / "topology.md"

CORE_DIR = NETOPS_ROOT / "core"
SCHEMA_FILE = CORE_DIR / "schemas" / "inventory.schema.json"
PROJECT_CONFIG = CORE_DIR / "config" / "project-config.yaml"

MEMORY_DIR = NETOPS_ROOT / "memory"
USER_MD = MEMORY_DIR / "USER.md"
MEMORY_MD = MEMORY_DIR / "MEMORY.md"
PATTERNS_FILE = MEMORY_DIR / "learned-patterns.yaml"
LESSONS_DIR = MEMORY_DIR / "lessons"

BEST_PRACTICES_DIR = NETOPS_ROOT / "best-practices"
BP_CATALOG = BEST_PRACTICES_DIR / "_catalog.yaml"
CONFIG_EXAMPLES_DIR = NETOPS_ROOT / "config-examples"
CE_INDEX = CONFIG_EXAMPLES_DIR / "_index.yaml"

WORKFLOWS_DIR = NETOPS_ROOT / "workflows"
AGENTS_DIR = NETOPS_ROOT / "agents"
REPORTS_DIR = NETOPS_ROOT / "reports"
RUNS_DIR = NETOPS_ROOT / "runs"

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Vendors válidos (espelha PADRAO.md + schema). Usado p/ validar pastas de conhecimento.
VENDORS = (
    "mikrotik", "unifi", "ubiquiti", "cisco", "huawei", "proxmox",
    "vmware", "datacom", "linux", "fiberhome", "intelbras", "general",
)


# --------------------------------------------------------------------------- #
# Estado do servidor (token de sessão, modo read-only)
# --------------------------------------------------------------------------- #
@dataclass
class ServerState:
    token: str = ""
    read_only: bool = False
    allow_vault_unlock: bool = True
    enable_terminal: bool = False
    allowed_hosts: tuple[str, ...] = field(default_factory=lambda: ("127.0.0.1", "localhost"))


STATE = ServerState()


def token_matches(supplied: str | None) -> bool:
    if not STATE.token:
        return False
    if not supplied:
        return False
    return hmac.compare_digest(supplied, STATE.token)


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
