---
description: Runs the network security audit (security-audit workflow)
argument-hint: "[optional host or group; empty = the whole network]"
---

You are operating the NetOps framework. Read `AGENTS.md` at the root for the full context.

Run the `workflows/security-audit.workflow.yaml` workflow as the `coordinator` agent.

Scope: $ARGUMENTS (if empty, audit all hosts in `network/hosts.yaml`).

Follow the workflow steps: define the scope → plan the collection → collect from the devices →
assess security → review with the user → generate the report → reflection. Adopt the persona of
each agent (`agents/*.agent.md`) at each step and respect `constitution.md`.
Answer in the user's language.
