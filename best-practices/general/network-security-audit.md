---
id: network-security-audit
title: Network Security Audit
vendor: general
tags: [security, audit, hardening]
severity: high
---

## Summary

Cross-vendor checklist to assess the security posture of any network device.
The `tester` agent uses this guide to classify the findings of an audit. Each item
below is an objective check — when it fails, it becomes a finding with a severity.

## Checklist

- [ ] Telnet disabled (SSH only for CLI access).
- [ ] Management access (SSH/API/HTTPS) restricted to management subnets.
- [ ] No factory default credentials; no user without a password.
- [ ] SNMP: no `public`/`private` community; prefer SNMPv3; restrict by ACL.
- [ ] Management web interface over HTTPS only (never plain HTTP), and restricted.
- [ ] Firmware/OS on a supported version with no known critical CVEs.
- [ ] Firewall with a restrictive `input` policy (default drop) at the edge.
- [ ] Logging enabled and sent to a central collector (syslog).
- [ ] NTP configured (correct time is a prerequisite for reliable logs).
- [ ] Unused services turned off (reduce the attack surface).
- [ ] Individual administrative accounts (no shared login when possible).

## Details

**Administrative access.** Telnet sends the password in plain text — anyone on the network can capture it.
Use SSH. Restrict where management is accepted from: a router that accepts SSH from any IP is
an invitation. List the management subnets explicitly.

**Credentials.** Attack vector no. 1 is the factory default password. Every audit starts by
checking whether `admin/admin`, `admin` with no password, or the vendor's well-known password still
work.

**SNMP.** The `public` community lets anyone read the configuration and the topology. Replace
it with a unique string, restrict it by ACL and, ideally, migrate to SNMPv3 (authenticated and
encrypted).

**Exposure.** A port scan of the management IP reveals what is exposed. Ports such as
23 (Telnet), 21 (FTP), 80 (HTTP), 3389 (RDP) being open are findings. Use
`scripts/tools/diagnostics/portscan.py`.

**Firmware.** Outdated devices accumulate vulnerabilities. Compare the collected version
with the one recommended by the vendor.

## Suggested severities

| Finding | Severity |
|--------|-----------|
| Default credential / no password | CRITICAL |
| Telnet enabled and exposed | HIGH |
| SNMP community public | HIGH |
| Management open to any IP | HIGH |
| Outdated firmware | MEDIUM |
| Management HTTP without TLS | MEDIUM |
| Unused service turned on | LOW |

## Related configuration

- `config-examples/mikrotik/security-hardening.rsc`
- `config-examples/mikrotik/firewall-baseline.rsc`
- `config-examples/linux/sshd_config`

## References

- CIS Benchmarks (per vendor/OS).
- `best-practices/general/ssh-hardening.md`
