#!/usr/bin/env python3
"""Snapshot pré-mudança de CT/VM do Proxmox (substitui o backup de config para guests).

  snapshot.py create  --host-id N [--tag t] [--max-pool-pct 90] [--min-free-gb 2] [--no-trim] [--force-space]
  snapshot.py list    --host-id N          # snapshots netops-pre-* do guest (ao vivo no Proxmox)
  snapshot.py delete  --host-id N [--name netops-pre-...] # apaga (só netops-pre-*; peça confirmação ao usuário ANTES)
  snapshot.py pending                      # snapshots criados pelo NetOps ainda não apagados (todos os guests)

N = ID do CT/VM no inventário (network/hosts.yaml). O Proxmox é o `runs_on` dele e o número do CT/VM
vem de `vmid:` no host ou de "CT 104 do ..." / "VM 200 do ..." nas notas.

`create`: 1) confere que o storage suporta snapshot (lvmthin/zfspool/rbd/btrfs); 2) lê o espaço do pool;
3) roda fstrim no guest (devolve blocos ao pool); 4) relê o espaço e BLOQUEIA se o pool passar do limite;
5) cria `netops-pre-AAAAMMDD-HHMM[-tag]`. Normalmente é chamado por `change.py begin --mode snapshot`.
Estado em runs/changes/snapshots.json. Acesso ao Proxmox: sessão persistente (change._run). Nada é apagado sozinho.
"""
import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "engine"))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import change as C  # noqa: E402  (também faz ensure_venv e carrega yaml)
from lib import i18n  # noqa: E402

PREFIX = "netops-pre-"
OK_STORAGE = {"lvmthin", "zfspool", "rbd", "btrfs"}
STATE_FILE = C.STATE / "snapshots.json"


# ---------- inventário ----------
def guest_of(h: dict):
    """(kind, vmid, pve_id) se o host é CT/VM de Proxmox; senão None."""
    pve = h.get("runs_on")
    if not pve:
        return None
    notes = str(h.get("notes") or "")
    m = re.search(r"\b(CT|VM)\s+(\d+)\b", notes)
    vmid = h.get("vmid") or (int(m.group(2)) if m else None)
    if not vmid:
        return None
    kind = "qemu" if (m and m.group(1) == "VM") or str(h.get("model") or "").upper() in ("VM", "QEMU", "KVM") else "lxc"
    return kind, int(vmid), int(pve)


def _pve(pve_id: int):
    h = C.host_info(pve_id)
    method = (h.get("access") or {}).get("method", "ssh")
    return lambda cmd: C._run(pve_id, method, cmd)


def _load():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001
        return []


def _save(items):
    C.STATE.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(items, indent=1))


# ---------- Proxmox ----------
def _tool(kind):
    return "pct" if kind == "lxc" else "qm"


def storages_of(run, kind, vmid):
    """Storages usados pelos discos do guest (ignora bind mounts)."""
    cfg = run(f"{_tool(kind)} config {vmid}")
    if "does not exist" in cfg or "not exist" in cfg.lower() and "unable" in cfg.lower():
        raise SystemExit(i18n.t("cli_backup.guest_not_found", tool=_tool(kind), vmid=vmid, output=cfg.strip()[:300]))
    stores = {}
    for line in cfg.splitlines():
        m = re.match(r"^(rootfs|mp\d+|scsi\d+|virtio\d+|sata\d+|ide\d+|efidisk\d+|tpmstate\d+):\s*([A-Za-z0-9_.-]+):", line.strip())
        if m and "media=cdrom" not in line:
            stores.setdefault(m.group(2), []).append(m.group(1))
    return stores, cfg


def pool_state(run, store):
    """{'type','avail_gb','used_pct','meta_pct'} do storage (pool thin/zfs)."""
    out = run(f"pvesm status --storage {store}")
    row = [l.split() for l in out.splitlines() if l.split()[:1] == [store]]
    if not row or len(row[0]) < 7:
        raise SystemExit(i18n.t("cli_backup.pvesm_unreadable", store=store, output=out.strip()[:300]))
    r = row[0]
    st = {"type": r[1], "avail_gb": float(r[5]) / 1024 / 1024, "used_pct": float(r[6].rstrip('%')), "meta_pct": None}
    if st["type"] == "lvmthin":
        c = run(f"pvesm config {store}")
        vg = (re.search(r"vgname\s+(\S+)", c) or [None, None])[1]
        tp = (re.search(r"thinpool\s+(\S+)", c) or [None, None])[1]
        if vg and tp:
            l = run(f"lvs --noheadings --separator , -o data_percent,metadata_percent {vg}/{tp}").strip().splitlines()
            if l and "," in l[-1]:
                d, m = l[-1].strip().split(",")[:2]
                try:
                    st["used_pct"], st["meta_pct"] = float(d), float(m)
                except ValueError:
                    pass
    return st


def fmt_pool(s):
    meta = i18n.t("cli_backup.pool_meta", pct=f"{s['meta_pct']:.1f}") if s["meta_pct"] is not None else ""
    return i18n.t("cli_backup.pool_state", type=s["type"], used=f"{s['used_pct']:.1f}", free=f"{s['avail_gb']:.1f}", meta=meta)


def create(hid, h, tag="", max_pool_pct=90.0, min_free_gb=2.0, trim=True, force_space=False):
    g = guest_of(h)
    if not g:
        raise SystemExit(i18n.t("cli_backup.not_guest_detail", host_id=hid))
    kind, vmid, pve_id = g
    run = _pve(pve_id)
    stores, _ = storages_of(run, kind, vmid)
    if not stores:
        raise SystemExit(i18n.t("cli_backup.no_managed_disk", tool=_tool(kind), vmid=vmid))
    pools = {}
    for s in stores:
        p = pool_state(run, s)
        if p["type"] not in OK_STORAGE:
            raise SystemExit(i18n.t("cli_backup.storage_no_snapshot", store=s, type=p["type"],
                                    kind="CT" if kind == "lxc" else "VM"))
        pools[s] = p
        print(i18n.t("cli_backup.space_before_trim", store=s, state=fmt_pool(p)))
    if trim:
        cmd = f"pct fstrim {vmid} 2>&1" if kind == "lxc" else f"qm guest cmd {vmid} fstrim 2>&1"
        try:
            out = run(cmd).strip()
        except BaseException as exc:  # noqa: BLE001
            out = i18n.t("cli_backup.fstrim_failed", error=exc)
        print(f"FSTRIM: {out[:300] or 'ok'}")
        pools = {s: pool_state(run, s) for s in stores}
        for s, p in pools.items():
            print(i18n.t("cli_backup.space_after_trim", store=s, state=fmt_pool(p)))
    for s, p in pools.items():
        bad = [m for m, c in ((i18n.t("cli_backup.pool_data"), p["used_pct"] >= max_pool_pct),
                              (i18n.t("cli_backup.pool_metadata"), (p["meta_pct"] or 0) >= max_pool_pct),
                              (i18n.t("cli_backup.pool_free_below", gb=min_free_gb), p["avail_gb"] < min_free_gb)) if c]
        if bad and not force_space:
            raise SystemExit(i18n.t("cli_backup.pool_blocked", store=s, reasons=", ".join(bad), limit=f"{max_pool_pct:.0f}"))
    name = PREFIX + time.strftime("%Y%m%d-%H%M")
    t = re.sub(r"[^A-Za-z0-9_-]+", "-", tag).strip("-")[:12]
    if t:
        name += "-" + t
    desc = f"NetOps pre-mudanca (host {hid})"
    out = run(f"{_tool(kind)} snapshot {vmid} {name} --description '{desc}' 2>&1").strip()
    lst = run(f"{_tool(kind)} listsnapshot {vmid}")
    if name not in lst:
        raise SystemExit(i18n.t("cli_backup.snapshot_missing", output=out[:400]))
    items = _load()
    items.append({"host_id": hid, "pve_id": pve_id, "vmid": vmid, "kind": kind, "name": name,
                  "created": int(time.time()), "status": "active"})
    _save(items)
    stale = [l.split()[1] for l in lst.splitlines() if PREFIX in l and name not in l and len(l.split()) > 1]
    print(i18n.t("cli_backup.snapshot_ok", tool=_tool(kind), vmid=vmid, name=name))
    if stale:
        print(i18n.t("cli_backup.stale_snapshots", names=", ".join(stale)))
    return name


def listing(hid, h):
    kind, vmid, pve_id = guest_of(h) or (_ for _ in ()).throw(SystemExit(i18n.t("cli_backup.not_guest", host_id=hid)))
    print(_pve(pve_id)(f"{_tool(kind)} listsnapshot {vmid}").strip())


def delete(hid, h, name=None):
    kind, vmid, pve_id = guest_of(h) or (_ for _ in ()).throw(SystemExit(i18n.t("cli_backup.not_guest", host_id=hid)))
    items = _load()
    if not name:
        act = [i for i in items if i["host_id"] == hid and i["status"] == "active"]
        if not act:
            raise SystemExit(i18n.t("cli_backup.no_pending_host"))
        name = act[-1]["name"]
    if not name.startswith(PREFIX):
        raise SystemExit(i18n.t("cli_backup.refuse_delete", name=name, prefix=PREFIX))
    out = _pve(pve_id)(f"{_tool(kind)} delsnapshot {vmid} {name} 2>&1").strip()
    if name in _pve(pve_id)(f"{_tool(kind)} listsnapshot {vmid}"):
        raise SystemExit(i18n.t("cli_backup.still_exists", output=out[:400]))
    for i in items:
        if i["host_id"] == hid and i["name"] == name:
            i["status"] = "deleted"
    _save(items)
    print(i18n.t("cli_backup.deleted", tool=_tool(kind), vmid=vmid, name=name))


def pending():
    act = [i for i in _load() if i["status"] == "active"]
    if not act:
        print(i18n.t("cli_backup.no_pending"))
    for i in act:
        age = (time.time() - i["created"]) / 86400
        print(i18n.t("cli_backup.pending_line", host_id=i["host_id"], kind=i["kind"], vmid=i["vmid"], pve_id=i["pve_id"],
                     name=i["name"], days=f"{age:.1f}"))


def main():
    ap = argparse.ArgumentParser(description=i18n.t("cli_backup.snapshot_description"))
    ap.add_argument("action", choices=["create", "list", "delete", "pending"])
    ap.add_argument("--host-id", type=int)
    ap.add_argument("--tag", default="")
    ap.add_argument("--name")
    ap.add_argument("--max-pool-pct", type=float, default=90.0)
    ap.add_argument("--min-free-gb", type=float, default=2.0)
    ap.add_argument("--no-trim", action="store_true")
    ap.add_argument("--force-space", action="store_true")
    a = ap.parse_args()
    if a.action == "pending":
        return pending()
    if not a.host_id:
        raise SystemExit(i18n.t("cli_backup.host_id_required"))
    h = C.host_info(a.host_id)
    if a.action == "create":
        create(a.host_id, h, a.tag, a.max_pool_pct, a.min_free_gb, not a.no_trim, a.force_space)
    elif a.action == "list":
        listing(a.host_id, h)
    else:
        delete(a.host_id, h, a.name)


if __name__ == "__main__":
    main()
