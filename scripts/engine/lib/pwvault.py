#!/usr/bin/env python3
"""Cofre de senhas — armazenamento de network/vault.yaml (segredos que NÃO são de host).

Credenciais de host (acesso a equipamento) seguem em network/credentials.yaml. Aqui ficam logins de
portais, chaves de API, tokens etc., para PESSOAS consultarem pelo console (menu Cofre de senhas).

Estrutura do arquivo (gerido pelo console; não editar à mão):

    version: 1
    fields:                      # catálogo de campos reutilizáveis (nome -> tipo)
      Senha: {kind: secret}
      URL: {kind: text}
    templates:                   # id -> rótulo + campos (obrigatório/visível são POR template)
      login:
        label: Login
        description: ...
        fields:
          - {field: URL, required: false, visible: true}
          - {field: Senha, required: true, visible: false}
    next_item_id: 2              # próximo ID numérico de item (nunca reutilizado)
    items:                       # ID numérico (estável) -> item do cofre
      1:
        title: Portal Claro
        aliases: [claro-portal]  # IDs antigos (slug) que continuam resolvendo em referências
        template: login
        template_label: Login    # sobrevive se o template for apagado
        notes: ...
        values: {URL: https://..., Senha: "enc.v1:..."}
        created_by / created_at / updated_by / updated_at

Referência (scripts/tools/secrets/run.py): `nvault://<ID>/<campo-em-slug>`. O ID do item é NUMÉRICO e não muda
quando o título muda; o slug antigo de cada item (formato anterior) fica em `aliases`. Campo renomeado guarda o
nome antigo em `fields.<nome>.aliases`, para referências antigas continuarem valendo.

Criptografia: campo `secret` é gravado como `enc.v1:` com a MESMA chave do cofre de credentials.yaml
(lib/vault.encrypt_value + chave da sessão destrancada). Campo `text` fica em claro.
`vault/cli.py change-password` re-cifra este arquivo junto (reencrypt_file).

INEGOCIÁVEL: a IA nunca lê/decifra valores deste arquivo (constitution.md §V).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

VERSION = 1
KINDS = ("secret", "text")
FILE_NAME = "vault.yaml"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FIELD_NAME_MAX = 60
RESERVED_IDS = {"new", "templates", "fields"}   # segmentos de URL do console (#vault/templates…)

DEFAULT_FIELDS = {
    "URL": {"kind": "text"},
    "Usuário": {"kind": "text"},
    "Senha": {"kind": "secret"},
    "API key": {"kind": "secret"},
    "Token": {"kind": "secret"},
}
DEFAULT_TEMPLATES = {
    "login": {"label": "Login", "description": "Usuário e senha de um sistema ou portal.",
              "fields": [{"field": "URL", "required": False, "visible": True},
                         {"field": "Usuário", "required": True, "visible": True},
                         {"field": "Senha", "required": True, "visible": False}]},
    "api": {"label": "API", "description": "Endereço e chave de uma API.",
            "fields": [{"field": "URL", "required": False, "visible": True},
                       {"field": "API key", "required": True, "visible": False}]},
}


def default_doc() -> dict:
    import copy  # noqa: PLC0415
    return {"version": VERSION, "fields": copy.deepcopy(DEFAULT_FIELDS),
            "templates": copy.deepcopy(DEFAULT_TEMPLATES), "items": {}}


def normalize(data: dict | None) -> dict:
    """Garante as chaves de topo (arquivo ausente/vazio => modelo padrão) e migra IDs de item em slug para
    numéricos (o slug vira apelido em `aliases`). Só em memória; grava na próxima escrita."""
    if not data:
        return default_doc() | {"next_item_id": 1}
    data.setdefault("version", VERSION)
    for k in ("fields", "templates", "items"):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    items, nums = data["items"], [k for k in data["items"] if _as_int(k) is not None]
    nxt = max([int(data.get("next_item_id") or 1)] + [_as_int(k) + 1 for k in nums])
    if len(nums) != len(items):
        new: dict = {}
        for k, it in items.items():
            n = _as_int(k)
            it = it or {}
            if n is None:
                n, nxt = nxt, nxt + 1
                it["aliases"] = sorted(set((it.get("aliases") or []) + [str(k)]))
            new[n] = it
        data["items"] = dict(sorted(new.items()))
    else:
        data["items"] = {_as_int(k): v for k, v in items.items()}
    data["next_item_id"] = nxt
    return data


def _as_int(k) -> int | None:
    if isinstance(k, bool):
        return None
    if isinstance(k, int):
        return k
    return int(k) if isinstance(k, str) and k.isdigit() else None


def find_item(data: dict, ref) -> int | None:
    """ID numérico do item por número ("3"/3) ou apelido (slug antigo); None se não existe."""
    n = _as_int(ref)
    if n is not None:
        return n if n in data["items"] else None
    ref = str(ref or "").strip().lower()
    for k, it in data["items"].items():
        if ref in [str(a).lower() for a in (it or {}).get("aliases") or []]:
            return k
    return None


def new_item_id(data: dict) -> int:
    n = int(data.get("next_item_id") or 1)
    while n in data["items"]:
        n += 1
    data["next_item_id"] = n + 1
    return n


def find_value_name(data: dict, item: dict, ref_field: str) -> str | None:
    """Nome do campo com valor no item: slug do nome atual, nome exato ou apelido (nome antigo) do campo."""
    want = slugify(str(ref_field).replace("%20", " "))
    names = list((item or {}).get("values") or {})
    for name in names:
        if slugify(name) == want or name.casefold() == str(ref_field).casefold():
            return name
    for name in names:
        for alias in ((data["fields"].get(name) or {}).get("aliases") or []):
            if slugify(alias) == want:
                return name
    return None


def load(path: Path) -> tuple[dict, str]:
    """(dados normalizados, texto bruto). Nunca decifra."""
    import yaml  # noqa: PLC0415
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    data = yaml.safe_load(text) if text.strip() else None
    return normalize(data), text


def dump(data: dict) -> str:
    import yaml  # noqa: PLC0415
    head = ("# Cofre de senhas do NetOps — gerido pelo console (menu Cofre de senhas). NÃO editar à mão.\n"
            "# Campos 'secret' ficam cifrados (enc.v1:) com a chave do cofre de credentials.yaml.\n")
    return head + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096)


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48].strip("-") or "item"


def unique_id(base: str, taken) -> str:
    base = slugify(base)
    if base in RESERVED_IDS:
        base = f"{base}-1"
    cand, n = base, 2
    while cand in taken:
        cand, n = f"{base}-{n}", n + 1
    return cand


def field_key(fields: dict, name: str) -> str | None:
    """Nome real do campo no catálogo (comparação sem caixa); None se não existe."""
    folded = str(name or "").strip().casefold()
    for k in fields:
        if str(k).casefold() == folded:
            return k
    return None


def reencrypt_file(path: Path, old_key: bytes, new_key: bytes) -> tuple[str | None, int]:
    """Texto novo do arquivo com todos os enc.v1: re-cifrados (None se o arquivo não existe)."""
    from lib import vault  # noqa: PLC0415
    if not path.exists():
        return None, 0
    data, _ = load(path)
    count = 0
    for item in data["items"].values():
        values = (item or {}).get("values") or {}
        for k, v in list(values.items()):
            if vault.is_encrypted(v):
                values[k] = vault.encrypt_value(new_key, vault.decrypt_value(old_key, v))
                count += 1
    return dump(data), count
