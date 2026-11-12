"""IDs inteiros atravessam scripts/backups; tudo usa arquivos e transportes fictícios."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ENGINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE.parent / "tools"))


@pytest.fixture()
def integer_inventory(tmp_path, monkeypatch):
    from lib import inventory, transport
    import deps

    data = {
        "version": 2, "next_host_id": 43,
        "groups": {"routers": {"vendor": "mikrotik", "access": {"method": "ssh", "port": 2222}}},
        "hosts": [
            {"id": 7, "hostname": "Roteador Matriz", "mgmt_ip": "192.0.2.7", "group": "routers"},
            {"id": 42, "hostname": "Servidor", "mgmt_ip": "192.0.2.42", "vendor": "linux"},
        ],
        "legacy_aliases": [{"alias": "rt-old", "host_id": 7}],
    }
    network = tmp_path / "network"
    network.mkdir()
    hosts_path = network / "hosts.yaml"
    hosts_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(inventory, "HOSTS_FILE", hosts_path)
    monkeypatch.setattr(inventory, "CREDS_FILE", network / "missing-credentials.yaml")
    monkeypatch.setattr(deps, "HOSTS_FILE", hosts_path)
    monkeypatch.setattr(deps, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(deps, "CREDS_FILE", network / "missing-credentials.yaml")
    monkeypatch.setattr(deps, "BACKUPS_FILE", network / "backups.yaml")
    monkeypatch.setattr(deps, "BACKUPS_STORE", tmp_path / "backups")
    monkeypatch.setattr(deps, "BACKUPS_RUNS", tmp_path / "runs" / "backups")

    def no_network(*args, **kwargs):
        raise AssertionError("o teste não pode abrir conexão")

    monkeypatch.setattr(transport, "open_cli", no_network)
    monkeypatch.setattr(transport, "open_routeros_api", no_network)
    monkeypatch.setattr(inventory, "resolve_secret", no_network)
    return data, tmp_path


@pytest.mark.parametrize("ref", [7, "rt-old", "Roteador Matriz"])
def test_cli_runner_resolves_integer_and_alias_to_management_ip(integer_inventory, monkeypatch, ref):
    from lib import cli_runner

    captured = {}

    class Connection:
        def send_command(self, command, read_timeout):
            captured["command"] = command
            return "coleta fictícia"

        def disconnect(self):
            captured["closed"] = True

    def open_fake(host, cred):
        captured.update(host=host, cred=cred)
        return Connection()

    monkeypatch.setattr(cli_runner, "open_cli", open_fake)
    assert cli_runner.run_commands(ref, ["show version"])["show version"] == "coleta fictícia"
    assert cli_runner.canonical_host_id(ref) == 7
    assert captured["host"]["id"] == 7
    assert type(captured["host"]["id"]) is int
    assert captured["host"]["mgmt_ip"] == "192.0.2.7"
    assert captured["host"]["access"]["port"] == 2222
    assert captured["closed"]


def test_access_legacy_scripts_removed():
    access = ENGINE.parent / "tools" / "access"
    assert not (access / "ssh.py").exists() and not (access / "telnet.py").exists()


def _fake_session(captured):
    class FakeSession:
        def __init__(self, sid, host_ref, method, shell):
            captured.append(host_ref)
            self.log_path = "fake.log"

        def connect(self):
            pass

        def run(self, cmd, timeout, expect, timing):
            return {"status": "ok", "output": "ok", "stderr": "", "exit": 0, "seconds": 0}

        def close(self):
            pass
    return FakeSession


def test_session_run_passes_true_integer(integer_inventory, monkeypatch):
    from access import session
    captured = []
    monkeypatch.setattr(session, "Session", _fake_session(captured))
    monkeypatch.setattr(sys, "argv", ["session", "run", "--host-id", "7", "--command", "show version"])
    assert session.main() == 0
    assert captured == [7] and type(captured[0]) is int
    monkeypatch.setattr(sys, "argv", ["session", "run", "--host-id", "7", "--host", "rt-old",
                                      "--command", "x"])
    with pytest.raises(SystemExit):
        session.main()


def test_session_run_rejects_host_outside_inventory(integer_inventory, monkeypatch):
    from access import session
    captured = []
    monkeypatch.setattr(session, "Session", _fake_session(captured))
    monkeypatch.setattr(sys, "argv", ["session", "run", "--host", "nao-existe", "--command", "x"])
    assert session.main() == 1 and captured == []


def test_api_mikrotik_passes_true_integer(integer_inventory, monkeypatch):
    from access import api_mikrotik
    captured = []
    monkeypatch.setattr(api_mikrotik, "query", lambda host, paths: captured.append(host) or {})
    monkeypatch.setattr(sys, "argv", ["api_mikrotik", "--host-id", "7", "--path", "/ip/service"])
    assert api_mikrotik.main() == 0
    assert captured == [7] and type(captured[0]) is int
    monkeypatch.setattr(sys, "argv", ["api_mikrotik", "--host-id", "7", "--host", "rt-old",
                                      "--path", "/ip/service"])
    with pytest.raises(SystemExit):
        api_mikrotik.main()


def test_access_output_uses_canonical_id_after_alias_selection(integer_inventory, monkeypatch):
    from access import api_mikrotik, session

    _, root = integer_inventory
    monkeypatch.setattr(session, "NETOPS_ROOT", root)
    monkeypatch.setattr(api_mikrotik, "NETOPS_ROOT", root)
    assert session.Session("t", "rt-old", "ssh", False).log_dir.name.endswith("-session-7")
    assert api_mikrotik._save("Roteador Matriz", {"/ip/service": []}).name == "7.json"


@pytest.mark.parametrize("module_name", ["ping_advanced", "portscan", "traceroute_advanced"])
def test_diagnostics_resolve_without_reading_credentials(integer_inventory, monkeypatch, module_name):
    from lib import inventory
    module = importlib.import_module("diagnostics." + module_name)

    class ForbiddenCredentials:
        def exists(self):
            raise AssertionError("diagnóstico não lê arquivo de credenciais")

    monkeypatch.setattr(inventory, "CREDS_FILE", ForbiddenCredentials())
    assert module.resolve_target(7, None) == "192.0.2.7"
    assert module.resolve_target("rt-old", None) == "192.0.2.7"


def test_security_all_uses_integer_ids_without_credentials(integer_inventory, monkeypatch, capsys):
    from analysis import security_assessment
    from lib import inventory

    class ForbiddenCredentials:
        def exists(self):
            raise AssertionError("análise não lê arquivo de credenciais")

    monkeypatch.setattr(inventory, "CREDS_FILE", ForbiddenCredentials())
    monkeypatch.setattr(security_assessment, "load_checks", lambda: [{"tipo": "config"}])
    monkeypatch.setattr(sys, "argv", ["assessment", "--all"])
    assert security_assessment.main() == 0
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert {item["host"] for item in findings} == {7, 42}
    assert all(type(item["host"]) is int for item in findings)


def test_topology_keeps_integer_identity_when_hostname_changes(integer_inventory):
    from docs.topology_render import render

    data, _ = integer_inventory
    topology = {"links": [{"a": {"host": 7}, "b": {"host": 42}}]}
    before = render(data, topology)
    data["hosts"][0]["hostname"] = "Novo nome"
    after = render(data, topology)
    assert "host_7 --- host_42" in before and "host_7 --- host_42" in after
    assert 'host_7["Novo nome<br/>' in after


def test_topology_dangling_endpoint_is_explicit_diagnostic_node(integer_inventory):
    from docs.topology_render import render

    data, _ = integer_inventory
    content = render(data, {"links": [{"a": {"host": 7}, "b": {"host": 404}}]})
    assert "404<br/>host ausente" in content
    assert "2 host(s), 1 enlace(s)" in content


def test_backup_targets_expand_as_integers(integer_inventory):
    from services import backups_svc

    assert backups_svc._expand_targets({"targets": {"hosts": [42, 7], "groups": ["routers"]}}) == [42, 7]


def test_backup_history_preserves_legacy_and_leaves_orphans_unassigned(integer_inventory):
    import deps
    from services import backups_svc

    config = {"version": 3, "services": [], "legacy_sources": [{"host_id": 7, "directory": "rt-old"}]}
    deps.BACKUPS_FILE.write_text(yaml.safe_dump(config), encoding="utf-8")
    for rel in ["rt-old/old.cfg", "by-id/7/new.cfg", "42/orphan.cfg", "removed/old.cfg", "by-id/42/new.cfg"]:
        path = deps.BACKUPS_STORE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("configuração fictícia", encoding="utf-8")
    result = backups_svc.list_hosts_with_backups()["hosts"]
    assigned = {row["host"]: row for row in result if row["assigned"]}
    assert assigned[7]["count"] == 2
    assert assigned[7]["hostname"] == "Roteador Matriz"
    assert assigned[42]["count"] == 1
    assert all(type(row["host"]) is int for row in assigned.values())
    assert {row["directory"] for row in result if not row["assigned"]} == {"42", "removed"}
    assert all(row["host"] is None for row in result if not row["assigned"])


@pytest.mark.parametrize("invalid", ["7", 7.0, True, 0, -1])
def test_backup_targets_model_rejects_non_integer_identity(invalid):
    from models import BackupTargets
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BackupTargets(hosts=[invalid])


def test_backup_save_preserves_immutable_legacy_associations(integer_inventory):
    import deps
    from services import backups_svc

    config = {"version": 3, "services": [], "legacy_sources": [{"host_id": 7, "directory": "rt-old"}]}
    deps.BACKUPS_FILE.write_text(yaml.safe_dump(config), encoding="utf-8")
    revision = backups_svc.load()["rev"]
    backups_svc.save(dict(config), revision)
    saved = backups_svc.load()
    assert saved["config"]["legacy_sources"] == config["legacy_sources"]
    tampered = {**config, "legacy_sources": [{"host_id": 42, "directory": "rt-old"}]}
    with pytest.raises(deps.ValidationFailed):
        backups_svc.save(tampered, saved["rev"])


def test_backup_delete_cascade_removes_targets_but_keeps_history(integer_inventory):
    import deps
    from services import backups_svc, yaml_io

    config = {"version": 3, "services": [{"id": "daily", "targets": {"hosts": [7, 42]}}],
              "legacy_sources": [{"host_id": 7, "directory": "rt-old"}]}
    deps.BACKUPS_FILE.write_text(yaml.safe_dump(config), encoding="utf-8")
    writes, checks = [], []
    backups_svc.cascade_host_delete(7, writes, checks)
    yaml_io.write_many(writes, checks=checks)
    result = backups_svc.load()["config"]
    assert result["services"][0]["targets"]["hosts"] == [42]
    assert result["legacy_sources"] == config["legacy_sources"]


def test_pending_migration_blocks_backup_save(integer_inventory):
    import deps
    from lib.inventory_lock import JOURNAL_NAME
    from services import backups_svc

    (deps.HOSTS_FILE.parent / JOURNAL_NAME).write_text('{"status":"applying"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="migração"):
        backups_svc.save({"version": 3, "services": [], "legacy_sources": []}, None)
    with pytest.raises(RuntimeError, match="migração"):
        backups_svc.list_hosts_with_backups()


def test_backup_launch_uses_current_interpreter_and_integer_status(integer_inventory, monkeypatch):
    import deps
    from lib import vault_session
    from services import backups_svc

    config = {"version": 3, "services": [{"id": "daily", "targets": {"hosts": [7]}}], "legacy_sources": []}
    deps.BACKUPS_FILE.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(vault_session, "get_session_key", lambda: object())
    captured = []
    monkeypatch.setattr(backups_svc.subprocess, "Popen", lambda argv, **kwargs: captured.append(argv))
    result = backups_svc.start_run("daily")
    assert captured[0][0] == sys.executable
    assert captured[0][-4:-2] == ["--data-root", str(deps.DATA_ROOT)]
    assert captured[0][-2:] == ["--run-id", result["run_id"]]
    state = backups_svc.read_run(result["run_id"])
    assert state["hosts"] == [{"id": 7, "hostname": "Roteador Matriz", "state": "pending", "detail": ""}]


def test_backup_runner_saves_integer_namespace_using_access_tool(integer_inventory, monkeypatch):
    import backup_runner

    data, root = integer_inventory
    store, runs = root / "backups", root / "runs" / "backups"
    runs.mkdir(parents=True)
    run_id = "fake-run"
    status_file = runs / (run_id + ".json")
    status_file.write_text(json.dumps({"hosts": [{"id": 7, "state": "pending"}]}), encoding="utf-8")
    monkeypatch.setattr(backup_runner, "HOSTS_FILE", root / "network" / "hosts.yaml")
    monkeypatch.setattr(backup_runner, "BACKUPS_STORE", store)
    monkeypatch.setattr(backup_runner, "BACKUPS_RUNS", runs)
    calls = []
    monkeypatch.setattr(backup_runner, "run_commands",
                        lambda host, commands, **kw: calls.append((host, commands, kw)) or {"/export": "/system identity\nset name=fake"})
    monkeypatch.setattr(sys, "argv", ["backup_runner", "--run-id", run_id])
    backup_runner.main()
    assert calls == [(7, ["/export"], {"force_method": "ssh", "read_timeout": 90})]
    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["hosts"][0]["id"] == 7 and type(status["hosts"][0]["id"]) is int
    assert status["hosts"][0]["path"] == "by-id/7/fake-run.cfg"
    assert (store / "by-id" / "7" / "fake-run.cfg").is_file()


def test_backup_runner_data_root_never_falls_back_to_real_inventory(integer_inventory, monkeypatch):
    import backup_runner
    from lib import inventory

    _, root = integer_inventory
    runs = root / "runs" / "backups"
    runs.mkdir(parents=True)
    (runs / "isolated.json").write_text('{"hosts":[{"id":7}]}', encoding="utf-8")
    captured = []
    monkeypatch.setattr(backup_runner, "HOSTS_FILE", Path("/forbidden/hosts.yaml"))
    monkeypatch.setattr(backup_runner, "BACKUPS_STORE", Path("/forbidden/backups"))
    monkeypatch.setattr(backup_runner, "BACKUPS_RUNS", Path("/forbidden/runs"))

    def collect(host, commands, **kwargs):
        captured.append((inventory.HOSTS_FILE, inventory.CREDS_FILE))
        return {"/export": "configuração fictícia"}

    monkeypatch.setattr(backup_runner, "run_commands", collect)
    monkeypatch.setattr(sys, "argv", ["runner", "--data-root", str(root), "--run-id", "isolated"])
    backup_runner.main()
    assert captured == [(root / "network" / "hosts.yaml", root / "network" / "credentials.yaml")]
    assert (root / "backups" / "by-id" / "7" / "isolated.cfg").exists()
