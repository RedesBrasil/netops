---
id: mikrotik-security-hardening
titulo: MikroTik RouterOS Security Hardening
vendor: mikrotik
tags: [security, mikrotik, routeros, hardening]
severidade: alta
---

## Summary

Hardening of a MikroTik router/switch (RouterOS 7.x). MikroTik ships from the factory
permissive — several services on and the `admin` user with no password. This guide lists what to
review and harden.

## Checklist

- [ ] `admin` user with a strong password (or removed in favor of a named user).
- [ ] Unused services disabled in `/ip service` — turn off `telnet`, `ftp`, `www`,
      `api` (no TLS); keep `ssh`, `winbox` and `api-ssl` as needed.
- [ ] `/ip service` with `address` restricted to the management subnet.
- [ ] MAC-server (Winbox/Telnet by MAC) restricted or disabled:
      `/tool mac-server` and `/tool mac-server mac-winbox`.
- [ ] Neighbor discovery (`/ip neighbor discovery-settings`) only on internal interfaces.
- [ ] Bandwidth-test, romon and proxy disabled if not used.
- [ ] SNMP: no `public` community; restricted by `address`; SNMPv3 when possible.
- [ ] `input` firewall with a restrictive policy (see `best-practices/mikrotik/firewall.md`).
- [ ] RouterOS up to date (`stable` channel); check `/system package update`.
- [ ] NTP/time client configured and logging to remote syslog.
- [ ] Automatic config backup (`/system backup` and `.rsc` export).

## Details

**Services.** `/ip service print` shows the state of each management service. Telnet (23),
FTP (21) and www (80) must stay `disabled`. The API on 8728 has no TLS — prefer `api-ssl`
(8729). Each service kept gets an `address` with the management subnet.

**MAC-server.** Winbox by MAC ignores IP — an attacker on the same L2 gets in even without a routable
IP. Restrict it to a management interface-list.

**Neighbor discovery.** By default MikroTik announces its identity/version via MNDP on all
interfaces, including the WAN. Limit it to the internal interfaces.

**Watch out for lockout.** Changing `/ip service`, the firewall or the management address can cut
your own session. Always use a scheduled `/system reboot` or RouterOS `safe-mode` when
applying sensitive changes remotely.

## Related configuration

- `config-examples/mikrotik/security-hardening.rsc`
- `config-examples/mikrotik/firewall-baseline.rsc`

## References

- MikroTik Wiki — "Securing your router".
- `best-practices/general/network-security-audit.md`
