#!/usr/bin/env python3
"""Cadastra CTs/VMs descobertos no inventário e posiciona no mapa, dentro da caixa do Proxmox.

Dois subcomandos (ambos DRY-RUN por padrão; `--apply` grava, com cópia em runs/copias-seguranca/network/):

  register  -- acrescenta hosts em network/hosts.yaml a partir de um YAML de especificação
  place     -- põe os hosts de um Proxmox (runs_on) no mapa "all": grade de 3+ colunas dentro da
               caixa azul, ligados à bridge com linha em ângulo reto (igual ao Proxmox Techify)
  append    -- caixa com desenho próprio (Redes Brasil, Techify): acrescenta embaixo da coluna menos cheia
  zone      -- Proxmox sem zona no mapa: cria caixa azul + nota + bridge e liga o host (depois, `place`)

    python3 scripts/tools/inventory/map_place.py register --spec /var/tmp/netops-x/spec.yaml [--apply]
    python3 scripts/tools/inventory/map_place.py place --proxmox 18 [--labels 37=VLAN3000,55=vmbr1] [--apply]

Spec do `register` (lista `hosts`; `proxmox` e `ct` viram `runs_on` + nota "CT N do <PROXMOX> (host P)"):

    proxmox: 18
    hosts:
      - {hostname: PROXY-TESTE, ip: 10.8.200.211, ct: 102, os: UBUNTU, os_version: '20.04',
         apps: [TRAEFIK, DOCKER], notes: "4 vCPU, 8 GB RAM."}
      - {hostname: CHR-X, ip: 192.168.99.1, ct: 300, kind: VM, os: ROUTEROS, model: CHR, icon: router}  # VM: ct = VMID
"""
import argparse
import math
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()

import yaml  # noqa: E402
from lib import i18n  # noqa: E402
from lib.inventory_lock import inventory_lock  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
NET = ROOT / "network"
BACKUP = ROOT / "runs" / "copias-seguranca" / "network"
MAP_ID = "all"
# Geometria copiada do Proxmox Techify (caixa 1328x941; 1ª linha a +176 do topo; coluna 1 a +308)
COL_OFFSET, COL_STEP, ROW_STEP, FIRST_ROW, HOST_H = 308, 297, 134, 176, 105
MAX_COLS = 3


class Dumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # listas indentadas, como o console grava
        return super().increase_indent(flow, False)


def dump(data, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False))
    tmp.replace(path)


def backup(path: Path, tag: str) -> None:
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, BACKUP / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}-{tag}")


def load(name: str):
    return yaml.safe_load((NET / name).read_text())


def cmd_register(args) -> int:
    spec = yaml.safe_load(Path(args.spec).read_text())
    data = load("hosts.yaml")
    hosts = data["hosts"]
    by_id = {h["id"]: h for h in hosts}
    prox = by_id.get(spec["proxmox"])
    if not prox:
        sys.exit(i18n.t("cli_inventory.proxmox_not_found", proxmox=spec["proxmox"]))
    names = {h["hostname"] for h in hosts}
    ips = {h.get("mgmt_ip") for h in hosts}
    nxt = data["next_host_id"]
    new = []
    for item in spec["hosts"]:
        name = item["hostname"]
        if name != name.upper():
            sys.exit(i18n.t("cli_inventory.hostname_uppercase", name=name))
        if name in names:
            print(i18n.t("cli_inventory.skip_name", name=name)); continue
        if item["ip"] in ips:
            print(i18n.t("cli_inventory.skip_ip", name=name, ip=item["ip"])); continue
        kind = item.get("kind", "CT")
        entry = {"id": nxt, "hostname": name, "mgmt_ip": item["ip"], "group": item.get("group", "LINUX-SERVERS"),
                 "icon": item.get("icon", "linux-server"), "model": item.get("model", "LXC" if kind == "CT" else "KVM"),
                 "os": item.get("os", "LINUX"), "os_version": str(item.get("os_version", ""))}
        if item.get("apps"):
            entry["apps"] = [{"name": a, "version": ""} for a in item["apps"]]
        entry["runs_on"] = spec["proxmox"]
        access = (f"Acesso por pct exec {item['ct']} a partir do host {spec['proxmox']}." if kind == "CT"
                  else f"Console por qm terminal/noVNC no host {spec['proxmox']}.")
        entry["notes"] = (f"{kind} {item['ct']} do {prox['hostname']} (host {spec['proxmox']}). "
                          f"{item.get('notes', '')} {access}").replace("  ", " ")
        new.append(entry); names.add(name); ips.add(item["ip"]); nxt += 1
    for e in new:
        print(i18n.t("cli_inventory.added_host", id=e["id"], hostname=e["hostname"], ip=e["mgmt_ip"], runs_on=e["runs_on"]))
    if args.apply and new:
        with inventory_lock(NET):
            backup(NET / "hosts.yaml", "pre-register")
            data["hosts"] = hosts + new
            data["next_host_id"] = nxt
            dump(data, NET / "hosts.yaml")
        print(i18n.t("cli_inventory.saved"))
    elif not args.apply:
        print(i18n.t("cli_inventory.dry_run"))
    return 0


def cmd_place(args) -> int:
    hosts = {h["id"]: h for h in load("hosts.yaml")["hosts"]}
    maps = load("maps.yaml")
    m = next(x for x in maps["maps"] if x["id"] == MAP_ID)
    objs = {o["id"]: o for o in m["objects"]}
    # bridge do Proxmox = objeto ligado por visual_link ao host Proxmox
    bridge = None
    for v in m["visual_links"]:
        s, t = v["source"], v["target"]
        if s.get("host_id") == args.proxmox and t.get("kind") == "object":
            bridge = objs[t["object_id"]]
        elif t.get("host_id") == args.proxmox and s.get("kind") == "object":
            bridge = objs[s["object_id"]]
    if not bridge:
        sys.exit(i18n.t("cli_inventory.no_bridge_link", proxmox=args.proxmox, map=MAP_ID))
    bx, by = bridge["position"]["x"], bridge["position"]["y"]
    box = next((o for o in m["objects"] if o["type"] == "shape" and not o.get("label") and o.get("color")
                and o["position"]["x"] <= bx <= o["position"]["x"] + o["width"]
                and o["position"]["y"] <= by <= o["position"]["y"] + o["height"]), None)
    if not box:
        sys.exit(i18n.t("cli_inventory.no_box"))
    bx0, by0 = box["position"]["x"], box["position"]["y"]
    labels = {int(k): v for k, v in (p.split("=", 1) for p in args.labels.split(",") if p)}
    pos = {p["host_id"]: p for p in m["positions"]}
    ids = args.hosts or sorted((i for i, h in hosts.items() if h.get("runs_on") == args.proxmox),
                               key=lambda i: (0, pos[i]["x"], pos[i]["y"]) if i in pos and bx0 <= pos[i]["x"] <= bx0 + box["width"]
                               and by0 <= pos[i]["y"] <= by0 + box["height"] else (1, i, 0))  # já na caixa: mantém a ordem; novos no fim
    n = len(ids)
    if not n:
        sys.exit(i18n.t("cli_inventory.no_hosts"))
    cap = int((box["height"] - FIRST_ROW - 20) // ROW_STEP)
    ncols = 1 if n <= 3 else max(MAX_COLS, math.ceil(n / cap))
    nrows = math.ceil(n / ncols)
    need_w = COL_OFFSET + COL_STEP * (ncols - 1) + 195 + 40  # largura útil: a caixa cresce se faltar espaço
    if need_w > box["width"]:
        print(i18n.t("cli_inventory.box_widened", old=f"{box['width']:.0f}", new=f"{need_w:.0f}"))
        box["width"] = float(need_w)
    xs = [bx0 + COL_OFFSET + COL_STEP * c for c in range(ncols)]
    trunks = [x - 52 for x in xs]  # vão entre a coluna anterior e esta (1139/1437/1734 no Techify)
    y0 = by0 + FIRST_ROW
    # centro da bridge: no vão entre linhas (a linha horizontal das colunas 2 e 3 passa por ali, sem cruzar host)
    if ncols == 1:
        center = y0 + ROW_STEP * (nrows - 1) / 2 + HOST_H / 2
    else:
        k = max(nrows // 2 - 1, 0)
        center = y0 + ROW_STEP * k + HOST_H + (ROW_STEP - HOST_H) / 2
    zp = max(p["z_index"] for p in m["positions"]) + 1
    zl = max(v.get("z_index", 0) for v in m["visual_links"]) + 1
    print(i18n.t("cli_inventory.layout", x=f"{bx0:.0f}", y=f"{by0:.0f}", w=f"{box['width']:.0f}", h=f"{box['height']:.0f}",
                 n=n, cols=ncols, rows=nrows, center=f"{center:.0f}"))
    for i, hid in enumerate(ids):
        c, r = divmod(i, nrows)
        x, y = float(xs[c]), float(y0 + ROW_STEP * r)
        if hid in pos:
            pos[hid]["x"], pos[hid]["y"] = x, y
        else:
            m["positions"].append({"x": x, "y": y, "z_index": zp, "host_id": hid}); zp += 1
        link = next((v for v in m["visual_links"] if v["source"].get("object_id") == bridge["id"]
                     and v["target"].get("host_id") == hid), None)
        if link is None:
            link = {"z_index": zl, "id": f"vl-bridge-{args.proxmox}-{hid}",
                    "source": {"kind": "object", "object_id": bridge["id"]},
                    "target": {"kind": "host", "host_id": hid}, "speed": "1G"}
            zl += 1; m["visual_links"].append(link)
        link["anchors"] = {"source": {"side": "right", "ratio": 0.5}, "target": {"side": "left", "ratio": 0.5}}
        link["route"] = {"axis": "x", "tracks": [float(trunks[c])]}
        link["label"] = labels.get(hid, link.get("label", "") or "")
        print(i18n.t("cli_inventory.placed", hostname=hosts[hid]["hostname"], host_id=hid, col=c + 1, row=r + 1,
                     x=f"{x:.0f}", y=f"{y:.0f}", label=link["label"]))
    bridge["position"] = {"x": float(bx0 + 71), "y": float(center - 44)}
    order = ["anchors", "route", "z_index", "id", "source", "target", "label", "speed"]
    m["visual_links"] = [{k: v[k] for k in order if k in v} | {k: v[k] for k in v if k not in order}
                         for v in m["visual_links"]]
    if args.apply:
        with inventory_lock(NET):
            backup(NET / "maps.yaml", "pre-place")
            dump(maps, NET / "maps.yaml")
        print(i18n.t("cli_inventory.saved_reload_map_warning"))
    else:
        print(i18n.t("cli_inventory.dry_run"))
    return 0


def find_bridge(m, objs, proxmox):
    for v in m["visual_links"]:
        s_, t_ = v["source"], v["target"]
        if s_.get("host_id") == proxmox and t_.get("kind") == "object":
            return objs[t_["object_id"]]
        if t_.get("host_id") == proxmox and s_.get("kind") == "object":
            return objs[s_["object_id"]]
    return None


def bridge_box_bottom(m, bridge) -> float:
    bx, by = bridge["position"]["x"], bridge["position"]["y"]
    for o in m["objects"]:
        if o["type"] == "shape" and not o.get("label") and o.get("color") and o["position"]["x"] <= bx <= o["position"]["x"] + o["width"] \
                and o["position"]["y"] <= by <= o["position"]["y"] + o["height"]:
            return o["position"]["y"] + o["height"]
    return float("inf")


def cmd_append(args) -> int:
    """Caixa com desenho próprio (Redes Brasil, Techify): acrescenta embaixo da coluna menos cheia, sem mexer nos demais."""
    hosts = {h["id"]: h for h in load("hosts.yaml")["hosts"]}
    maps = load("maps.yaml")
    m = next(x for x in maps["maps"] if x["id"] == MAP_ID)
    objs = {o["id"]: o for o in m["objects"]}
    bridge = find_bridge(m, objs, args.proxmox) or sys.exit(i18n.t("cli_inventory.proxmox_no_bridge"))
    pos = {p["host_id"]: p for p in m["positions"]}
    links = [v for v in m["visual_links"] if v["source"].get("object_id") == bridge["id"] and v["target"].get("host_id") in pos]
    cols = {}
    for v in links:
        cols.setdefault(round(pos[v["target"]["host_id"]]["x"]), []).append(v)
    if not cols:
        sys.exit(i18n.t("cli_inventory.bridge_no_hosts"))
    labels = {int(k): v for k, v in (p.split("=", 1) for p in args.labels.split(",") if p)}
    zp = max(p["z_index"] for p in m["positions"]) + 1
    zl = max(v.get("z_index", 0) for v in m["visual_links"]) + 1
    xy = [tuple(float(n) for n in c.split(",")) for c in args.xy]
    if xy and len(xy) != len(args.hosts):
        sys.exit(i18n.t("cli_inventory.xy_count"))
    for i, hid in enumerate(args.hosts):
        if xy:                                                         # caixa cheia: posição escolhida à mão (--xy / --trunk)
            x, y = xy[i]
            tracks = [args.trunk] if args.trunk is not None else [x - 52.0]
        else:
            x = min(cols, key=lambda c: (len(cols[c]), c))             # coluna menos cheia
            ys = sorted(pos[v["target"]["host_id"]]["y"] for v in cols[x])
            step = min([b - a for a, b in zip(ys, ys[1:])] or [ROW_STEP])
            y = ys[-1] + max(step, 115)
            ref = next((v for v in cols[x] if v.get("route")), cols[x][0])
            tracks = list(ref["route"]["tracks"]) if ref.get("route") else [x - 52.0]
            if y + HOST_H > bridge_box_bottom(m, bridge) - 10:
                sys.exit(i18n.t("cli_inventory.does_not_fit", hostname=hosts[hid]["hostname"]))
        link = {"anchors": {"source": {"side": "right", "ratio": 0.5}, "target": {"side": "left", "ratio": 0.5}},
                "route": {"axis": "x", "tracks": tracks},
                "z_index": zl, "id": f"vl-bridge-{args.proxmox}-{hid}",
                "source": {"kind": "object", "object_id": bridge["id"]}, "target": {"kind": "host", "host_id": hid},
                "label": labels.get(hid, ""), "speed": "1G"}
        zl += 1
        if hid in pos:
            pos[hid]["x"], pos[hid]["y"] = float(x), float(y)
        else:
            pos[hid] = {"x": float(x), "y": float(y), "z_index": zp, "host_id": hid}; zp += 1
            m["positions"].append(pos[hid])
        if not any(v["target"].get("host_id") == hid and v["source"].get("object_id") == bridge["id"] for v in m["visual_links"]):
            m["visual_links"].append(link)
        cols.setdefault(round(x), []).append(link)
        print(i18n.t("cli_inventory.appended", hostname=hosts[hid]["hostname"], host_id=hid, x=f"{x:.0f}", y=f"{y:.0f}",
                     label=link["label"]))
    if args.apply:
        with inventory_lock(NET):
            backup(NET / "maps.yaml", "pre-append")
            dump(maps, NET / "maps.yaml")
        print(i18n.t("cli_inventory.saved_reload_map"))
    else:
        print(i18n.t("cli_inventory.dry_run"))
    return 0


def cmd_zone(args) -> int:
    """Cria a zona de um Proxmox ainda sem caixa: caixa azul 1328x941 + nota de título + bridge + ligação host -> bridge."""
    hosts = {h["id"]: h for h in load("hosts.yaml")["hosts"]}
    maps = load("maps.yaml")
    m = next(x for x in maps["maps"] if x["id"] == MAP_ID)
    objs = {o["id"]: o for o in m["objects"]}
    if find_bridge(m, objs, args.proxmox):
        sys.exit(i18n.t("cli_inventory.zone_exists"))
    boxes = [o for o in m["objects"] if o["type"] == "shape" and not o.get("label") and o.get("color") and o["width"] == 1328.0]
    top = max(b["position"]["y"] + b["height"] for b in boxes)
    box_y = float(top + 24)                                               # mesmo vão de ~24 entre as caixas
    zones = [p for p in m["positions"] if 400 < p["x"] < 470]              # coluna dos Proxmox (x ~ 435)
    host_y = float(max(p["y"] for p in zones) + 137)
    import uuid
    ids = {k: str(uuid.uuid4()) for k in ("box", "note", "bridge", "link")}
    zo = max(o.get("z_index", 0) for o in m["objects"])
    m["objects"] += [
        {"id": ids["box"], "type": "shape", "position": {"x": 883.0, "y": box_y}, "label": "", "form": "rect",
         "width": 1328.0, "height": 941.0, "z_index": 1, "color": "#dbeafe", "stroke": "#2563eb"},
        {"id": ids["note"], "type": "note", "position": {"x": 1130.0, "y": box_y + 12}, "label": args.name, "form": "rect",
         "width": 835.0, "height": 155.0, "z_index": zo + 1, "text_color": "#000000"},
        {"id": ids["bridge"], "type": "shape", "position": {"x": 954.0, "y": box_y + 189}, "label": "bridge", "form": "rect",
         "width": 138.0, "height": 88.0, "z_index": zo + 2, "icon": "switch"}]
    pos = next((p for p in m["positions"] if p["host_id"] == args.proxmox), None)
    if pos:
        pos["x"], pos["y"] = 434.0, host_y
    else:
        m["positions"].append({"x": 434.0, "y": host_y, "z_index": zo + 3, "host_id": args.proxmox})
    m["visual_links"].append({"anchors": {"source": {"side": "right", "ratio": 0.5}, "target": {"side": "left", "ratio": 0.5}},
                              "route": {"axis": "x", "tracks": [797.0]},
                              "z_index": max(v.get("z_index", 0) for v in m["visual_links"]) + 1, "id": ids["link"],
                              "source": {"kind": "host", "host_id": args.proxmox},
                              "target": {"kind": "object", "object_id": ids["bridge"]}, "label": "", "speed": "10G"})
    print(i18n.t("cli_inventory.zone_created", name=args.name, y=f"{box_y:.0f}", host_id=args.proxmox,
                 hostname=hosts[args.proxmox]["hostname"], host_y=f"{host_y:.0f}"))
    if args.apply:
        with inventory_lock(NET):
            backup(NET / "maps.yaml", "pre-zone")
            dump(maps, NET / "maps.yaml")
        print(i18n.t("cli_inventory.saved_run_place"))
    else:
        print(i18n.t("cli_inventory.dry_run"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=i18n.t("cli_inventory.description"), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register", help=i18n.t("cli_inventory.help_register")); r.add_argument("--spec", required=True); r.add_argument("--apply", action="store_true")
    p = sub.add_parser("place", help=i18n.t("cli_inventory.help_place"))
    p.add_argument("--proxmox", type=int, required=True, help=i18n.t("cli_inventory.help_proxmox"))
    p.add_argument("--hosts", type=int, nargs="*", help=i18n.t("cli_inventory.help_hosts"))
    p.add_argument("--labels", default="", help=i18n.t("cli_inventory.help_labels"))
    p.add_argument("--apply", action="store_true")
    a = sub.add_parser("append", help=i18n.t("cli_inventory.help_append"))
    a.add_argument("--proxmox", type=int, required=True); a.add_argument("--hosts", type=int, nargs="+", required=True)
    a.add_argument("--labels", default=""); a.add_argument("--apply", action="store_true")
    a.add_argument("--xy", nargs="*", default=[], help=i18n.t("cli_inventory.help_xy"))
    a.add_argument("--trunk", type=float, help=i18n.t("cli_inventory.help_trunk"))
    z = sub.add_parser("zone", help=i18n.t("cli_inventory.help_zone"))
    z.add_argument("--proxmox", type=int, required=True); z.add_argument("--name", required=True)
    z.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    return {"register": cmd_register, "place": cmd_place, "append": cmd_append, "zone": cmd_zone}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
