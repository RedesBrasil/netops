#!/usr/bin/env python3
"""Backup automático antes/depois de uma sessão de mudança num host.

  change.py begin --host-id N [--force]   # backup "pré" (bloqueia a mudança se falhar)
  change.py end   --host-id N             # backup "pós" + diff pré×pós + retenção

Usa o mesmo armazenamento da aba Backups: backups/by-id/<id>/. Só roda se o host tem
`backup_before_change: true` (herdável do grupo) ou com --force. Segredos no backup ficam em
texto puro (como o próprio export do equipamento); a credencial de acesso nunca é lida aqui.
Retenção: project-config.yaml -> backups.keep_versions (padrão 10 arquivos por host).
"""
import argparse, difflib, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "engine"))
sys.path.insert(0, str(ROOT / "scripts" / "tools"))
sys.path.insert(0, str(ROOT / "scripts" / "engine" / "ui"))

import yaml  # noqa: E402
from lib.inventory import resolve_host  # noqa: E402
from access.ssh import run_commands  # noqa: E402
from backup_runner import _strip_ros, _atomic_write  # noqa: E402

STORE = ROOT / "backups" / "by-id"
STATE = ROOT / "runs" / "changes"
LINUX_FILES = "/etc/network/interfaces /etc/hosts /etc/resolv.conf /etc/fstab /etc/ssh/sshd_config /etc/sysctl.conf"
LINUX_CMD = ("for f in %s /etc/pve/*.cfg /etc/pve/nodes/*/host.fw /etc/pve/firewall/*.fw; do "
             "[ -f \"$f\" ] && { echo \"### $f\"; cat \"$f\"; }; done; echo '### iptables-save'; iptables-save 2>/dev/null" % LINUX_FILES)


def collector(vendor: str):
    """(comando, limpeza) por vendor; None = vendor sem coletor."""
    v = vendor.lower()
    if v == "mikrotik":
        return "/export show-sensitive", _strip_ros
    if v == "cisco":
        return "show running-config", str.strip
    if v == "huawei":
        return "display current-configuration", str.strip
    if v in ("linux", "proxmox"):
        return LINUX_CMD, str.strip
    return None


def keep_versions() -> int:
    try:
        cfg = yaml.safe_load((ROOT / "core/config/project-config.yaml").read_text()) or {}
        return max(2, int((cfg.get("backups") or {}).get("keep_versions", 10)))
    except Exception:  # noqa: BLE001
        return 10


def host_info(hid: int):
    hosts = yaml.safe_load((ROOT / "network/hosts.yaml").read_text()) or {}
    h, _ = resolve_host(hid, hosts, {}, decrypt=False)
    return h


def collect(hid: int, h: dict) -> str:
    col = collector(h.get("vendor") or "")
    if not col:
        raise SystemExit(f"vendor '{h.get('vendor')}' sem coletor de backup")
    cmd, clean = col
    method = (h.get("access") or {}).get("method", "ssh")
    if method not in ("ssh", "telnet"):
        raise SystemExit(f"acesso {method} não coleta config — cadastre SSH")
    out = run_commands(hid, [cmd], force_method=method, read_timeout=120)[cmd]
    if cmd.startswith("/export show-sensitive") and ("expected end of command" in out or "syntax error" in out):
        out = run_commands(hid, ["/export"], force_method=method, read_timeout=120)["/export"]
    text = clean(out)
    if len(text.strip()) < 50:
        raise SystemExit("backup vazio/curto demais — abortando por segurança")
    return text if text.endswith("\n") else text + "\n"


def prune(hid: int) -> int:
    files = sorted(STORE.joinpath(str(hid)).glob("*.cfg"), key=lambda p: p.stat().st_mtime)
    extra = files[:-keep_versions()] if len(files) > keep_versions() else []
    for p in extra:
        p.unlink()
    return len(extra)


def save(hid: int, tag: str, text: str) -> str:
    d = STORE / str(hid)
    d.mkdir(parents=True, exist_ok=True)
    name = f"change-{time.strftime('%Y%m%d-%H%M%S')}-{tag}.cfg"
    _atomic_write(d / name, text, 0o600)
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["begin", "end"])
    ap.add_argument("--host-id", type=int, required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    hid = a.host_id
    h = host_info(hid)
    STATE.mkdir(parents=True, exist_ok=True)
    marker = STATE / f"{hid}.json"
    if not h.get("backup_before_change") and not a.force:
        print(f"SKIP: host {hid} sem backup_before_change (use --force para forçar)")
        return
    if a.action == "begin":
        name = save(hid, "pre", collect(hid, h))
        marker.write_text(json.dumps({"pre": name, "started": int(time.time())}))
        print(f"OK pre: backups/by-id/{hid}/{name} (podados: {prune(hid)})")
    else:
        if not marker.exists():
            raise SystemExit("sessão não iniciada (rode begin antes)")
        pre = json.loads(marker.read_text())["pre"]
        name = save(hid, "post", collect(hid, h))
        a_txt = (STORE / str(hid) / pre).read_text().splitlines()
        b_txt = (STORE / str(hid) / name).read_text().splitlines()
        diff = list(difflib.unified_diff(a_txt, b_txt, pre, name, lineterm="", n=1))
        marker.unlink()
        print(f"OK post: backups/by-id/{hid}/{name} (podados: {prune(hid)})")
        print(f"DIFF: {sum(1 for l in diff if l[:1] in '+-' and l[:3] not in ('+++','---'))} linhas alteradas")
        print("\n".join(diff[:200]))


if __name__ == "__main__":
    main()
