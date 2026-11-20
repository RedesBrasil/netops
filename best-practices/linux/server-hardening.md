---
id: linux-server-hardening
title: Linux Server Hardening
vendor: linux
tags: [security, linux, hardening, server]
severity: high
---

## Summary

Hardening of an infrastructure Linux server (Ubuntu/Debian/RHEL). Covers access,
attack surface, updates and auditing. Applies to physical hosts, VMs and Proxmox hosts.

## Checklist

- [ ] SSH hardened: key instead of password, `PermitRootLogin` controlled (see `ssh-hardening`).
- [ ] Host firewall active (`ufw`/`firewalld`/`nftables`) with a default deny policy on input.
- [ ] Only the required services listening — review `ss -tulpn`.
- [ ] Packages up to date; automatic security updates enabled (`unattended-upgrades`).
- [ ] Individual user accounts; `sudo` instead of direct `root` login.
- [ ] Strong passwords on local accounts; system accounts without a login shell.
- [ ] Centralized logs (syslog/journald → remote collector) and time via NTP.
- [ ] `fail2ban` (or equivalent) protecting SSH and exposed services.
- [ ] Correct permissions on sensitive files (`/etc/shadow`, keys, service configs).
- [ ] Backup defined and tested.

## Details

**Attack surface.** `ss -tulpn` lists what is listening. Everything that is not needed
should be stopped and disabled (`systemctl disable --now <service>`). Every open port is
a port to defend.

**Host firewall.** Do not rely only on the edge firewall. The host must have its own
firewall with default deny on input, opening only what is needed (SSH from management, the ports of the
service it provides).

**Updates.** Most compromises exploit a known CVE that has already been fixed.
`unattended-upgrades` for security fixes drastically reduces the exposure window.

**Access.** Logging in directly as `root` removes traceability. Each admin has their own account and uses
`sudo` — the log shows who did what.

**fail2ban.** Monitors logs and temporarily bans IPs with many authentication failures —
an effective and cheap defense against brute force.

## Related configuration

- `config-examples/linux/sshd_config` — hardened SSH (seed example).
- Host firewall (ufw/nftables): to be added to `config-examples/linux/` as the project evolves.

## References

- CIS Benchmark for the distribution in use.
- `best-practices/general/ssh-hardening.md`, `best-practices/linux/services-hardening.md`
