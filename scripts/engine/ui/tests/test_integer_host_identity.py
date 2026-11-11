"""Identidade inteira e migração transacional, sempre em inventário fictício."""
from __future__ import annotations

import copy
import json
import multiprocessing
from pathlib import Path

import pytest
import yaml

import deps
from lib import host_id_migration as migration
from lib.host_identity import MAX_HOST_ID, host_index, identity_errors, resolve_reference
from lib.inventory import resolve_host
from services import inventory_svc, yaml_io


def _v2():
    return {"version": 2, "next_host_id": 3, "groups": {}, "hosts": [
        {"id": 1, "hostname": "Core", "mgmt_ip": "192.0.2.1", "vendor": "linux",
         "access": {"method": "ssh", "port": 2222}, "credential": "test"},
        {"id": 2, "hostname": "Access", "mgmt_ip": "192.0.2.2", "vendor": "mikrotik",
         "access": {"method": "api", "port": 8728}, "credential": "test"}],
        "legacy_aliases": [{"alias": "old-core", "host_id": 1}]}


def _legacy(root):
    network = root / "network"
    network.mkdir(parents=True, exist_ok=True)
    docs = {
        "hosts.yaml": {"version": 1, "groups": {"routers": {"vendor": "mikrotik", "access": {"method": "ssh", "port": 22}, "credential": "test"}},
                       "hosts": {"old-a": {"hostname": "Core", "mgmt_ip": "192.0.2.1", "group": "routers"},
                                 "old-b": {"hostname": "Access", "mgmt_ip": "192.0.2.2", "group": "routers"}}},
        "topology.yaml": {"version": 1, "links": [{"a": {"host": "old-a", "port": "ether1"}, "b": {"host": "old-b"}, "speed": "1G"}], "segments": []},
        "maps.yaml": {"version": 1, "maps": [{"id": "all", "name": "Rede", "kind": "all", "members": ["old-a", "old-b"],
            "positions": {"old-a": {"x": 10, "y": 20, "z_index": -2}, "old-b": {"x": 30, "y": 40}},
            "objects": [{"id": "box", "type": "shape", "position": {"x": 100, "y": 0}}],
            "visual_links": [{"id": "visual", "source": "host:old-a", "target": "object:box"}], "edges": {}}]},
        "backups.yaml": {"version": 2, "services": [{"id": "night", "name": "Noturno", "targets": {"hosts": ["old-b"], "groups": ["routers"]}}]},
    }
    for name, doc in docs.items():
        yaml_io.atomic_write(network / name, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
    (root / "backups" / "old-a").mkdir(parents=True)
    (root / "backups" / "42").mkdir()
    return docs


@pytest.mark.parametrize("value", [True, False, "1", 1.0, 0, -1, MAX_HOST_ID + 1, None])
def test_invalid_canonical_ids_rejected(value):
    data = _v2()
    data["hosts"][0]["id"] = value
    assert identity_errors(data)
    with pytest.raises(ValueError):
        host_index(data)


def test_alias_hostname_ambiguity_and_retired_alias_reservation():
    data = _v2()
    assert resolve_reference(1, data) == 1
    assert resolve_reference("old-core", data) == 1
    assert resolve_reference("Core", data) == 1
    with pytest.raises(KeyError):
        resolve_reference("1", data)
    data["hosts"][1]["hostname"] = "Core"
    with pytest.raises(ValueError, match="ambíguo"):
        resolve_reference("Core", data)
    data["hosts"].pop(0)
    data["hosts"][0]["hostname"] = "old-core"
    with pytest.raises(KeyError, match="excluído"):
        resolve_reference("old-core", data)


def test_numeric_legacy_alias_is_distinct_from_integer_id():
    data = _v2()
    data["legacy_aliases"].append({"alias": "1", "host_id": 2})
    assert resolve_reference("1", data) == 2
    assert resolve_reference(1, data) == 1


def test_group_inheritance_and_no_decrypt(monkeypatch):
    data = _v2()
    data["groups"] = {"router": {"access": {"method": "ssh", "port": 22}, "vendor": "linux", "credential": "test"}}
    data["hosts"][0] = {"id": 1, "hostname": "Core", "mgmt_ip": "192.0.2.1", "group": "router", "access": {"port": 2222}}
    def forbidden(*args):
        raise AssertionError("não deve descriptografar")
    monkeypatch.setattr("lib.inventory.resolve_secret", forbidden)
    host, cred = resolve_host(1, data, {}, decrypt=False)
    assert host["id"] == host["name"] == 1
    assert host["access"] == {"method": "ssh", "port": 2222}
    assert host["mgmt_ip"] == "192.0.2.1" and cred == {}


def test_counters_duplicate_ids_and_aliases_rejected():
    for change in (lambda d: d.update(next_host_id=2),
                   lambda d: d["hosts"][1].update(id=1),
                   lambda d: d["legacy_aliases"].append({"alias": "old-core", "host_id": 2})):
        data = _v2()
        change(data)
        assert identity_errors(data)


def test_create_edit_delete_never_reuses_id(client, env):
    fields = {"hostname": "Novo", "mgmt_ip": "192.0.2.20", "vendor": "linux",
              "credential": "test", "access": {"method": "ssh"}}
    created = client.post("/api/hosts", json=fields)
    assert created.status_code == 201, created.text
    first = created.json()["id"]
    assert type(first) is int
    assert client.patch(f"/api/hosts/{first}", json={"hostname": "Renomeado"}).status_code == 200
    assert client.get(f"/api/hosts/{first}").json()["effective"]["hostname"] == "Renomeado"
    assert client.delete(f"/api/hosts/{first}").status_code == 200
    again = client.post("/api/hosts", json=fields)
    assert again.status_code == 201, again.text
    assert again.json()["id"] > first
    data = yaml.safe_load(deps.HOSTS_FILE.read_text())
    assert data["next_host_id"] > again.json()["id"]


@pytest.mark.parametrize("manual", [42, "42", True, 1.5, None])
def test_api_forbids_id_input_on_create_and_edit(client, manual):
    fields = {"hostname": "Manual", "mgmt_ip": "192.0.2.10", "id": manual}
    assert client.post("/api/hosts", json=fields).status_code == 422
    assert client.patch("/api/hosts/1", json={"id": manual}).status_code == 422
    assert client.put("/api/hosts/1", json={"id": manual}).status_code == 422


def test_rename_id_refused(client):
    assert client.post("/api/hosts/1/rename", json={"to": "new"}).status_code == 422
    assert client.get("/api/hosts/text").status_code == 422


def test_migration_preserves_links_maps_backups_and_comments(tmp_path):
    docs = _legacy(tmp_path)
    raw = (tmp_path / "network" / "hosts.yaml").read_text()
    yaml_io.atomic_write(tmp_path / "network" / "hosts.yaml", "# inventário comentado\n" + raw.replace("  old-a:", "  # roteador principal\n  old-a:"))
    from services.topology_svc import link_ids
    old_link_id = link_ids(docs["topology.yaml"]["links"])[0]
    before = {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    prepared = migration.plan(tmp_path)
    assert {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES} == before
    assert prepared["mapping"] == [{"alias": "old-a", "host_id": 1}, {"alias": "old-b", "host_id": 2}]
    done = migration.apply(tmp_path)
    assert done["status"] == "complete"
    inv = yaml.safe_load((tmp_path / "network" / "hosts.yaml").read_text())
    assert inv["hosts"][0]["id"] == 1 and type(inv["hosts"][0]["id"]) is int
    assert "# inventário comentado" in (tmp_path / "network" / "hosts.yaml").read_text()
    assert "roteador principal" in (tmp_path / "network" / "hosts.yaml").read_text()
    topo = yaml.safe_load((tmp_path / "network" / "topology.yaml").read_text())
    assert topo["links"][0]["id"] == old_link_id
    assert topo["links"][0]["a"]["host"] == 1
    maps = yaml.safe_load((tmp_path / "network" / "maps.yaml").read_text())["maps"][0]
    assert maps["positions"][0] == {"host_id": 1, "x": 10, "y": 20, "z_index": -2}
    assert maps["visual_links"][0]["source"] == {"kind": "host", "host_id": 1}
    backups = yaml.safe_load((tmp_path / "network" / "backups.yaml").read_text())
    assert backups["services"][0]["targets"]["hosts"] == [2]
    assert backups["legacy_sources"] == [{"host_id": 1, "directory": "old-a"}]
    assert (tmp_path / "backups" / "42").is_dir()
    after = {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    assert migration.apply(tmp_path)["status"] == "already_migrated"
    assert after == {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    assert migration.recover(tmp_path, rollback_complete=True)["status"] == "rolled_back"
    assert before == {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}


def test_missing_refs_block_every_write(tmp_path):
    docs = _legacy(tmp_path)
    docs["topology.yaml"]["links"][0]["a"]["host"] = "absent"
    yaml_io.atomic_write(tmp_path / "network" / "topology.yaml", yaml.safe_dump(docs["topology.yaml"]))
    before = {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    with pytest.raises(migration.PreflightError) as exc:
        migration.apply(tmp_path)
    assert exc.value.problems[0]["reference"] == "absent"
    assert before == {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    assert not (tmp_path / "runs").exists()


def test_crash_journal_blocks_reads_then_recovers(tmp_path, monkeypatch):
    _legacy(tmp_path)
    before = {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    original = migration._atomic_write
    def crash(path, data, mode=0o600):
        if path == tmp_path / "network" / "maps.yaml":
            raise SystemExit("queda simulada")
        return original(path, data, mode)
    monkeypatch.setattr(migration, "_atomic_write", crash)
    with pytest.raises(SystemExit):
        migration.apply(tmp_path)
    from lib.inventory_lock import ensure_migration_complete
    with pytest.raises(RuntimeError, match="incompleta"):
        ensure_migration_complete(tmp_path / "network")
    monkeypatch.setattr(migration, "_atomic_write", original)
    assert migration.recover(tmp_path)["status"] == "rolled_back"
    assert before == {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    ensure_migration_complete(tmp_path / "network")


def test_io_failure_rolls_back_automatically(tmp_path, monkeypatch):
    _legacy(tmp_path)
    before = {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    original = migration._atomic_write
    failed = False
    def fail_once(path, data, mode=0o600):
        nonlocal failed
        if path == tmp_path / "network" / "maps.yaml" and not failed:
            failed = True
            raise OSError("falha simulada")
        return original(path, data, mode)
    monkeypatch.setattr(migration, "_atomic_write", fail_once)
    with pytest.raises(OSError):
        migration.apply(tmp_path)
    assert before == {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}


def test_rollback_never_overwrites_subsequent_user_edits(tmp_path):
    _legacy(tmp_path)
    migration.apply(tmp_path)
    path = tmp_path / "network" / "hosts.yaml"
    yaml_io.atomic_write(path, path.read_text() + "# edição posterior\n")
    before = {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    with pytest.raises(ValueError, match="preservar edições"):
        migration.recover(tmp_path, rollback_complete=True)
    assert before == {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}


def test_expected_plan_hash_rejects_external_changes(tmp_path):
    _legacy(tmp_path)
    plan = migration.plan(tmp_path)
    hashes = {name: migration._digest(raw) for name, raw in plan["before"].items()}
    path = tmp_path / "network" / "maps.yaml"
    yaml_io.atomic_write(path, path.read_text() + "# nova revisão\n")
    with pytest.raises(ValueError, match="dry-run"):
        migration.apply(tmp_path, expected_hashes=hashes)


@pytest.mark.parametrize("problem", ["coordinates", "reference_map", "duplicate_positions", "duplicate_members", "duplicate_legacy_sources", "bad_access_port"])
def test_malformed_prepared_documents_block_before_baseline(tmp_path, problem):
    docs = _legacy(tmp_path)
    if problem == "coordinates":
        docs["maps.yaml"]["maps"][0]["positions"]["old-a"]["x"] = "bad"
    elif problem == "reference_map":
        docs["maps.yaml"]["maps"][0]["objects"][0].update(type="reference", map_id="missing")
    elif problem == "duplicate_members":
        docs["maps.yaml"]["maps"][0]["members"] = ["old-a", "old-a"]
    elif problem == "duplicate_legacy_sources":
        docs["backups.yaml"]["legacy_sources"] = [{"host_id": 1, "directory": "old-a"}, {"host_id": 2, "directory": "old-a"}]
    elif problem == "bad_access_port":
        docs["hosts.yaml"]["groups"]["routers"]["access"]["port"] = 99999
    elif problem == "duplicate_positions":
        converted, _ = migration.transform(docs, [])
        converted["maps.yaml"]["maps"][0]["positions"].append(copy.deepcopy(converted["maps.yaml"]["maps"][0]["positions"][0]))
        docs = converted
    for name, doc in docs.items():
        yaml_io.atomic_write(tmp_path / "network" / name, migration._dump(doc))
    before = {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    with pytest.raises(migration.PreflightError):
        migration.apply(tmp_path)
    assert before == {name: (tmp_path / "network" / name).read_bytes() for name in migration.FILES}
    assert not (tmp_path / "runs").exists()


def test_retained_canonical_archives_prevent_identity_reuse_after_rollback(tmp_path):
    _legacy(tmp_path)
    migration.apply(tmp_path)
    canonical = tmp_path / "backups" / "by-id" / "1" / "run.cfg"
    canonical.parent.mkdir(parents=True)
    yaml_io.atomic_write(canonical, "config fictícia\n")
    with pytest.raises(ValueError, match="preservar identidades"):
        migration.recover(tmp_path, rollback_complete=True)


def test_symlinked_baseline_parent_refused(tmp_path):
    _legacy(tmp_path)
    external = tmp_path / "external-runs"
    external.mkdir()
    (tmp_path / "runs").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        migration.apply(tmp_path)
    assert not list(external.iterdir())


def test_readonly_inventory_never_opens_credentials(tmp_path, monkeypatch):
    _legacy(tmp_path)
    from lib import inventory
    monkeypatch.setattr(inventory, "HOSTS_FILE", tmp_path / "network" / "hosts.yaml")
    monkeypatch.setattr(inventory, "CREDS_FILE", tmp_path / "network" / "credentials.yaml")
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path.name == "credentials.yaml":
            raise AssertionError("leitura de credenciais proibida")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded)
    hosts, creds = inventory.load_inventory(include_credentials=False)
    assert hosts["version"] == 1 and creds == {}
    assert inventory.validate()[0]


def test_v1_read_compatibility_blocks_edits_with_migration_message(client, env):
    _legacy(env)
    assert client.get("/api/hosts/old-a").status_code == 200
    response = client.patch("/api/hosts/old-a", json={"hostname": "Outro"})
    assert response.status_code == 422
    assert "migração" in response.text
    assert client.delete("/api/hosts/old-a").status_code == 422


def test_dry_run_refuses_interrupted_journal(tmp_path, capsys):
    _legacy(tmp_path)
    yaml_io.atomic_write(tmp_path / "network" / ".host-id-migration.json", json.dumps({"version": 1, "status": "applying"}))
    assert migration.main(["dry-run", "--root", str(tmp_path)]) == 1
    assert "incompleta" in capsys.readouterr().out


def _concurrent_create(queue, number):
    try:
        result = inventory_svc.create_host({"hostname": f"Node {number}", "mgmt_ip": f"192.0.2.{number}",
            "vendor": "linux", "credential": "test", "access": {"method": "ssh"}}, None)
        queue.put(result["id"])
    except Exception as exc:
        queue.put(type(exc).__name__ + ":" + str(exc))


def test_multiprocess_allocator_serializes_counter(env):
    data = _v2()
    data["hosts"] = []
    data["legacy_aliases"] = []
    data["next_host_id"] = 1
    yaml_io.atomic_write(deps.HOSTS_FILE, yaml.safe_dump(data))
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    processes = [ctx.Process(target=_concurrent_create, args=(queue, number)) for number in range(1, 5)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    assert sorted(queue.get(timeout=3) for _ in processes) == [1, 2, 3, 4]
    data = yaml.safe_load(deps.HOSTS_FILE.read_text())
    assert data["next_host_id"] == 5 and len(data["hosts"]) == 4
