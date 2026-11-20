# Plan: Network Security Audit

## Goal

Assess the security posture of all devices in the inventory and produce a
prioritized report with recommendations.

## Context

Read first: `network/hosts.yaml`, `network/topology.yaml`,
`best-practices/general/network-security-audit.md`, `best-practices/general/ssh-hardening.md`,
the `best-practices/<vendor>/` guides of the vendors present, and `memory/MEMORY.md`.

## Scope

- **Includes:** all hosts in `network/hosts.yaml` (or the requested subset).
- **Out of scope:** any configuration change — this task is **read-only**.

## Steps

1. **coordinator** — validate the inventory, define the scope, create `runs/<id>/`.
2. **planner** — build, per host/vendor, the list of read-only audit commands
   (firewall, services, users, SNMP, firmware version).
3. **executor** — connect and collect; save in `runs/<id>/collected/`.
4. **tester** — run `scripts/tools/analysis/security_assessment.py`, check against the best
   practices, classify findings by severity.
5. **documenter** — generate the report in `reports/` and record lessons in `memory/`.

## Risks and mitigation

| Risk | Mitigation |
|------|------------|
| Collection command that changes state | The planner only includes commands proven to be read-only |
| Connection failure on a host | Record it and move on; the host becomes "not assessed" in the report |
| Scan triggers an IDS alarm | Warn the user; use a moderate scan |

## Rollback

Not applicable — read-only task.

## Success criteria

- All hosts in scope were collected or marked as "not assessed".
- Report generated in `reports/`, with prioritized findings and references.
- At least one lesson recorded in `memory/MEMORY.md`.
