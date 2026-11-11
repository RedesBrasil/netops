"""Contratos locais de distribuição, caminhos e estado privado (somente stdlib)."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath

REPOSITORY = "RedesBrasil/netops"
PROTOCOL = 1
STATE_DIR = ".netops-update"
MAX_PACKAGE = 256 * 1024 * 1024
MAX_UNPACKED = 512 * 1024 * 1024
MAX_FILES = 10000
CUSTOM_ROOTS = {"agents", "workflows", "best-practices", "config-examples", "planning-examples"}
DIST_ROOTS = CUSTOM_ROOTS | {"scripts", "core", "network", ".github"}
DIST_FILES = {"README.md", "CLAUDE.md", "PADRAO.md", "constitution.md", "requirements.txt", ".gitignore", "CHANGELOG.md"}
TERMINAL_STATES = {"completed", "failed", "rolled_back", "recovery_failed"}


class UpdateError(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(detail)


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise UpdateError("invalid_version", "Versão estável inválida; use X.Y.Z.")
    return tuple(map(int, value.removeprefix("v").split(".")))


def read_version(root: Path) -> str:
    text = (root / "core/config/core-config.yaml").read_text(encoding="utf-8")
    match = re.search(r'^  version: [\"\']([0-9]+\.[0-9]+\.[0-9]+)[\"\']\s*$', text, re.M)
    if not match:
        raise UpdateError("invalid_version", "Versão central ausente ou inválida.")
    version_tuple(match[1])
    return match[1]


def safe_relative(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or any(ord(c) < 32 for c in value)):
        raise UpdateError("unsafe_path", "Caminho inválido no pacote.")
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise UpdateError("unsafe_path", "Caminho fora do escopo permitido.")
    return value


def distributed(path: str) -> bool:
    safe_relative(path)
    parts = PurePosixPath(path).parts
    if path in DIST_FILES:
        return True
    if parts[:2] == (".claude", "commands"):
        return len(parts) == 3 and parts[-1].endswith(".md")
    if parts[0] not in DIST_ROOTS:
        return False
    if any(p in {"node_modules", "__pycache__", ".pytest_cache", ".venv"} for p in parts):
        return False
    if any(p.startswith(".") for p in parts[1:]):
        return False
    if path.startswith("scripts/analysis/") or path == "core/config/project-config.yaml":
        return False
    if parts[0] == "network":
        return len(parts) == 2 and (path.endswith(".example.yaml") or parts[-1] == "PADRAO.md")
    name = parts[-1].lower()
    return not (name.endswith((".pyc", ".pyo", ".log", ".orig", ".bak", ".env"))
                or ".bak." in name or ".bak-" in name or name in {".dev.vars", "build-meta.json"})


def customizable(path: str) -> bool:
    return path.split("/", 1)[0] in CUSTOM_ROOTS or path.startswith("scripts/tools/") or path.startswith(".claude/commands/")


def target_path(root: Path, rel: str) -> Path:
    safe_relative(rel)
    current = root
    for part in PurePosixPath(rel).parts:
        current = current / part
        if current.is_symlink():
            raise UpdateError("symlink", "Um caminho gerenciado contém link simbólico: " + rel)
    return current


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def private_dir(path: Path) -> Path:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise UpdateError("unsafe_state", "Diretório privado não pode conter links no caminho.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
        raise UpdateError("unsafe_state", "Diretório privado pertence a outro usuário.")
    os.chmod(path, 0o700)
    return path


def atomic_bytes(path: Path, content: bytes, mode: int = 0o600) -> None:
    fd, temp = tempfile.mkstemp(prefix=".netops-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path: Path, value: dict) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    if path.is_symlink():
        raise UpdateError("unsafe_state", "Arquivo de estado não pode ser um link.")
    return json.loads(path.read_text(encoding="utf-8"))


@contextlib.contextmanager
def installation_lock(root: Path):
    directory = private_dir(root / STATE_DIR)
    fd = os.open(directory / "update.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError("busy", "Já existe uma atualização em andamento.") from None
        yield directory
    finally:
        os.close(fd)
