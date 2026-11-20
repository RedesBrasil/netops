---
id: diagnostics
name: Network Diagnostics
type: script
runtime: python
description: Connectivity tests — port scan, advanced ping and traceroute.
env: []
---

## What it does

Diagnostic scripts the `tester` agent uses to validate connectivity and map
service exposure — without having to log into the equipment.

| Script | What it measures |
|--------|-----------|
| `portscan.py` | Open TCP ports / exposed services (nmap, socket fallback) |
| `ping_advanced.py` | Packet loss and latency (RTT min/avg/max) |
| `traceroute_advanced.py` | Network path hop by hop |

## When to use

- Security audit: `portscan.py` reveals exposed Telnet/SNMP/HTTP.
- Troubleshooting: `ping_advanced.py` and `traceroute_advanced.py` locate where the loss is.
- Post-change verification: confirm that a service came up/went down as expected.

## How to use

```bash
python3 scripts/tools/diagnostics/portscan.py --host-id 1
python3 scripts/tools/diagnostics/ping_advanced.py --target 8.8.8.8 --count 20
python3 scripts/tools/diagnostics/traceroute_advanced.py --host-id 3
```

All accept one mutually exclusive option: `--host-id` (integer ID), `--host` (unique name or
legacy alias) or `--target` (direct IP/name). Resolving the inventory entry to get the IP does not read
credentials nor require unlocking the vault.

## Setup

`ping` already comes with the system. For the best results install:
`sudo apt install nmap traceroute`.

## Examples

Check whether a MikroTik has Telnet (23) or API without TLS (8728) exposed:
```bash
python3 scripts/tools/diagnostics/portscan.py --host rt-core-01 --ports 22,23,8728,8729
```
