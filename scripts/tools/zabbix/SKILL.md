---
id: zabbix
name: Zabbix
type: script
runtime: python
description: Queries the Zabbix API — lists items and triggers of a template.
env: []
---

## What it does

Reads the Zabbix JSON-RPC API (URL in `ZABBIX_URL`, token in `ZABBIX_API_TOKEN`) and prints an X-ray of a template:
monitored items grouped by category (key, type, unit, interval) and triggers
with priority, status and expression. **Read-only** — changes nothing in Zabbix.

## When to use

- Understand what a template monitors before applying it to a host.
- Audit alerts (triggers) of a template or compare templates.

For queries on hosts/items/history of a device, see also
`scripts/tools/diagnostics/zabbix_api.py` (Network Diagnostics skill).

## Scripts

| Script | Function |
|--------|--------|
| `analise_template.py` | Items + triggers of a template (default: `SNMP LINUX`) |

## Usage

```bash
python3 scripts/tools/zabbix/analise_template.py "SNMP LINUX"
python3 scripts/tools/zabbix/analise_template.py "Mikrotik by SNMP"
```

## Token

The API token is read from the `ZABBIX_API_TOKEN` environment variable (it is never in the code).
The old token was versioned in the git history: **rotate it in Zabbix** (Users → API tokens).
