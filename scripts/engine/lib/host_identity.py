"""Identidade dos hosts: IDs inteiros estritos e leitura compatível do inventário v1.

Somente metadados; este módulo nunca carrega credenciais nem acessa equipamentos.
"""
from __future__ import annotations

from lib import i18n

MAX_HOST_ID = 2**53 - 1


def require_host_id(value) -> int:
    """Valida sem converter strings, floats ou booleanos em identidade."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HOST_ID:
        raise ValueError(i18n.t("lib_host_identity.host_id_invalid"))
    return value


def identity_errors(data: dict) -> list[dict]:
    """Valida unicidade, contador e aliases, inclusive reservas de hosts excluídos."""
    errors = []

    def fail(loc, msg):
        errors.append({"loc": loc, "msg": msg})

    if not isinstance(data, dict):
        return [{"loc": "(raiz)", "msg": i18n.t("lib_host_identity.inventory_not_object")}]
    version = data.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 2):
        return [{"loc": "version", "msg": i18n.t("lib_host_identity.unknown_inventory_version")}]
    hosts = data.get("hosts", {} if version == 1 else [])
    if version == 1:
        if not isinstance(hosts, dict):
            fail("hosts", i18n.t("lib_host_identity.v1_needs_text_keys"))
        elif any(not isinstance(key, str) or not key for key in hosts):
            fail("hosts", i18n.t("lib_host_identity.legacy_keys_text"))
        elif any(not isinstance(host, dict) for host in hosts.values()):
            fail("hosts", i18n.t("lib_host_identity.each_host_object"))
        return errors
    if not isinstance(hosts, list):
        return [{"loc": "hosts", "msg": i18n.t("lib_host_identity.v2_needs_list")}]
    try:
        next_id = require_host_id(data.get("next_host_id"))
    except ValueError as exc:
        fail("next_host_id", str(exc))
        next_id = None
    seen = set()
    for index, host in enumerate(hosts):
        if not isinstance(host, dict):
            fail(f"hosts/{index}", i18n.t("lib_host_identity.host_not_object"))
            continue
        try:
            host_id = require_host_id(host.get("id"))
        except ValueError as exc:
            fail(f"hosts/{index}/id", str(exc))
            continue
        if host_id in seen:
            fail(f"hosts/{index}/id", i18n.t("lib_host_identity.duplicate_id"))
        seen.add(host_id)
        if next_id is not None and host_id >= next_id:
            fail("next_host_id", i18n.t("lib_host_identity.counter_too_low"))
    aliases = data.get("legacy_aliases", [])
    if not isinstance(aliases, list):
        fail("legacy_aliases", i18n.t("lib_host_identity.aliases_not_list"))
        return errors
    names = set()
    for index, item in enumerate(aliases):
        loc = f"legacy_aliases/{index}"
        if not isinstance(item, dict):
            fail(loc, i18n.t("lib_host_identity.alias_not_object"))
            continue
        alias = item.get("alias")
        if not isinstance(alias, str) or not alias:
            fail(loc + "/alias", i18n.t("lib_host_identity.alias_not_text"))
        elif alias in names:
            fail(loc + "/alias", i18n.t("lib_host_identity.duplicate_alias"))
        else:
            names.add(alias)
        try:
            host_id = require_host_id(item.get("host_id"))
            if next_id is not None and host_id >= next_id:
                fail(loc + "/host_id", i18n.t("lib_host_identity.alias_unallocated"))
        except ValueError as exc:
            fail(loc + "/host_id", str(exc))
    return errors


def host_index(data: dict) -> dict:
    """Índice efêmero: chaves int no v2, chaves legadas str somente no v1."""
    errors = identity_errors(data)
    if errors:
        raise ValueError("; ".join(f"{e['loc']}: {e['msg']}" for e in errors))
    if data.get("version", 1) == 1:
        return data.get("hosts") or {}
    return {host["id"]: host for host in data.get("hosts", [])}


def host_records(data: dict) -> list[dict]:
    """Registros com campo id; não altera o documento durante leitura."""
    return [{**host, "id": key} for key, host in host_index(data).items()]


def resolve_reference(reference, data: dict):
    """Inteiro seleciona ID; texto seleciona alias legado ou hostname único.

    Um alias reservado de host excluído nunca é redirecionado para outro hostname.
    Texto numérico continua sendo texto: `"42"` não seleciona automaticamente ID 42.
    """
    hosts = host_index(data)
    if isinstance(reference, int) and not isinstance(reference, bool):
        require_host_id(reference)
        if data.get("version", 1) == 2 and reference in hosts:
            return reference
        raise KeyError(i18n.t("lib_host_identity.host_id_not_found", ref=reference))
    if not isinstance(reference, str) or not reference:
        raise ValueError(i18n.t("lib_host_identity.use_int_or_name"))
    if data.get("version", 1) == 1 and reference in hosts:
        return reference
    for item in data.get("legacy_aliases", []):
        if item["alias"] == reference:
            if item["host_id"] not in hosts:
                raise KeyError(i18n.t("lib_host_identity.alias_reserved", ref=reference))
            return item["host_id"]
    matches = [key for key, host in hosts.items() if host.get("hostname") == reference]
    if not matches:  # hostname é gravado em MAIÚSCULAS; a referência textual aceita qualquer caixa
        matches = [key for key, host in hosts.items()
                   if str(host.get("hostname") or "").casefold() == reference.casefold()]
    if len(matches) > 1:
        raise ValueError(i18n.t("lib_host_identity.hostname_ambiguous", ref=reference))
    if matches:
        return matches[0]
    raise KeyError(i18n.t("lib_host_identity.host_not_found", ref=reference))
