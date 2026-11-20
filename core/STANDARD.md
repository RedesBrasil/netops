# STANDARD — `core/`

`core/` holds the framework infrastructure: config, schemas, templates and rules. It is the
stable part — it rarely changes. Network knowledge does NOT live here (it lives in
`best-practices/`, `config-examples/`, `memory/`).

## Subfolders

| Folder | Content |
|--------|---------|
| `config/` | Framework configuration: `core-config.yaml`, `framework-config.yaml`, `project-config.yaml` |
| `schemas/` | JSON validation schemas. Today: `inventory.schema.json` (used by `scripts/engine/lib/inventory.py`). The agent and workflow format is defined by the `_TEMPLATE` files of the `agents/` and `workflows/` folders. |
| `templates/` | Templates: `agent-handoff.tmpl.yaml`, `run-state.tmpl.json`, `security-report.tmpl.md`, `change-record.tmpl.md` |
| `rules/` | Rules loaded by all agents: `agent-handoff.md`, `connection-safety.md`, `memory-protocol.md` |

## Rules (`core/rules/`)

They are mandatory reading for the agents in the situations they cover:

- `agent-handoff.md` — how context passes between agents.
- `connection-safety.md` — how to connect and change config safely.
- `memory-protocol.md` — how to read/write memory and do the reflection (living project).

## Templates (`core/templates/`)

Templates to copy — do not edit them when running a task; copy and fill them in.
