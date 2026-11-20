# STANDARD — `scripts/`

Python scripts that the `executor` agent (access) and the `tester` (diagnostics/analysis) invoke
through the terminal. The "intelligence" stays in the agents; the deterministic technical work stays here.

## Default access stack

Answer to the question "raw SSH, Paramiko or Telnet?": do **not** use raw SSH or Telnet as the
default. The default layer is **Netmiko** — it uses Paramiko underneath, but already handles
prompt/paging and talks to 100+ vendors via `device_type`.

| Layer | Library | Role |
|-------|---------|------|
| Multi-vendor SSH/Telnet | **Netmiko** | Default for running CLI commands |
| Structured collection + diff | **NAPALM** | Cisco/Juniper/Arista — getters and `compare_config` |
| MikroTik API | **librouteros** | RouterOS via the native API (structured data) |
| Port/security scan | **nmap** (binary) | `portscan.py`, `security_assessment.py` |

## Structure

`scripts/` separates the NetOps **engine** (static infrastructure) from the **operational scripts**
(what the user creates/edits). Only the operational ones appear on the console's **Scripts / Skills** page.

### `engine/` — NetOps engine (does not appear in the UI)

| Folder | Content |
|--------|---------|
| `engine/lib/` | Reusable core — `inventory.py`, `vendor_map.py`, `transport.py` |
| `engine/vault/` | Credential vault — CLI `init`/`encrypt`/`unlock`/`lock`/`status`/`change-password` |
| `engine/ui/` | Web console (FastAPI + SPA). ALWAYS start it with `scripts/engine/ui/start.sh` |

`engine/update/` contains the distribution policy, GitHub client, package, snapshot, journal and
ephemeral update supervisor. `SKILL.md` documents usage and recovery. The Python modules
follow the engine separation, do not appear as operational scripts and never connect to devices.

### `tools/` — operational scripts (CRUD through the UI)

| Folder | Content |
|--------|---------|
| `tools/access/` | Connection to devices — `session.py` (the only one for SSH/Telnet: `run` and `open/exec/close`), `api_mikrotik.py` |
| `tools/diagnostics/` | Network diagnostics — `portscan.py`, `ping_advanced.py`, `traceroute_advanced.py` |
| `tools/analysis/` | Analysis — `security_assessment.py`, `config_diff.py` |
| `tools/docs/` | Documentation generation — `topology_render.py` |
| `tools/_TEMPLATE/` | Template (`SKILL.md` + `script.py`) to create a new script/family |

## Standard of a script

- Python 3, runnable as `python3 scripts/tools/<family>/<script>.py [args]`.
- **Enters the venv by itself:** right after the bootstrap's `sys.path.insert` and BEFORE any external lib,
  `from lib._venv import ensure_venv; ensure_venv()` (already in the `_TEMPLATE`). This way nobody needs to
  activate `.venv` or install anything to run a script.
- `argparse` with a clear `--help`. Works offline (network imports are lazy).
- Always reads the inventory via `from lib.inventory import …` (the engine in `engine/lib/`,
  put on `sys.path` by the script's bootstrap) — never receives a credential as an argument.
- Selects the numeric identity with `--host-id <integer>`; `--host <hostname-or-alias>`
  keeps compatibility by unique name. Diagnostics use `include_credentials=False`
  and `resolve_host(..., {}, decrypt=False)`, without reading or decrypting credentials.
- Output in JSON or text; when it saves, it saves in `runs/<id>/`.
- Each family has a `SKILL.md` next to it describing usage (OpenSquad format); it
  appears as a 📄 icon next to the family's scripts in the UI.
- Visible messages (help, output, errors) go through `i18n.t()` (see `core/rules/i18n.md`).

## How to add a script

Copy `scripts/tools/_TEMPLATE/` (it has `SKILL.md` + `script.py`), implement it, and — if it is
a new family — create the folder's `SKILL.md`. Or create it directly from the **Scripts / Skills** page of the
web console (**+ New** button, path `family/file.py`).


### Visual editor of the console

`engine/ui/maps/` contains the JSX editor and its maintenance build. It is an isolated exception to the
build-less SPA: the operator receives the ESM/CSS module already generated in `static/vendor/`. npm is not
needed to start the console. It keeps a shared Preact and pinned local dependencies.
The usage pattern and structure are in `engine/ui/maps/SKILL.md`.


The editor's image library lives in `engine/ui/static/icons/network/`, with originals,
catalog, thumbnails and checksums. `engine/ui/vendor_icons.py` updates these assets from
a fixed revision, without being run on the server. See the local README and `engine/ui/SKILL.md`.
