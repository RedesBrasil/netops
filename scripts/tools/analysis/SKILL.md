---
id: analysis
name: Analysis
type: script
runtime: python
description: Security assessment and configuration diff.
env: []
---

## What it does

Analysis scripts the `tester` agent uses to audit and compare.

| Script | What it does |
|--------|-----------|
| `security_assessment.py` | Checks hosts against the `checks.yaml` catalog (ports + config) |
| `config_diff.py` | Unified diff between two config files (before × proposal) |

## When to use

- `security_assessment.py`: in the `security-audit` workflow, to generate prioritized findings.
- `config_diff.py`: before applying a change (review the diff) and after it (before × after).

## How to use

```bash
# Security assessment of all hosts
python3 scripts/tools/analysis/security_assessment.py --all

# Assessment with configuration checks (needs the collected config)
python3 scripts/tools/analysis/security_assessment.py --host-id 1 \
  --config-file runs/2026-05-18-1430-security-audit/collected/1.txt

# Configuration diff
python3 scripts/tools/analysis/config_diff.py --before baseline.txt --after proposta.txt
```

## Setup

`--host-id` selects the integer ID; `--host` accepts a unique name or legacy alias. Each
run picks exactly one of `--host-id`, `--host` and `--all`. Findings use
the numeric canonical ID and inventory resolution neither loads nor decrypts credentials.

`pip install -r requirements.txt` (pyyaml). For the full scan: `sudo apt install nmap`.
The checks catalog is in `scripts/tools/analysis/checks.yaml` — add checks there.

## Examples

The checks cover: exposed Telnet/FTP/RDP, exposed SNMP and default community, HTTP
management without TLS, RouterOS API without TLS, SNMP v1/v2c. Findings are sorted by severity
(CRITICAL → INFO) and each one cites the reference best practice.
