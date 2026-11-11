"""Trava reentrante por diretório de inventário, compartilhada entre processos.

O flock protege todo o ciclo leitura/validação/gravação dos consumidores cooperantes.
O journal incompleto impede novas escritas até recuperação explícita da migração.
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from threading import RLock, local

_THREAD_LOCK = RLock()
_HELD = local()
JOURNAL_NAME = ".host-id-migration.json"


class MigrationIncomplete(RuntimeError):
    """Inventário indisponível até recuperar o journal de migração."""


@contextmanager
def inventory_lock(network_dir: Path):
    network_dir = Path(network_dir).absolute()
    if any(component.is_symlink() for component in (network_dir, *network_dir.parents)):
        raise ValueError("diretório do inventário não pode passar por symlink")
    network_dir = Path(network_dir).resolve()
    with _THREAD_LOCK:
        held = getattr(_HELD, "paths", None)
        if held is None:
            held = _HELD.paths = {}
        if network_dir in held:
            held[network_dir] += 1
            try:
                yield
            finally:
                held[network_dir] -= 1
            return
        network_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(network_dir / ".inventory.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            held[network_dir] = 1
            yield
        finally:
            held.pop(network_dir, None)
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def ensure_migration_complete(network_dir: Path):
    """Recusa uso de uma migração interrompida antes de misturar versões."""
    import json
    journal = Path(network_dir) / JOURNAL_NAME
    if any(component.is_symlink() for component in (journal, *journal.parents)):
        raise MigrationIncomplete("journal de migração inválido; verifique symlinks antes de recuperar")
    if journal.exists():
        try:
            state = json.loads(journal.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise MigrationIncomplete("journal de migração ilegível; recupere o baseline antes de continuar") from exc
        if not isinstance(state, dict) or state.get("version") != 1 or state.get("status") not in ("complete", "rolled_back"):
            raise MigrationIncomplete("migração de IDs incompleta; execute host_id_migration.py recover")
