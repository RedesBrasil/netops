---
id: privileges
name: Operational account permissions (network without root; root only with the vault unlocked)
type: script
runtime: python
description: Prepares the server so the netops account can run network diagnostics without root and become root (sudo or directly) only while the vault is unlocked.
env: []
---

## Model

| What | How it works | Needs the vault? |
|---|---|---|
| `ping`, `traceroute -I/-T`, `mtr`, `nmap -sS/-O`, `nping`, `tcpdump`, `arping`, `fping`, `arp-scan` | runs directly as `netops` | **no** |
| `sudo <any command>` | root, no password | **yes** — locked = denied |
| `apt`, `systemctl`/`journalctl` (without `--user`), `nft`, `iptables`, `docker`, `mount`, `sysctl`, `ss`, `lsof`… typed in the shell | become root on their own ("auto sudo") | **yes** — locked = run as `netops` |
| `rootcat <file>`, `rootedit <file>`, `rootsh '<pipeline>'` | read/edit/redirect a system file as root | **yes** |
| `git`, `python3`, editing in `/opt/netops` | always `netops` (never creates root files in the tree) | — |

Pieces (all root-owned, created by `provision.py install`, called by `install.sh` on every install/repair):

- `/etc/sysctl.d/60-netops-ping.conf` — `net.ipv4.ping_group_range` over the mapped GID range. In an unprivileged LXC CT
  the Debian default (`0 2147483647`) is rejected by the kernel and ping stays root-only.
- `/usr/local/sbin/netops-netcaps` — file capabilities (`cap_net_raw`/`cap_net_admin`, not setuid) on the
  network tools; reapplied after every apt run (`/etc/apt/apt.conf.d/80netops-netcaps`) and by the
  `netops-netcaps.timer` timer (boot + 1 h, other distros). Wrappers `/usr/local/bin/nmap|nping` pass `--privileged`.
- `/etc/sudoers.d/netops-cofre` (`netops ALL=(ALL:ALL) ALL`, `timestamp_timeout=0`) + a `pam_exec` line at the top of the
  auth section of `/etc/pam.d/sudo` → `/usr/local/sbin/netops-sudo-cofre`. The account has no password: PAM only allows it if the
  vault session (`/run/user/<uid>/netops/session.key`) is valid — owner/mode, same boot, not expired and a key
  that opens the **verifier pinned by root** in `/etc/netops/vault-verifier.d/<slug>.pin` (HMAC of the Fernet token,
  stdlib only). Every grant/denial goes to syslog AUTHPRIV (`netops-sudo-cofre`).
- `/usr/local/share/netops/auto-sudo.bash`, loaded at the **top** of the account's `~/.bashrc` (before the interactive
  shell test, so Claude Code loads it too). Non-interactive scripts do not load it: use `sudo` in them.
- `/etc/netops/privileges.conf` — which account is the operational one (read by `netops-sudo-cofre`).
- `/usr/local/sbin/netops-setup-finish <slug>` — root step of the **first access** (single use). A new installation has
  no vault, so the pin above and the Local host password are deferred until after the `#setup` wizard: the
  `netops-setup-finish-<slug>.path` unit (watches `runs/setup/finish-request`) runs the script, which only acts with
  `/etc/netops/instances/<slug>.setup-pending` (root), pins via `netops-sudo-cofre --pin` (only what the unlocked
  session opens) and generates the `netops-admin` password (the operational account writes it to the vault; root applies it). Result in
  `<slug>.setup-done`; when finished, it deletes the marker and disables the unit. Recovery: run the same command with `sudo`.

## Usage (root)

```bash
sudo python3 -I -B scripts/engine/privileges/provision.py install --root /opt/netops   # installs/repairs (idempotent)
sudo python3 -I -B scripts/engine/privileges/provision.py status  --root /opt/netops   # what is active + vault now
sudo python3 -I -B scripts/engine/privileges/provision.py pin     --root /opt/netops   # re-pins the verifier
sudo python3 -I -B scripts/engine/privileges/provision.py remove  --root /opt/netops   # undoes everything
```

- **Changed the master password?** Unlock the vault and run `pin` (otherwise sudo starts being denied).
- `install --trust-creds` is only used by `install.sh` on a **new** installation (the vault was just created by
  it). Otherwise `pin` requires the vault unlocked, because `credentials.yaml` belongs to the operational account.
- `sudo -n` does **not** work (sudo refuses before calling PAM). Use plain `sudo`.

## Limits (honest)

- The vault is an **operational gate**, not a boundary against the `netops` account itself: while unlocked, the
  key sits in a file the account can read; a malicious process of that account could keep it and allow sudo later.
- sudo does not apply the console's per-user permissions (`server.admin`): anyone with terminal/Claude tab in the console
  becomes root while the vault is unlocked. The Local host (`scripts/engine/localadmin/`) still enforces them.
- Using `sudo` does not renew the vault TTL (15 min without use, `vault.session_ttl_seconds`).
