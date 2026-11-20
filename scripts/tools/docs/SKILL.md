---
id: docs
name: Documentation Generation
type: script
runtime: python
description: Generates network documentation artifacts from the inventory.
env: []
---

## What it does

Scripts the `documenter` agent uses to generate documentation from the
framework's data.

| Script | What it generates |
|--------|-----------|
| `topology_render.py` | `network/topology.md` — Mermaid diagram of the topology |

## When to use

Whenever `network/topology.yaml` or `network/hosts.yaml` changes — to keep the diagram
up to date. It is part of the documentation step of the workflows.

## How to use

```bash
python3 scripts/tools/docs/topology_render.py            # writes network/topology.md
python3 scripts/tools/docs/topology_render.py --stdout   # only prints
```

## Setup

`pip install -r requirements.txt` (pyyaml).

## Examples

After registering new hosts and links, regenerate the diagram:
```bash
python3 scripts/tools/docs/topology_render.py
```
The resulting `network/topology.md` renders the graph directly in the IDE and on GitHub.
In inventory v2, links reference integer IDs and the labels show `hostname`.
Renaming a host preserves the Mermaid node identifier and its links. The generator also
reads the legacy v1 inventory and never loads credentials.
