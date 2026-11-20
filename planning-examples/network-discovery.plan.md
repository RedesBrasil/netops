# Plan: Network Discovery and Documentation

## Goal

Survey the real state of the network (active hosts, neighbors, links) and generate/update the
topology documentation.

## Context

Read first: `network/hosts.yaml`, `network/topology.yaml` and `memory/MEMORY.md`.

## Scope

- **Includes:** the inventory hosts and the discovery of their direct neighbors.
- **Out of scope:** configuration changes; scanning unauthorized IP ranges.

## Steps

1. **coordinator** — define the scope of the discovery from the inventory.
2. **executor** — on each host, collect the neighbor table (LLDP/CDP/MNDP), interfaces and
   routes; save them in `runs/<id>/collected/`.
3. **tester** — optional: `scripts/tools/diagnostics/portscan.py` and `ping_advanced.py` to
   confirm who is active.
4. **planner** — compare what was discovered with `network/topology.yaml`; point out divergences.
5. **documenter** — update `network/topology.yaml`, run
   `scripts/tools/docs/topology_render.py` and record lessons.

## Risks and mitigation

| Risk | Mitigation |
|------|------------|
| Neighbor discovered outside the inventory | Report it to the user; do not connect to it |
| Divergence between inventory and reality | Document the divergence, do not overwrite without approval |

## Rollback

Not applicable — read-only task (it only updates local documentation).

## Success criteria

- Neighbors and links collected from all reachable hosts.
- `network/topology.yaml` and `network/topology.md` updated.
- Divergences between inventory and reality documented.
