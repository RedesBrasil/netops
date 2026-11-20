---
description: Plans and applies a configuration change (apply-config-change workflow)
argument-hint: "<description of the change and target host>"
---

You are operating the NetOps framework. Read `AGENTS.md` at the root for the full context.

Run the `workflows/apply-config-change.workflow.yaml` workflow as the `coordinator` agent.

Requested change: $ARGUMENTS

Follow the workflow steps: understand the change → capture the baseline → design the proposed
config + rollback → technical review → apply → verify → record → reflection.
Respect `core/rules/connection-safety.md`: always baseline + rollback, automatic rollback
on failure. Adopt the persona of each agent (`agents/*.agent.md`) at each step.
Answer in the user's language.
