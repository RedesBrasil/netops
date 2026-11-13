#!/usr/bin/env python3
"""CRUD de hosts e grupos sobre network/hosts.yaml (round-trip ruamel).

Validação: além do gate de schema (core/schemas/inventory.schema.json) + checagens
pós-herança (espelham lib.inventory.validate), usamos validação-DELTA: só barramos
erros que a edição INTRODUZ — não os pré-existentes em outros hosts (o seed já vem com
model/notes vazios = null, que o schema rejeita; não é justo travar o operador por isso).

Escrita LIMPA: campos opcionais vazios (model/site/notes) não viram `null` no arquivo —
são omitidos, deixando o nó válido.
"""
from __future__ import annotations

import json
import re

import deps
from lib.inventory import lookup_ci, normalize_node_fields, upper_value
from lib.host_identity import MAX_HOST_ID, host_index, identity_errors, require_host_id
from services import yaml_io

# Grupos continuam identificados por nome; hosts usam inteiro imutável.
ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

# Ordem de chaves p/ hosts/grupos novos (legibilidade do YAML).
HOST_KEY_ORDER = ["id", "hostname", "mgmt_ip", "extra_ips", "group", "vendor", "role", "icon", "model", "version", "site", "access", "credential", "notes"]
GROUP_KEY_ORDER = ["vendor", "role", "access", "credential", "model", "version", "site", "notes"]
OPTIONAL_STR = {"model", "version", "site", "notes", "icon"}


def _gkey(groups: dict, name: str) -> str:
    """Chave real do grupo (aceita qualquer caixa); KeyError se não existir."""
    folded = str(name).casefold()
    for k in groups:
        if str(k).casefold() == folded:
            return k
    raise KeyError(f"grupo '{name}' não existe")


def _same(a, b) -> bool:
    return str(a or "").casefold() == str(b or "").casefold()


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #
@yaml_io.serialized
def load_hosts() -> tuple[dict, str]:
    import yaml  # noqa: PLC0415
    text, rev, _ = yaml_io.read_text_meta(deps.HOSTS_FILE)
    data = (yaml.safe_load(text) if text.strip() else {}) or {}
    return data, rev


@yaml_io.serialized
def list_hosts_detailed() -> dict:
    from lib.inventory import resolve_host  # noqa: PLC0415
    data, rev = load_hosts()
    hosts = host_index(data)
    out = []
    for name in sorted(hosts.keys()):
        explicit = dict(hosts[name])
        try:
            effective, _ = resolve_host(name, data, {}, decrypt=False, lowercase_enums=False)
        except KeyError:
            effective = explicit
        effective.pop("name", None)
        out.append({"id": name, "explicit": explicit, "effective": effective})
    return {"hosts": out, "rev": rev, "groups": sorted((data.get("groups") or {}).keys())}


@yaml_io.serialized
def get_host(name: int | str) -> dict:
    from lib.inventory import resolve_host  # noqa: PLC0415
    data, rev = load_hosts()
    hosts = host_index(data)
    if name not in hosts:
        raise KeyError(f"host '{name}' não existe")
    effective, _ = resolve_host(name, data, {}, decrypt=False, lowercase_enums=False)
    effective.pop("name", None)
    return {"id": name, "explicit": dict(hosts[name]), "effective": effective, "rev": rev}


def list_groups() -> dict:
    data, rev = load_hosts()
    groups = data.get("groups") or {}
    hosts = host_index(data)
    usage = {}
    for h in hosts.values():
        g = h.get("group")
        if g:
            usage[g] = usage.get(g, 0) + 1
    out = [{"name": n, "fields": dict(groups[n]), "used_by": usage.get(n, 0)} for n in sorted(groups.keys())]
    return {"groups": out, "rev": rev}


# --------------------------------------------------------------------------- #
# Validação (schema + pós-herança), formato {loc, msg}
# --------------------------------------------------------------------------- #
def validate_data(hosts_data: dict) -> list[dict]:
    import jsonschema  # noqa: PLC0415
    from lib.inventory import list_hosts, resolve_host, schema_view  # noqa: PLC0415

    errors: list[dict] = []
    schema = json.loads(deps.SCHEMA_FILE.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(schema_view(hosts_data)), key=str):
        loc = "/".join(str(p) for p in err.absolute_path) or "(raiz)"
        errors.append({"loc": loc, "msg": err.message})

    identity = identity_errors(hosts_data)
    errors.extend(identity)
    if identity:
        return errors

    for name in list_hosts(hosts_data):
        try:
            host, _ = resolve_host(name, hosts_data, {}, decrypt=False, lowercase_enums=False)
        except KeyError as exc:
            errors.append({"loc": f"hosts/{name}", "msg": str(exc)})
            continue
        for field in ("vendor", "credential"):
            if not host.get(field):
                errors.append({"loc": f"hosts/{name}/{field}",
                               "msg": f"campo '{field}' ausente (nem no host nem no grupo)"})
        if not (host.get("access") or {}).get("method"):
            errors.append({"loc": f"hosts/{name}/access/method", "msg": "'access.method' ausente"})
    return errors


def _gate(before: dict, after: dict) -> None:
    """Levanta ValidationFailed se `after` tem erros que `before` não tinha (delta)."""
    identity = identity_errors(after)
    if identity:
        raise deps.ValidationFailed(identity)
    before_errs = {(e["loc"], e["msg"]) for e in validate_data(before)}
    new = [e for e in validate_data(after) if (e["loc"], e["msg"]) not in before_errs]
    if new:
        raise deps.ValidationFailed(new)


# --------------------------------------------------------------------------- #
# Helpers de mutação no doc ruamel
# --------------------------------------------------------------------------- #
def _apply_fields(node: dict, fields: dict, *, partial: bool) -> None:
    """Aplica `fields` em `node` (CommentedMap). None/'' em opcionais => remove a chave.

    partial=True (PATCH): só mexe nas chaves presentes em `fields`.
    partial=False (PUT/POST): trata `fields` como o conjunto completo de overrides.
    """
    fields = normalize_node_fields(fields)
    for key, val in fields.items():
        if key == "access":
            _apply_access(node, val)
            continue
        if val is None or (key in OPTIONAL_STR and val == ""):
            node.pop(key, None)
        elif key == "extra_ips" and key not in node and "mgmt_ip" in node and hasattr(node, "insert"):
            # chave nova entra logo após o mgmt_ip (e não depois do espaço em branco no fim do host)
            node.insert(list(node.keys()).index("mgmt_ip") + 1, key, val)
        else:
            node[key] = val


def _apply_access(node: dict, access: dict | None) -> None:
    if not access:
        node.pop("access", None)
        return
    method = access.get("method")
    port = access.get("port")
    acc = {}
    if method:
        acc["method"] = method
    if port:
        acc["port"] = port
    if acc:
        node["access"] = acc
    else:
        node.pop("access", None)


def _ordered(fields: dict, order: list[str]) -> dict:
    out = {}
    for k in order:
        if k in fields:
            out[k] = fields[k]
    for k in fields:  # quaisquer extras (improvável; modelos barram)
        if k not in out:
            out[k] = fields[k]
    return out


def _clean_new(fields: dict, order: list[str]) -> dict:
    fields = normalize_node_fields(fields)
    node = {}
    for k, v in fields.items():
        if k == "access":
            acc = {}
            if (v or {}).get("method"):
                acc["method"] = v["method"]
            if (v or {}).get("port"):
                acc["port"] = v["port"]
            if acc:
                node["access"] = acc
        elif v is None or (k in OPTIONAL_STR and v == ""):
            continue
        else:
            node[k] = v
    return _ordered(node, order)


# --------------------------------------------------------------------------- #
# CRUD de hosts
# --------------------------------------------------------------------------- #
@yaml_io.serialized
def create_host(fields: dict, rev: str | None, *, placement: dict | None = None) -> dict:
    if "id" in fields:
        raise deps.ValidationFailed([{"loc": "id", "msg": "ID é gerado automaticamente"}])
    data, doc, y = _load_doc()
    hosts = data.setdefault("hosts", [])
    host_id = require_host_id(data["next_host_id"])
    if host_id == MAX_HOST_ID:
        raise deps.ValidationFailed([{"loc": "id", "msg": "espaço de IDs esgotado"}])
    before = _plain(data)
    hosts.append(_clean_new({"id": host_id, **fields}, HOST_KEY_ORDER))
    data["next_host_id"] = host_id + 1
    _gate(before, _plain(data))
    if placement:
        from services import maps_svc
        if not rev:
            maps_svc._fail("rev", "revisão do inventário obrigatória ao criar pelo mapa")
        writes = [(deps.HOSTS_FILE, yaml_io.dump_rt(y, data), 0o644)]
        checks = [(deps.HOSTS_FILE, rev)]
        maps_svc.place_host(host_id, placement, _plain(data), writes, checks)
        new_rev = yaml_io.write_many(writes, checks=checks)[deps.HOSTS_FILE]
    else:
        new_rev = yaml_io.write_rt(deps.HOSTS_FILE, y, data, expected=rev, backup=True)
    return get_host(host_id) | {"rev": new_rev}


@yaml_io.serialized
def update_host(host_id: int, fields: dict, rev: str | None, *, partial: bool) -> dict:
    if "id" in fields:
        raise deps.ValidationFailed([{"loc": "id", "msg": "ID é permanente e não pode ser editado"}])
    data, doc, y = _load_doc()
    require_host_id(host_id)
    hosts = host_index(data)
    if host_id not in hosts:
        raise KeyError(f"host '{host_id}' não existe")
    before = _plain(data)
    _apply_fields(hosts[host_id], fields, partial=partial)
    _gate(before, _plain(data))
    new_rev = yaml_io.write_rt(deps.HOSTS_FILE, y, data, expected=rev, backup=True)
    return get_host(host_id) | {"rev": new_rev}


@yaml_io.serialized
def delete_host(host_id: int, rev: str | None) -> dict:
    data, doc, y = _load_doc()
    require_host_id(host_id)
    hosts = host_index(data)
    if host_id not in hosts:
        raise KeyError(f"host '{host_id}' não existe")
    data["hosts"].remove(hosts[host_id])
    from services import maps_svc, topology_svc, backups_svc
    writes = [(deps.HOSTS_FILE, yaml_io.dump_rt(y, data), 0o644)]
    checks = [(deps.HOSTS_FILE, rev)]
    topo, tr, ty = yaml_io.load_rt(deps.TOPOLOGY_FILE)
    removed = set()
    if topo is not None:
        topology_svc.ensure_link_ids(topo)
        links = topo.get("links") or []
        removed = {lk["id"] for lk in links if any((lk.get(e) or {}).get("host") == host_id for e in ("a", "b"))}
        if removed:
            topo["links"] = [lk for lk in links if lk["id"] not in removed]
            writes.append((deps.TOPOLOGY_FILE, yaml_io.dump_rt(ty, topo), 0o644))
            checks.append((deps.TOPOLOGY_FILE, tr))
    maps_svc.cascade_host(host_id, None, removed, writes, checks)
    backups_svc.cascade_host_delete(host_id, writes, checks)
    new_rev = yaml_io.write_many(writes, checks=checks)[deps.HOSTS_FILE]
    return {"deleted": host_id, "rev": new_rev}


# --------------------------------------------------------------------------- #
# Renomear host (cascade: topology.yaml links)
# --------------------------------------------------------------------------- #
def _topology_host_refs(host_id: int | str) -> list[dict]:
    """Enlaces em topology.yaml que apontam para `host_id` (preview do cascade)."""
    import yaml  # noqa: PLC0415
    if not deps.TOPOLOGY_FILE.exists():
        return []
    data = yaml.safe_load(deps.TOPOLOGY_FILE.read_text(encoding="utf-8")) or {}
    out = []
    for i, lk in enumerate(data.get("links") or []):
        for end in ("a", "b"):
            e = (lk or {}).get(end) or {}
            if e.get("host") == host_id:
                other = ((lk or {}).get("b" if end == "a" else "a") or {}).get("host", "?")
                out.append({"kind": "topology-link", "index": i, "field": f"{end}.host",
                            "label": f"enlace {host_id}:{e.get('port', '?')} ↔ {other}"})
    return out


@yaml_io.serialized
def host_references(host_id: int | str) -> dict:
    data, _ = load_hosts()
    if host_id not in host_index(data):
        raise KeyError(f"host '{host_id}' não existe")
    from services import maps_svc
    refs = _topology_host_refs(host_id) + maps_svc.host_references(host_id)
    return {"id": host_id, "references": refs, "count": len(refs)}


@yaml_io.serialized
def rename_host(old: str, new: str, rev: str | None) -> dict:
    """Compatibilidade de rota: nenhuma chamada pode alterar identidade permanente."""
    raise deps.ValidationFailed([{"loc": "id", "msg": "ID é permanente; edite somente hostname"}])


# --------------------------------------------------------------------------- #
# CRUD de grupos
# --------------------------------------------------------------------------- #
@yaml_io.serialized
def create_group(name: str, fields: dict, rev: str | None) -> dict:
    data, doc, y = _load_doc()
    groups = data.setdefault("groups", {})
    name = upper_value(name)
    if any(_same(k, name) for k in groups):
        raise deps.ValidationFailed([{"loc": "name", "msg": f"grupo '{name}' já existe"}])
    before = _plain(data)
    groups[name] = _clean_new(fields, GROUP_KEY_ORDER)
    _gate(before, _plain(data))  # grupos não têm requisito próprio; valida que não quebrou hosts
    new_rev = yaml_io.write_rt(deps.HOSTS_FILE, y, data, expected=rev, backup=True)
    return {"name": name, "fields": fields, "rev": new_rev}


@yaml_io.serialized
def update_group(name: str, fields: dict, rev: str | None, *, partial: bool) -> dict:
    data, doc, y = _load_doc()
    groups = data.get("groups") or {}
    name = _gkey(groups, name)
    before = _plain(data)
    _apply_fields(groups[name], fields, partial=partial)
    _gate(before, _plain(data))
    new_rev = yaml_io.write_rt(deps.HOSTS_FILE, y, data, expected=rev, backup=True)
    return {"name": name, "fields": dict(groups[name]), "rev": new_rev}


@yaml_io.serialized
def delete_group(name: str, rev: str | None, *, force: bool) -> dict:
    data, doc, y = _load_doc()
    groups = data.get("groups") or {}
    name = _gkey(groups, name)
    used = [h for h, v in host_index(data).items() if _same(v.get("group"), name)]
    if used and not force:
        raise deps.ConflictError(yaml_io.file_rev(deps.HOSTS_FILE),
                                 detail=f"grupo em uso por {len(used)} host(s): {', '.join(map(str, used))}")
    del groups[name]
    new_rev = yaml_io.write_rt(deps.HOSTS_FILE, y, data, expected=rev, backup=True)
    return {"deleted": name, "rev": new_rev}


# --------------------------------------------------------------------------- #
# Renomear grupo (cascade: campo 'group' dos hosts no mesmo arquivo)
# --------------------------------------------------------------------------- #
def group_references(name: str) -> dict:
    data, _ = load_hosts()
    name = _gkey(data.get("groups") or {}, name)
    refs = [{"kind": "host", "id": h, "field": "group", "label": f"host {h}"}
            for h, v in host_index(data).items() if _same((v or {}).get("group"), name)]
    return {"name": name, "references": refs, "count": len(refs)}


@yaml_io.serialized
def rename_group(old: str, new: str, rev: str | None) -> dict:
    if not ID_RE.match(new):
        raise deps.ValidationFailed([{"loc": "to", "msg": "use a-z, 0-9, ponto, hífen ou underline"}])
    new = upper_value(new)
    data, _, y = _load_doc()
    groups = data.get("groups") or {}
    old = _gkey(groups, old)
    if new == old:
        raise deps.ValidationFailed([{"loc": "to", "msg": "o novo nome é igual ao atual"}])
    if new in groups:
        raise deps.ValidationFailed([{"loc": "to", "msg": f"grupo '{new}' já existe"}])

    yaml_io.rename_key(groups, old, new)
    updated = []
    for hid, h in host_index(data).items():
        if h and _same(h.get("group"), old):
            h["group"] = new
            updated.append({"kind": "host", "id": hid, "field": "group"})
    new_rev = yaml_io.write_rt(deps.HOSTS_FILE, y, data, expected=rev, backup=True)
    return {"renamed": {"from": old, "to": new}, "updated": updated, "rev": new_rev}


# --------------------------------------------------------------------------- #
# Internos
# --------------------------------------------------------------------------- #
def _load_doc():
    data, rev, y = yaml_io.load_rt(deps.HOSTS_FILE)
    if data is None:
        data = {"version": 2, "next_host_id": 1, "groups": {}, "hosts": [], "legacy_aliases": []}
    if data.get("version") != 2:
        raise deps.ValidationFailed([{"loc": "version", "msg": "inventário legado: execute a migração de IDs antes de editar"}])
    identity = identity_errors(data)
    if identity:
        raise deps.ValidationFailed(identity)
    return data, data, y


def _plain(data) -> dict:
    """Converte CommentedMap aninhado em dict puro (p/ jsonschema/resolve_host estáveis)."""
    import json as _json
    return _json.loads(_json.dumps(data, default=str))
