---
id: identity-migration
name: Migration to the dedicated netops account
type: script
runtime: python
description: Migrates a legacy installation (console as root) to the netops operational account, with dry-run, baseline, journal and rollback.
env: []
---

## When to use

An old installation (before layout 2) runs the console as **root**: `install.sh` and the console warn
"instalação LEGADA" (LEGACY installation). The migration makes the console, AI, terminal, scheduler and updater run as `netops`.
**Only root runs it** (the human, in a maintenance window) — never the AI on its own.

## Step by step

```bash
sudo python3 -I /opt/netops/scripts/engine/identity/migrate.py plan      # dry-run: inventory + blockers
# recommended in production: external snapshot/backup of the VM/CT first (e.g. pct snapshot <CT> antes-netops)
sudo python3 -I /opt/netops/scripts/engine/identity/migrate.py apply     # console goes down ~1 min
#   validate: login, Claude tab (/login again), conversations and memory, scheduled tasks
sudo reboot                                                              # confirms boot without login
sudo python3 -I /opt/netops/scripts/engine/identity/migrate.py commit
# Local administration (separate step, with the vault unlocked)
sudo python3 -I /opt/netops/scripts/engine/localadmin/provision.py install
```

Before `commit`, `migrate.py rollback` restores the old owner/mode, unit and cron and turns the root console back on.
New data is preserved; the database is **not** restored blindly (the pre-migration copy is in the baseline).

## What changes

| Before | After |
|---|---|
| root console (`/etc/systemd/system/netops-console.service` or transient unit) | `netops-console@<slug>.service` of the `netops` user (linger) |
| `/root/.claude` (login + conversations) | `/var/lib/netops/.claude` (memory and conversations copied; **new login** in the tab) |
| `/etc/cron.d/netops-scheduler` (root) | `netops` crontab (`netops-scheduler` block) |
| mixed root/netops files | everything owned by `netops` (without following links or crossing mounts) |
| — | `/etc/netops/instances/<slug>.env` (identity, root-owned) |

Baseline/journal: `/var/backups/netops-migration/<slug>-<date>/` (root 0700): `ownership.jsonl`, consistent
copy of the SQLite, `network/`, `core/config`, old cron and unit, `SHA256SUMS`, `RESTAURAR.txt`.

## Caveats

- Several installations on the same machine: each one migrates separately; all use the `netops` account and the same
  AI profile (conversations separated by folder). One that was not migrated keeps running as root.
- Do not migrate with a pending update (`.netops-update/journal.json`) — `plan` blocks it.
- Keep rescue access outside the console (e.g. `pct enter` on Proxmox) during the window.
