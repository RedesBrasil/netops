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


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Monta um NetOps mínimo em tmp e reaponta os caminhos de deps."""
    import deps

    (tmp_path / "network").mkdir()
    (tmp_path / "core" / "schemas").mkdir(parents=True)
    (tmp_path / "core" / "config").mkdir(parents=True)
    (tmp_path / "memory").mkdir(parents=True)

    cp = lambda rel: shutil.copy(PROJECT / rel, tmp_path / rel)
    cp("network/hosts.yaml")
    cp("network/topology.yaml")
    cp("core/schemas/inventory.schema.json")
    cp("core/config/project-config.yaml")
    cp("memory/MEMORY.md")

    monkeypatch.setattr(deps, "HOSTS_FILE", tmp_path / "network" / "hosts.yaml")
    monkeypatch.setattr(deps, "CREDS_FILE", tmp_path / "network" / "credentials.yaml")
    monkeypatch.setattr(deps, "TOPOLOGY_FILE", tmp_path / "network" / "topology.yaml")
    monkeypatch.setattr(deps, "TOPOLOGY_MD", tmp_path / "network" / "topology.md")
    monkeypatch.setattr(deps, "SCHEMA_FILE", tmp_path / "core" / "schemas" / "inventory.schema.json")
    monkeypatch.setattr(deps, "PROJECT_CONFIG", tmp_path / "core" / "config" / "project-config.yaml")
    monkeypatch.setattr(deps, "MEMORY_MD", tmp_path / "memory" / "MEMORY.md")
    deps.STATE.token = "T"
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
    """Cliente já "logado": token + uma sessão de login válida. (O gate de login só morde
    quando há cofre inicializado; o header de sessão é inócuo quando não é exigido.)"""
    from fastapi.testclient import TestClient
    import deps
    from app import create_app
    sid = deps.create_auth_session(3600)
    return TestClient(create_app(), base_url="http://127.0.0.1",
                      headers={"Authorization": "Bearer T", "X-Netops-Session": sid})
