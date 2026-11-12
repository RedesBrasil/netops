"""Fixtures: ambiente isolado (cópia tmp dos arquivos canônicos) + TestClient.

Os testes NUNCA tocam nos arquivos reais do projeto — deps.* é reapontado p/ um tmp.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[1]      # scripts/engine/ui
PROJECT = Path(__file__).resolve().parents[4]      # raiz
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))


@pytest.fixture(autouse=True)
def _isolated_vault_session(tmp_path_factory, monkeypatch):
    """Cache de sessão do cofre privado por teste.

    Sem isto, vault_session usa $XDG_RUNTIME_DIR ou /run/user/<uid>, isto é, a sessão REAL do
    operador: um clear_session() de teste trancava o cofre do console em produção, e testes em
    paralelo (xdist) disputavam o mesmo session.key. Subprocessos herdam a variável.
    """
    runtime = tmp_path_factory.mktemp("xdg-runtime")
    runtime.chmod(0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    # Estes módulos fixam o caminho em runs/claude/ no import: sem isto o teste lia (e podia
    # gravar) as preferências, o cache de modelos e o token de transcrição REAIS do console.
    import importlib
    claude_runs = tmp_path_factory.mktemp("runs-claude")
    for module, attr, name in (("services.claude_prefs", "_FILE", "prefs.json"),
                               ("services.claude_models", "_CACHE_FILE", "models-cache.json"),
                               ("services.audio_svc", "_FILE", "audio-transcription.json"),
                               ("services.claude_svc", "_AGENT_LOG", "agent-stderr.log")):
        monkeypatch.setattr(importlib.import_module(module), attr, claude_runs / name)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Monta um NetOps mínimo em tmp e reaponta os caminhos de deps."""
    import deps

    (tmp_path / "network").mkdir()
    (tmp_path / "core" / "schemas").mkdir(parents=True)
    (tmp_path / "core" / "config").mkdir(parents=True)
    (tmp_path / "memory").mkdir(parents=True)

    cp = lambda rel: shutil.copy(PROJECT / rel, tmp_path / rel)
    shutil.copy(PROJECT / "network/hosts.example.yaml", tmp_path / "network/hosts.yaml")
    shutil.copy(PROJECT / "network/topology.example.yaml", tmp_path / "network/topology.yaml")
    cp("core/schemas/inventory.schema.json")
    cp("core/config/project-config.yaml")
    cp("memory/MEMORY.md")

    monkeypatch.setattr(deps, "NETOPS_ROOT", tmp_path)
    monkeypatch.setattr(deps, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(deps, "BACKUPS_RUNS", tmp_path / "runs" / "backups")
    monkeypatch.setattr(deps, "BACKUPS_FILE", tmp_path / "network" / "backups.yaml")
    monkeypatch.setattr(deps, "BACKUPS_STORE", tmp_path / "backups")
    monkeypatch.setattr(deps, "NETWORK_DIR", tmp_path / "network")
    cp("core/config/core-config.yaml")
    deps.STATE.update_pending = False
    deps.STATE.active_writes = 0
    deps.STATE.active_sessions = 0
    deps.STATE.active_requests = 0
    monkeypatch.setattr(deps, "HOSTS_FILE", tmp_path / "network" / "hosts.yaml")
    monkeypatch.setattr(deps, "CREDS_FILE", tmp_path / "network" / "credentials.yaml")
    monkeypatch.setattr(deps, "MAPS_FILE", tmp_path / "network" / "maps.yaml")
    monkeypatch.setattr(deps, "TOPOLOGY_FILE", tmp_path / "network" / "topology.yaml")
    monkeypatch.setattr(deps, "TOPOLOGY_MD", tmp_path / "network" / "topology.md")
    monkeypatch.setattr(deps, "SCHEMA_FILE", tmp_path / "core" / "schemas" / "inventory.schema.json")
    monkeypatch.setattr(deps, "PROJECT_CONFIG", tmp_path / "core" / "config" / "project-config.yaml")
    monkeypatch.setattr(deps, "MEMORY_MD", tmp_path / "memory" / "MEMORY.md")
    monkeypatch.setattr(deps, "AUTH_SESSIONS_FILE", tmp_path / "runs" / ".ui-auth-sessions.json")
    deps.STATE.read_only = False
    deps.STATE.allow_vault_unlock = True
    deps.STATE.enable_terminal = False
    deps.STATE.enable_claude = False
    deps.STATE.allowed_hosts = ("127.0.0.1", "localhost")
    deps.STATE.auth_sessions = {}
    deps._vault_init_cache.clear()
    return tmp_path


@pytest.fixture()
def client(env):
    """Cliente já "logado": uma sessão de login válida (header X-Netops-Session). (O gate de login
    só morde quando há cofre inicializado; o header de sessão é inócuo quando não é exigido.)"""
    from fastapi.testclient import TestClient
    import deps
    from app import create_app
    sid = deps.create_auth_session(3600)
    return TestClient(create_app(), base_url="http://127.0.0.1",
                      headers={"X-Netops-Session": sid})
