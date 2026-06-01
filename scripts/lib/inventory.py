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
    python scripts/lib/inventory.py --validate
    python scripts/lib/inventory.py --list
    python scripts/lib/inventory.py --show rt-core-01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NETOPS_ROOT = Path(__file__).resolve().parents[2]
HOSTS_FILE = NETOPS_ROOT / "network" / "hosts.yaml"
CREDS_FILE = NETOPS_ROOT / "network" / "credentials.yaml"
SCHEMA_FILE = NETOPS_ROOT / "core" / "schemas" / "inventory.schema.json"


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
    via 'python scripts/vault/cli.py unlock'). Cofre trancado -> levanta VaultLocked com
    instrução clara. Migrar para criptografia altera SÓ esta função — os hosts não mudam.
    """
    if not isinstance(value, str) or not value.startswith("enc.v1:"):
        return value
    # Imports preguiçosos; garante scripts/ no sys.path mesmo se inventory.py rodar direto.
    scripts_dir = str(Path(__file__).resolve().parents[1])
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from lib.vault import decrypt_value  # noqa: PLC0415
    from lib.vault_session import get_session_key  # noqa: PLC0415
    return decrypt_value(get_session_key(), value)  # get_session_key levanta VaultLocked


def load_inventory() -> tuple[dict, dict]:
    """Lê hosts.yaml e credentials.yaml. credentials.yaml ausente => credenciais vazias."""
    yaml = _require_yaml()
    if not HOSTS_FILE.exists():
        sys.exit(f"ERRO: inventário não encontrado: {HOSTS_FILE}")
    hosts_data = yaml.safe_load(HOSTS_FILE.read_text(encoding="utf-8")) or {}
    creds_data = {}
    if CREDS_FILE.exists():
        creds_data = yaml.safe_load(CREDS_FILE.read_text(encoding="utf-8")) or {}
    return hosts_data, creds_data


def list_hosts(hosts_data: dict) -> list[str]:
    """Nomes de todos os hosts do inventário."""
    return sorted((hosts_data.get("hosts") or {}).keys())


def resolve_host(name: str, hosts_data: dict, creds_data: dict, decrypt: bool = True) -> tuple[dict, dict]:
    """Retorna (host_resolvido, credencial_resolvida).

    O host herda os campos do seu 'group'; campos definidos no host vencem.

    decrypt=True (padrão): descriptografa segredos 'enc.v1:' (exige cofre destrancado) —
        usado pelos scripts de acesso que vão conectar.
    decrypt=False: não descriptografa (deixa os valores como estão) — usado por operações
        que não conectam (--validate / --list / --show), para funcionarem com o cofre trancado.
    """
    hosts = hosts_data.get("hosts") or {}
    if name not in hosts:
        raise KeyError(f"host '{name}' não está em network/hosts.yaml")

    host = dict(hosts[name])
    group_name = host.get("group")
    group = (hosts_data.get("groups") or {}).get(group_name, {}) if group_name else {}

    merged = {**group, **host}
    # 'access' é aninhado: mescla chave a chave (host vence).
    if group.get("access") or host.get("access"):
        merged["access"] = {**(group.get("access") or {}), **(host.get("access") or {})}
    merged["name"] = name

    cred_name = merged.get("credential")
    cred_raw = (creds_data.get("credentials") or {}).get(cred_name, {}) if cred_name else {}
    if decrypt:
        cred = {k: (resolve_secret(v) if isinstance(v, str) else v) for k, v in cred_raw.items()}
    else:
        cred = dict(cred_raw)

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

    hosts_data = yaml.safe_load(HOSTS_FILE.read_text(encoding="utf-8")) or {}
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(hosts_data), key=str):
        loc = "/".join(str(p) for p in err.absolute_path) or "(raiz)"
        errors.append(f"{loc}: {err.message}")

    # Checagem pós-herança: cada host precisa de vendor + access + credential resolvidos.
    creds_data = {}
    if CREDS_FILE.exists():
        creds_data = yaml.safe_load(CREDS_FILE.read_text(encoding="utf-8")) or {}
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

    hosts_data, creds_data = load_inventory()

    if args.list:
        for name in list_hosts(hosts_data):
            host, _ = resolve_host(name, hosts_data, creds_data, decrypt=False)
            acc = host.get("access", {})
            print(f"  {name:16s} {host.get('mgmt_ip',''):16s} "
                  f"{host.get('vendor',''):10s} {acc.get('method','')}:{acc.get('port','')}")
        return 0

    if args.show:
        host, cred = resolve_host(args.show, hosts_data, creds_data, decrypt=False)
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
