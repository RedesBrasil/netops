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
        sys.exit(f"Proxmox {spec['proxmox']} não existe no inventário")
    names = {h["hostname"] for h in hosts}
    ips = {h.get("mgmt_ip") for h in hosts}
    nxt = data["next_host_id"]
    new = []
    for item in spec["hosts"]:
        name = item["hostname"]
        if name != name.upper():
            sys.exit(f"{name}: hostname tem de ser TUDO MAIÚSCULO (AGENTS.md)")
        if name in names:
            print(f"- pulei {name}: já cadastrado"); continue
        if item["ip"] in ips:
            print(f"- pulei {name}: IP {item['ip']} já cadastrado"); continue
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
        print(f"+ host {e['id']}: {e['hostname']} ({e['mgmt_ip']}) runs_on {e['runs_on']}")
    if args.apply and new:
        with inventory_lock(NET):
            backup(NET / "hosts.yaml", "pre-register")
            data["hosts"] = hosts + new
            data["next_host_id"] = nxt
            dump(data, NET / "hosts.yaml")
        print("gravado.")
    elif not args.apply:
        print("(dry-run: nada gravado; use --apply)")
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
        sys.exit(f"Proxmox {args.proxmox} não está ligado a uma bridge no mapa '{MAP_ID}': ligue-o antes (host -> bridge)")
    bx, by = bridge["position"]["x"], bridge["position"]["y"]
    box = next((o for o in m["objects"] if o["type"] == "shape" and not o.get("label") and o.get("color")
                and o["position"]["x"] <= bx <= o["position"]["x"] + o["width"]
                and o["position"]["y"] <= by <= o["position"]["y"] + o["height"]), None)
    if not box:
        sys.exit("não achei a caixa azul (shape) que contém a bridge")
    bx0, by0 = box["position"]["x"], box["position"]["y"]
    labels = {int(k): v for k, v in (p.split("=", 1) for p in args.labels.split(",") if p)}
    pos = {p["host_id"]: p for p in m["positions"]}
    ids = args.hosts or sorted((i for i, h in hosts.items() if h.get("runs_on") == args.proxmox),
                               key=lambda i: (0, pos[i]["x"], pos[i]["y"]) if i in pos and bx0 <= pos[i]["x"] <= bx0 + box["width"]
                               and by0 <= pos[i]["y"] <= by0 + box["height"] else (1, i, 0))  # já na caixa: mantém a ordem; novos no fim
    n = len(ids)
    if not n:
        sys.exit("nenhum host com runs_on = proxmox; rode `register` antes")
    cap = int((box["height"] - FIRST_ROW - 20) // ROW_STEP)
    ncols = 1 if n <= 3 else max(MAX_COLS, math.ceil(n / cap))
    nrows = math.ceil(n / ncols)
    need_w = COL_OFFSET + COL_STEP * (ncols - 1) + 195 + 40  # largura útil: a caixa cresce se faltar espaço
    if need_w > box["width"]:
        print(f"caixa alargada: {box['width']:.0f} -> {need_w:.0f}")
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
    print(f"caixa ({bx0:.0f},{by0:.0f}) {box['width']:.0f}x{box['height']:.0f}; {n} hosts em {ncols} col x {nrows} lin; bridge centro y={center:.0f}")
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
        print(f"  {hosts[hid]['hostname']} (host {hid}) -> col {c + 1} lin {r + 1} ({x:.0f},{y:.0f}) {link['label']}")
    bridge["position"] = {"x": float(bx0 + 71), "y": float(center - 44)}
    order = ["anchors", "route", "z_index", "id", "source", "target", "label", "speed"]
    m["visual_links"] = [{k: v[k] for k in order if k in v} | {k: v[k] for k in v if k not in order}
                         for v in m["visual_links"]]
    if args.apply:
        with inventory_lock(NET):
            backup(NET / "maps.yaml", "pre-place")
            dump(maps, NET / "maps.yaml")
        print("gravado. Peça para recarregar o mapa (a tela aberta com estado antigo sobrescreve).")
    else:
        print("(dry-run: nada gravado; use --apply)")
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
    bridge = find_bridge(m, objs, args.proxmox) or sys.exit("Proxmox sem bridge no mapa")
    pos = {p["host_id"]: p for p in m["positions"]}
    links = [v for v in m["visual_links"] if v["source"].get("object_id") == bridge["id"] and v["target"].get("host_id") in pos]
    cols = {}
    for v in links:
        cols.setdefault(round(pos[v["target"]["host_id"]]["x"]), []).append(v)
    if not cols:
        sys.exit("bridge sem hosts ligados: use `place`")
    labels = {int(k): v for k, v in (p.split("=", 1) for p in args.labels.split(",") if p)}
    zp = max(p["z_index"] for p in m["positions"]) + 1
    zl = max(v.get("z_index", 0) for v in m["visual_links"]) + 1
    xy = [tuple(float(n) for n in c.split(",")) for c in args.xy]
    if xy and len(xy) != len(args.hosts):
        sys.exit("--xy precisa de uma coordenada x,y por host")
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
                sys.exit(f"{hosts[hid]['hostname']} não cabe embaixo da coluna; use --xy x,y [--trunk X] ou aumente a caixa")
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
        print(f"  {hosts[hid]['hostname']} (host {hid}) -> x={x:.0f} y={y:.0f} {link['label']}")
    if args.apply:
        with inventory_lock(NET):
            backup(NET / "maps.yaml", "pre-append")
            dump(maps, NET / "maps.yaml")
        print("gravado. Peça para recarregar o mapa.")
    else:
        print("(dry-run: nada gravado; use --apply)")
    return 0


def cmd_zone(args) -> int:
    """Cria a zona de um Proxmox ainda sem caixa: caixa azul 1328x941 + nota de título + bridge + ligação host -> bridge."""
    hosts = {h["id"]: h for h in load("hosts.yaml")["hosts"]}
    maps = load("maps.yaml")
    m = next(x for x in maps["maps"] if x["id"] == MAP_ID)
    objs = {o["id"]: o for o in m["objects"]}
    if find_bridge(m, objs, args.proxmox):
        sys.exit("esse Proxmox já tem bridge/zona no mapa")
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
    print(f"zona '{args.name}': caixa y={box_y:.0f}, host {args.proxmox} ({hosts[args.proxmox]['hostname']}) em (434,{host_y:.0f})")
    if args.apply:
        with inventory_lock(NET):
            backup(NET / "maps.yaml", "pre-zone")
            dump(maps, NET / "maps.yaml")
        print("gravado. Agora rode `place` para os hosts.")
    else:
        print("(dry-run: nada gravado; use --apply)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register"); r.add_argument("--spec", required=True); r.add_argument("--apply", action="store_true")
    p = sub.add_parser("place")
    p.add_argument("--proxmox", type=int, required=True, help="ID do host Proxmox (runs_on)")
    p.add_argument("--hosts", type=int, nargs="*", help="IDs e ordem (padrão: todos com runs_on = proxmox)")
    p.add_argument("--labels", default="", help="rótulos por host: 37=VLAN3000,55=vmbr1")
    p.add_argument("--apply", action="store_true")
    a = sub.add_parser("append", help="acrescenta hosts numa caixa com desenho próprio, sem reorganizar")
    a.add_argument("--proxmox", type=int, required=True); a.add_argument("--hosts", type=int, nargs="+", required=True)
    a.add_argument("--labels", default=""); a.add_argument("--apply", action="store_true")
    a.add_argument("--xy", nargs="*", default=[], help="posições à mão, uma 'x,y' por host (caixa cheia)")
    a.add_argument("--trunk", type=float, help="x do tronco da linha (com --xy)")
    z = sub.add_parser("zone", help="cria a caixa/nota/bridge de um Proxmox que ainda não tem zona no mapa")
    z.add_argument("--proxmox", type=int, required=True); z.add_argument("--name", required=True)
    z.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    return {"register": cmd_register, "place": cmd_place, "append": cmd_append, "zone": cmd_zone}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
