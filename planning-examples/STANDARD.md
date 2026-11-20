# STANDARD — `planning-examples/`

Template planning documents. The `planner` agent consults this folder before building
a new plan — to reuse the structure and the reasoning of similar plans (REUSE > ADAPT >
CREATE). They are not plans of a real run; they are **templates** of how to plan each type of task.

## Format (`<name>.plan.md`)

```markdown
# Plan: <title>

## Goal
What is to be achieved.

## Context
What the planner needs to read first (inventory, topology, best-practices, memory).

## Scope
Hosts/services involved and what is out of scope.

## Steps
Sequence of steps, each one with the responsible agent.

## Risks and mitigation
What can go wrong and how to avoid it.

## Rollback
How to undo it, if the task changes configuration.

## Success criteria
How to know the task finished well.
```

## How to add one

Copy `_TEMPLATE.plan.md`. Whenever a new type of task is planned, save the template
here — so the next similar planning already starts ready (living project).
