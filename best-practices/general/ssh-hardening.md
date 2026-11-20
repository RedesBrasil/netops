---
id: ssh-hardening
titulo: SSH Access Hardening
vendor: general
tags: [security, ssh, hardening, access]
severidade: alta
---

## Summary

SSH is the standard administration channel. Badly configured, it becomes the attacker's way in.
This guide covers SSH hardening on network devices and Linux servers.

## Checklist

- [ ] Telnet disabled — SSH is the only CLI access.
- [ ] Key authentication preferred over password (mandatory on Linux servers).
- [ ] Direct `root`/`admin` login restricted or disabled when the device allows it.
- [ ] SSH access restricted by management IP/subnet (firewall or `allowed-address`).
- [ ] Default port (22) is acceptable if there is an ACL; changing the port is obfuscation, not security.
- [ ] Weak algorithms disabled (no legacy `ssh-rsa`, no obsolete CBC ciphers).
- [ ] Idle session timeout configured.
- [ ] Login attempts limited (brute force protection).
- [ ] Warning banner configured (a legal/compliance requirement in many cases).

## Details

**Key vs password.** A password can be guessed and is subject to brute force. A key (ed25519
preferably) removes that vector. On Linux servers, the default should be
`PasswordAuthentication no` after the keys are distributed.

**Restriction by source.** Even with SSH well configured, exposing it to the whole internet is an
unnecessary risk. Restrict it to the management subnet — on MikroTik via `/ip/firewall` and
`/ip/service address`; on Linux via firewall + `AllowUsers`/`Match Address`.

**Algorithms.** Old devices negotiate weak ciphers/MACs. Check with
`nmap --script ssh2-enum-algos` and disable whatever is obsolete.

**Brute force.** Limit attempts: `MaxAuthTries` on Linux; a dynamic address-list on
MikroTik (see `config-examples/mikrotik/firewall-baseline.rsc`).

## Related configuration

- `config-examples/linux/sshd_config`
- `config-examples/mikrotik/security-hardening.rsc`

## References

- Mozilla OpenSSH Guidelines.
- `best-practices/general/network-security-audit.md`
