# Rule — Handoff between Agents

How context passes from one agent to another inside a workflow. Adapted from the AIOX
handoff model.

## Principle

When the `coordinator` delegates a step, the incoming agent receives **only two things**:

1. **Its own full profile** — the matching `.agent.md` (persona, principles,
   operating mode).
2. **The handoff artifact** from the previous agent — filled in from
   `core/templates/agent-handoff.tmpl.yaml`.

The incoming agent does **not** receive the persona or the full history of the previous agent —
only the compact summary. This keeps the context lean and cheap.

## Procedure

1. When it finishes its step, the agent fills in the handoff template: what it decided, which
   files it touched, open blockers and what the next one must do.
2. The filled-in artifact **must be under 500 tokens**. If it goes over, summarize more.
3. The `coordinator` adopts the persona of the next agent and gives it the artifact.
4. The live artifact of the run stays in `runs/<id>/handoff.yaml` (overwritten at each step).

## Limits

- Decisions: max. 5 · Files modified: max. 10 · Blockers: max. 3.
- `next_action`: at most 2 sentences.
- At most 3 chained summaries are kept; the oldest one is discarded.

## Default chain

```
coordinator → planner → executor → tester → documenter → coordinator
```

Possible detours: `tester → planner/executor` (when something needs fixing) and
`planner → tester` (when a config proposal must be reviewed before applying).
