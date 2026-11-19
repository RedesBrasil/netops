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
    items:                       # id -> item do cofre
      claro-portal:
        title: Portal Claro
        template: login
        template_label: Login    # sobrevive se o template for apagado
        notes: ...
        values: {URL: https://..., Senha: "enc.v1:..."}
        created_by / created_at / updated_by / updated_at

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
    """Garante as 4 chaves de topo (arquivo ausente/vazio => modelo padrão)."""
    if not data:
        return default_doc()
    data.setdefault("version", VERSION)
    for k in ("fields", "templates", "items"):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return data


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
