---
id: inventory-map
name: Discover hosts and organize them on the map
type: script
runtime: python
description: Discovers CTs/VMs of a Proxmox, registers them in the inventory and places them on the map inside the Proxmox box, with right-angle lines.
env: []
---

## What it does

Recipe (and script) for "register the running containers of Proxmox X in the inventory and on the map":
discovers what is running, registers it in `network/hosts.yaml` and places it on the **Rede geral** map (map `all`, the general network map) inside the
Proxmox's blue box, linked to the bridge with right-angle lines — the same drawing as Proxmox Techify.

## When to use

A request to register/map CTs, VMs or "everything that runs on Proxmox X". Also to reorganize a Proxmox
whose drawing ended up outside the box or with diagonal lines.

## Step by step

**1. Choose the Proxmox.** Find it in `network/hosts.yaml`. If there is more than one candidate (e.g. two "PROXMOX TESTES"),
**ask which one** (`AskUserQuestion`); do not register on both by guessing.

**2. Discover what is running** (read-only, one session per host, `session.py exec`):

```bash
python3 scripts/tools/access/session.py exec --host-id <PVE> --command "pct list; qm list"
```

"Running containers" = `pct list` with `running`. VMs (`qm list`) only if the user asks; say that they were left out.
Then collect the details of each running CT in a single command (config + OS + IP + ports + docker):

```bash
python3 scripts/tools/access/session.py exec --host-id <PVE> --command 'for i in <CTs>; do echo "== $i $(pct config $i | grep -E "^(hostname|cores|memory|ostype)" | tr "\n" " ") $(pct config $i | grep -oE "ip=[^,]*,|tag=[0-9]+|bridge=[a-z0-9]+" | tr "\n" " ")"; pct exec $i -- sh -c ". /etc/os-release; echo \$PRETTY_NAME; ip -4 -o addr show scope global | awk \"{print \\\$2,\\\$4}\"; ss -tlnH | awk \"{print \\\$4}\" | sed \"s/.*://\" | sort -un | tr \"\n\" \" \"; echo; command -v docker >/dev/null && docker ps --format \"{{.Names}}\" | head -8 | tr \"\n\" \" \"" 2>&1 | head -8; done'
```

It gives hostname, vCPU/RAM, bridge/VLAN (`tag=`), IP, OS, ports and Docker containers (the `apps` come from here). A CT without a fixed `ip=` = DHCP
(say so in the note "IP pode mudar" — IP may change). A CT with a **public** IP directly on the bridge deserves to be highlighted in the note.

**3. Check what already exists** before registering: `grep -n "mgmt_ip: <IP>" network/hosts.yaml` and by name. `register`
skips a repeated name or IP. A name equal to another host's (e.g. two `PROXY-TESTE` on different Proxmox) → use a suffix
(`PROXY-TESTE-DESKTOP`) and say so in the answer; the name inside the Proxmox is not renamed without a request (requires `change.py begin/end`).

**4. Register** (`register`). Rules: hostname **ALL UPPERCASE** with hyphens; `runs_on` = Proxmox ID; note
`CT N do <PROXMOX> (host P)`; `group: LINUX-SERVERS`, `icon: linux-server`, `model: LXC`. Write the spec outside `/tmp`
(e.g. `/var/tmp/netops-inv/spec.yaml`) and delete it at the end.

```bash
python3 scripts/tools/inventory/map_place.py register --spec /var/tmp/netops-inv/spec.yaml          # dry-run
python3 scripts/tools/inventory/map_place.py register --spec /var/tmp/netops-inv/spec.yaml --apply  # writes
```

**5. Place on the map** (`place`). Runs over **all** hosts with `runs_on` = the Proxmox (reorganizes the whole box).
Line labels: `VLANxxxx` for whatever has `tag=` in `pct config`; the bridge name (`vmbr1`, `vmbr2`) for an internal network without VLAN;
empty for the default network.

```bash
python3 scripts/tools/inventory/map_place.py place --proxmox <PVE> --labels 37=VLAN3000,55=vmbr1          # dry-run
python3 scripts/tools/inventory/map_place.py place --proxmox <PVE> --labels 37=VLAN3000,55=vmbr1 --apply
```

**5b. A box that already has its own drawing** (Redes Brasil, Techify) **is not reorganized**: use `append` (puts the host under the least full column) and, if the
box is full, `--xy x,y [...] --trunk X` (manual position, e.g. in the gap between two existing rows). A Proxmox **without a zone** on the map
(e.g. Wholesale): `zone --proxmox <ID> --name "Proxmox X" --apply` creates box + note + bridge below the last one and puts the host in the
Proxmox column; then `place`. `place` widens the box on its own when it goes over 15 hosts (4+ columns).

```bash
python3 scripts/tools/inventory/map_place.py append --proxmox <PVE> --hosts <IDs> [--labels ID=vmbr1] [--apply]
python3 scripts/tools/inventory/map_place.py zone --proxmox <PVE> --name "Proxmox X" --apply
```

**6. Tell the user to reload the map.** The open screen keeps the old state and, if they change anything, it overwrites the file.

## Sweep of ALL Proxmox (without duplicating)

For each Proxmox in the inventory (`icon: proxmox`, currently 14–18): list the running `pct list`/`qm list`, get each one's IP (`pct exec`) and compare
with `hosts.yaml` **by IP and by name**. Beware of false positives: the same private IP repeats in different internal networks (`192.168.100.1` is
both the Vivo modem AND the MANAGER-ATLAS bridge; `10.8.100.x` shows up on several Proxmox) — decide by name + `runs_on` + note "CT N do …", not only
by IP. The same CT can have 2 IPs while the inventory keeps only one. VM without guest agent: find the IP by MAC (`qm config` → `net0`) with a ping sweep of the
network on the bridge (`seq 1 254 | xargs -P64 -I{} ping -c1 -W1 10.8.200.{}`) and `grep -i <mac> /proc/net/arp` on the Proxmox; CHR router = gateway IP of the
CTs on the same bridge (`pct exec <ct> -- ip route`), marking "deduzido" (deduced) in the note. Finish with `inventory.py --validate` and check that IDs, names and IPs are unique.
Hosts that stay **off** the map by design: the labs' CHRs (MK-00-201..204) and Techify's 2nd group (linked to the proxy, green lines of the topology).

## How the map works (lessons learned)

- Each Proxmox has 3 things in `network/maps.yaml` (map `all`): the Proxmox **host** (column x≈435), a **bridge** (`type: shape`,
  `label: bridge`) and a **blue box** (`type: shape` without label, `color: '#dbeafe'`, 1328×941) with a title **note**
  (`type: note`, e.g. "Proxmox Testes HP"). The large text at the top of the box is the note; the shape is the shape. **New hosts must
  stay INSIDE the box** (x 883–2211, y from the top to +941); whatever leaves the box "ended up outside the shape".
- A map has `positions` (host_id, x, y, z_index), `objects` (shapes/notes) and `visual_links` (bridge → host). Lines **without** `anchors`
  and `route` come out diagonal; for the right angle each link carries
  `anchors: {source: {side: right, ratio: 0.5}, target: {side: left, ratio: 0.5}}` and `route: {axis: x, tracks: [X]}`, where `X` is the
  vertical gap (trunk) between the bridge/previous column and the host's column.
- Techify geometry (copied by the script): column 1 at x = box + 308, column step 297, rows every 134 (host ≈ 105
  high), 1st row at +176 from the top, **max. 3 columns × 5 rows** (15 hosts) per box; trunk = column x − 52.
- The **bridge** sits at x = box + 71 with its center **in the gap between two rows**, because the horizontal line of columns 2 and 3 leaves
  from the center of the bridge and would pass over a host. That is why the script moves the bridge.
- Filling by column (column 1 top to bottom, then column 2…), grouping by affinity (e.g. proxy + coolify of each customer in the
  same column).
- The map is also written by the console: use the lock (`inventory_lock`, the script already uses it) and always make a copy first
  (`runs/copias-seguranca/network/`, never `.bak` next to it). `maps.yaml` and `hosts.yaml` are git-ignored (they go in the full backup).
- Does not touch `topology.yaml`: containers only appear on the map, never there.

## Examples

```bash
python3 scripts/tools/inventory/map_place.py place --proxmox 17 --labels 55=vmbr1,56=vmbr2,57=vmbr2 --apply
```
