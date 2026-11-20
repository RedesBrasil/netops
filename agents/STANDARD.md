# STANDARD — `agents/`

Each agent is an `.agent.md` file that describes **one role** with **one main function**.
When a workflow delegates a step to an agent, the IDE adopts the persona from that file.

## The 5 agents

| File | Main function | Role |
|------|---------------|------|
| `coordinator.agent.md` | orchestrate | Receives the request, picks the workflow, delegates, consolidates |
| `planner.agent.md` | **plan** | Decides hosts, commands, order; designs config + rollback |
| `executor.agent.md` | **execute** | The only one that connects to the devices; collects and applies |
| `tester.agent.md` | **test** | Audits security, validates collections, verifies after changes |
| `documenter.agent.md` | document | Generates reports, documents the network, feeds `memory/` |

## `.agent.md` format (8 mandatory sections)

YAML front-matter + 8 sections, in this order:

```
---
id:        agent-slug
name:      Name
icon:      emoji
function:  plan | execute | test | orchestrate | document
scope:     one line summarizing what the agent does
---

## Persona              — who the agent is, its mindset
## Principles           — the agent's non-negotiable rules
## Operating Mode       — step by step of how it works; which scripts/folders it uses
## Tone of Voice        — how it communicates (the user's language, technical, concise)
## Output Examples      — concrete examples of what it produces
## Anti-Patterns        — what the agent NEVER does
## Quality Criteria     — how to know the work went well
## Integration          — authority, to/from which agents it hands off, files it touches
```

## How to create a new agent

Copy `_TEMPLATE.agent.md`, fill in the 8 sections, and register it here in the table.
Keep **one main function per agent** (OpenSquad's YAGNI principle).
