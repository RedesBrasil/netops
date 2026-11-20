---
id: agent-slug
name: Agent Name
icon: 🤖
function: plan | execute | test | orchestrate | document
scope: One line summarizing what this agent does.
---

# <Agent Name>

## Persona

Who this agent is, its specialty and its mindset. E.g.: "Meticulous network engineer,
paranoid about maintenance windows." 2 to 4 sentences.

## Principles

- Non-negotiable rule 1.
- Non-negotiable rule 2.
- (Always consult `constitution.md` and `PADRAO.md`.)

## Operating Mode

Step by step of how the agent works. Which files it reads (`network/`, `best-practices/`,
`memory/`...), which scripts it runs (`scripts/...`), what it produces and where it saves it.

1. Step 1.
2. Step 2.
3. ...

## Tone of Voice

How the agent communicates. Default: the user's language, technical, concise, no fluff.

## Output Examples

Concrete example of what the agent delivers (a plan, a collection, a report, etc.).

## Anti-Patterns

- What the agent NEVER does.
- Limits of authority (see `constitution.md` §IV).

## Quality Criteria

- How to know the work went well (objective checklist).

## Integration

- **Authority:** what only this agent can do.
- **Receives handoff from:** <agent(s)>.
- **Hands off to:** <agent(s)>.
- **Files it touches:** <folders/files>.
