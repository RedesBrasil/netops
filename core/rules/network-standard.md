# STANDARD — `network/` (Inventory and Topology)

This folder is the **source of truth of the network**. The agent only knows the devices described here.

## Files

| File | Versioned? | What it is |
|------|------------|------------|
| `hosts.yaml` | no | Inventory of devices and how to access them |
| `credentials.yaml` | **NO** (git-ignored) | Credentials (encrypted vault `enc.v1:`, or plaintext) |
| `credentials.example.yaml` | yes | Credentials template, without real secrets |
| `topology.yaml` | no | Links between hosts (logical/physical map) |
| `topology.md` | no | Mermaid diagram generated from `topology.yaml` |
| `maps.yaml` | no | Presentation of the maps, positions, shapes, texts and paths |
| `maps.example.yaml` | yes | Presentation template, without real data |

## `hosts.yaml`

Structure: `groups` (inherited defaults) + `hosts`. A host inherits the fields of its `group`
and may override any of them.

Inventory v2 uses `hosts` as a list of records with a positive and immutable integer `id`.
`next_host_id` is incremented in the same write that creates the host and never decreases, even after
deletions. The console generates the ID; the operator provides only the hostname and the other fields.
`legacy_aliases` associates previous names with the integer for script compatibility,
including reserving aliases of deleted hosts. IDs are numeric values in the YAML/JSON.
v1 files remain readable, but need an explicit migration before editing.

v2 links use integers in `a.host`/`b.host`. v2 maps use integer members, positions
as a list of `{host_id, x, y, z_index?}` and visual endpoints typed by `kind`.
The v3 backup configuration uses `targets.hosts` with integers and `legacy_sources` to
associate historical folders with the registry. New collections go to `backups/by-id/<id>/`.
The inventory remains the only source of devices; historical files do not
create hosts. The `.inventory.lock` lock and the `.host-id-migration.json` journal are private
and git-ignored; they contain no credentials.

Fields of a host:

| Field | Required | Values |
|-------|----------|--------|
| `id` | yes, generated | Positive integer, unique, permanent; not editable through the UI/API |
| `hostname` | yes | FQDN or name |
| `mgmt_ip` | yes | Management IP |
| `extra_ips` | optional | Up to 20 additional IPs, each `{ip, role?, description?}` (e.g.: public, internal, VIP). `ip` accepts IPv4/IPv6 with an optional mask; no repeats among them or with the `mgmt_ip`. Informational only: the scripts connect through the `mgmt_ip` |
| `vendor` | yes (host or group) | `mikrotik`, `unifi`, `ubiquiti`, `cisco`, `huawei`, `proxmox`, `vmware`, `datacom`, `linux`, `fiberhome`, `intelbras`, `zabbix` |
| `model` | recommended | Device model |
| `os` | recommended | Operating system/firmware **as the device itself reports it** (`/etc/os-release`, `/system resource`): `ROUTEROS`, `DEBIAN`, `UBUNTU`. Inheritable from the group |
| `os_version` | recommended | OS version (`7.23.4`, `12.15`, `22.04.5`). Inheritable from the group |
| `apps` | optional | List of what runs **on top of** the OS, the 1st is the main one: `[{name: ZABBIX SERVER, version: 7.0.32}]` (max. 10). E.g.: Debian CT with Zabbix → `os: DEBIAN`, `apps: [ZABBIX SERVER]`; Proxmox → `os: DEBIAN` + `apps: [PROXMOX VE]`; MikroTik → only `os: ROUTEROS` |
| `runs_on` | optional | ID of the host that hosts this one (CT/VM → hypervisor). Informational only; deleting the host machine clears the reference |
| `version` | legacy | Old field (OS **or** app in a single text). Still read; the screen shows it in gray and removes it when saving with OS/applications filled in |
| `icon` | optional | ID from the local library: `router`, `switch`, `linux-server`, `windows-server`, `access-point`, `olt`, `cloud`, `pc`, `proxmox`, `vmware` |
| `role` | recommended | `core`, `distribution`, `access`, `firewall`, `wireless`, `server`, `other` |
| `access.method` | yes (host or group) | `ssh`, `telnet`, `api`, `winbox` |
| `access.port` | yes (host or group) | TCP port |
| `credential` | yes (host or group) | Name of the credential in `credentials.yaml` |
| `site` | recommended | Physical location |
| `group` | optional | Name of the group it inherits from |
| `notes` | optional | Free notes |

Validate: `python3 scripts/engine/lib/inventory.py --validate` (uses `core/schemas/inventory.schema.json`).

## `credentials.yaml`

**Named** credentials (`cred_<something>`) that the hosts reference by name — so the same
password is not repeated.

Fields of a credential: `username`, `password`, and the optional `secret` (Cisco enable),
`key_file` (SSH key), `api_ssl`.

**Encryption (vault).** Passwords can be encrypted with a master password: each secret
value becomes `enc.v1:<token>` and is decrypted only in memory, during the session. Manage it with
`scripts/engine/vault/cli.py` (`init` → `encrypt` → `unlock`/`lock`); see `scripts/engine/vault/SKILL.md`. The
decryption happens only in `scripts/engine/lib/inventory.py:resolve_secret()` — the hosts never change,
and mixed files (part plaintext, part `enc.v1:`) are valid.

## `topology.yaml`

List of `links`: each link has `a` and `b` with a required `host` and an optional `port`.
`media`, `speed` and `desc` are also optional. The interfaces can be provided later.
Optionally `segments` (VLANs/subnets). The script `scripts/tools/docs/topology_render.py` reads
this file + `hosts.yaml` and regenerates `topology.md` with a Mermaid diagram.

## How to add a device

1. Add the host to `hosts.yaml` (use an existing `group` or create one).
2. If the credential is new, add it to `credentials.yaml`.
3. Add its links to `topology.yaml`.
4. Run `python3 scripts/tools/docs/topology_render.py` to update `topology.md`.


## `maps.yaml`

The **Maps** page of the console reads the single registry in `hosts.yaml` and the links in
`topology.yaml`. The maps file stores only presentation and references:

- `kind: all`: general map, always with all hosts.
- `kind: site`: automatic map per effective `site` of the host, including group inheritance.
  If a single location contains all hosts, its view is unified into `all`, without
  duplicating the selector. The general layout takes precedence, and adjustments exclusive to the location
  are incorporated. Old references point to the general map; `custom` maps are kept.
- `kind: custom`: additional map, with an explicit association in `members`.
- `positions`: coordinates per host ID. The registry is not duplicated.
- `objects`: texts (`note`), shapes (`shape`) and shortcuts to other maps (`reference`).
  Shapes accept an optional `icon` from the local catalog, without an IP or a record in the inventory.
- `edges`: layout per stable ID of the real link: `anchors` and `route`.
- `visual_links`: visual connections between hosts, shapes and map references. When an
  endpoint is a shape, the connection stays only in this map, without creating a host or a physical link in the
  inventory. Connections between two hosts stay in `topology.yaml`. They do not go into the Mermaid diagram.

The IDs of legacy links are pinned in `topology.yaml` on the first graphical edit.
Editing a link on the map preserves the ID; removing a link clears its paths.
Renaming a host updates the maps and the topology. Deleting a host also removes its links and
visual references, after confirmation in the UI. Removing a host from an additional map only
removes the association: the device stays in the inventory and in the general map.

Creating a device from the map and positioning it is a coordinated operation on hosts and maps,
with review, backup and rollback on failure. The map does not connect to devices.

The real `network/maps.yaml` is git-ignored. Only the examples are versioned. GET does not create
files; without a saved layout, the initial position is calculated by the console.


The align horizontal/vertical actions save the positions of the whole group in a single
edit of the map, with 24 units of spacing between the edges. The selection of devices is
transient and is not written to the YAML. The alignment uses the measured dimensions, keeps the visual
order and does not change nodes outside the group or the paths/anchors of the connections.
