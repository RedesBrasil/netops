#!/usr/bin/env python3
"""CRUD de links/segments (network/topology.yaml) + regeneração do topology.md.

topology.md é GERADO (reusa scripts/tools/docs/topology_render.py) — a UI nunca edita à mão,
só oferece "regenerar". Links que apontam p/ host fora do inventário são sinalizados
(constituição VI), mas não bloqueiam (o seed traz exemplos com hosts inexistentes)."""
from __future__ import annotations

import hashlib
import json
import uuid

from ruamel.yaml.comments import CommentedMap

import deps
from lib.host_identity import host_index, require_host_id
from services import yaml_io


def _load_doc():
    data, rev, y = yaml_io.load_rt(deps.TOPOLOGY_FILE)
    if data is None:
        data = {"version": 2, "links": [], "segments": []}
    return data, rev, y


def _known_hosts() -> set[int | str]:
    import yaml  # noqa: PLC0415
    if not deps.HOSTS_FILE.exists():
        return set()
    data = yaml.safe_load(deps.HOSTS_FILE.read_text(encoding="utf-8")) or {}
    return set(host_index(data))


def _require_migrated(data):
    from services import inventory_svc
    hosts, _ = inventory_svc.load_hosts()
    if hosts.get("version") != 2 or data.get("version") != 2:
        raise deps.ValidationFailed([{"loc": "hosts/version", "msg": "Migre o inventário e a topologia para IDs inteiros antes de editar os enlaces."}])


def _validate_link(link):
    known = _known_hosts()
    for end in ("a", "b"):
        try:
            ident = require_host_id(link[end]["host"])
        except (ValueError, TypeError, KeyError):
            raise deps.ValidationFailed([{"loc": f"{end}/host", "msg": "ID inteiro de host obrigatório"}])
        if ident not in known:
            raise deps.ValidationFailed([{"loc": f"{end}/host", "msg": "host fora do inventário"}])


def link_ids(links) -> list[str]:
    """IDs legados determinísticos, inclusive para enlaces exatamente duplicados."""
    seen = {}
    ids = []
    for link in links:
        if link.get("id"):
            value = str(link["id"])
        else:
            fingerprint = hashlib.sha256(json.dumps(link, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
            ordinal = seen.get(fingerprint, 0)
            seen[fingerprint] = ordinal + 1
            value = f"link-{fingerprint}-{ordinal}"
        if value in ids:
            raise deps.ValidationFailed([{"loc": "links/id", "msg": "IDs de enlace duplicados"}])
        ids.append(value)
    return ids

def ensure_link_ids(data) -> bool:
    changed = False
    links = data.get("links") or []
    for link, value in zip(links, link_ids(links)):
        if not link.get("id"):
            link["id"] = value
            changed = True
    return changed

@yaml_io.serialized
def load_topology() -> dict:
    import yaml  # noqa: PLC0415
    text, rev, _ = yaml_io.read_text_meta(deps.TOPOLOGY_FILE)
    data = (yaml.safe_load(text) if text.strip() else {}) or {}
    known = _known_hosts()
    links = data.get("links") or []
    out_links = []
    for i, (lk, link_id) in enumerate(zip(links, link_ids(links))):
        a = (lk.get("a") or {}).get("host")
        b = (lk.get("b") or {}).get("host")
        dangling = [h for h in (a, b) if h and h not in known]
        out_links.append({"index": i, **lk, "id": link_id, "dangling": dangling})
    segments = [{"index": i, **s} for i, s in enumerate(data.get("segments") or [])]
    return {"version": data.get("version", 1 if data else 2), "links": out_links, "segments": segments, "rev": rev}


def _flow_end(end: dict) -> CommentedMap:
    m = CommentedMap()
    m["host"] = end["host"]
    port = (end.get("port") or "").strip()
    if port:
        m["port"] = port
    m.fa.set_flow_style()
    return m


def _link_node(link: dict) -> CommentedMap:
    node = CommentedMap()
    node["a"] = _flow_end(link["a"])
    node["b"] = _flow_end(link["b"])
    for k in ("media", "speed", "desc"):
        if link.get(k) not in (None, ""):
            node[k] = link[k]
    return node


def _seg_node(seg: dict) -> CommentedMap:
    node = CommentedMap()
    node["name"] = seg["name"]
    for k in ("vlan", "subnet"):
        if seg.get(k) not in (None, ""):
            node[k] = seg[k]
    return node


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #
@yaml_io.serialized
def add_link(link: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    _require_migrated(data)
    _validate_link(link)
    ensure_link_ids(data)
    node = _link_node(link)
    node["id"] = "link-" + uuid.uuid4().hex
    data.setdefault("links", []).append(node)
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


@yaml_io.serialized
def update_link(index: int, link: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    _require_migrated(data)
    _validate_link(link)
    links = data.get("links") or []
    if not 0 <= index < len(links):
        raise KeyError(f"link índice {index} não existe")
    ensure_link_ids(data)
    node = links[index]
    for key in ("a", "b", "media", "speed", "desc"):
        if key in ("a", "b"):
            node[key] = _flow_end(link[key])
        elif link.get(key) not in (None, ""):
            node[key] = link[key]
        else:
            node.pop(key, None)
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


@yaml_io.serialized
def delete_link(index: int, rev: str | None) -> dict:
    data, _, y = _load_doc()
    _require_migrated(data)
    links = data.get("links") or []
    if not 0 <= index < len(links):
        raise KeyError(f"link índice {index} não existe")
    ensure_link_ids(data)
    removed = links[index]["id"]
    del links[index]
    from services import maps_svc
    writes = [(deps.TOPOLOGY_FILE, yaml_io.dump_rt(y, data), 0o644)]
    checks = [(deps.TOPOLOGY_FILE, rev)]
    maps_svc.cascade_links({removed}, writes, checks)
    yaml_io.write_many(writes, checks=checks)
    return load_topology()


# --------------------------------------------------------------------------- #
# Segments
# --------------------------------------------------------------------------- #
@yaml_io.serialized
def add_segment(seg: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    _require_migrated(data)
    data.setdefault("segments", []).append(_seg_node(seg))
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


@yaml_io.serialized
def update_segment(index: int, seg: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    _require_migrated(data)
    segs = data.get("segments") or []
    if not 0 <= index < len(segs):
        raise KeyError(f"segmento índice {index} não existe")
    segs[index] = _seg_node(seg)
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


@yaml_io.serialized
def delete_segment(index: int, rev: str | None) -> dict:
    data, _, y = _load_doc()
    _require_migrated(data)
    segs = data.get("segments") or []
    if not 0 <= index < len(segs):
        raise KeyError(f"segmento índice {index} não existe")
    del segs[index]
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def _render_markdown() -> str:
    import yaml  # noqa: PLC0415
    from docs.topology_render import render  # noqa: PLC0415
    hosts_data = yaml.safe_load(deps.HOSTS_FILE.read_text(encoding="utf-8")) if deps.HOSTS_FILE.exists() else {}
    topo_data = yaml.safe_load(deps.TOPOLOGY_FILE.read_text(encoding="utf-8")) if deps.TOPOLOGY_FILE.exists() else {}
    return render(hosts_data or {}, topo_data or {})


def preview() -> dict:
    return {"markdown": _render_markdown()}


def render_to_file() -> dict:
    md = _render_markdown()
    yaml_io.atomic_write(deps.TOPOLOGY_MD, md)
    return {"markdown": md, "rev": yaml_io.file_rev(deps.TOPOLOGY_MD)}


def read_md() -> dict:
    text, rev, _ = yaml_io.read_text_meta(deps.TOPOLOGY_MD)
    return {"markdown": text, "rev": rev}


@yaml_io.serialized
def link_index(link_id: str) -> int:
    data, _, _ = _load_doc()
    for i, value in enumerate(link_ids(data.get("links") or [])):
        if value == link_id:
            return i
    raise KeyError("enlace não existe")
