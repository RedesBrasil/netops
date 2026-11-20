# NetOps Constitution

> **Version:** 1.3.0 | **Ratified:** 2026-05-18 | **Revised:** 2026-11-20 (§I: files read by the AI are kept only in English; the AI answers in the user's language; before 2026-11-19, §V: operational account `netops` and Local access backend; before 2026-11-13, §VII: Zabbix exception in web access)

This document defines the non-negotiable principles of NetOps. All agents, workflows and
scripts MUST respect them. Adapted from the AIOX `constitution.md` to the network and
infrastructure domain.

---

## Core Principles

### I. Standardization Above All (NON-NEGOTIABLE)

Everything in the framework follows `PADRAO.md`. Consistency is what allows the AI agent to
always know where to look and where to save.

- **MUST:** Every new file follows the template (`_TEMPLATE`) of its folder.
- **MUST:** Technical folder/file names in English. Files read by the AI (agents, workflows, rules,
  standards, templates, skills) are kept only in English; the AI always answers in the user's language
  (see `core/rules/i18n.md`). Local files of an installation (`AGENTS.md`, `memory/MEMORY.md`) are born in the
  installation's language.
- **MUST:** Every knowledge folder has a `PADRAO.md` and a `_TEMPLATE`.
- **MUST NOT:** Create structures outside the standard without first updating `PADRAO.md`.

### II. Living Project (NON-NEGOTIABLE)

Every run teaches something. That learning is documented so that the next run is
better — without it, the framework does not evolve.

- **MUST:** Every workflow ends with a **reflection** step that records lessons in `memory/MEMORY.md`.
- **MUST:** Connection errors, vendor quirks and discoveries become recorded lessons.
- **MUST:** Consolidated knowledge is promoted to `best-practices/` and `config-examples/`.
- **MUST:** Lessons are dated bullets in `memory/MEMORY.md`, written as a declarative fact (not as an order).

### III. REUSE > ADAPT > CREATE (MUST)

Before generating any config or plan from scratch, consult what already exists.

- **MUST:** Consult `best-practices/` and `config-examples/` before proposing a solution.
- **MUST:** Consult `memory/MEMORY.md` for already known quirks.
- **MUST:** Consult `planning-examples/` before building a new plan.
- **MAY:** Create from scratch only when nothing relevant exists — and then document it.

### IV. Agent Authority (MUST)

Each agent has one main function. Work outside the scope is delegated.

| Authority | Exclusive agent |
|-----------|-----------------|
| Orchestrate and delegate | `coordinator` |
| Plan (decide what/how) | `planner` |
| Connect to devices | `executor` |
| Validate / audit / test | `tester` |
| Document and feed `memory/` | `documenter` |

- **MUST:** Only the `executor` opens a connection to devices.
- **MUST:** The `executor` follows the plan — it does not decide *what* to change.

### V. Operational Safety (NON-NEGOTIABLE)

Touching a production network can bring services down. Every change is reversible.

- **MUST:** Capture the current state (baseline) before any config change.
- **MUST:** Generate the rollback script together with the proposed config.
- **MUST:** On failure during the application, run the rollback automatically.
- **MUST NOT:** Connect to a host that is not in `network/hosts.yaml`.
- **MUST:** NetOps runs as the dedicated Linux account `netops` (console, AI, subagents, terminal,
  scheduler, updater) — never as root. Root on this server is **per operation**, through the Local host
  (no SSH, vault unlocked, `server.admin` permission); never sudo/an administrative group for `netops`,
  never a root service or cron running code writable by `netops`.
- **MUST NOT:** Expose credentials in logs, reports or versioned outputs.
- **MUST NOT:** The AI must not obtain, decrypt, read, print or copy the plaintext value of
  any `password`/`secret` field — not "for transparency", not with the vault unlocked. Decryption
  is **exclusive** to the access scripts (`scripts/tools/access/*`), at the moment of
  connecting, and to the **Local** backend (`scripts/engine/localadmin/`, service `netops-localadmin`), which uses the
  local admin password (`CRED_LOCAL_ADMIN`) only to authenticate the `su` on the server itself — the AI triggers it
  through `session.py --host-id <ID of the Local host>`, and never reads, asks for or prints that password. The AI connects **only** by invoking those scripts with `--host <name>`; it **never** writes
  code that calls `resolve_host(decrypt=True)`, `resolve_secret` or `decrypt_value`, nor reads the
  `password`/`secret` fields. Vault unlocked = permission for the TOOLS to connect, not
  for the AI to read secrets.

### VI. The Inventory is the Source of Truth (MUST)

The agent only knows the network through what is in `network/`.

- **MUST:** `network/hosts.yaml` lists every reachable host.
- **MUST:** `network/topology.yaml` describes how the hosts interconnect.
- **MUST:** Host credentials stay only in `network/credentials.yaml` (git-ignored). Secrets that are not for a
  host (portals, APIs, tokens, for people) stay in the Password vault, `network/vault.yaml` (git-ignored, same
  vault key). The AI never reads or decrypts the secrets of either one (§V). It uses the Password vault keys
  only through `nvault run` (`scripts/tools/secrets/`), which injects the value into the process and masks the output.

### VII. No Runtime of Its Own (MUST)

The intelligence lives in Markdown/YAML interpreted by the IDE; the technical execution lives in
Python scripts. No database, no Docker, no server (OpenSquad principle).

- **MUST:** Run state in files (`runs/<id>/state.json`).
- **MUST:** Memory in text files (`memory/`).
- **MAY:** There may be an **ephemeral operator tool** — the CRUD web console in
  `scripts/engine/ui/` — provided that: (a) it is *stateless* (each request reads/writes only the canonical
  files; no state cache, no database, no second vault); (b) it binds to loopback
  by default (`127.0.0.1`) when run directly; the official launcher (`start.sh`) may listen on all
  IPs (`0.0.0.0`) **provided that** nothing opens without login (no vault/user = only the first-access
  wizard, with a single-use token); (c) the framework works 100% with it turned off (the AI IDEs
  remain the primary interface). It is a *tool over the files*, in the same
  spirit as `scripts/tools/docs/topology_render.py` — it is **not** a framework runtime.
- **MUST NOT:** The operator tool must not, **through its own UI functionality** (buttons,
  forms, automations), keep a device connection open, trigger workflows/changes
  that bypass the `baseline → rollback → veto` model (§V), or return plaintext secrets
  to the browser.
- **MAY:** Offer a **web terminal** (`--enable-terminal`, **OFF by default**) that
  is only a *passthrough* to a shell of the **human operator** — equivalent to an SSH
  session on the machine. This is **not** the framework/UI operating devices autonomously: it is the
  person at the keyboard. Requirements: explicit opt-in, login with the master password, never in `--read-only`, and
  the framework keeps working 100% with it turned off. What is typed there is the responsibility
  of the human (as in any SSH), outside the automation of the agents.
- **MAY:** Offer **"Access → Web"** (`POST /api/hosts/<id>/web-launch`, same gate as the web terminal) that opens the
  web interface of the host in a new tab already authenticated (`scripts/engine/lib/web_login/`, one provider per app). The login
  runs on the server; destination and credential come only from the inventory/vault. **Proxmox:** the browser receives only the *ticket*
  (valid ~2 h), never the password.
- **SINGLE EXCEPTION (authorized on 13/11/2026) — Zabbix:** the `zbx_session` cookie cannot be written from outside, so the
  `Handoff` of the `zabbix` provider carries the password to the operator's browser, **once**, in response to an explicit click
  (`Cache-Control: no-store`, form sent directly to Zabbix and removed from the page, no log or audit of the value).
  It applies **only** to the `zabbix` provider; another app that requires this needs a new amendment here.

---

## Governance

- Changes to these principles require a version update and propagation to `PADRAO.md`.
- **NON-NEGOTIABLE:** a violation blocks the run. **MUST:** a violation generates an alert.
- Versioning: MAJOR (incompatible redefinition), MINOR (new principle), PATCH (adjustment).

*NetOps Constitution v1.3.0 — Standardized | Living Project | Safe*
