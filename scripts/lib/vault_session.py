#!/usr/bin/env python3
"""Cache da chave derivada do cofre — vive só em RAM, durante a sessão.

Modo padrão (cache): a chave derivada (NUNCA a senha) é gravada num arquivo 0600
em tmpfs (`$XDG_RUNTIME_DIR/netops/session.key`). Funciona entre processos — então
serve tanto pro operador humano quanto pros agentes de IA, que rodam cada comando
num shell novo. Re-bloqueio por inatividade (TTL deslizante), no `lock`, ou no logout
(tmpfs é destruído pelo logind).

Modo terminal-puro (env var): se `NETOPS_VAULT_KEY` estiver setada no ambiente, ela é
usada — vida = vida do shell ("fechou o terminal, trancou"). Não funciona quando a IA
executa os scripts (cada comando é um shell novo).

API pública:
    get_session_key() -> bytes        # cache -> env -> levanta VaultLocked
    set_session_key(key, ttl=None)    # grava o cache (modo unlock)
    clear_session()                   # apaga o cache (modo lock)
    session_status() -> dict          # estado, sem nunca expor a chave
    encode_key(key) / decode_key(s)   # base64 p/ a env var do modo --env
"""
from __future__ import annotations

import base64
import os
import stat
import struct
import tempfile
import time
from pathlib import Path

from lib.vault import VaultLocked

NETOPS_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = NETOPS_ROOT / "core" / "config" / "project-config.yaml"

ENV_KEY = "NETOPS_VAULT_KEY"
MAGIC = b"NETOPSK1"
FORMAT_VERSION = 1
SESSION_TTL_DEFAULT = 900  # 15 min de inatividade
_HEADER = ">8sBQQIH"  # magic, version, created, expires, ttl, boot_id_len


# --------------------------------------------------------------------------- #
# Localização do cache
# --------------------------------------------------------------------------- #
def _cache_dir() -> tuple[Path, bool]:
    """Retorna (diretório_do_cache, é_fallback_em_disco)."""
    uid = os.getuid()
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg and os.path.isdir(xdg):
        return Path(xdg) / "netops", False
    run_user = Path(f"/run/user/{uid}")
    if run_user.is_dir():
        return run_user / "netops", False
    return Path(tempfile.gettempdir()) / f"netops-vault-{uid}", True


def cache_path() -> tuple[Path, bool]:
    d, fallback = _cache_dir()
    return d / "session.key", fallback


def _boot_id() -> bytes:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip().encode("ascii")
    except OSError:
        return b""


def default_ttl() -> int:
    """TTL configurável em core/config/project-config.yaml (vault.session_ttl_seconds)."""
    try:
        import yaml  # noqa: PLC0415
        if CONFIG_FILE.exists():
            cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
            ttl = ((cfg.get("vault") or {}).get("session_ttl_seconds"))
            if isinstance(ttl, int) and ttl > 0:
                return ttl
    except Exception:
        pass
    return SESSION_TTL_DEFAULT


# --------------------------------------------------------------------------- #
# Codificação da chave p/ env var
# --------------------------------------------------------------------------- #
def encode_key(key: bytes) -> str:
    return base64.urlsafe_b64encode(key).decode("ascii")


def decode_key(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


# --------------------------------------------------------------------------- #
# Escrita / leitura do cache
# --------------------------------------------------------------------------- #
def _ensure_dir(d: Path) -> None:
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)


def set_session_key(key: bytes, ttl: int | None = None) -> tuple[Path, bool]:
    """Grava a chave derivada no cache (atomicamente, 0600). Retorna (caminho, fallback_em_disco)."""
    ttl = int(ttl if ttl is not None else default_ttl())
    d, fallback = _cache_dir()
    _ensure_dir(d)
    now = int(time.time())
    boot = _boot_id()
    payload = (
        struct.pack(_HEADER, MAGIC, FORMAT_VERSION, now, now + ttl, ttl, len(boot))
        + boot
        + struct.pack(">H", len(key))
        + key
    )
    path = d / "session.key"
    tmp = d / f"session.key.tmp.{os.getpid()}"
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(fd)
    os.replace(str(tmp), str(path))
    return path, fallback


def _parse(data: bytes) -> dict | None:
    hsize = struct.calcsize(_HEADER)
    if len(data) < hsize:
        return None
    magic, version, created, expires, ttl, boot_len = struct.unpack(_HEADER, data[:hsize])
    if magic != MAGIC or version != FORMAT_VERSION:
        return None
    off = hsize
    boot = data[off:off + boot_len]
    off += boot_len
    if len(data) < off + 2:
        return None
    (key_len,) = struct.unpack(">H", data[off:off + 2])
    off += 2
    key = data[off:off + key_len]
    if len(key) != key_len:
        return None
    return {"created": created, "expires": expires, "ttl": ttl, "boot": boot, "key": key}


def _load_cache() -> dict | None:
    """Lê e valida o cache (perms, magic, boot_id, expiração). NÃO renova o TTL.

    Levanta VaultLocked se as permissões estiverem inseguras (fail-closed).
    Retorna o dict parseado, ou None se ausente/expirado/reboot.
    """
    path, _ = cache_path()
    if not path.exists():
        return None

    d = path.parent
    st_dir = os.lstat(str(d))
    if st_dir.st_uid != os.getuid() or stat.S_IMODE(st_dir.st_mode) != 0o700:
        raise VaultLocked(
            f"Diretório do cache com permissões inseguras: {d}. "
            "Rode: python scripts/vault/cli.py lock"
        )

    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise VaultLocked(f"Não foi possível abrir o cache com segurança: {exc}") from exc
    try:
        st = os.fstat(fd)
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o600
        ):
            raise VaultLocked(
                "Arquivo de cache com permissões inseguras. "
                "Rode: python scripts/vault/cli.py lock  (e depois unlock)"
            )
        data = os.read(fd, 65536)
    finally:
        os.close(fd)

    parsed = _parse(data)
    if parsed is None:
        _safe_unlink(path)
        return None
    if parsed["boot"] != _boot_id():
        _safe_unlink(path)  # cache antigo de antes do reboot (só ocorre em fallback de disco)
        return None
    if parsed["expires"] <= int(time.time()):
        _safe_unlink(path)
        return None
    return parsed


def get_session_key() -> bytes:
    """Chave da sessão: cache (com TTL deslizante) -> env var -> VaultLocked."""
    parsed = _load_cache()
    if parsed is not None:
        # TTL deslizante: o uso renova a janela de inatividade.
        set_session_key(parsed["key"], parsed["ttl"])
        return parsed["key"]

    env = os.environ.get(ENV_KEY)
    if env:
        try:
            return decode_key(env)
        except Exception as exc:
            raise VaultLocked(f"{ENV_KEY} inválida: {exc}") from exc

    raise VaultLocked()


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def clear_session() -> bool:
    """Apaga o cache (lock). Idempotente. Retorna True se havia algo pra apagar."""
    path, _ = cache_path()
    existed = path.exists()
    if existed:
        try:
            with open(path, "r+b") as fh:  # overwrite best-effort (cosmético em tmpfs)
                size = os.fstat(fh.fileno()).st_size
                fh.seek(0)
                fh.write(b"\x00" * size)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass
        _safe_unlink(path)
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return existed


def session_status() -> dict:
    """Estado da sessão, sem jamais expor a chave."""
    if os.environ.get(ENV_KEY):
        return {"state": "env"}
    path, fallback = cache_path()
    try:
        parsed = _load_cache()
    except VaultLocked as exc:
        return {"state": "insecure", "detail": str(exc), "path": str(path)}
    if parsed is None:
        return {"state": "locked", "path": str(path), "fallback": fallback}
    return {
        "state": "cache",
        "expires_in": max(0, parsed["expires"] - int(time.time())),
        "path": str(path),
        "fallback": fallback,
    }
