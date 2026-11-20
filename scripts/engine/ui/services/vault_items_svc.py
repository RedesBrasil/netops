#!/usr/bin/env python3
"""Cofre de senhas (network/vault.yaml): campos reutilizáveis, templates e itens.

- Campo `text` fica em claro e aparece sempre (mesmo com o cofre trancado).
- Campo `secret` é cifrado com a chave do cofre (encrypt-on-write); a listagem só diz {set: true}.
  Gravar/revelar segredo exige o cofre destrancado (VaultLocked -> 423).
- Obrigatório/visível são POR template; o tipo (segredo/texto) é do campo (catálogo).
Concorrência: `rev` (sha256 do arquivo) via If-Match, igual às credenciais. Arquivo 0600.
"""
from __future__ import annotations

import time

import deps
from lib import i18n
from lib import pwvault
from services import yaml_io

MODE_600 = 0o600


def _path():
    return deps.NETWORK_DIR / pwvault.FILE_NAME


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _bad(loc: str, msg: str):
    return deps.ValidationFailed([{"loc": loc, "msg": msg}])


def _load():
    data, text = pwvault.load(_path())
    return data, yaml_io.sha256_text(text)


def _save(data: dict, rev: str | None) -> str:
    return yaml_io.write_text(_path(), pwvault.dump(data), expected=rev, mode=MODE_600, backup=True)


def _ik(data: dict, iid) -> int:
    """ID numérico do item (aceita número ou o slug antigo); KeyError se não existe."""
    k = pwvault.find_item(data, iid)
    if k is None:
        raise KeyError(i18n.t("api_vault_items.item_not_exists", id=iid))
    return k


def _key() -> bytes:
    """Chave do cofre (mesma do credentials.yaml). Levanta VaultNotInitialized / VaultLocked."""
    import yaml  # noqa: PLC0415
    from lib import vault, vault_session  # noqa: PLC0415
    text = deps.CREDS_FILE.read_text(encoding="utf-8") if deps.CREDS_FILE.exists() else ""
    meta = vault.load_meta(yaml.safe_load(text) if text.strip() else {})
    key = vault_session.get_session_key()
    vault.verify_key(key, meta)
    return key


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #
def _field_usage(data: dict) -> dict:
    use = {k: {"templates": 0, "items": 0} for k in data["fields"]}
    for t in data["templates"].values():
        for f in (t or {}).get("fields") or []:
            if f.get("field") in use:
                use[f["field"]]["templates"] += 1
    for it in data["items"].values():
        for k in ((it or {}).get("values") or {}):
            if k in use:
                use[k]["items"] += 1
    return use


def _item_view(iid: int, it: dict, fields: dict) -> dict:
    vals = []
    for name, v in ((it or {}).get("values") or {}).items():
        kind = (fields.get(name) or {}).get("kind", "secret")
        if kind == "text" and not str(v).startswith("enc.v1:"):
            vals.append({"field": name, "kind": "text", "value": v})
        else:
            vals.append({"field": name, "kind": "secret", "set": bool(v)})
    out = {"id": iid, "values": vals}
    for k in ("title", "template", "template_label", "notes", "aliases", "created_by", "created_at", "updated_by", "updated_at"):
        if (it or {}).get(k) not in (None, ""):
            out[k] = it[k]
    return out


def catalog() -> dict:
    data, rev = _load()
    use = _field_usage(data)
    fields = [{"name": k, "kind": (v or {}).get("kind", "secret"), **use.get(k, {})} for k, v in data["fields"].items()]
    templates = []
    for tid, t in data["templates"].items():
        t = t or {}
        n_items = sum(1 for it in data["items"].values() if (it or {}).get("template") == tid)
        templates.append({"id": tid, "label": t.get("label") or tid, "description": t.get("description", ""),
                          "fields": [{"field": f["field"], "required": bool(f.get("required")),
                                      "visible": bool(f.get("visible")),
                                      "kind": (data["fields"].get(f["field"]) or {}).get("kind", "secret")}
                                     for f in t.get("fields") or [] if f.get("field")],
                          "items": n_items})
    return {"fields": fields, "templates": templates, "rev": rev}


def list_items() -> dict:
    data, rev = _load()
    items = [_item_view(i, it, data["fields"]) for i, it in data["items"].items()]
    items.sort(key=lambda x: str(x.get("title") or x["id"]).casefold())
    return {"items": items, "rev": rev, **{k: v for k, v in catalog().items() if k != "rev"}}


def get_item(iid: str) -> dict:
    data, rev = _load()
    iid = _ik(data, iid)
    return _item_view(iid, data["items"][iid], data["fields"]) | {"rev": rev}


# --------------------------------------------------------------------------- #
# Campos (catálogo)
# --------------------------------------------------------------------------- #
def _clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise _bad("name", i18n.t("api_vault_items.field_name_required"))
    if len(name) > pwvault.FIELD_NAME_MAX:
        raise _bad("name", i18n.t("api_vault_items.max_chars", max=pwvault.FIELD_NAME_MAX))
    return name


def _ensure_field(data: dict, name: str, kind: str | None) -> str:
    """Nome real do campo; cria no catálogo se não existir (o novo campo fica reutilizável)."""
    name = _clean_name(name)
    real = pwvault.field_key(data["fields"], name)
    if real:
        return real
    data["fields"][name] = {"kind": kind if kind in pwvault.KINDS else "secret"}
    return name


def _convert_kind(data: dict, name: str, kind: str) -> None:
    """Muda o tipo de um campo e converte os valores já gravados (cifra/decifra)."""
    from lib import vault  # noqa: PLC0415
    if kind not in pwvault.KINDS:
        raise _bad("kind", i18n.t("api_vault_items.bad_kind"))
    if data["fields"][name].get("kind") == kind:
        return
    used = [it for it in data["items"].values() if (it or {}).get("values", {}).get(name) not in (None, "")]
    if used:
        key = _key()
        for it in used:
            v = it["values"][name]
            it["values"][name] = (vault.encrypt_value(key, str(v)) if kind == "secret"
                                  else vault.decrypt_value(key, v))
    data["fields"][name]["kind"] = kind


@yaml_io.serialized
def create_field(name: str, kind: str, rev: str | None) -> dict:
    data, _ = _load()
    name = _clean_name(name)
    if pwvault.field_key(data["fields"], name):
        raise _bad("name", i18n.t("api_vault_items.field_exists", name=name))
    if kind not in pwvault.KINDS:
        raise _bad("kind", i18n.t("api_vault_items.bad_kind"))
    data["fields"][name] = {"kind": kind}
    _save(data, rev)
    return catalog()


@yaml_io.serialized
def update_field(name: str, new_name: str | None, kind: str | None, rev: str | None) -> dict:
    data, _ = _load()
    real = pwvault.field_key(data["fields"], name)
    if not real:
        raise KeyError(i18n.t("api_vault_items.field_not_exists", name=name))
    if kind:
        _convert_kind(data, real, kind)
    if new_name is not None:
        new_name = _clean_name(new_name)
        other = pwvault.field_key(data["fields"], new_name)
        if other and other != real:
            raise _bad("name", i18n.t("api_vault_items.field_exists", name=new_name))
        if new_name != real:
            # o nome antigo vira apelido: referências nvault://<id>/<campo-antigo> continuam resolvendo
            meta = dict(data["fields"][real] or {})
            meta["aliases"] = sorted(set((meta.get("aliases") or []) + [real]) - {new_name})
            data["fields"][real] = meta
            data["fields"] = {(new_name if k == real else k): v for k, v in data["fields"].items()}
            for t in data["templates"].values():
                for f in (t or {}).get("fields") or []:
                    if f.get("field") == real:
                        f["field"] = new_name
            for it in data["items"].values():
                vals = (it or {}).get("values")
                if vals and real in vals:
                    it["values"] = {(new_name if k == real else k): v for k, v in vals.items()}
    _save(data, rev)
    return catalog()


@yaml_io.serialized
def delete_field(name: str, rev: str | None) -> dict:
    data, _ = _load()
    real = pwvault.field_key(data["fields"], name)
    if not real:
        raise KeyError(i18n.t("api_vault_items.field_not_exists", name=name))
    use = _field_usage(data)[real]
    if use["templates"] or use["items"]:
        raise deps.ConflictError(yaml_io.file_rev(_path()),
                                 detail=i18n.t("api_vault_items.field_in_use", templates=use["templates"], items=use["items"]))
    del data["fields"][real]
    _save(data, rev)
    return catalog()


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def _apply_template(data: dict, tpl: dict, body: dict) -> None:
    label = " ".join(str(body.get("label") or "").split())
    if not label:
        raise _bad("label", i18n.t("api_vault_items.template_name_required"))
    rows, seen = [], set()
    for i, f in enumerate(body.get("fields") or []):
        real = _ensure_field(data, f.get("field") or "", f.get("kind"))
        if real in seen:
            raise _bad(f"fields.{i}", i18n.t("api_vault_items.field_repeated", name=real))
        seen.add(real)
        if f.get("kind") and f["kind"] != data["fields"][real].get("kind"):
            _convert_kind(data, real, f["kind"])
        rows.append({"field": real, "required": bool(f.get("required")), "visible": bool(f.get("visible"))})
    tpl.update({"label": label, "description": str(body.get("description") or "").strip(), "fields": rows})


@yaml_io.serialized
def create_template(body: dict, rev: str | None) -> dict:
    data, _ = _load()
    tid = pwvault.unique_id(body.get("label") or "template", data["templates"])
    tpl: dict = {}
    _apply_template(data, tpl, body)
    data["templates"][tid] = tpl
    _save(data, rev)
    return catalog() | {"id": tid}


@yaml_io.serialized
def update_template(tid: str, body: dict, rev: str | None) -> dict:
    data, _ = _load()
    if tid not in data["templates"]:
        raise KeyError(i18n.t("api_vault_items.template_not_exists", id=tid))
    tpl = data["templates"][tid] or {}
    _apply_template(data, tpl, body)
    data["templates"][tid] = tpl
    for it in data["items"].values():                 # o rótulo guardado nos itens acompanha
        if (it or {}).get("template") == tid:
            it["template_label"] = tpl["label"]
    _save(data, rev)
    return catalog() | {"id": tid}


@yaml_io.serialized
def delete_template(tid: str, rev: str | None) -> dict:
    """Apaga o template; os itens continuam (com o nome antigo em template_label)."""
    data, _ = _load()
    if tid not in data["templates"]:
        raise KeyError(i18n.t("api_vault_items.template_not_exists", id=tid))
    del data["templates"][tid]
    for it in data["items"].values():
        if (it or {}).get("template") == tid:
            it.pop("template", None)
    _save(data, rev)
    return catalog()


# --------------------------------------------------------------------------- #
# Itens
# --------------------------------------------------------------------------- #
def _apply_item(data: dict, it: dict, body: dict, *, user: str, is_new: bool) -> None:
    from lib import vault  # noqa: PLC0415
    title = " ".join(str(body.get("title") or "").split())
    if not title:
        raise _bad("title", i18n.t("api_vault_items.title_required"))
    tid = body.get("template") or None
    if tid and tid not in data["templates"]:
        raise _bad("template", i18n.t("api_vault_items.template_not_exists", id=tid))
    old_vals = dict(it.get("values") or {})
    new_vals: dict = {}
    key = None
    for i, row in enumerate(body.get("values") or []):
        real = pwvault.field_key(data["fields"], row.get("field") or "")
        if not real:
            raise _bad(f"values.{i}", i18n.t("api_vault_items.field_not_in_catalog", name=row.get("field")))
        if real in new_vals:
            raise _bad(f"values.{i}", i18n.t("api_vault_items.field_repeated", name=real))
        value = row.get("value")
        kind = data["fields"][real].get("kind", "secret")
        if value is None:                              # segredo omitido = mantém o atual
            if real in old_vals:
                new_vals[real] = old_vals[real]
            continue
        value = str(value)
        if kind == "text":
            value = value.strip()
            if value:
                new_vals[real] = value
        elif value != "":
            key = key or _key()
            new_vals[real] = vault.encrypt_value(key, value)
    if tid:
        tpl = data["templates"][tid] or {}
        missing = [f["field"] for f in tpl.get("fields") or []
                   if f.get("required") and new_vals.get(f["field"]) in (None, "")]
        if missing:
            raise _bad("values", i18n.t("api_vault_items.required_empty", fields=", ".join(missing)))
        it["template"], it["template_label"] = tid, tpl.get("label") or tid
    else:
        it.pop("template", None)
        it.pop("template_label", None)
    it["title"] = title
    notes = str(body.get("notes") or "").strip()
    if notes:
        it["notes"] = notes
    else:
        it.pop("notes", None)
    it["values"] = new_vals
    now = _now()
    if is_new:
        it["created_by"], it["created_at"] = user or "—", now
    it["updated_by"], it["updated_at"] = user or "—", now


@yaml_io.serialized
def create_item(body: dict, rev: str | None, user: str) -> dict:
    data, _ = _load()
    iid = pwvault.new_item_id(data)
    it: dict = {}
    _apply_item(data, it, body, user=user, is_new=True)
    data["items"][iid] = {k: it[k] for k in ("title", "template", "template_label", "notes", "aliases", "values",
                                              "created_by", "created_at", "updated_by", "updated_at") if k in it}
    new_rev = _save(data, rev)
    return _item_view(iid, data["items"][iid], data["fields"]) | {"rev": new_rev}


@yaml_io.serialized
def update_item(iid: str, body: dict, rev: str | None, user: str) -> dict:
    data, _ = _load()
    iid = _ik(data, iid)
    it = dict(data["items"][iid] or {})
    _apply_item(data, it, body, user=user, is_new=False)
    data["items"][iid] = it
    new_rev = _save(data, rev)
    return _item_view(iid, it, data["fields"]) | {"rev": new_rev}


@yaml_io.serialized
def delete_item(iid: str, rev: str | None) -> dict:
    data, _ = _load()
    iid = _ik(data, iid)
    del data["items"][iid]
    return {"deleted": iid, "rev": _save(data, rev)}


def reveal(iid: str, field: str | None) -> dict:
    """Valores em claro dos segredos de um item (um campo ou todos). Só para o humano no console:
    exige cofre destrancado + permissão vault.reveal (authz). Auditado pelo middleware."""
    from lib import vault  # noqa: PLC0415
    data, _ = _load()
    iid = _ik(data, iid)
    vals = (data["items"][iid] or {}).get("values") or {}
    if field:
        real = pwvault.find_value_name(data, data["items"][iid], field)   # nome, slug ou nome antigo do campo
        if not real:
            raise KeyError(i18n.t("api_vault_items.field_no_value", name=field))
        vals = {real: vals[real]}
    key = _key()
    return {"id": iid, "values": {k: vault.decrypt_value(key, v) for k, v in vals.items()}}
