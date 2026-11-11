#!/usr/bin/env python3
"""Migração explícita de IDs: dry-run, baseline, commit com journal e recuperação.

Não lê credentials.yaml, não altera configurações coletadas e não acessa dispositivos.
Uso e limites em scripts/engine/lib/SKILL.md.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from lib.host_identity import host_index, identity_errors, require_host_id
from lib.inventory_lock import JOURNAL_NAME, MigrationIncomplete, ensure_migration_complete, inventory_lock

FILES = ("hosts.yaml", "topology.yaml", "maps.yaml", "backups.yaml")
MAX_FILE_BYTES = 32 * 1024 * 1024


class PreflightError(ValueError):
    def __init__(self, problems):
        self.problems = problems
        super().__init__(f"pré-validação falhou: {len(problems)} problema(s); nenhuma alteração aplicada")


def _yaml():
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _dump(data):
    out = StringIO()
    _yaml().dump(data, out)
    return out.getvalue()


def _copy_key_comment(mapping, key, sequence, index):
    comment = getattr(getattr(mapping, "ca", None), "items", {}).get(key)
    if not comment:
        return
    tokens = [token for part in comment if part for token in (part if isinstance(part, list) else [part])]
    value = "\n".join(token.value.rstrip().lstrip("# ") for token in tokens if hasattr(token, "value"))
    if value:
        sequence.yaml_set_comment_before_after_key(index, before=value)


def _digest(data: bytes | None):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _read(path):
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"symlink não permitido no caminho de migração: {component.name}")
    if path.is_symlink():
        raise ValueError(f"não é permitido migrar symlink: {path.name}")
    if not path.exists():
        return None
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"arquivo excede o limite de migração: {path.name}")
    return path.read_bytes()


def _documents(root):
    defaults = {
        "hosts.yaml": {"version": 1, "groups": {}, "hosts": {}},
        "topology.yaml": {"version": 1, "links": [], "segments": []},
        "maps.yaml": {"version": 1, "maps": []},
        "backups.yaml": {"version": 2, "services": []},
    }
    originals, docs = {}, {}
    for name in FILES:
        raw = _read(root / "network" / name)
        originals[name] = raw
        doc = _yaml().load(raw.decode("utf-8")) if raw and raw.strip() else defaults[name]
        if not isinstance(doc, dict):
            raise ValueError(f"{name}: documento precisa ser um objeto")
        docs[name] = doc
    if originals["hosts.yaml"] is None:
        raise ValueError("network/hosts.yaml não existe")
    return originals, docs


def transform(documents, backup_directories=()):
    """Transformação pura em cópia round-trip; falha nunca altera a entrada."""
    docs = copy.deepcopy(documents)
    inventory = docs["hosts.yaml"]
    problems = []

    def fail(loc, msg, reference=None):
        problem = {"loc": loc, "msg": msg}
        if reference is not None:
            problem["reference"] = reference
        problems.append(problem)

    for error in identity_errors(inventory):
        fail("hosts.yaml/" + error["loc"], error["msg"])
    if not isinstance(inventory.get("groups", {}), dict):
        fail("hosts.yaml/groups", "grupos precisam ser um objeto")
    for filename, field in (("topology.yaml", "links"), ("maps.yaml", "maps"), ("backups.yaml", "services")):
        values = docs[filename].get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
            fail(f"{filename}/{field}", "campo precisa ser uma lista de objetos")
    sources = docs["backups.yaml"].get("legacy_sources", [])
    if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
        fail("backups.yaml/legacy_sources", "fontes históricas precisam ser uma lista de objetos")
    if problems:
        raise PreflightError(problems)
    version = inventory.get("version", 1)
    hosts = host_index(inventory)
    mapping = {old: number for number, old in enumerate(sorted(hosts), 1)} if version == 1 else {}
    for key, host in hosts.items():
        for field in ("hostname", "mgmt_ip"):
            if not isinstance(host.get(field), str) or not host[field].strip():
                fail(f"hosts.yaml/hosts/{key}/{field}", "campo obrigatório ausente")

    def lookup(reference, loc):
        if version == 1:
            if isinstance(reference, str) and reference in mapping:
                return mapping[reference]
        else:
            try:
                require_host_id(reference)
                if reference in hosts:
                    return reference
            except ValueError:
                pass
        fail(loc, "referência a host não cadastrado ou ID inválido", reference)
        return None

    topo = docs["topology.yaml"]
    expected = 1 if version == 1 else 2
    if topo.get("version", expected) != expected:
        fail("topology.yaml/version", "versão incompatível com o inventário")
    seen, ids = {}, set()
    for index, link in enumerate(topo.get("links") or []):
        if not isinstance(link, dict):
            fail(f"topology.yaml/links/{index}", "enlace precisa ser um objeto")
            continue
        # Mesmo algoritmo do topology_svc, ANTES de mudar as pontas.
        value = link.get("id")
        if not value:
            fingerprint = hashlib.sha256(json.dumps(link, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
            ordinal = seen.get(fingerprint, 0)
            seen[fingerprint] = ordinal + 1
            value = f"link-{fingerprint}-{ordinal}"
            link["id"] = value
        if not isinstance(value, str) or value in ids:
            fail(f"topology.yaml/links/{index}/id", "ID de enlace inválido ou duplicado")
        ids.add(value)
        for end in ("a", "b"):
            endpoint = link.get(end)
            if not isinstance(endpoint, dict):
                fail(f"topology.yaml/links/{index}/{end}", "ponta precisa ser um objeto")
                continue
            endpoint["host"] = lookup(endpoint.get("host"), f"topology.yaml/links/{index}/{end}/host")
    topo["version"] = 2

    maps = docs["maps.yaml"]
    if maps.get("version", expected) != expected:
        fail("maps.yaml/version", "versão incompatível com o inventário")
    map_ids = set()
    for index, network_map in enumerate(maps.get("maps") or []):
        loc = f"maps.yaml/maps/{index}"
        if not isinstance(network_map, dict):
            fail(loc, "mapa precisa ser um objeto")
            continue
        if not isinstance(network_map.get("id"), str) or network_map["id"] in map_ids:
            fail(loc + "/id", "ID de mapa inválido ou duplicado")
        map_ids.add(network_map.get("id"))
        members = network_map.get("members") or []
        if not isinstance(members, list):
            fail(loc + "/members", "membros precisam ser uma lista")
            members = []
        network_map["members"] = [lookup(value, f"{loc}/members/{i}") for i, value in enumerate(members)]
        positions = network_map.get("positions") or ({} if version == 1 else [])
        if version == 1 and isinstance(positions, dict):
            converted = CommentedSeq()
            if hasattr(positions, "ca"):
                converted.ca.comment = copy.deepcopy(positions.ca.comment)
            for old, point in positions.items():
                if not isinstance(point, dict):
                    fail(loc + "/positions/" + str(old), "posição precisa ser um objeto")
                    continue
                point["host_id"] = lookup(old, loc + "/positions/" + str(old))
                converted.append(point)
                _copy_key_comment(positions, old, converted, len(converted) - 1)
            network_map["positions"] = converted
        elif version == 2 and isinstance(positions, list):
            for i, point in enumerate(positions):
                if not isinstance(point, dict):
                    fail(f"{loc}/positions/{i}", "posição precisa ser um objeto")
                    continue
                lookup(point.get("host_id"), f"{loc}/positions/{i}/host_id")
        else:
            fail(loc + "/positions", "formato de posições incompatível")
        objects = network_map.get("objects") or []
        object_ids = {obj.get("id") for obj in objects if isinstance(obj, dict)}
        for li, link in enumerate(network_map.get("visual_links") or []):
            if not isinstance(link, dict):
                fail(f"{loc}/visual_links/{li}", "conexão visual precisa ser um objeto")
                continue
            for end in ("source", "target"):
                path = f"{loc}/visual_links/{li}/{end}"
                ref = link.get(end)
                if version == 1:
                    if isinstance(ref, str) and ref.startswith("host:"):
                        link[end] = {"kind": "host", "host_id": lookup(ref[5:], path)}
                    elif isinstance(ref, str) and ref.startswith("object:"):
                        link[end] = {"kind": "object", "object_id": ref[7:]}
                    else:
                        fail(path, "ponta visual inválida", ref)
                        continue
                endpoint = link[end]
                if not isinstance(endpoint, dict):
                    fail(path, "ponta visual precisa ser um objeto")
                elif endpoint.get("kind") == "host":
                    if version == 2:
                        lookup(endpoint.get("host_id"), path + "/host_id")
                elif endpoint.get("kind") == "object":
                    if endpoint.get("object_id") not in object_ids:
                        fail(path, "objeto visual ausente", endpoint.get("object_id"))
                else:
                    fail(path, "tipo de ponta visual inválido")
    maps["version"] = 2

    backups = docs["backups.yaml"]
    if backups.get("version", 2) not in ((1, 2) if version == 1 else (3,)):
        fail("backups.yaml/version", "versão de backups incompatível")
    # v1 possuía um serviço implícito, normalizado sem perder seu agendamento.
    if backups.get("version") == 1:
        legacy = backups
        service = copy.deepcopy(backups)
        service.pop("version", None)
        if hasattr(service, "ca"):
            service.ca.comment = None
        service.setdefault("id", "default")
        service.setdefault("name", "Backup")
        backups = docs["backups.yaml"] = CommentedMap(version=2, services=[service])
        if hasattr(legacy, "ca"):
            backups.ca.comment = copy.deepcopy(legacy.ca.comment)
            if "version" in legacy.ca.items:
                backups.ca.items["version"] = copy.deepcopy(legacy.ca.items["version"])
    for si, service in enumerate(backups.get("services") or []):
        schedule = service.get("schedule")
        if isinstance(schedule, dict) and isinstance(schedule.get("time"), str):
            schedule["time"] = DoubleQuotedScalarString(schedule["time"])
        targets = service.setdefault("targets", {})
        if not isinstance(targets, dict):
            fail(f"backups.yaml/services/{si}/targets", "alvos precisam ser um objeto")
            continue
        refs = targets.get("hosts") or []
        if not isinstance(refs, list) or not isinstance(targets.get("groups", []), list):
            fail(f"backups.yaml/services/{si}/targets", "hosts e grupos precisam ser listas")
            continue
        targets["hosts"] = [lookup(old, f"backups.yaml/services/{si}/targets/hosts/{i}") for i, old in enumerate(refs)]
        groups = inventory.get("groups") or {}
        for gi, group in enumerate(targets.get("groups") or []):
            if group not in groups:
                fail(f"backups.yaml/services/{si}/targets/groups/{gi}", "grupo ausente", group)
    backups["version"] = 3
    if version == 1:
        sources = backups.setdefault("legacy_sources", [])
        existing = {item.get("directory") for item in sources}
        for directory in sorted(backup_directories):
            if directory in mapping and directory not in existing:
                sources.append({"host_id": mapping[directory], "directory": directory})
        old_hosts = inventory["hosts"]
        records = CommentedSeq()
        if hasattr(old_hosts, "ca"):
            records.ca.comment = copy.deepcopy(old_hosts.ca.comment)
        for old, new in mapping.items():
            node = old_hosts[old]
            if isinstance(node, CommentedMap):
                node.insert(0, "id", new)
            else:
                node = CommentedMap({"id": new, **node})
            records.append(node)
            # Comentários ligados à antiga chave também acompanham o registro.
            _copy_key_comment(old_hosts, old, records, len(records) - 1)
        inventory["hosts"] = records
        inventory["version"] = 2
        inventory["next_host_id"] = len(mapping) + 1
        inventory.setdefault("groups", {})
        inventory["legacy_aliases"] = [{"alias": old, "host_id": new} for old, new in mapping.items()]
    for error in identity_errors(inventory):
        fail("hosts.yaml/" + error["loc"], error["msg"])
    for i, item in enumerate(backups.get("legacy_sources") or []):
        directory = item.get("directory")
        if not isinstance(directory, str) or not re.fullmatch(r"[a-zA-Z0-9._-]+", directory) or directory in (".", ".."):
            fail(f"backups.yaml/legacy_sources/{i}/directory", "pasta histórica inválida")
        try:
            require_host_id(item.get("host_id"))
            # Fontes de hosts excluídos são mantidas para não reassociar o histórico.
            if item["host_id"] >= inventory["next_host_id"]:
                raise ValueError("ID histórico ainda não alocado")
        except ValueError as exc:
            fail(f"backups.yaml/legacy_sources/{i}/host_id", str(exc))
    directories = [item.get("directory") for item in backups.get("legacy_sources") or []]
    if len(directories) != len(set(directories)):
        fail("backups.yaml/legacy_sources/directory", "pastas históricas duplicadas ou com proprietários conflitantes")
    if problems:
        raise PreflightError(problems)
    _validate_prepared(docs)
    return docs, [{"alias": old, "host_id": new} for old, new in mapping.items()]


def _validate_prepared(docs):
    """Mesmo contrato da UI, incluindo referências e formatos de apresentação."""
    import jsonschema
    from pydantic import ValidationError
    ui_dir = str(Path(__file__).resolve().parents[1] / "ui")
    if ui_dir not in sys.path:
        sys.path.insert(0, ui_dir)
    import deps
    from models import BackupsConfig, Link, NetworkMap
    from services import maps_svc
    from lib.inventory import resolve_host

    errors = []
    inventory = docs["hosts.yaml"]
    schema_file = Path(__file__).resolve().parents[3] / "core" / "schemas" / "inventory.schema.json"
    validator = jsonschema.Draft202012Validator(json.loads(schema_file.read_text(encoding="utf-8")))
    for error in validator.iter_errors(inventory):
        errors.append({"loc": "hosts.yaml/" + "/".join(map(str, error.absolute_path)), "msg": error.message})
    if errors:
        raise PreflightError(errors)
    hosts = host_index(inventory)
    effective = {}
    for host_id, host in hosts.items():
        if host.get("group") and host["group"] not in (inventory.get("groups") or {}):
            errors.append({"loc": f"hosts.yaml/hosts/{host_id}/group", "msg": "grupo ausente"})
        merged, _ = resolve_host(host_id, inventory, {}, decrypt=False)
        effective[host_id] = merged
        for field in ("vendor", "credential"):
            if not merged.get(field):
                errors.append({"loc": f"hosts.yaml/hosts/{host_id}/{field}", "msg": "campo obrigatório ausente após herança"})
        if not (merged.get("access") or {}).get("method"):
            errors.append({"loc": f"hosts.yaml/hosts/{host_id}/access/method", "msg": "método de acesso ausente"})

    def model_error(filename, prefix, exc):
        for error in exc.errors():
            errors.append({"loc": filename + "/" + prefix + "/" + "/".join(map(str, error["loc"])), "msg": error["msg"]})

    for index, link in enumerate(docs["topology.yaml"].get("links") or []):
        try:
            Link.model_validate({key: value for key, value in link.items() if key != "id"})
        except ValidationError as exc:
            model_error("topology.yaml", f"links/{index}", exc)
    try:
        BackupsConfig.model_validate(docs["backups.yaml"])
    except ValidationError as exc:
        model_error("backups.yaml", "", exc)
    services = docs["backups.yaml"].get("services") or []
    names = [service.get("id") for service in services]
    if len(names) != len(set(names)):
        errors.append({"loc": "backups.yaml/services/id", "msg": "IDs de serviço duplicados"})
    maps = docs["maps.yaml"].get("maps") or []
    all_maps = list(maps)
    present = {m["id"] for m in maps}
    all_maps.extend(m for m in maps_svc._default_maps(effective) if m["id"] not in present)
    links = {link["id"] for link in docs["topology.yaml"].get("links") or []}
    for index, network_map in enumerate(maps):
        try:
            validated = NetworkMap.model_validate(network_map).model_dump(exclude_none=True)
            if len(validated["members"]) != len(set(validated["members"])):
                errors.append({"loc": f"maps.yaml/maps/{index}/members", "msg": "host duplicado nos membros"})
            maps_svc._validate(validated, all_maps, effective, links)
        except ValidationError as exc:
            model_error("maps.yaml", f"maps/{index}", exc)
        except deps.ValidationFailed as exc:
            errors.extend({"loc": f"maps.yaml/maps/{index}/" + error["loc"], "msg": error["msg"]} for error in exc.errors)
    if errors:
        raise PreflightError(errors)


def plan(root: Path):
    root = Path(root).resolve()
    originals, documents = _documents(root)
    if documents["hosts.yaml"].get("version", 1) == 1 and _canonical_backups_exist(root):
        raise PreflightError([{"loc": "backups/by-id", "msg": "há histórico com IDs inteiros; reconciliar a identidade anterior antes de migrar novamente"}])
    backup_root = root / "backups"
    directories = [path.name for path in backup_root.iterdir() if path.is_dir() and not path.is_symlink()] if backup_root.exists() else []
    # Ausência de arquivo em instalação já migrada equivale ao documento vazio novo.
    if documents["hosts.yaml"].get("version") == 2:
        for name, version in (("topology.yaml", 2), ("maps.yaml", 2), ("backups.yaml", 3)):
            if originals[name] is None:
                documents[name]["version"] = version
    converted, mapping = transform(documents, directories)
    prepared = {name: _dump(converted[name]).encode("utf-8") for name in FILES}
    # Rodar novamente em v2 é validação, não uma reformatação dos arquivos.
    already = documents["hosts.yaml"].get("version") == 2
    if already:
        prepared = dict(originals)
    return {"root": root, "before": originals, "after": prepared, "mapping": mapping, "already_migrated": already}


def _canonical_backups_exist(root):
    path = root / "backups" / "by-id"
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("symlink não permitido no armazenamento de backups")
    if not path.exists():
        return False
    for directory in path.iterdir():
        if not directory.name.isascii() or not directory.name.isdigit():
            continue
        if directory.is_symlink():
            raise ValueError("symlink não permitido no histórico de identidade inteira")
        if directory.is_dir() and any(item.is_file() for item in directory.rglob("*")):
            return True
    return False


def _atomic_write(path: Path, data: bytes, mode=0o600):
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"symlink não permitido na escrita de migração: {component.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, path)
        _sync_dir(path.parent)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _journal(root, state):
    _atomic_write(root / "network" / JOURNAL_NAME, json.dumps(state, indent=2, ensure_ascii=False).encode("utf-8"))


def _load_journal(root):
    path = root / "network" / JOURNAL_NAME
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise ValueError("journal não pode passar por symlink")
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != 1 or set(state.get("files", {})) != set(FILES):
        raise ValueError("journal inválido")
    if state.get("status") not in ("prepared", "applying", "complete", "rolling_back", "rolled_back"):
        raise ValueError("estado de journal inválido")
    for entry in state["files"].values():
        if not isinstance(entry, dict) or not isinstance(entry.get("mode"), int) or not 0 <= entry["mode"] <= 0o777:
            raise ValueError("metadados de journal inválidos")
        for kind in ("before", "after"):
            value = entry.get(kind)
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
                raise ValueError("hash de journal inválido")
    run_dir = (root / state["run_dir"]).resolve()
    if not run_dir.is_relative_to((root / "runs").resolve()):
        raise ValueError("baseline fora de runs/")
    return state


def _rollback(root, state):
    run_dir = root / state["run_dir"]
    originals = {}
    for name, entry in state["files"].items():
        baseline = _read(run_dir / "baseline" / name) if entry["before"] is not None else None
        if _digest(baseline) != entry["before"]:
            raise ValueError(f"baseline corrompido: {name}")
        current = _digest(_read(root / "network" / name))
        if current not in (entry["before"], entry["after"]):
            raise ValueError(f"{name} mudou após a migração; rollback recusado para preservar edições")
        originals[name] = baseline
    state["status"] = "rolling_back"
    _journal(root, state)
    for name, baseline in originals.items():
        path = root / "network" / name
        if baseline is None:
            path.unlink(missing_ok=True)
            _sync_dir(path.parent)
        else:
            _atomic_write(path, baseline, state["files"][name]["mode"])
    state["status"] = "rolled_back"
    _journal(root, state)
    return {"status": "rolled_back", "run_dir": state["run_dir"]}


def apply(root: Path, *, expected_hashes: dict | None = None):
    """Commit sob flock. Falha comum restaura baseline; queda usa recover()."""
    root = Path(root).resolve()
    with inventory_lock(root / "network"):
        old = _load_journal(root)
        if old and old["status"] not in ("complete", "rolled_back"):
            raise ValueError("migração incompleta; execute recover antes de apply")
        migration = plan(root)
        if expected_hashes is not None:
            actual = {name: _digest(value) for name, value in migration["before"].items()}
            if actual != expected_hashes:
                raise ValueError("arquivos mudaram desde o dry-run; gere outro plano")
        if migration["already_migrated"]:
            return {"status": "already_migrated", "mapping": []}
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        relative = f"runs/{stamp}-host-id-migration-{uuid.uuid4().hex[:8]}"
        run_dir = root / relative
        state = {"version": 1, "status": "prepared", "run_dir": relative,
                 "mapping": migration["mapping"], "files": {}}
        for name in FILES:
            before, after = migration["before"][name], migration["after"][name]
            target = root / "network" / name
            mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
            state["files"][name] = {"before": _digest(before), "after": _digest(after), "mode": mode}
            if before is not None:
                _atomic_write(run_dir / "baseline" / name, before)
            _atomic_write(run_dir / "prepared" / name, after)
        _atomic_write(run_dir / "manifest.json", json.dumps(state, indent=2).encode("utf-8"))
        _journal(root, state)
        state["status"] = "applying"
        _journal(root, state)
        try:
            for name in FILES:
                if _digest(_read(root / "network" / name)) != state["files"][name]["before"]:
                    raise ValueError(f"{name} mudou durante a preparação")
            for name in FILES:
                _atomic_write(root / "network" / name, migration["after"][name], state["files"][name]["mode"])
            # Pré-validação também cobre o conjunto efetivamente gravado.
            validation = plan(root)
            if not validation["already_migrated"]:
                raise ValueError("inventário não migrou para v2")
            state["status"] = "complete"
            _journal(root, state)
        except Exception:
            _rollback(root, state)
            raise
        return {"status": "complete", "mapping": migration["mapping"], "run_dir": relative}


def recover(root: Path, *, rollback_complete=False):
    root = Path(root).resolve()
    with inventory_lock(root / "network"):
        state = _load_journal(root)
        if state is None:
            return {"status": "no_migration"}
        if state["status"] == "rolled_back":
            return {"status": "rolled_back", "run_dir": state["run_dir"]}
        if state["status"] == "complete" and not rollback_complete:
            return {"status": "complete", "run_dir": state["run_dir"]}
        if state["status"] == "complete" and _canonical_backups_exist(root):
            raise ValueError("há backups criados após a migração; rollback exige reconciliação para preservar identidades")
        return _rollback(root, state)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migra hosts para IDs inteiros sem acessar dispositivos.")
    parser.add_argument("command", choices=("dry-run", "apply", "recover", "rollback"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--expected-plan", type=Path, help="JSON de dry-run; apply exige hashes idênticos")
    args = parser.parse_args(argv)
    try:
        if args.command == "dry-run":
            with inventory_lock(args.root / "network"):
                ensure_migration_complete(args.root / "network")
                migration = plan(args.root)
            result = {"status": "already_migrated" if migration["already_migrated"] else "ready",
                      "mapping": migration["mapping"],
                      "hashes": {name: _digest(value) for name, value in migration["before"].items()}}
        elif args.command == "apply":
            hashes = json.loads(args.expected_plan.read_text(encoding="utf-8"))["hashes"] if args.expected_plan else None
            result = apply(args.root, expected_hashes=hashes)
        else:
            result = recover(args.root, rollback_complete=args.command == "rollback")
    except PreflightError as exc:
        print(json.dumps({"status": "blocked", "problems": exc.problems}, ensure_ascii=False, indent=2))
        return 2
    except (ValueError, OSError, KeyError, TypeError, MigrationIncomplete) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
