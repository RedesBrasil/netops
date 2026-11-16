"""Chaves SSH dedicadas por tarefa agendada (acesso sem cofre destrancado).

Cada tarefa que precisa de equipamento com o cofre trancado tem a PRÓPRIA chave, com o mínimo de poder
(somente leitura = comando forçado `netops-ro-shell` no equipamento). A chave nasce com a tarefa e morre
com ela: apagar a tarefa (CLI, console ou editando o YAML na mão) apaga a pasta da chave e enfileira a
revogação da linha no authorized_keys dos equipamentos (executada por `task_key.py revoke-pending`).

Layout (git-ignorado): network/task-keys/<task_id>/{id_ed25519,id_ed25519.pub,access.yaml}
                       network/task-keys/_revoke.yaml  (fila de revogação nos equipamentos)
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml

MARK = "netops-task:"
FORCED = "/usr/local/sbin/netops-ro-shell"
OPTS = "no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding"


def keys_root(root: Path | str) -> Path:
    return Path(root) / "network" / "task-keys"


def task_dir(root, task_id: str) -> Path:
    if not task_id or "/" in task_id or task_id.startswith("."):
        raise ValueError("task_id inválido")
    return keys_root(root) / task_id


def _write(path: Path, data: str | bytes, mode: int) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)
    os.chmod(tmp, mode)
    tmp.replace(path)


def load_access(root, task_id: str) -> dict:
    p = task_dir(root, task_id) / "access.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def save_access(root, task_id: str, data: dict) -> None:
    _write(task_dir(root, task_id) / "access.yaml", yaml.safe_dump(data, allow_unicode=True, sort_keys=False), 0o600)


def generate(root, task_id: str, force: bool = False) -> str:
    """Cria o par ed25519 da tarefa (se não existir). Retorna a chave pública (linha OpenSSH)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    d = task_dir(root, task_id)
    priv, pub = d / "id_ed25519", d / "id_ed25519.pub"
    if priv.exists() and pub.exists() and not force:
        return pub.read_text().strip()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    os.chmod(keys_root(root), 0o700)
    k = Ed25519PrivateKey.generate()
    _write(priv, k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                 serialization.NoEncryption()), 0o600)
    line = k.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    line += f" {MARK}{task_id}"
    _write(pub, line + "\n", 0o644)
    return line


def authorized_line(pub: str, mode: str) -> str:
    """Linha do authorized_keys: leitura = comando forçado; escrita = só sem forwarding/pty."""
    if mode == "ro":
        return f'command="{FORCED}",{OPTS} {pub}'
    if mode == "rw":
        return f"{OPTS} {pub}"
    raise ValueError("mode deve ser 'ro' ou 'rw'")


def _revoke_file(root) -> Path:
    return keys_root(root) / "_revoke.yaml"


def pending_revocations(root) -> list[dict]:
    p = _revoke_file(root)
    return (yaml.safe_load(p.read_text()) or []) if p.exists() else []


def save_revocations(root, items: list[dict]) -> None:
    keys_root(root).mkdir(parents=True, exist_ok=True)
    _write(_revoke_file(root), yaml.safe_dump(items, allow_unicode=True), 0o600)


def delete(root, task_id: str) -> bool:
    """Apaga a chave da tarefa e enfileira a revogação nos equipamentos provisionados."""
    d = task_dir(root, task_id)
    if not d.exists():
        return False
    acc = load_access(root, task_id)
    hosts = [h["host_id"] for h in acc.get("hosts", [])]
    if hosts:
        q = [x for x in pending_revocations(root) if x.get("task_id") != task_id]
        q.append({"task_id": task_id, "hosts": hosts})
        save_revocations(root, q)
    shutil.rmtree(d, ignore_errors=True)
    return True


def sweep(root, valid_task_ids: set[str]) -> list[str]:
    """Remove pastas de chave sem tarefa correspondente (ex.: tarefa apagada editando o YAML)."""
    kr = keys_root(root)
    gone = []
    if kr.exists():
        for d in kr.iterdir():
            if d.is_dir() and d.name not in valid_task_ids:
                delete(root, d.name)
                gone.append(d.name)
    return gone
