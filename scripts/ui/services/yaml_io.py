#!/usr/bin/env python3
"""I/O de arquivos da UI: round-trip YAML (preserva comentários), escrita atômica,
backups e concorrência otimista (hash sha256).

Princípios:
  - LEITURA estrutural via ruamel round-trip (mantém comentários/ordem/aspas).
  - ESCRITA atômica (tmp + os.replace), com modo de permissão configurável
    (0600 p/ credentials.yaml). Mesmo padrão do scripts/vault/cli.py:_atomic_write.
  - CONCORRÊNCIA: o cliente guarda o sha256 do conteúdo (`rev`); antes de gravar a
    gente relê e compara — divergiu => ConflictError (409).
"""
from __future__ import annotations

import hashlib
import os
import time
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

import deps

MAX_BACKUPS = 10


# --------------------------------------------------------------------------- #
# Hash / metadados
# --------------------------------------------------------------------------- #
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text_meta(path: Path) -> tuple[str, str, int]:
    """Retorna (texto, sha256, mtime_ns). Arquivo ausente => ('', hash do vazio, 0)."""
    if not path.exists():
        text = ""
        return text, sha256_text(text), 0
    text = path.read_text(encoding="utf-8")
    return text, sha256_text(text), path.stat().st_mtime_ns


def file_rev(path: Path) -> str:
    """sha256 atual do arquivo (o token de concorrência)."""
    _, h, _ = read_text_meta(path)
    return h


def check_rev(path: Path, expected: str | None) -> None:
    """Levanta ConflictError se o arquivo mudou desde que o cliente leu (`expected`)."""
    current = file_rev(path)
    if expected is not None and expected != current:
        raise deps.ConflictError(current)


# --------------------------------------------------------------------------- #
# ruamel round-trip
# --------------------------------------------------------------------------- #
def _yaml() -> YAML:
    y = YAML()  # typ='rt' por padrão — preserva comentários, ordem e aspas
    y.preserve_quotes = True
    y.width = 4096            # não quebra linhas longas (tokens enc.v1:, descrições)
    y.indent(mapping=2, sequence=4, offset=2)   # estilo do projeto: "  - item"
    return y


def load_rt(path: Path):
    """Lê o YAML em modo round-trip. Retorna (data, rev, yaml_engine).

    data é None se o arquivo estiver ausente/vazio (o chamador decide o esqueleto).
    """
    text, rev, _ = read_text_meta(path)
    y = _yaml()
    data = y.load(text) if text.strip() else None
    return data, rev, y


def dump_rt(y: YAML, data) -> str:
    buf = StringIO()
    y.dump(data, buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Escrita atômica + backup
# --------------------------------------------------------------------------- #
def atomic_write(path: Path, text: str, mode: int = 0o644, backup: bool = False) -> str:
    """Escreve atomicamente (tmp + replace). Retorna o novo sha256.

    mode: 0o600 p/ credentials.yaml (e backups dela). backup=True guarda <path>.bak.<ts>.
    """
    if backup and path.exists():
        _make_backup(path, mode)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, mode)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))
    if mode != 0o644:  # garante o modo mesmo se o arquivo já existia com outro
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    return sha256_text(text)


def write_rt(path: Path, y: YAML, data, *, expected: str | None, mode: int = 0o644,
             backup: bool = False) -> str:
    """check_rev -> dump round-trip -> atomic_write. Retorna o novo rev."""
    check_rev(path, expected)
    text = dump_rt(y, data)
    return atomic_write(path, text, mode=mode, backup=backup)


def write_text(path: Path, text: str, *, expected: str | None, mode: int = 0o644,
               backup: bool = False) -> str:
    check_rev(path, expected)
    return atomic_write(path, text, mode=mode, backup=backup)


def _make_backup(path: Path, mode: int) -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(f"{path.name}.bak.{ts}")
    try:
        bak.write_bytes(path.read_bytes())
        os.chmod(bak, mode)
    except OSError:
        return
    # Mantém só os últimos MAX_BACKUPS
    backups = sorted(path.parent.glob(f"{path.name}.bak.*"))
    for old in backups[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass
