# Rule — Connection and Change Safety

Mandatory rules for any access to devices. They apply mainly to the
`executor` agent. Derived from §V and §VI of `constitution.md`.

## Before connecting

- Connect **only** to hosts present in `network/hosts.yaml`. A host outside the inventory
  is forbidden — record it as a blocker and stop.
- Resolve the access method and the **name** of the credential via `scripts/engine/lib/inventory.py`
  (`--show` masks secrets) — or let the access script itself resolve it. Never type
  loose credentials and **never** decrypt the secret yourself (see "Handling secrets").
- Use a `timeout` on every connection. A connection failure does not halt the run: the error is recorded
  and you move on to the next host.

## Collection (read-only)

- Collection commands are **read-only**. If in doubt whether a command changes state, treat it as a
  change (see below).
- Save the output in `runs/<id>/collected/<host>.txt`. Never in a versioned folder.

## Configuration change

Direct writing is allowed (project decision), but **always reversible**:

1. **Baseline.** Capture the current state of the affected area → `runs/<id>/collected/<host>.before.txt`.
2. **Rollback ready.** Confirm that `runs/<id>/proposals/<host>.rollback.txt` exists.
   Without a rollback, do not apply.
3. **Apply.** Run the config from `runs/<id>/proposals/<host>.change.txt`.
4. **Post-state.** Capture `runs/<id>/collected/<host>.after.txt`.
5. **Failure = automatic rollback.** If any command fails, or if management
   connectivity drops, run the rollback immediately and stop.

## Lockout risk

Before changing firewall rules, the management address, ACLs or access services (SSH/API),
check whether the change can cut the management connection itself. If there is a risk, the
`planner` must include a safety mechanism (e.g.: `safe-mode` on MikroTik, scheduling
an automatic rollback).

## Credentials and handling secrets (NON-NEGOTIABLE)

**The AI never handles a plaintext secret.** Decrypting, reading, printing, saving or copying
the value of a `password`/`secret` field is **forbidden** — even with the vault unlocked, even
"to check" or "for transparency". The only things that decrypt are **exclusively** the access
scripts (`scripts/tools/access/*`), at the moment of connecting, and the **Local** backend
(`scripts/engine/localadmin/`), which authenticates the `su` of `netops-admin` on the server itself.

## Local host (this NetOps server)

- It is the host with `access.method: local` (created by the installer, protected: it cannot be deleted and its
  access/credential cannot be changed). It does not use the network: `session.py exec|run --host-id <ID-LOCAL> --command "..."` runs
  **as root**, one operation per command (no persistent root shell: put `cd`/`export` in the same command).
- A command that does not need root: run it directly in Bash (the AI already is `netops`). Root only when the request requires it.
- Prerequisites: vault unlocked and a user with `server.admin`. Something missing -> the script says what (code
  `vault_locked`, `authorization_denied`, `local_access_disabled`...): **inform the human and stop**; never try
  `sudo`, `su`, SSH to 127.0.0.1 or reading the credential.
- Backup before/after (`change.py begin/end --host-id <ID-LOCAL>`) applies the same way: the Local baseline includes
  packages, services, ports, groups and firewall. The package manager has **no** universal rollback: say
  beforehand what is irreversible. Installing Docker does not add `netops` to the `docker` group.
- Never treat the IP of a remote host as local, nor `127.0.0.1` as proof that it is the Local host.

- To connect/collect/change, **invoke the access script** with `--host-id <integer>`
  (or `--host <hostname-or-alias>` for compatibility). It resolves the
  credential internally and uses the secret without returning it — you receive the command OUTPUT, never
  the password.
- **Never** write code that calls `resolve_host(decrypt=True)`, `resolve_secret()` or
  `decrypt_value()`, nor read the `password`/`secret` fields of `credentials.yaml`.
- **Never** print/echo a password (`print`, `echo`, `log`) nor pass it as a shell argument
  (it becomes visible in `ps`/history). If a command returns a secret, **mask** it before displaying.
- An unlocked vault is permission for the **tools** to connect — **not** for the AI to read
  secrets. If you think you need the password value, you do not: the tool needs it,
  not you. Stop and use the tool.

Credentials **never** go into `runs/`, `reports/`, `memory/` or logs (only into `credentials.yaml`,
git-ignored). Decryption happens only in memory, **inside the access script**, via
`scripts/engine/lib/inventory.py:resolve_secret()`; the session key lives in RAM (tmpfs, `0600`),
never on disk. The vault is unlocked by the human (`python3 scripts/engine/vault/cli.py unlock`);
the AI does not type the master password.
