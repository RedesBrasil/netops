#!/usr/bin/env python3
"""Mapas são apresentação do inventário, sem cadastro paralelo de dispositivos."""
from __future__ import annotations

import hashlib
from copy import deepcopy

from pydantic import ValidationError

import deps
from lib.host_identity import host_index, resolve_reference
from models import NetworkMap
from services import inventory_svc, topology_svc, yaml_io


def _fail(loc, message):
    raise deps.ValidationFailed([{"loc": loc, "msg": message}])


def _hosts(data=None):
    from lib.inventory import resolve_host
    if data is None:
        data, _ = inventory_svc.load_hosts()
    result = {}
    for name, explicit in host_index(data).items():
        try:
            host, _ = resolve_host(name, data, {}, decrypt=False)
        except KeyError:
            host = explicit
        result[name] = {"id": name, **{k: host.get(k, "") for k in ("hostname", "mgmt_ip", "vendor", "role", "site", "icon")}}
    return result


def _require_migrated():
    data, _ = inventory_svc.load_hosts()
    if data.get("version") != 2:
        _fail("hosts/version", "Migre o inventário para IDs inteiros antes de editar os mapas e enlaces.")


def _ref_key(ref):
    """Identidade tipada; IDs textuais de nós existem somente no navegador."""
    if ref.get("kind") == "host":
        return ("host", ref.get("host_id"))
    return ("object", ref.get("object_id"))


def _normalise_legacy_maps(data):
    """Visão de leitura v1, sem escrita implícita ou alteração de IDs dos enlaces."""
    hosts_data, _ = inventory_svc.load_hosts()

    def identity(value):
        try:
            return resolve_reference(value, hosts_data)
        except (KeyError, ValueError, TypeError):
            # Referências externas são limpas pelo snapshot; não inventa associação.
            return value

    def reference(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.startswith("host:"):
            return {"kind": "host", "host_id": identity(value[5:])}
        if isinstance(value, str) and value.startswith("object:"):
            return {"kind": "object", "object_id": value[7:]}
        _fail("visual_links", "ponta da conexão visual inválida")

    for m in data["maps"]:
        m["members"] = [identity(value) for value in m.get("members") or []]
        if isinstance(m.get("positions", {}), dict):
            m["positions"] = [{"host_id": identity(ident), **position}
                              for ident, position in (m.get("positions") or {}).items()]
        for link in m.get("visual_links") or []:
            for end in ("source", "target"):
                link[end] = reference(link[end])
    if hosts_data.get("version") == 2:
        data["version"] = 2


def _single_site(hosts):
    sites = {host.get("site") for host in hosts.values()}
    return next(iter(sites)) if len(sites) == 1 and all(sites) else None


def _default_maps(hosts):
    maps = [NetworkMap(id="all", name="Rede geral", kind="all").model_dump(exclude_none=True)]
    # Com todos os hosts no mesmo local, o geral já representa essa localidade.
    if not _single_site(hosts):
        for site in sorted({h["site"] for h in hosts.values() if h.get("site")}):
            ident = "site-" + hashlib.sha256(site.encode()).hexdigest()[:20]
            maps.append(NetworkMap(id=ident, name=site, kind="site", site=site).model_dump(exclude_none=True))
    return maps


def _unique_visual_id(ident, taken, source):
    if ident not in taken:
        return ident
    suffix = hashlib.sha256(f"{source}:{ident}".encode()).hexdigest()[:12]
    candidate = f"{ident[:80]}-{suffix}"
    while candidate in taken:
        candidate = hashlib.sha256(candidate.encode()).hexdigest()
    return candidate


def _consolidate_maps(data, hosts):
    site = _single_site(hosts)
    if not site:
        return {}
    maps = data["maps"]
    general = next(m for m in maps if m["id"] == "all")
    duplicates = [m for m in maps if m.get("kind") == "site" and m.get("site") == site]
    aliases = {m["id"]: "all" for m in duplicates}
    # Aceita também seleção antiga de um mapa automático ainda não salvo.
    legacy_id = "site-" + hashlib.sha256(site.encode()).hexdigest()[:20]
    if not any(m["id"] == legacy_id and m not in duplicates for m in maps):
        aliases[legacy_id] = "all"
    for duplicate in duplicates:
        positions = general.setdefault("positions", [])
        placed = {p["host_id"] for p in positions}
        positions.extend(deepcopy(p) for p in duplicate.get("positions") or [] if p["host_id"] not in placed)
        for ident, value in (duplicate.get("edges") or {}).items():
            general.setdefault("edges", {}).setdefault(ident, deepcopy(value))
        objects = general.setdefault("objects", [])
        by_id = {obj["id"]: obj for obj in objects}
        remapped = {}
        for obj in duplicate.get("objects") or []:
            ident = obj["id"]
            if by_id.get(ident) == obj:
                remapped[ident] = ident
                continue
            new_id = _unique_visual_id(ident, by_id, duplicate["id"])
            merged = deepcopy(obj)
            merged["id"] = new_id
            objects.append(merged)
            by_id[new_id] = merged
            remapped[ident] = new_id
        visual = general.setdefault("visual_links", [])
        taken = {link["id"] for link in visual}
        for link in duplicate.get("visual_links") or []:
            merged = deepcopy(link)
            for end in ("source", "target"):
                if merged[end]["kind"] == "object":
                    ident = merged[end]["object_id"]
                    merged[end]["object_id"] = remapped.get(ident, ident)
            if merged in visual:
                continue
            merged["id"] = _unique_visual_id(link["id"], taken, duplicate["id"])
            taken.add(merged["id"])
            visual.append(merged)
    maps[:] = [m for m in maps if m["id"] not in aliases]
    for m in maps:
        removed = set()
        for obj in m.get("objects") or []:
            if obj.get("type") == "reference":
                obj["map_id"] = aliases.get(obj.get("map_id"), obj.get("map_id"))
                if m["id"] == "all" and obj["map_id"] == "all":
                    removed.add(("object", obj["id"]))
        if removed:
            # Um atalho entre as duas visões idênticas não precisa virar auto-referência.
            m["objects"] = [obj for obj in m["objects"] if ("object", obj["id"]) not in removed]
            m["visual_links"] = [link for link in m.get("visual_links") or []
                                 if _ref_key(link["source"]) not in removed and _ref_key(link["target"]) not in removed]
    return aliases

def _document(hosts=None):
    hosts = _hosts() if hosts is None else hosts
    data, rev, y = yaml_io.load_rt(deps.MAPS_FILE)
    if data is None:
        data = {"version": 2, "maps": []}
    if data.get("version") not in (1, 2) or not isinstance(data.get("maps"), list):
        _fail("maps", "formato de maps.yaml inválido")
    if any(not isinstance(m, dict) or not isinstance(m.get("id"), str) for m in data["maps"]):
        _fail("maps", "todo mapa precisa de um ID textual")
    stored = {m["id"]: m for m in data["maps"]}
    if len(stored) != len(data["maps"]):
        _fail("maps/id", "IDs de mapa duplicados")
    if data.get("version") == 1:
        _normalise_legacy_maps(data)
    for m in _default_maps(hosts):
        if m["id"] not in stored:
            data["maps"].append(m)
    aliases = _consolidate_maps(data, hosts)
    return data, rev, y, aliases


def host_ids(m, hosts):
    if m["kind"] == "all":
        return sorted(hosts)
    included = set(m.get("members") or [])
    if m["kind"] == "site":
        included.update(h for h, fields in hosts.items() if fields.get("site") == m.get("site"))
    return sorted(included & hosts.keys())


@yaml_io.serialized
def snapshot():
    hosts = _hosts()
    hosts_data, _ = inventory_svc.load_hosts()
    legacy = hosts_data.get("version") != 2
    data, rev, _, aliases = _document(hosts)
    topology = topology_svc.load_topology()
    known_links = {link["id"] for link in topology["links"]}
    maps = []
    for m in data["maps"]:
        try:
            value = deepcopy(m) if legacy else NetworkMap.model_validate(m).model_dump(exclude_none=True)
        except ValidationError:
            _fail("maps", "mapa salvo com formato inválido")
        # Alterações externas nos arquivos canônicos não deixam referências mortas
        # no editor. A leitura é pura; a próxima gravação persiste a limpeza.
        value["members"] = [name for name in value.get("members", []) if name in hosts]
        value["positions"] = [pos for pos in value.get("positions", []) if pos["host_id"] in hosts]
        value["objects"] = value.get("objects") or []
        value["edges"] = {ident: layout for ident, layout in value.get("edges", {}).items() if ident in known_links}
        visible = host_ids(value, hosts)
        nodes = {("host", name) for name in visible} | {("object", o["id"]) for o in value["objects"]}
        value["visual_links"] = [link for link in value.get("visual_links", []) if _ref_key(link["source"]) in nodes and _ref_key(link["target"]) in nodes]
        maps.append({**value, "host_ids": visible})
    return {"version": 2, "maps": maps, "map_aliases": aliases, "hosts": list(hosts.values()), "rev": rev,
            "hosts_rev": yaml_io.file_rev(deps.HOSTS_FILE),
            "topology": topology, "read_only": deps.STATE.read_only or legacy,
            "migration_required": legacy}


def _validate(m, maps, hosts, links):
    valid_hosts = set(hosts)
    positions = m.get("positions") or []
    if len({p["host_id"] for p in positions}) != len(positions):
        _fail("positions/host_id", "posição de host duplicada")
    for name in set(m.get("members") or []) | {p["host_id"] for p in positions}:
        if name not in valid_hosts:
            _fail("hosts", f"host '{name}' fora do inventário")
    map_ids = {item["id"] for item in maps}
    objects = m.get("objects") or []
    ids = [o["id"] for o in objects]
    if len(ids) != len(set(ids)):
        _fail("objects/id", "IDs de objeto duplicados")
    for obj in objects:
        if obj["type"] == "reference" and (obj.get("map_id") not in map_ids or obj["map_id"] == m["id"]):
            _fail("objects/map_id", "mapa de destino inexistente ou igual ao atual")
    visible = set(host_ids(m, hosts))
    node_ids = {("host", name) for name in visible} | {("object", name) for name in ids}
    for ident in (m.get("edges") or {}):
        if ident not in links:
            _fail("edges", "enlace não existe na topologia, recarregue o mapa")
    visual_ids = [v["id"] for v in m.get("visual_links") or []]
    if len(visual_ids) != len(set(visual_ids)):
        _fail("visual_links/id", "IDs de conexão visual duplicados")
    for link in m.get("visual_links") or []:
        if _ref_key(link["source"]) not in node_ids or _ref_key(link["target"]) not in node_ids or link["source"] == link["target"]:
            _fail("visual_links", "ponta da conexão visual inválida")
        if link["source"]["kind"] == "host" and link["target"]["kind"] == "host":
            _fail("visual_links", "ligação entre hosts precisa ser cadastrada como enlace real")


def _require_rev(rev):
    if not rev:
        _fail("rev", "revisão do mapa obrigatória (If-Match)")


@yaml_io.serialized
def save_map(m, rev, hosts_rev, topology_rev):
    _require_migrated()
    _require_rev(rev)
    hosts = _hosts()
    data, _, y, aliases = _document(hosts)
    if m["id"] in aliases:
        raise deps.ConflictError(yaml_io.file_rev(deps.MAPS_FILE),
                                 detail="Este mapa foi unificado com Rede geral. Recarregue antes de editar.")
    existing = next((item for item in data["maps"] if item["id"] == m["id"]), None)
    if existing and (existing["kind"] != m["kind"] or existing.get("site") != m.get("site")):
        _fail("kind", "o tipo e a localidade de um mapa existente não podem mudar")
    if existing:
        # Mantém os comentários do bloco do mapa ao substituir seus campos editáveis.
        for key in list(existing):
            if key not in m:
                del existing[key]
        existing.update(m)
    maps = list(data["maps"])
    if not existing:
        if m["kind"] != "custom":
            _fail("kind", "novos mapas adicionais usam o tipo custom")
        maps.append(m)
    topo, _, ty = topology_svc._load_doc()
    _validate(m, maps, hosts, set(topology_svc.link_ids(topo.get("links") or [])))
    data["maps"] = maps
    writes = [(deps.MAPS_FILE, yaml_io.dump_rt(y, data), 0o644)]
    checks = [(deps.MAPS_FILE, rev), (deps.HOSTS_FILE, hosts_rev), (deps.TOPOLOGY_FILE, topology_rev)]
    # O primeiro layout fixa a identidade dos enlaces legados na mesma transação.
    if topology_svc.ensure_link_ids(topo):
        writes.append((deps.TOPOLOGY_FILE, yaml_io.dump_rt(ty, topo), 0o644))
    yaml_io.write_many(writes, checks=checks)
    return snapshot()


@yaml_io.serialized
def delete_map(ident, rev):
    _require_migrated()
    _require_rev(rev)
    data, _, y, aliases = _document()
    if ident in aliases:
        _fail("map", "este mapa foi unificado com Rede geral")
    m = next((m for m in data["maps"] if m["id"] == ident), None)
    if not m:
        raise KeyError("mapa não existe")
    if m["kind"] != "custom":
        _fail("map", "mapas automáticos acompanham o inventário e não podem ser excluídos")
    data["maps"] = [m for m in data["maps"] if m["id"] != ident]
    for other in data["maps"]:
        removed = {o["id"] for o in other.get("objects") or [] if o.get("map_id") == ident}
        other["objects"] = [o for o in other.get("objects") or [] if o["id"] not in removed]
        other["visual_links"] = [v for v in other.get("visual_links") or []
                                 if _ref_key(v["source"]) not in {("object", i) for i in removed}
                                 and _ref_key(v["target"]) not in {("object", i) for i in removed}]
    yaml_io.write_rt(deps.MAPS_FILE, y, data, expected=rev, backup=True)
    return snapshot()


def place_host(host_id, placement, hosts_data, writes, checks):
    hosts = _hosts(hosts_data)
    data, _, y, aliases = _document(hosts)
    ident = aliases.get(placement["map_id"], placement["map_id"])
    m = next((m for m in data["maps"] if m["id"] == ident), None)
    if not m:
        raise KeyError("mapa não existe")
    positions = m.setdefault("positions", [])
    positions[:] = [p for p in positions if p["host_id"] != host_id]
    positions.append({"host_id": host_id, "x": placement["x"], "y": placement["y"]})
    if m["kind"] != "all" and host_id not in host_ids(m, hosts):
        m.setdefault("members", []).append(host_id)
    writes.append((deps.MAPS_FILE, yaml_io.dump_rt(y, data), 0o644))
    checks.append((deps.MAPS_FILE, placement["maps_rev"]))


def cascade_links(removed, writes, checks):
    if not deps.MAPS_FILE.exists():
        return
    data, rev, y = yaml_io.load_rt(deps.MAPS_FILE)
    changed = False
    for m in (data or {}).get("maps") or []:
        for ident in removed:
            if ident in (m.get("edges") or {}):
                del m["edges"][ident]
                changed = True
    if changed:
        writes.append((deps.MAPS_FILE, yaml_io.dump_rt(y, data), 0o644))
        checks.append((deps.MAPS_FILE, rev))


def host_references(host_id):
    data, _, _, _ = _document()
    return [{"kind": "map", "id": m["id"], "field": "host", "label": f"mapa {m['name']}"}
            for m in data["maps"] if host_id in host_ids(m, _hosts()) or host_id in {p["host_id"] for p in m.get("positions") or []}]


def cascade_host(old, new, removed_links, writes, checks):
    if not deps.MAPS_FILE.exists():
        return
    data, rev, y, _ = _document()
    for m in (data or {}).get("maps") or []:
        members = m.get("members") or []
        m["members"] = [new if name == old else name for name in members if name != old or new]
        positions = m.get("positions") or []
        m["positions"] = [{**p, "host_id": new if p["host_id"] == old else p["host_id"]}
                          for p in positions if p["host_id"] != old or new is not None]
        for ident in removed_links:
            (m.get("edges") or {}).pop(ident, None)
        visual = []
        for link in m.get("visual_links") or []:
            if ("host", old) in (_ref_key(link["source"]), _ref_key(link["target"])):
                if new is None:
                    continue
                for end in ("source", "target"):
                    if _ref_key(link[end]) == ("host", old):
                        link[end]["host_id"] = new
            visual.append(link)
        m["visual_links"] = visual
    writes.append((deps.MAPS_FILE, yaml_io.dump_rt(y, data), 0o644))
    checks.append((deps.MAPS_FILE, rev))
