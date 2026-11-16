#!/usr/bin/env python3
"""Executa comando num equipamento com a CHAVE DEDICADA da tarefa agendada (não usa o cofre).

  task_exec.py --task <id-da-tarefa> --host-id N --command "<cmd>" [--timeout 60]

A chave vive em network/task-keys/<tarefa>/ e só vale enquanto a tarefa existir. Chave somente leitura:
o equipamento só aceita comandos de leitura (netops-ro-shell) e nega o resto. Fingerprint do equipamento
é fixada no provisionamento (access.yaml) e conferida a cada conexão.
"""
import argparse, base64, hashlib, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "engine"))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()

import paramiko, yaml  # noqa: E402
from lib import taskkeys  # noqa: E402
from lib.inventory import resolve_host  # noqa: E402


def target(host_id: int) -> tuple[str, int]:
    h = yaml.safe_load((ROOT / "network" / "hosts.yaml").read_text())
    r, _ = resolve_host(host_id, h, {}, decrypt=False)
    return r["mgmt_ip"], int((r.get("access") or {}).get("port") or 22)


class Pin(paramiko.MissingHostKeyPolicy):
    def __init__(self, fp):
        self.fp, self.seen = fp, None

    def missing_host_key(self, client, hostname, key):
        self.seen = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if self.fp and self.seen != self.fp:
            raise paramiko.SSHException(f"fingerprint do host mudou ({self.seen})")


def connect(task: str, host_id: int, timeout: float = 15, learn: bool = False):
    acc = taskkeys.load_access(ROOT, task)
    entry = next((h for h in acc.get("hosts", []) if h["host_id"] == host_id), None)
    if entry is None and not learn:
        raise SystemExit(f"tarefa '{task}' não tem chave provisionada no host {host_id}")
    ip, port = target(host_id)
    pin = Pin(entry.get("fingerprint") if entry else None)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(pin)
    c.connect(ip, port=port, username="root", pkey=paramiko.Ed25519Key.from_private_key_file(
        str(taskkeys.task_dir(ROOT, task) / "id_ed25519")), look_for_keys=False, allow_agent=False,
        timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
    return c, pin


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--host-id", type=int, required=True)
    ap.add_argument("--command", required=True)
    ap.add_argument("--timeout", type=int, default=60)
    a = ap.parse_args()
    t0 = time.time()
    c, _ = connect(a.task, a.host_id)
    try:
        _, out, err = c.exec_command(a.command, timeout=a.timeout)
        out.channel.settimeout(a.timeout)
        o, e = out.read().decode(errors="replace"), err.read().decode(errors="replace")
        code = out.channel.recv_exit_status()
    finally:
        c.close()
    sys.stdout.write(o)
    sys.stderr.write(e)
    print(f"[status={'ok' if code == 0 else 'erro'} exit={code} {time.time() - t0:.2f}s]")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
