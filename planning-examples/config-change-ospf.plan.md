# Plan: Configure OSPF on a MikroTik

## Goal

Enable OSPF routing on a MikroTik router so that it exchanges routes with the
network neighbors, with a guaranteed baseline and rollback.

## Context

Read first: `network/hosts.yaml` (the target host), `network/topology.yaml` (neighbors and links),
`best-practices/mikrotik/security-hardening.md`, `config-examples/mikrotik/ospf-basic.rsc`,
`memory/MEMORY.md` (OSPF quirks in RouterOS).

## Scope

- **Includes:** the indicated MikroTik router and the configuration of the OSPF instance/area.
- **Out of scope:** changes to the firewall, to IP addressing or to other hosts.

## Steps

1. **coordinator** — confirm the target host, the desired areas/networks and the maintenance window.
2. **executor** — baseline: collect the current `/routing/ospf/...` and `/ip/route`.
3. **planner** — adapt `config-examples/mikrotik/ospf-basic.rsc` to the host (router-id,
   networks, interfaces); generate `change.txt` and the `rollback.txt` (remove the created instance).
4. **tester** — validate the syntax against the MikroTik example; check the impact on the topology.
5. **executor** — apply in `safe-mode`; capture the post-change state.
6. **tester** — confirm the adjacencies (`/routing/ospf/neighbor`) and the learned routes.
7. **documenter** — record the change and the lessons.

## Risks and mitigation

| Risk | Mitigation |
|------|------------|
| Different RouterOS 6 vs 7 syntax | Use the v7 example; confirm `/system/resource` |
| Loop/unexpected route | Start with passive interfaces where there is no OSPF neighbor |
| Loss of management access | Apply in `safe-mode`; automatic rollback on failure |

## Rollback

`runs/<id>/proposals/<host>.rollback.txt` — removes the instance, the area and the
interface-templates created, going back to the baseline state.

## Success criteria

- OSPF adjacencies formed with the expected neighbors.
- OSPF routes present in `/ip/route`.
- Management connectivity preserved.
