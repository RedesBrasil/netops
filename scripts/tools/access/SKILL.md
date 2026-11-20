---
id: device-access
name: Equipment Access
type: script
runtime: python
description: Connects to inventory equipment (SSH/Telnet via session.py, MikroTik API) and runs commands.
env: []
---

## What it does

Family of scripts the `executor` agent uses to connect to network equipment and
run commands — collection (read-only) or configuration changes.

| Script | Access | Library |
|--------|--------|-----------|
| `session.py` | **SSH/Telnet — the ONLY CLI script** (`run` = batch; `open`/`exec`/`close` = persistent) | Netmiko + Paramiko exec channel (Linux) |
| `api_mikrotik.py` | RouterOS API (structured data, only if `access.method: api`) | librouteros |
| (console) **Access → Web** | Not a script: a console button opens Proxmox/Zabbix already logged in (`lib/web_login`, see `memory/web-launch-acessar-web-login-automatico.md`). Request "open the web interface of host X" = ask the human to click Access → Web | — |
| `terminal_link.py` | **Does not connect**: generates the link that opens the host's web terminal in a console window (request "open the edge router for me") | — |

`ssh.py` and `telnet.py` **no longer exist** (removed on 12/11/2026): `session.py` does everything
they did. The engine (console backup etc.) uses the `scripts/engine/lib/cli_runner.py` library.

## Recipe — copy and run (no preparation)

System `python3` (or `python`); the script **enters** the project's `.venv` **on its own** — do not activate a venv,
do not install anything. Always from `/opt/netops` (or an absolute path). Host by `--host-id <ID>`
(ID from `network/hosts.yaml`) or `--host <name/alias>`.

```bash
# DEFAULT — persistent session per host (1 login per host, N commands, state kept)
python3 scripts/tools/access/session.py exec --host-id 21 --command "/ip address print"   # login + open
python3 scripts/tools/access/session.py exec --host-id 22 --command "ip -br addr"         # another host, another session
python3 scripts/tools/access/session.py exec --host-id 21 --command "/ip arp print"       # REUSES (no login)
python3 scripts/tools/access/session.py exec --host-id 21 --command "/ping 192.0.2.2" --timing --timeout 5
python3 scripts/tools/access/session.py list                       # open sessions, idle/limit
python3 scripts/tools/access/session.py close --host-id 21         # or close --all (or wait for idle)

# Isolated batch (connects, runs, disconnects — no reuse): only for one-off collection
python3 scripts/tools/access/session.py run --host-id 21 --command "/system identity print"

# Explicit SESSION_ID (rare): S=$(... open --host-id 21) [--new forces another] → exec --session $S → close --session $S
# Telnet (only if the user asks / legacy equipment): add --telnet to exec/open/run
```

Which to use: **`exec --host-id`** whenever there is more than one command on the same host, even in separate
calls (command → read output → decide the next one) and even when alternating between several hosts: each host
keeps its session open (measured: Linux 0.02–0.05 s/command, MikroTik ~0.9 s, versus 1.4–1.6 s+ of
login on every new connection). It keeps state (`enable`, context, variables/`cd` on Linux) and does not flood the
equipment log with logins. `run` only for an isolated collection. Do not use the system's `ssh`/`sshpass`/`telnet`:
only `session.py` resolves the vault credential without exposing it.

## Behavior

- Linux (`vendor` linux/proxmox): **1 login + 1 persistent shell** (`bash -l`, or `sh -l`) per
  session/`run`. All commands run in the SAME shell (same `$$`): `export`, `cd`, functions,
  `source` (e.g. `. ~/.nvm/nvm.sh`) and venv **persist** across `exec`s — with a real exit code and separate
  stderr (no PTY; end of command detected by a random marker). `modo=shell-persistente`.
  - Commands' stdin = `/dev/null` (no interactive prompts; `read` returns immediately).
  - `exit`/`set -e` that kills the shell: returns the output and the exit code; the next command starts a
    new shell **in the same login** and warns `AVISO: shell novo — variáveis/cd anteriores foram perdidos` (new shell — previous variables/cd were lost).
  - Background process that must survive `close`: `setsid nohup cmd >/tmp/x.log 2>&1 &`.
  - Host without `base64`/restricted shell: falls back on its own to `modo=exec-por-comando` (no state).
  - `--shell` forces the Netmiko shell with PTY (rare: only for a command that requires a terminal; no exit code).
- Network (MikroTik/Cisco/Huawei...): a single Netmiko shell per session — context/`enable` persist.
- Continuous/paged command (ping without count, `/tool torch`): `--timing --timeout N` reads for N s,
  sends Ctrl-C and returns the output (`status=interrompido`, rc 0).
- `status=timeout` (rc 3): interrupts (Ctrl-C on network devices; SIGINT to the shell's children on Linux) — the
  session and the state stay alive. If even that does not bring it back (loop in a builtin), the shell is killed and the next
  command opens another one (with the lost-state warning). With several
  `--command`, it stops at the first one that fails. Connection drop: reconnects **before** the next command and
  **never resends** what was in progress.
- Multiline command/complex quoting: send it in base64 (`echo <b64> | base64 -d | sh`) or use
  `--commands-file` (one command per line, with `run`).
- A persistent session closes on its own after **`access.session_idle_minutes`** without a command (default **5 min**;
  `core/config/project-config.yaml` or console → **Settings** → "Equipment access session").
  Re-read every 5 s by the sessions: changing the config takes effect immediately, even for sessions already open.
  `NETOPS_SESSION_IDLE=<seconds>` overrides it (tests). Maximum life 2 h (`NETOPS_SESSION_MAX`). The vault
  must be unlocked only to OPEN; an already open session keeps working if it gets locked again.
  Socket in `$XDG_RUNTIME_DIR` or `/tmp/netops-sessions-<uid>/` (0700/0600); reuse under a per-host lock.
- Audit: every command/output (run or session) goes to `runs/<ts>-session-<id>/session.log` — `run`
  prints the path at the end (`[log] ...`). That is the "save the collection"; there is no `--save`.
- The credential only exists inside the process; the vault must be unlocked (otherwise it fails with
  a clear instruction — the human runs `python3 scripts/engine/vault/cli.py unlock`).
- Configuration changes follow the same rules: baseline + rollback first (workflow apply-config-change).

## Exit codes

`0` ok · `1` host not in the inventory / login failure / vault locked · `2` no command ·
`3` command with status ≠ ok (stopped the sequence) · `4` session missing/dead (run `open` again) ·
other = exit code of the Linux command.

## Host

`--host-id` takes the integer, automatic and immutable ID from the inventory. `--host` accepts a unique name or
legacy alias. The options are mutually exclusive; numeric text passed to `--host` is treated as a name/alias.
The connection uses the management IP and port from the inventory (`access.port`), never the ID as an address.
Never connect to a host outside `network/hosts.yaml`.

## MikroTik API

```bash
python3 scripts/tools/access/api_mikrotik.py --host-id 1 --path /ip/service --path /user
python3 scripts/tools/access/api_mikrotik.py --host rt-core-01 \
  --path /ip/firewall/filter --path /ip/service --path /snmp --save
```

`--save` writes to `runs/<run>/collected/<integer-id>.json`.

## Setup

None per call. At installation: `.venv` with `requirements.txt` (netmiko, librouteros) — see
`README.md`. Credentials come from `network/credentials.yaml` — never pass a password as an argument.
