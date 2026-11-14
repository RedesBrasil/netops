#!/usr/bin/env python3
"""Carrega e resolve o inventário do NetOps (network/hosts.yaml + credentials.yaml).

Responsabilidades:
  - Ler hosts.yaml e credentials.yaml.
  - Resolver a herança de grupo (campos do grupo herdados pelo host).
  - Resolver a credencial nomeada de cada host.
  - resolve_secret(): PONTO ÚNICO de descriptografia (segredos 'enc.v1:' do cofre).
  - Validar hosts.yaml contra core/schemas/inventory.schema.json.

Uso como biblioteca:
    from lib.inventory import load_inventory, resolve_host, list_hosts

Uso como CLI:
    python3 scripts/engine/lib/inventory.py --validate
    python3 scripts/engine/lib/inventory.py --list
    python3 scripts/engine/lib/inventory.py --show rt-core-01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto

NETOPS_ROOT = Path(__file__).resolve().parents[3]
HOSTS_FILE = NETOPS_ROOT / "network" / "hosts.yaml"
CREDS_FILE = NETOPS_ROOT / "network" / "credentials.yaml"
SCHEMA_FILE = NETOPS_ROOT / "core" / "schemas" / "inventory.schema.json"


# Padrão de cadastro: tudo em MAIÚSCULAS, exceto site e notes (livres).
UPPER_NODE_FIELDS = ("hostname", "model", "os", "os_version", "version", "vendor", "role", "credential", "group")
ENUM_FIELDS = ("vendor", "role")  # + access.method; os scripts consomem em minúsculas (canônico)


def upper_value(value):
    return value.strip().upper() if isinstance(value, str) else value


def normalize_node_fields(fields: dict) -> dict:
    """Devolve cópia de `fields` (host/grupo) com o padrão MAIÚSCULAS aplicado."""
    out = dict(fields)
    for key in UPPER_NODE_FIELDS:
        if key in out:
            out[key] = upper_value(out[key])
    if isinstance(out.get("access"), dict) and isinstance(out["access"].get("method"), str):
        out["access"] = {**out["access"], "method": upper_value(out["access"]["method"])}
    if "extra_access" in out:  # método/credencial em MAIÚSCULAS; chaves vazias somem; lista vazia => None
        items = []
        for item in (out["extra_access"] or []):
            item = {k: v for k, v in item.items() if v not in (None, "")}
            for k in ("method", "credential"):
                if k in item:
                    item[k] = upper_value(item[k])
            items.append(item)
        out["extra_access"] = items or None
    if "apps" in out:  # aplicações: nome/versão em MAIÚSCULAS; sem nome = descartada; lista vazia => None
        items = []
        for item in (out["apps"] or []):
            item = {k: upper_value(v) for k, v in dict(item).items() if v not in (None, "")}
            item = {k: v for k, v in item.items() if v != ""}
            if item.get("name"):
                items.append(item)
        out["apps"] = items or None
    if "extra_ips" in out:  # remove chaves vazias; lista vazia => None (a chave some do YAML)
        items = [{k: v for k, v in item.items() if v not in (None, "")} for item in (out["extra_ips"] or [])]
        out["extra_ips"] = items or None
    return out


def lookup_ci(mapping, key):
    """mapping[key] tolerando diferença de caixa (exato primeiro)."""
    if not mapping or key is None:
        return None
    if key in mapping:
        return mapping[key]
    folded = str(key).casefold()
    for k, v in mapping.items():
        if str(k).casefold() == folded:
            return v
    return None


def canonical_enums(node: dict) -> dict:
    """Minúsculas p/ vendor/role/access.method — contrato interno dos scripts e do schema."""
    out = dict(node)
    for key in ENUM_FIELDS:
        if isinstance(out.get(key), str):
            out[key] = out[key].lower()
    if isinstance(out.get("access"), dict) and isinstance(out["access"].get("method"), str):
        out["access"] = {**out["access"], "method": out["access"]["method"].lower()}
    if isinstance(out.get("extra_access"), list):
        out["extra_access"] = [{**i, "method": i["method"].lower()} if isinstance(i, dict) and isinstance(i.get("method"), str) else i
                               for i in out["extra_access"]]
    return out


def schema_view(hosts_data: dict) -> dict:
    """Cópia do inventário com enums em minúsculas, só para validar contra o JSON Schema."""
    data = dict(hosts_data)
    if isinstance(data.get("groups"), dict):
        data["groups"] = {k: canonical_enums(v) if isinstance(v, dict) else v for k, v in data["groups"].items()}
    if isinstance(data.get("hosts"), list):
        data["hosts"] = [canonical_enums(h) if isinstance(h, dict) else h for h in data["hosts"]]
    elif isinstance(data.get("hosts"), dict):
        data["hosts"] = {k: canonical_enums(v) if isinstance(v, dict) else v for k, v in data["hosts"].items()}
    return data


def _require_yaml():
    try:
        import yaml  # noqa: PLC0415
        return yaml
    except ImportError:
        sys.exit("ERRO: PyYAML não instalado. Rode: pip install -r requirements.txt")


def resolve_secret(value):
    """Resolve o valor de um segredo.

    Texto puro -> retorna como está (compatível com arquivos não migrados/mistos).
    'enc.v1:<token>' -> descriptografa EM MEMÓRIA com a chave da sessão (cofre destrancado
    via 'python3 scripts/engine/vault/cli.py unlock'). Cofre trancado -> levanta VaultLocked com
    instrução clara. Migrar para criptografia altera SÓ esta função — os hosts não mudam.
    """
    if not isinstance(value, str) or not value.startswith("enc.v1:"):
        return value
    # Imports preguiçosos; garante scripts/engine/ no sys.path mesmo se inventory.py rodar direto.
    engine_dir = str(Path(__file__).resolve().parents[1])
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    from lib.vault import decrypt_value  # noqa: PLC0415
    from lib.vault_session import get_session_key  # noqa: PLC0415
    return decrypt_value(get_session_key(), value)  # get_session_key levanta VaultLocked


def load_inventory(*, include_credentials: bool = True) -> tuple[dict, dict]:
    """Lê hosts.yaml e credentials.yaml. credentials.yaml ausente => credenciais vazias."""
    yaml = _require_yaml()
    from lib.inventory_lock import ensure_migration_complete, inventory_lock
    with inventory_lock(HOSTS_FILE.parent):
        ensure_migration_complete(HOSTS_FILE.parent)
        if not HOSTS_FILE.exists():
            sys.exit(f"ERRO: inventário não encontrado: {HOSTS_FILE}")
        hosts_data = yaml.safe_load(HOSTS_FILE.read_text(encoding="utf-8")) or {}
        creds_data = {}
        if include_credentials and CREDS_FILE.exists():
            creds_data = yaml.safe_load(CREDS_FILE.read_text(encoding="utf-8")) or {}
    return hosts_data, creds_data


def list_hosts(hosts_data: dict) -> list[int | str]:
    """IDs inteiros no v2; chaves legadas durante leitura de inventário v1."""
    from lib.host_identity import host_index
    return sorted(host_index(hosts_data))


def resolve_host(name: int | str, hosts_data: dict, creds_data: dict, decrypt: bool = True,
                 lowercase_enums: bool = True) -> tuple[dict, dict]:
    """Retorna (host_resolvido, credencial_resolvida).

    O host herda os campos do seu 'group'; campos definidos no host vencem.

    decrypt=True (padrão): descriptografa segredos 'enc.v1:' (exige cofre destrancado) —
        usado pelos scripts de acesso que vão conectar.
    lowercase_enums=True (padrão): vendor/role/access.method em minúsculas, o contrato dos scripts
        (o inventário guarda MAIÚSCULAS). A UI passa False para exibir o valor gravado.
    decrypt=False: não descriptografa (deixa os valores como estão) — usado por operações
        que não conectam (--validate / --list / --show), para funcionarem com o cofre trancado.
    """
    from lib.host_identity import host_index, resolve_reference
    canonical = resolve_reference(name, hosts_data)
    host = dict(host_index(hosts_data)[canonical])
    group_name = host.get("group")
    group = (lookup_ci(hosts_data.get("groups") or {}, group_name) or {}) if group_name else {}

    merged = {**group, **host}
    # 'access' é aninhado: mescla chave a chave (host vence).
    if group.get("access") or host.get("access"):
        merged["access"] = {**(group.get("access") or {}), **(host.get("access") or {})}
    merged["name"] = canonical
    if hosts_data.get("version") == 2:
        merged["id"] = canonical

    cred_name = merged.get("credential")
    cred_raw = (lookup_ci(creds_data.get("credentials") or {}, cred_name) or {}) if cred_name else {}
    if decrypt:
        cred = {k: (resolve_secret(v) if isinstance(v, str) else v) for k, v in cred_raw.items()}
    else:
        cred = dict(cred_raw)

    if lowercase_enums:
        merged = canonical_enums(merged)
    return merged, cred


def validate() -> tuple[bool, list[str]]:
    """Valida hosts.yaml contra o JSON Schema. Retorna (ok, lista_de_erros)."""
    yaml = _require_yaml()
    errors: list[str] = []
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        return False, ["jsonschema não instalado (pip install -r requirements.txt)"]

    if not SCHEMA_FILE.exists():
        return False, [f"schema não encontrado: {SCHEMA_FILE}"]

    hosts_data, _ = load_inventory(include_credentials=False)
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(schema_view(hosts_data)), key=str):
        loc = "/".join(str(p) for p in err.absolute_path) or "(raiz)"
        errors.append(f"{loc}: {err.message}")

    from lib.host_identity import identity_errors
    identity = identity_errors(hosts_data)
    errors.extend(f"{error['loc']}: {error['msg']}" for error in identity)
    if identity:
        return False, errors
    # Validação de metadados não precisa abrir o arquivo de credenciais.
    creds_data = {}
    for name in list_hosts(hosts_data):
        try:
            host, _ = resolve_host(name, hosts_data, creds_data, decrypt=False)
        except KeyError as exc:
            errors.append(str(exc))
            continue
        for field in ("vendor", "credential"):
            if not host.get(field):
                errors.append(f"hosts/{name}: campo '{field}' ausente (nem no host nem no grupo)")
        if not (host.get("access") or {}).get("method"):
            errors.append(f"hosts/{name}: 'access.method' ausente")

    return (not errors), errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Carrega/valida o inventário do NetOps.")
    parser.add_argument("--validate", action="store_true", help="Valida hosts.yaml contra o schema")
    parser.add_argument("--list", action="store_true", help="Lista os hosts do inventário")
    parser.add_argument("--show", metavar="HOST", help="Mostra um host resolvido (sem senha)")
    parser.add_argument("--show-id", type=int, metavar="ID", help="Mostra um host pelo ID inteiro")
    args = parser.parse_args()

    if args.validate:
        ok, errors = validate()
        if ok:
            print("OK — inventário válido.")
            return 0
        print("INVÁLIDO:")
        for e in errors:
            print(f"  - {e}")
        return 1

    hosts_data, creds_data = load_inventory(include_credentials=False)

    if args.list:
        for name in list_hosts(hosts_data):
            host, _ = resolve_host(name, hosts_data, creds_data, decrypt=False)
            acc = host.get("access", {})
            print(f"  {str(name):16s} {host.get('mgmt_ip',''):16s} "
                  f"{host.get('vendor',''):10s} {acc.get('method','')}:{acc.get('port','')}")
        return 0

    if args.show or args.show_id is not None:
        reference = args.show_id if args.show_id is not None else args.show
        host, cred = resolve_host(reference, hosts_data, creds_data, decrypt=False)
        safe_cred = {
            k: ("***" if k in ("password", "secret") or (isinstance(v, str) and v.startswith("enc.v1:")) else v)
            for k, v in cred.items()
        }
        print(json.dumps({"host": host, "credential": safe_cred}, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
