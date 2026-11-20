# STANDARD — `best-practices/`

Best practices as **descriptive text** — the "why" and the "what". Little or no
configuration (detailed config lives in `config-examples/`). The agent reads these guides before
planning or auditing.

## Organization

- `general/` — cross-vendor best practices (valid for any vendor).
- `<vendor>/` — best practices specific to one vendor (`mikrotik/`, `linux/`, ...).
- `_catalog.yaml` — index of all guides; the agent reads the catalog first and only opens
  the relevant guide.

## Format of a guide (`<topic>.md`)

YAML front-matter + body (the front-matter keys and the `severidade` values stay as they are: the console reads them):

```markdown
---
id: unique-identifier
titulo: Readable title
vendor: general | mikrotik | linux | ...
tags: [security, ssh, ...]
severidade: alta | media | baixa
---

## Summary
What this guide is for, in 1-2 paragraphs.

## Checklist
- [ ] Verifiable item 1
- [ ] Verifiable item 2

## Details
Explanation of each point.

## Related configuration
Points to the files in `config-examples/<vendor>/` that implement this.

## References
Links and official documentation.
```

`severidade`: `alta` = high, `media` = medium, `baixa` = low.

## How to add a guide

Copy `_TEMPLATE.md`, write the content, and register the guide in `_catalog.yaml`.
Full seed content: `general/`, `mikrotik/`, `linux/`. Other vendors: fill in
as the living project evolves (see the root `PADRAO.md`, §5).
