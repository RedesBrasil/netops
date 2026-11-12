#!/usr/bin/env python3
"""Runner de backup — processo efêmero disparado pela aba Backups (botão Run).

Piloto: coleta apenas MikroTik via SSH (/export). Lê runs/backups/<run_id>.json,
processa cada host e atualiza o status incrementalmente (a UI faz polling).

Segredos: o host é resolvido SEM decifrar para decidir elegibilidade; a credencial
só é decifrada (pelo lib de acesso, via chave do vault) no momento de conectar.
A senha NUNCA é impressa nem gravada — só usada para abrir a sessão.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent          # scripts/engine/ui
ENGINE_DIR = UI_DIR.parent                          # scripts/engine
NETOPS_ROOT = UI_DIR.parents[2]                     # raiz
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(ENGINE_DIR.parent / "tools"))

BACKUPS_STORE = NETOPS_ROOT / "backups"
BACKUPS_RUNS = NETOPS_ROOT / "runs" / "backups"
HOSTS_FILE = NETOPS_ROOT / "network" / "hosts.yaml"

import yaml  # noqa: E402
from lib.inventory import resolve_host  # noqa: E402
from lib.host_identity import require_host_id  # noqa: E402
from lib.inventory_lock import ensure_migration_complete, inventory_lock  # noqa: E402
from lib.cli_runner import run_commands  # noqa: E402


def _atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, mode)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))


def _save_status(run_id: str, status: dict) -> None:
    _atomic_write(BACKUPS_RUNS / f"{run_id}.json", json.dumps(status, ensure_ascii=False, indent=2))


_ANSI = re.compile(r"\x1B\[[0-9;]*[mK]")


def _strip_ros(cfg: str) -> str:
    """Limpeza mínima do /export: tira ANSI e as linhas de data/hora (v6 e v7)."""
    cfg = _ANSI.sub("", cfg)
    out = []
    for line in cfg.splitlines():
        line = line.rstrip()
        if re.match(r"^#\s\w{3}/\d{2}/\d{4}", line):   # data v6
            continue
        if re.match(r"^#\s\d{4}-\d{2}-\d{2}", line):    # data v7
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def _run(run_id: str) -> None:
    # A coleta e a seleção precisam usar a mesma instalação, inclusive em ambiente isolado.
    from lib import inventory
    inventory.HOSTS_FILE = HOSTS_FILE
    inventory.CREDS_FILE = HOSTS_FILE.with_name("credentials.yaml")
    status = json.loads((BACKUPS_RUNS / f"{run_id}.json").read_text(encoding="utf-8"))
    hosts_data = yaml.safe_load(HOSTS_FILE.read_text(encoding="utf-8")) or {}
    def set_host(hid: int | str, **kw) -> None:
        for h in status["hosts"]:
            if h["id"] == hid:
                h.update(kw)
        _save_status(run_id, status)

    for entry in status["hosts"]:
        hid = entry["id"]
        set_host(hid, state="running", detail="")
        try:
            # 1) resolve SEM decifrar — decide elegibilidade sem tocar no vault
            host0, _ = resolve_host(hid, hosts_data, {}, decrypt=False)
            canonical_id = require_host_id(host0.get("id", host0["name"]))
            if canonical_id != hid:
                set_host(hid, id=canonical_id)
                hid = canonical_id
            vendor = (host0.get("vendor") or "").lower()
            method = (host0.get("access") or {}).get("method", "ssh")
            if vendor != "mikrotik":
                set_host(hid, state="skip", detail=f"piloto: só MikroTik (vendor={vendor or '?'})")
                continue
            if method not in ("ssh", "telnet"):
                set_host(hid, state="skip",
                         detail=f"MikroTik via {method} não exporta config — cadastre acesso SSH")
                continue

            # 2) o script de acesso resolve a credencial apenas ao abrir a conexão.
            out = run_commands(hid, ["/export"], force_method=method, read_timeout=90)["/export"]
            cfg = _strip_ros(out)

            (BACKUPS_STORE / "by-id" / str(hid)).mkdir(parents=True, exist_ok=True)
            rel = f"by-id/{hid}/{run_id}.cfg"
            _atomic_write(BACKUPS_STORE / rel, cfg)
            set_host(hid, state="ok", detail=f"{len(cfg.encode('utf-8'))} bytes",
                     path=rel, size=len(cfg.encode("utf-8")))
        except Exception as e:  # noqa: BLE001
            set_host(hid, state="fail", detail=f"{type(e).__name__}: {str(e)[:200]}")

    status["state"] = "done"
    status["finished_at"] = int(time.time())
    _save_status(run_id, status)


def main() -> None:
    global HOSTS_FILE, BACKUPS_STORE, BACKUPS_RUNS
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--data-root", type=Path, help="Instalação que contém network/, backups/ e runs/")
    args = ap.parse_args()
    data_root = args.data_root or os.environ.get("NETOPS_UI_DATA_ROOT")
    if data_root:
        root = Path(data_root).resolve()
        HOSTS_FILE = root / "network" / "hosts.yaml"
        BACKUPS_STORE = root / "backups"
        BACKUPS_RUNS = root / "runs" / "backups"
    run_id = args.run_id
    with inventory_lock(HOSTS_FILE.parent):
        ensure_migration_complete(HOSTS_FILE.parent)
        _run(run_id)


if __name__ == "__main__":
    main()
