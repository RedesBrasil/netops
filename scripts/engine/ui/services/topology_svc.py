#!/usr/bin/env python3
"""CRUD de links/segments (network/topology.yaml) + regeneração do topology.md.

topology.md é GERADO (reusa scripts/tools/docs/topology_render.py) — a UI nunca edita à mão,
só oferece "regenerar". Links que apontam p/ host fora do inventário são sinalizados
(constituição VI), mas não bloqueiam (o seed traz exemplos com hosts inexistentes)."""
from __future__ import annotations

from ruamel.yaml.comments import CommentedMap

import deps
from services import yaml_io


def _load_doc():
    data, rev, y = yaml_io.load_rt(deps.TOPOLOGY_FILE)
    if data is None:
        data = {"version": 1, "links": [], "segments": []}
    return data, rev, y


def _known_hosts() -> set[str]:
    import yaml  # noqa: PLC0415
    if not deps.HOSTS_FILE.exists():
        return set()
    data = yaml.safe_load(deps.HOSTS_FILE.read_text(encoding="utf-8")) or {}
    return set((data.get("hosts") or {}).keys())


def load_topology() -> dict:
    import yaml  # noqa: PLC0415
    text, rev, _ = yaml_io.read_text_meta(deps.TOPOLOGY_FILE)
    data = (yaml.safe_load(text) if text.strip() else {}) or {}
    known = _known_hosts()
    links = data.get("links") or []
    out_links = []
    for i, lk in enumerate(links):
        a = (lk.get("a") or {}).get("host")
        b = (lk.get("b") or {}).get("host")
        dangling = [h for h in (a, b) if h and h not in known]
        out_links.append({"index": i, **lk, "dangling": dangling})
    segments = [{"index": i, **s} for i, s in enumerate(data.get("segments") or [])]
    return {"links": out_links, "segments": segments, "rev": rev}


def _flow_end(end: dict) -> CommentedMap:
    m = CommentedMap()
    m["host"] = end["host"]
    m["port"] = end["port"]
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
def add_link(link: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    data.setdefault("links", []).append(_link_node(link))
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


def update_link(index: int, link: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    links = data.get("links") or []
    if not 0 <= index < len(links):
        raise KeyError(f"link índice {index} não existe")
    links[index] = _link_node(link)
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


def delete_link(index: int, rev: str | None) -> dict:
    data, _, y = _load_doc()
    links = data.get("links") or []
    if not 0 <= index < len(links):
        raise KeyError(f"link índice {index} não existe")
    del links[index]
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


# --------------------------------------------------------------------------- #
# Segments
# --------------------------------------------------------------------------- #
def add_segment(seg: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    data.setdefault("segments", []).append(_seg_node(seg))
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


def update_segment(index: int, seg: dict, rev: str | None) -> dict:
    data, _, y = _load_doc()
    segs = data.get("segments") or []
    if not 0 <= index < len(segs):
        raise KeyError(f"segmento índice {index} não existe")
    segs[index] = _seg_node(seg)
    yaml_io.write_rt(deps.TOPOLOGY_FILE, y, data, expected=rev, backup=True)
    return load_topology()


def delete_segment(index: int, rev: str | None) -> dict:
    data, _, y = _load_doc()
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
