---
id: mikrotik-firewall
titulo: MikroTik Firewall Best Practices
vendor: mikrotik
tags: [security, mikrotik, firewall]
severidade: alta
---

## Summary

The RouterOS firewall has three main chains: `input` (traffic destined to the router
itself), `forward` (traffic passing through it) and `output` (originated by it). Most
security problems on MikroTik come from a permissive `input` chain.

## Checklist

- [ ] `input` chain: accept `established`/`related`, accept management from the trusted
      subnets, and **drop the rest** (final rule `action=drop`).
- [ ] Accept ICMP in a controlled way (do not drop everything — it breaks PMTUD and diagnostics).
- [ ] Block management access coming from the WAN interface.
- [ ] Address-lists for management and for trusted networks (readable, reusable rules).
- [ ] SSH/Winbox brute force protection via a dynamic address-list.
- [ ] `fasttrack` for established connections in `forward` (performance), with care.
- [ ] Commented rules — each rule explains what it does and why.
- [ ] Order matters: more specific rules first; the final `drop` last.

## Details

**Input chain — secure model.** The logic is: let through what is legitimate and explicitly drop everything
else. Without the final `drop` rule, the chain "accepts by default" and the router
is exposed.

**ICMP.** Dropping all ICMP looks safe but breaks Path MTU Discovery and diagnostics.
Accept the required types (controlled echo, fragmentation-needed, time-exceeded).

**WAN.** Put the WAN interface(s) in an interface-list and block management coming from
them — even if the `input` firewall is correct, it is an extra layer.

**Brute force.** New connections to the SSH/Winbox port feed a staged
address-list; after N attempts, the IP goes into a temporary block list.

**Order and lockout.** Add the accept-management rule **before** the `drop` rule. When
applying via the API/remote SSH, use `safe-mode` — if the rule locks you out, RouterOS reverts it.

## Related configuration

- `config-examples/mikrotik/firewall-baseline.rsc` — complete, commented `input` chain.

## References

- MikroTik Wiki — "Building Your First Firewall".
- `best-practices/mikrotik/security-hardening.md`
