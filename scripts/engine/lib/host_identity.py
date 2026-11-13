"""Identidade dos hosts: IDs inteiros estritos e leitura compatível do inventário v1.

Somente metadados; este módulo nunca carrega credenciais nem acessa equipamentos.
"""
from __future__ import annotations

MAX_HOST_ID = 2**53 - 1


def require_host_id(value) -> int:
    """Valida sem converter strings, floats ou booleanos em identidade."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HOST_ID:
        raise ValueError("ID de host precisa ser um inteiro positivo até 9007199254740991")
    return value


def identity_errors(data: dict) -> list[dict]:
    """Valida unicidade, contador e aliases, inclusive reservas de hosts excluídos."""
    errors = []

    def fail(loc, msg):
        errors.append({"loc": loc, "msg": msg})

    if not isinstance(data, dict):
        return [{"loc": "(raiz)", "msg": "inventário precisa ser um objeto"}]
    version = data.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 2):
        return [{"loc": "version", "msg": "versão de inventário desconhecida"}]
    hosts = data.get("hosts", {} if version == 1 else [])
    if version == 1:
        if not isinstance(hosts, dict):
            fail("hosts", "inventário v1 precisa de hosts por chave textual")
        elif any(not isinstance(key, str) or not key for key in hosts):
            fail("hosts", "chaves legadas precisam ser texto não vazio")
        elif any(not isinstance(host, dict) for host in hosts.values()):
            fail("hosts", "cada host precisa ser um objeto")
        return errors
    if not isinstance(hosts, list):
        return [{"loc": "hosts", "msg": "inventário v2 precisa de uma lista de hosts"}]
    try:
        next_id = require_host_id(data.get("next_host_id"))
    except ValueError as exc:
        fail("next_host_id", str(exc))
        next_id = None
    seen = set()
    for index, host in enumerate(hosts):
        if not isinstance(host, dict):
            fail(f"hosts/{index}", "host precisa ser um objeto")
            continue
        try:
            host_id = require_host_id(host.get("id"))
        except ValueError as exc:
            fail(f"hosts/{index}/id", str(exc))
            continue
        if host_id in seen:
            fail(f"hosts/{index}/id", "ID duplicado")
        seen.add(host_id)
        if next_id is not None and host_id >= next_id:
            fail("next_host_id", "contador deve estar acima de todos os IDs já alocados")
    aliases = data.get("legacy_aliases", [])
    if not isinstance(aliases, list):
        fail("legacy_aliases", "aliases precisam ser uma lista")
        return errors
    names = set()
    for index, item in enumerate(aliases):
        loc = f"legacy_aliases/{index}"
        if not isinstance(item, dict):
            fail(loc, "alias precisa ser um objeto")
            continue
        alias = item.get("alias")
        if not isinstance(alias, str) or not alias:
            fail(loc + "/alias", "alias precisa ser texto não vazio")
        elif alias in names:
            fail(loc + "/alias", "alias duplicado")
        else:
            names.add(alias)
        try:
            host_id = require_host_id(item.get("host_id"))
            if next_id is not None and host_id >= next_id:
                fail(loc + "/host_id", "alias aponta para ID ainda não alocado")
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
        raise KeyError(f"host ID {reference} não está em network/hosts.yaml")
    if not isinstance(reference, str) or not reference:
        raise ValueError("use um ID inteiro ou um nome/alias textual")
    if data.get("version", 1) == 1 and reference in hosts:
        return reference
    for item in data.get("legacy_aliases", []):
        if item["alias"] == reference:
            if item["host_id"] not in hosts:
                raise KeyError(f"alias '{reference}' reservado para host excluído")
            return item["host_id"]
    matches = [key for key, host in hosts.items() if host.get("hostname") == reference]
    if not matches:  # hostname é gravado em MAIÚSCULAS; a referência textual aceita qualquer caixa
        matches = [key for key, host in hosts.items()
                   if str(host.get("hostname") or "").casefold() == reference.casefold()]
    if len(matches) > 1:
        raise ValueError(f"hostname '{reference}' ambíguo; informe o ID inteiro")
    if matches:
        return matches[0]
    raise KeyError(f"host '{reference}' não está em network/hosts.yaml")
