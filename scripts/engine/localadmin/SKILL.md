---
id: localadmin
name: Local administration (root on this server, without SSH)
type: script
runtime: python
description: Runs operations as root on the NetOps server itself through the Local host, with the local admin password in the vault (the AI never sees it).
env: []
---

## Model

- NetOps runs as the `netops` account (no sudo). Root on the **server itself** is **per operation**.
- The installer creates `netops-admin` (random password, never shown, only in the vault as `CRED_LOCAL_ADMIN`)
  and `/etc/sudoers.d/netops-admin` (`NOPASSWD: ALL` **only** for it; SSH blocked for it).
- The user service `netops-localadmin@<instance>` (`daemon.py`) authenticates `su - netops-admin` in a private
  PTY (echo off, password only in memory), checks the effective UID `0` via a marker, runs the command with a
  clean environment (`env -i`, nothing from the `netops` account) and a root-side `timeout`, and returns the output.
  It is separate from the console and the AI: AI processes cannot inspect its memory.
- The **Local** host (`access.method: local`, e.g. `NETOPS-LOCAL`) is created by the installer, bound to the credential
  and to this installation's ID (`local_instance`) and is **protected**: it cannot be deleted; access/credential/IP/binding do not change.
- To use it: **vault unlocked** + user with **`server.admin`** (admin only). Without that, it fails closed with a code.

## Usage (AI and human)

```bash
# as root, one operation per command (no SSH; there is no persistent root shell)
python3 scripts/tools/access/session.py exec --host-id <ID-LOCAL> --timeout 900 --command "apt-get update && apt-get install -y htop"
# backup before/after (mandatory for changes, as on any host)
python3 scripts/tools/backup/change.py begin --host-id <ID-LOCAL> && python3 scripts/tools/access/session.py exec --host-id <ID-LOCAL> --command "..." ; python3 scripts/tools/backup/change.py end --host-id <ID-LOCAL>
# status (no secrets)
python3 scripts/engine/localadmin/cli.py status
```

`cd`/`export` do not carry over from one command to the next — join them in the same one (`cd /x && ...`). A command that does not
need root runs directly in Bash. Files as root: menu **Files → 🔓 Open as root** (short session
of 5 min, red banner, audited; never available to the AI).

> Main path today: `sudo <command>` directly (allowed only with the vault unlocked — see AGENTS.md). The Local
> host remains valid as an alternative.

## Errors (fail closed — tell the human and stop; never try su/SSH)

| Code | Meaning / what to do |
|---|---|
| `vault_locked` | Vault locked: the human runs `python3 scripts/engine/vault/cli.py unlock` (or logs into the console) |
| `authorization_denied` | User without `server.admin` (or request without `NETOPS_USER` in multi-user mode) |
| `local_access_disabled` | Disabled: `sudo python3 -I scripts/engine/localadmin/provision.py enable` |
| `credential_missing` / `authentication_failed` | Password missing/rejected: `sudo python3 -I scripts/engine/localadmin/provision.py rotate` (no automatic retry; there is a 2 min wait after a failure) |
| `binding_mismatch` | Clone/restore on another machine: `sudo python3 -I scripts/engine/localadmin/provision.py rebind` |
| `backend_unavailable` | Service stopped: `systemctl --user status netops-localadmin@<instance>` (as netops) |
| `timeout` | Deadline exceeded: the partial effect must be checked — **there was no rollback** |

## Administration (root, stdlib only, `python3 -I`)

```bash
sudo python3 -I scripts/engine/localadmin/provision.py install   # account, sudoers, vault, Local host, service
sudo python3 -I scripts/engine/localadmin/provision.py rotate    # new password (also recovers a lost vault)
sudo python3 -I scripts/engine/localadmin/provision.py disable   # locks netops-admin (passwd -l)
sudo python3 -I scripts/engine/localadmin/provision.py enable
sudo python3 -I scripts/engine/localadmin/provision.py rebind    # revalidates the binding (clone/restore)
sudo python3 -I scripts/engine/localadmin/provision.py status
```

Audit: `runs/localadmin/audit.jsonl` (0600) + journal/syslog (`netops-localadmin`, AUTHPRIV) + the system
authentication log (`su`). No password, authentication prompt or environment is logged.

## Limits (documented in the 2026-11-19 plan)

- Unrestricted local root is a broad administrative capability. With the vault unlocked, another process of the **same**
  `netops` account can request operations from the service: the UID is not a strong boundary — only trusted people with shell/AI.
- The package manager has no universal rollback: say beforehand what is irreversible.
- Installing Docker ≠ giving the application control of the daemon: `netops` never joins the `docker` group by default.
- Scheduled tasks do not use local root (initial scope).
