#!/usr/bin/env python3
"""Núcleo criptográfico do cofre de credenciais do NetOps.

Funções PURAS — sem I/O de sessão, sem prompt, sem ler arquivos de sessão.
A persistência da chave na sessão fica em `lib/vault_session.py`; a CLI do
operador fica em `scripts/engine/vault/cli.py`.

API pública:
    derive_key(master_password, meta) -> bytes      # KDF (Argon2id; fallback Scrypt)
    build_meta(master_password) -> (meta, key)       # cria o bloco 'vault:' (salt + verifier)
    verify_key(key, meta) -> None                    # valida a senha-mestra (rápido, via verifier)
    encrypt_value(key, plaintext) -> "enc.v1:<token>"
    decrypt_value(key, value) -> plaintext
    is_encrypted(value) -> bool
    load_meta(creds_data) -> dict                    # extrai/valida o bloco 'vault:'

Não usa o módulo `secrets` da stdlib (evita sombreamento por pacotes do projeto);
a aleatoriedade vem de os.urandom.
"""
from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from lib import i18n

ENC_PREFIX = "enc.v1:"
VERIFIER_PLAINTEXT = "netops-vault-verifier-v1"
SALT_BYTES = 16

# Parâmetros padrão do Argon2id (OWASP-friendly; sub-segundo numa workstation).
ARGON2_DEFAULTS = {"iterations": 3, "memory_cost": 65536, "lanes": 4, "length": 32}
# Fallback para ambientes sem Argon2id (cryptography antigo).
SCRYPT_DEFAULTS = {"n": 2 ** 15, "r": 8, "p": 1, "length": 32}


# --------------------------------------------------------------------------- #
# Exceções
# --------------------------------------------------------------------------- #
class VaultError(Exception):
    """Erro genérico do cofre."""


class VaultLocked(VaultError):
    """Há segredos 'enc.v1:' mas nenhuma chave disponível na sessão."""

    def __init__(self, msg: str | None = None):
        super().__init__(
            msg
            or i18n.t("lib_vault.locked", cmd="cd /home/francisco/netops && .venv/bin/python3 scripts/engine/vault/cli.py unlock")
        )


class VaultWrongKey(VaultError):
    """Senha-mestra incorreta ou dado adulterado (HMAC do Fernet falhou)."""


class VaultNotInitialized(VaultError):
    """O arquivo não tem o bloco 'vault:' (rode 'init')."""

    def __init__(self, msg: str | None = None):
        super().__init__(
            msg
            or i18n.t("lib_vault.not_initialized", cmd="python3 scripts/engine/vault/cli.py init")
        )


# --------------------------------------------------------------------------- #
# Helpers de codificação
# --------------------------------------------------------------------------- #
def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _fernet(key: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(key))


# --------------------------------------------------------------------------- #
# KDF
# --------------------------------------------------------------------------- #
def derive_key(master_password: str, meta: dict) -> bytes:
    """Deriva a chave de 32 bytes a partir da senha-mestra e dos metadados.

    Função pura/determinística: mesmos (senha, meta) => mesma chave.
    """
    kdf = meta.get("kdf") or {}
    algo = kdf.get("algorithm")
    salt = _b64d(kdf["salt"])
    pw = master_password.encode("utf-8")

    if algo == "argon2id":
        return Argon2id(
            salt=salt,
            length=int(kdf.get("length", 32)),
            iterations=int(kdf["iterations"]),
            lanes=int(kdf["lanes"]),
            memory_cost=int(kdf["memory_cost"]),
        ).derive(pw)
    if algo == "scrypt":
        return Scrypt(
            salt=salt,
            length=int(kdf.get("length", 32)),
            n=int(kdf["n"]),
            r=int(kdf["r"]),
            p=int(kdf["p"]),
        ).derive(pw)
    raise VaultError(i18n.t("lib_vault.unknown_kdf", kdf=repr(algo)))


def _new_meta(algorithm: str = "argon2id") -> dict:
    salt = os.urandom(SALT_BYTES)
    if algorithm == "argon2id":
        kdf = {"algorithm": "argon2id", "salt": _b64e(salt), **ARGON2_DEFAULTS}
    elif algorithm == "scrypt":
        kdf = {"algorithm": "scrypt", "salt": _b64e(salt), **SCRYPT_DEFAULTS}
    else:
        raise VaultError(i18n.t("lib_vault.unsupported_kdf", kdf=repr(algorithm)))
    return {"version": 1, "kdf": kdf}


def build_meta(master_password: str, algorithm: str = "argon2id") -> tuple[dict, bytes]:
    """Cria um bloco 'vault:' novo (salt + verifier) e retorna (meta, chave_derivada)."""
    meta = _new_meta(algorithm)
    key = derive_key(master_password, meta)
    meta["verifier"] = encrypt_value(key, VERIFIER_PLAINTEXT)
    return meta, key


def verify_key(key: bytes, meta: dict) -> None:
    """Valida a chave contra o verifier. Levanta VaultWrongKey se a senha estiver errada."""
    verifier = meta.get("verifier")
    if not verifier:
        raise VaultNotInitialized(i18n.t("lib_vault.no_verifier"))
    if decrypt_value(key, verifier) != VERIFIER_PLAINTEXT:  # decrypt já levanta VaultWrongKey
        raise VaultWrongKey(i18n.t("lib_vault.wrong_master"))


# --------------------------------------------------------------------------- #
# Cifra de valor
# --------------------------------------------------------------------------- #
def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def encrypt_value(key: bytes, plaintext: str) -> str:
    token = _fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def decrypt_value(key: bytes, value: str) -> str:
    if not is_encrypted(value):
        return value
    token = value[len(ENC_PREFIX):].encode("ascii")
    try:
        return _fernet(key).decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise VaultWrongKey(i18n.t("lib_vault.wrong_master_or_corrupt")) from exc


# --------------------------------------------------------------------------- #
# Metadados
# --------------------------------------------------------------------------- #
def load_meta(creds_data: dict) -> dict:
    """Extrai e valida o bloco 'vault:' de um credentials.yaml já parseado."""
    meta = (creds_data or {}).get("vault")
    if not meta:
        raise VaultNotInitialized()
    if "kdf" not in meta or "verifier" not in meta:
        raise VaultNotInitialized(i18n.t("lib_vault.incomplete_block"))
    return meta
