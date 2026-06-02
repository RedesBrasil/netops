#!/usr/bin/env python3
"""CRUD de credenciais (network/credentials.yaml).

Duas estratégias de escrita, por segurança:
  - Campos NÃO-secretos (username/key_file/api_ssl) e criar/remover blocos de credencial
    => ruamel round-trip (credentials.yaml round-trip é byte-idêntico; o bloco 'vault:'
    sobrevive intacto).
  - password/secret => substituição textual REUSANDO scripts/vault/cli.py (_set_field/_emit/
    _atomic_write) + vault.encrypt_value — resultado byte-idêntico ao da CLI do cofre.

NUNCA devolve segredo em texto puro: password/secret saem mascarados {set, encrypted}.
"""
from __future__ import annotations

import re

import deps
from services import yaml_io

CRED_KEY_ORDER = ["username", "password", "secret", "key_file", "api_ssl"]
SECRET_FIELDS = ("password", "secret")
MODE_600 = 0o600
ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")  # espelha models.CredentialCreate


# --------------------------------------------------------------------------- #
# Leitura (mascarada)
# --------------------------------------------------------------------------- #
def load_creds() -> tuple[dict, str]:
    import yaml  # noqa: PLC0415
    text, rev, _ = yaml_io.read_text_meta(deps.CREDS_FILE)
    data = (yaml.safe_load(text) if text.strip() else {}) or {}
    return data, rev


def _mask_one(name: str, raw: dict) -> dict:
    from lib.vault import is_encrypted  # noqa: PLC0415
    out = {"name": name}
    for field in ("username", "key_file", "api_ssl"):
        if field in raw:
            out[field] = raw[field]
    for field in SECRET_FIELDS:
        if field in raw:
            out[field] = {"set": bool(raw[field]), "encrypted": is_encrypted(raw[field])}
    return out


def list_credentials() -> dict:
    data, rev = load_creds()
    creds = data.get("credentials") or {}
    out = [_mask_one(n, dict(creds[n] or {})) for n in sorted(creds.keys())]
    return {"credentials": out, "rev": rev, "vault_initialized": bool(data.get("vault"))}


def get_credential(name: str) -> dict:
    data, rev = load_creds()
    creds = data.get("credentials") or {}
    if name not in creds:
        raise KeyError(f"credencial '{name}' não existe")
    return _mask_one(name, dict(creds[name] or {})) | {"rev": rev}


# --------------------------------------------------------------------------- #
# Escrita de campos não-secretos (ruamel)
# --------------------------------------------------------------------------- #
def _load_doc():
    data, rev, y = yaml_io.load_rt(deps.CREDS_FILE)
    if data is None:
        data = {"version": 1, "credentials": {}}
    return data, y


def _clean_fields(fields: dict) -> dict:
    out = {}
    for k in CRED_KEY_ORDER:
        if k in fields and fields[k] not in (None, ""):
            out[k] = fields[k]
    return out


def create_credential(name: str, fields: dict, rev: str | None) -> dict:
    data, y = _load_doc()
    creds = data.setdefault("credentials", {})
    if name in creds:
        raise deps.ValidationFailed([{"loc": "name", "msg": f"credencial '{name}' já existe"}])
    creds[name] = _clean_fields(fields)
    new_rev = yaml_io.write_rt(deps.CREDS_FILE, y, data, expected=rev, mode=MODE_600, backup=True)
    return get_credential(name) | {"rev": new_rev}


def update_credential(name: str, fields: dict, rev: str | None, *, partial: bool) -> dict:
    data, y = _load_doc()
    creds = data.get("credentials") or {}
    if name not in creds:
        raise KeyError(f"credencial '{name}' não existe")
    node = creds[name]
    if node is None:
        node = creds[name] = {}
    for k in ("username", "key_file", "api_ssl"):
        if k in fields:
            if fields[k] in (None, ""):
                node.pop(k, None)
            else:
                node[k] = fields[k]
    new_rev = yaml_io.write_rt(deps.CREDS_FILE, y, data, expected=rev, mode=MODE_600, backup=True)
    return get_credential(name) | {"rev": new_rev}


def delete_credential(name: str, rev: str | None, *, force: bool) -> dict:
    data, y = _load_doc()
    creds = data.get("credentials") or {}
    if name not in creds:
        raise KeyError(f"credencial '{name}' não existe")
    used = _referencing_hosts(name)
    if used and not force:
        raise deps.ConflictError(yaml_io.file_rev(deps.CREDS_FILE),
                                 detail=f"credencial em uso por: {', '.join(used)}")
    del creds[name]
    new_rev = yaml_io.write_rt(deps.CREDS_FILE, y, data, expected=rev, mode=MODE_600, backup=True)
    return {"deleted": name, "rev": new_rev}


def _referencing_hosts(cred_name: str) -> list[str]:
    return [f"{r['kind']}:{r['id']}" for r in _credential_refs(cred_name)]


def _credential_refs(cred_name: str) -> list[dict]:
    """Hosts e grupos (em hosts.yaml) que apontam para `cred_name`."""
    import yaml  # noqa: PLC0415
    if not deps.HOSTS_FILE.exists():
        return []
    data = yaml.safe_load(deps.HOSTS_FILE.read_text(encoding="utf-8")) or {}
    refs = []
    for n, h in (data.get("hosts") or {}).items():
        if (h or {}).get("credential") == cred_name:
            refs.append({"kind": "host", "id": n, "field": "credential", "label": f"host {n}"})
    for n, g in (data.get("groups") or {}).items():
        if (g or {}).get("credential") == cred_name:
            refs.append({"kind": "group", "id": n, "field": "credential", "label": f"grupo {n}"})
    return refs


# --------------------------------------------------------------------------- #
# Renomear credencial (cascade: campo 'credential' de hosts/grupos em hosts.yaml)
# --------------------------------------------------------------------------- #
def credential_references(name: str) -> dict:
    data, _ = load_creds()
    if name not in (data.get("credentials") or {}):
        raise KeyError(f"credencial '{name}' não existe")
    refs = _credential_refs(name)
    return {"name": name, "references": refs, "count": len(refs)}


def rename_credential(old: str, new: str, rev: str | None) -> dict:
    """Renomeia a chave da credencial e atualiza 'credential' em hosts/grupos, numa
    transação atômica. credentials.yaml mantém modo 0600 e o bloco vault: intacto
    (ruamel round-trip); os tokens enc.v1: viajam junto com o valor."""
    if not ID_RE.match(new):
        raise deps.ValidationFailed([{"loc": "to", "msg": "use a-z, 0-9, ponto, hífen ou underline"}])
    data, y = _load_doc()
    creds = data.get("credentials") or {}
    if old not in creds:
        raise KeyError(f"credencial '{old}' não existe")
    if new == old:
        raise deps.ValidationFailed([{"loc": "to", "msg": "o novo nome é igual ao atual"}])
    if new in creds:
        raise deps.ValidationFailed([{"loc": "to", "msg": f"credencial '{new}' já existe"}])

    yaml_io.rename_key(creds, old, new)
    writes = [(deps.CREDS_FILE, yaml_io.dump_rt(y, data), MODE_600)]
    checks: list[tuple] = [(deps.CREDS_FILE, rev)]

    hosts_data, hosts_rev, hy = yaml_io.load_rt(deps.HOSTS_FILE)
    updated: list[dict] = []
    if hosts_data is not None:
        for section, kind in (("hosts", "host"), ("groups", "group")):
            for node_id, node in (hosts_data.get(section) or {}).items():
                if node and node.get("credential") == old:
                    node["credential"] = new
                    updated.append({"kind": kind, "id": node_id, "field": "credential"})
        if updated:
            writes.append((deps.HOSTS_FILE, yaml_io.dump_rt(hy, hosts_data), 0o644))
            checks.append((deps.HOSTS_FILE, hosts_rev))

    revs = yaml_io.write_many(writes, checks=checks)
    return {"renamed": {"from": old, "to": new}, "updated": updated, "rev": revs[deps.CREDS_FILE]}


# --------------------------------------------------------------------------- #
# Set/rotacionar segredo (encrypt-on-write; reusa o cofre)
# --------------------------------------------------------------------------- #
def set_secret(name: str, field: str, value: str, rev: str | None) -> dict:
    """Encripta `value` com a chave da sessão e grava via substituição textual.

    Cofre trancado => VaultLocked (423). Cofre não iniciado => VaultNotInitialized (409).
    O plaintext NUNCA persiste nem volta pro cliente.
    """
    from lib import vault, vault_session  # noqa: PLC0415
    from vault import cli  # reaproveita _set_field/_emit/_atomic_write

    text, current_rev, _ = yaml_io.read_text_meta(deps.CREDS_FILE)
    if rev is not None and rev != current_rev:
        raise deps.ConflictError(current_rev)
    import yaml as _yaml  # noqa: PLC0415
    data = _yaml.safe_load(text) if text.strip() else {}
    if name not in ((data or {}).get("credentials") or {}):
        raise KeyError(f"credencial '{name}' não existe")

    meta = vault.load_meta(data)              # levanta VaultNotInitialized se sem bloco vault:
    key = vault_session.get_session_key()     # levanta VaultLocked se trancado
    vault.verify_key(key, meta)               # garante que a chave bate com este cofre
    token = vault.encrypt_value(key, value)

    new_lines = cli._set_field(text.splitlines(), name, field, token)
    if new_lines is None:
        raise KeyError(f"bloco da credencial '{name}' não encontrado no arquivo")
    cli._atomic_write(deps.CREDS_FILE, "\n".join(new_lines) + "\n")  # 0600
    return get_credential(name)
