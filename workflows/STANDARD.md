# STANDARD — `workflows/`

A workflow is a YAML pipeline that orchestrates the agents to solve one type of request.
The `coordinator` picks the workflow and runs the `steps` in order.

## Format

```yaml
workflow:
  id: identifier
  name: Readable name
  description: What it solves.
  triggers: [phrases/commands that trigger this workflow]
  steps:
    - id: "01"
      name: Step name
      type: subagent | inline | checkpoint
      agent: planner | executor | tester | documenter | coordinator
      inputFiles: [files read]
      outputFiles: [files generated]
      instructions: What to do in this step.
      qualityCriteria: How to know the step went well.
      vetoConditions: [conditions that abort the step]
```

## Step types

- `inline` — the `coordinator` runs it directly (quick decisions, loading context).
- `subagent` — delegates to a specialized agent, with a handoff.
- `checkpoint` — pauses and shows options to the user before continuing.

## Rule

Every workflow ends with a **reflection** step (`documenter`) that records lessons in
`memory/` — this is what keeps the project alive (see `core/rules/memory-protocol.md`).

## How to create one

Copy `_TEMPLATE.workflow.yaml`, define the steps, and add a matching planning example
in `planning-examples/`.
