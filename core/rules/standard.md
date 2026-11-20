# STANDARD — The NetOps Master Standard

This is the document that defines **how everything is organized and named** in NetOps. Whenever
there is a doubt about where to put something or how to name it, the answer is here. Every AI
agent reads this file before creating anything.

> **Golden rule:** structure/folders/files in **English**; files read by the AI (agents, workflows, rules,
> standards, templates, skills) are kept **only in English**, and the AI answers in the user's language
> (see `core/rules/i18n.md`). Local files of an installation (`AGENTS.md`, `memory/MEMORY.md`) are born in the
> installation's language. When in doubt, prefer REUSE > ADAPT > CREATE (see `constitution.md`).

---

## 1. Directory structure

```
netops/
├── agents/            Definitions of the AI agents (scope + function: plan/execute/test)
├── best-practices/    Best practices as descriptive TEXT (little or no config)
├── config-examples/   REAL configuration examples, per vendor
├── scripts/           Python scripts: access (ssh/telnet/api), diagnostics, vault and UI
│   └── ui/            CRUD web console (FastAPI + Preact without build) — ephemeral operator
│                      tool, loopback, stateless. See scripts/engine/ui/SKILL.md and constitution.md §VII.
├── planning-examples/ Template documents for planning tasks
├── network/           Inventory: hosts, credentials and topology map
├── workflows/         YAML pipelines that orchestrate the agents (plan→execute→test)
├── memory/            Memory and self-learning — the "living project"
├── runs/              Raw output per run (git-ignored)
├── reports/           Curated final reports (versioned)
└── core/              Config, schemas, templates and rules of the framework
```

### Distribution and update

Scheduled tasks live in `scripts/engine/scheduler/` (`SKILL.md`): registry in `network/schedules.yaml`,
runs in `runs/schedules/`, triggered by the system cron.

The update engine lives in `scripts/engine/update/`, with `SKILL.md`. Private state and snapshots
stay in `.netops-update/` (git-ignored). Releases follow `core/rules/releases.md`,
with a single version in `core/config/core-config.yaml`, notes in `CHANGELOG.md` and the workflow in
`.github/workflows/release.yml`. Packages distribute only authorized paths, never local data.

## 2. Naming conventions

| Item | Standard | Example |
|------|----------|---------|
| Folder | `kebab-case`, English | `config-examples/` |
| Agent file | `<name>.agent.md` | `executor.agent.md` |
| Workflow file | `<name>.workflow.yaml` | `security-audit.workflow.yaml` |
| Best practice | `<topic>.md` in `best-practices/<vendor-or-general>/` | `best-practices/mikrotik/firewall.md` |
| Config example | `<topic>.<native-ext>` in `config-examples/<vendor>/` | `config-examples/mikrotik/ospf.rsc` |
| Template plan | `<name>.plan.md` | `security-audit.plan.md` |
| Lesson learned | dated bullet `YYYY-MM-DD — fact` in `memory/MEMORY.md` | `2026-06-01 — Vault before access` |
| Run folder | `runs/YYYY-MM-DD-HHMM-<task>/` | `runs/2026-05-18-1430-security-audit/` |
| Equipment name (`hostname` in `network/hosts.yaml`) | **UPPERCASE**, hyphen instead of space | `9ROUTER-TEST`, `COOLIFY-FRANCISCO` |
| Vendor (identifier) | lowercase, no space | `mikrotik`, `cisco`, `linux`, `unifi` |

Special files (prefix `_`):
- `_TEMPLATE.*` / `_TEMPLATE/` — template to copy when creating a new item in the folder.
- `_catalog.yaml` / `_index.yaml` — index of the folder, read by the agent for quick discovery.
- `STANDARD.md` (inside each folder) — rules specific to that folder. The standard of `network/` is
  `core/rules/network-standard.md` (the updater only ships `*.example.yaml` inside `network/`).

## 3. Supported vendors

`mikrotik`, `unifi`, `ubiquiti`, `cisco`, `huawei`, `proxmox`, `vmware`, `datacom`,
`linux`, `fiberhome`, `intelbras`, `zabbix` — and any that come up. `general` = cross-vendor
best practices (does not belong to a vendor).

**Full seed content:** `mikrotik` and `linux`. The others already have the folder and the
`_TEMPLATE` — they are filled in as the living project evolves.

## 4. Format of each folder (summary — detail in the `STANDARD.md` of each one)

- **agents/** — `.agent.md` with 8 sections (Persona, Principles, Operating Mode,
  Tone of Voice, Output Examples, Anti-Patterns, Quality Criteria, Integration).
- **best-practices/** — Markdown with YAML front-matter; subfolders per vendor + `general/`;
  indexed by `_catalog.yaml`. Descriptive text, commands only as illustration.
- **config-examples/** — files in the vendor's native syntax (`.rsc`, `.ios`, `.conf`...);
  subfolders per vendor; indexed by `_index.yaml`. Each example has a commented header.
- **scripts/** — each script has a `SKILL.md` next to it describing usage. `lib/` is the reusable
  core; `access/`, `diagnostics/`, `analysis/`, `docs/` are the script families.
- **planning-examples/** — `.plan.md` showing goal, scope, steps, risks, rollback.
- **network/**: real inventory, git-ignored (`hosts.yaml`, `credentials.yaml`, `topology.yaml`,
  `topology.md`, `maps.yaml`); `*.example.yaml` templates versioned. Layout is presentation,
  never a second host registry.
- **workflows/** — `.workflow.yaml` with `steps` (type `subagent`/`inline`/`checkpoint`).
- **memory/** — a single file: `MEMORY.md` (sections: Preferences, Environment and conventions, Lessons learned, written
  in the installation's language).
  **Personal to the instance, git-ignored:** `memory/`, `reports/`, `runs/`, `backups/`, `network/hosts.yaml`/`credentials.yaml` and
  `core/config/project-config.yaml` never go up to the product repository (it is distributed to other companies); what
  keeps that data is the backup of the instance itself. A new installation starts with an empty `memory/` and config from
  `core/config/project-config.example.yaml`. Product code, docs and tests do not mention real companies, ISPs, IPs or hosts: use
  generic examples (RFC 5737 `192.0.2.0/24`, `203.0.113.0/24`; RFC 3849 `2001:db8::/32`).

## 5. How to add a new vendor

1. Create `best-practices/<vendor>/` by copying `best-practices/_TEMPLATE.md`.
2. Create `config-examples/<vendor>/` by copying `config-examples/_TEMPLATE/`.
3. Register the vendor in `best-practices/_catalog.yaml` and `config-examples/_index.yaml`.
4. Add the mapping in `scripts/engine/lib/vendor_map.py` (Netmiko `device_type` / NAPALM driver / API).
5. Add the vendor section to this file (item 3).

## 6. How to add a learning (living project)

1. During the post-run reflection, append a dated bullet (`YYYY-MM-DD — fact`) under "Lessons
   learned" in `memory/MEMORY.md` — a declarative fact, not an order.
2. If it becomes permanent knowledge about a vendor, promote it to `best-practices/` or
   `config-examples/`.

See `core/rules/memory-protocol.md` for the full protocol.
