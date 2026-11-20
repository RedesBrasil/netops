#!/usr/bin/env python3
"""CRUD de conhecimento: best-practices/ e config-examples/ (+ seus índices).

Cria/edita/remove arquivos por vendor e mantém o índice (_catalog.yaml/_index.yaml)
em sincronia. Nomes em kebab-case; vendor precisa estar na lista de core/rules/standard.md."""
from __future__ import annotations

from fastapi import APIRouter, Request

import deps
from lib import i18n
from services import docs_svc, yaml_io

router = APIRouter(tags=["knowledge"])

# kind -> (base_dir, index_file, list_key)
KINDS = {
    "best-practices": (deps.BEST_PRACTICES_DIR, deps.BP_CATALOG, "guides"),
    "config-examples": (deps.CONFIG_EXAMPLES_DIR, deps.CE_INDEX, "examples"),
}


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


def _kind(kind: str):
    if kind not in KINDS:
        raise KeyError(i18n.t("api_knowledge.bad_kind", kind=kind))
    return KINDS[kind]


# Index keys are English; installs older than 2.7 may still have the Portuguese ones (read both, write English).
LEGACY_KEYS = {"titulo": "title", "quando_usar": "when_to_use", "topico": "topic", "descricao": "description"}


def _norm(entry):
    if not isinstance(entry, dict):
        return entry
    out = {}
    for k, v in entry.items():
        out.setdefault(LEGACY_KEYS.get(k, k), v)
    return out


def _field(body: dict, key: str, default=""):
    legacy = next((k for k, v in LEGACY_KEYS.items() if v == key), None)
    return body.get(key) or (body.get(legacy) if legacy else None) or default


def _entry(kind: str, vendor: str, name: str, body: dict) -> dict:
    rel = f"{vendor}/{name}"
    if kind == "best-practices":
        return {
            "id": body.get("id") or name.rsplit(".", 1)[0],
            "title": _field(body, "title", name),
            "vendor": vendor,
            "file": rel,
            "when_to_use": _field(body, "when_to_use"),
        }
    return {
        "vendor": vendor,
        "topic": _field(body, "topic") or name.rsplit(".", 1)[0],
        "file": rel,
        "description": _field(body, "description"),
    }


@router.get("/knowledge/{kind}")
def get_index(kind: str):
    import yaml  # noqa: PLC0415
    base, index_file, key = _kind(kind)
    text, rev, _ = yaml_io.read_text_meta(index_file)
    data = (yaml.safe_load(text) if text.strip() else {}) or {}
    # arquivos reais em disco (pode haver itens não indexados)
    on_disk = []
    if base.exists():
        for f in sorted(base.rglob("*")):
            if f.is_file() and not f.name.startswith("_") and f.parent != base:
                on_disk.append(str(f.relative_to(base)))
    return {"index": [_norm(e) for e in (data.get(key) or [])], "vendors": data.get("vendors") or {},
            "files": on_disk, "rev": rev}


@router.get("/knowledge/{kind}/file")
def get_file(kind: str, vendor: str, name: str):
    base, _, _ = _kind(kind)
    path = docs_svc.safe_child(base, vendor, name)
    if not path.exists():
        raise KeyError(i18n.t("api_common.path_not_exists", path=f"{vendor}/{name}"))
    info = docs_svc.read_text_file(path)
    fm, _body = docs_svc.split_frontmatter(info["text"])
    info["frontmatter"] = fm
    return info


@router.post("/knowledge/{kind}", status_code=201)
def create_file(kind: str, body: dict, request: Request):
    base, index_file, key = _kind(kind)
    vendor = (body.get("vendor") or "").strip()
    name = (body.get("name") or body.get("file") or "").strip()
    docs_svc.assert_vendor(vendor)
    if not name or "/" in name or name.startswith("_"):
        raise deps.ValidationFailed([{"loc": "name", "msg": i18n.t("api_common.invalid_filename")}])
    path = docs_svc.safe_child(base, vendor, name)
    if path.exists():
        raise deps.ValidationFailed([{"loc": "name", "msg": i18n.t("api_common.path_exists", path=f"{vendor}/{name}")}])
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml_io.atomic_write(path, body.get("text", ""))
    # adiciona entrada ao índice (ruamel preserva comentários)
    data, _, y = yaml_io.load_rt(index_file)
    if data is None:
        data = {"version": 1, key: []}
    data.setdefault(key, []).append(_entry(kind, vendor, name, body))
    yaml_io.write_rt(index_file, y, data, expected=None, backup=True)
    return {"file": f"{vendor}/{name}", "rev": yaml_io.file_rev(path)}


@router.put("/knowledge/{kind}/file")
def update_file(kind: str, body: dict, request: Request):
    base, _, _ = _kind(kind)
    vendor, name = body.get("vendor", ""), body.get("name", "")
    path = docs_svc.safe_child(base, vendor, name)
    if not path.exists():
        raise KeyError(i18n.t("api_common.path_not_exists", path=f"{vendor}/{name}"))
    new_rev = yaml_io.write_text(path, body.get("text", ""), expected=_rev(request), backup=True)
    return {"file": f"{vendor}/{name}", "rev": new_rev}


@router.post("/knowledge/{kind}/rename")
def rename_file(kind: str, body: dict):
    """Move o arquivo (renomeia e/ou troca de vendor) e atualiza a entrada do índice."""
    import os  # noqa: PLC0415
    base, index_file, key = _kind(kind)
    vendor = (body.get("vendor") or "").strip()
    name = (body.get("name") or "").strip()
    to_vendor = (body.get("to_vendor") or vendor).strip()
    to_name = (body.get("to_name") or "").strip()
    docs_svc.assert_vendor(to_vendor)
    if not to_name or "/" in to_name or to_name.startswith("_"):
        raise deps.ValidationFailed([{"loc": "to_name", "msg": i18n.t("api_common.invalid_filename")}])
    src = docs_svc.safe_child(base, vendor, name)
    if not src.exists():
        raise KeyError(i18n.t("api_common.path_not_exists", path=f"{vendor}/{name}"))
    dst = docs_svc.safe_child(base, to_vendor, to_name)
    if dst == src:
        raise deps.ValidationFailed([{"loc": "to_name", "msg": i18n.t("api_common.same_target")}])
    if dst.exists():
        raise deps.ValidationFailed([{"loc": "to_name", "msg": i18n.t("api_common.path_exists", path=f"{to_vendor}/{to_name}")}])
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    old_rel, new_rel = f"{vendor}/{name}", f"{to_vendor}/{to_name}"
    data, _, y = yaml_io.load_rt(index_file)
    indexed = False
    if data and data.get(key):
        for e in data[key]:
            if e.get("file") == old_rel:
                e["file"] = new_rel
                e["vendor"] = to_vendor
                indexed = True
        if indexed:
            yaml_io.write_rt(index_file, y, data, expected=None, backup=True)
    return {"renamed": {"from": old_rel, "to": new_rel}, "indexed": indexed,
            "rev": yaml_io.file_rev(dst)}


@router.delete("/knowledge/{kind}/file")
def delete_file(kind: str, vendor: str, name: str):
    base, index_file, key = _kind(kind)
    path = docs_svc.safe_child(base, vendor, name)
    if not path.exists():
        raise KeyError(i18n.t("api_common.path_not_exists", path=f"{vendor}/{name}"))
    path.unlink()
    rel = f"{vendor}/{name}"
    data, _, y = yaml_io.load_rt(index_file)
    if data and data.get(key):
        data[key] = [e for e in data[key] if e.get("file") != rel]
        yaml_io.write_rt(index_file, y, data, expected=None, backup=True)
    return {"deleted": rel}
