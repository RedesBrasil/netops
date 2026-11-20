---
id: vault
name: Credential vault
type: script
runtime: python
description: Encrypts the passwords in network/credentials.yaml with a master password and unlocks the session.
env: [NETOPS_VAULT_KEY]
---

## What it does

Encrypts at rest the secret fields (`password`, `secret`) of
`network/credentials.yaml`, leaving each value as `enc.v1:<token>` (the structure and the
`username` values stay readable). Decryption happens **only in memory**, during the
session, after unlocking with the **master password**.

- **Encryption:** Fernet (AES-128-CBC + HMAC). **KDF:** Argon2id (Scrypt fallback).
- **Session:** the derived key (never the password) is kept in a `0600` file in RAM
  (`$XDG_RUNTIME_DIR/netops/session.key`, tmpfs). It re-locks on **inactivity (15 min,
  configurable)**, on `lock`, or on logout. Since it lives across processes, it works both for the
  operator and for the AI agents (each of their commands runs in a new shell).
- **Terminal-only mode (`--env`):** optional; the key goes into an environment variable and dies
  when the terminal closes — but it is not shared with the scripts run by the AI.

## Password vault (`network/vault.yaml`)

The same vault (master password and session key) also protects the console's **Password vault**
(**Inventory → Password vault**, `#vault`): secrets that do not belong to a host, such as a portal login, API key or token.
- **Structure:** `fields` is the catalog of reusable fields (`kind: secret|text`). `templates` holds the fields of each
  template, with `required`/`visible` per template. `items` (key = stable numeric ID, `next_item_id`, old slug in `aliases`) holds the values; the `secret` type becomes `enc.v1:` and `text` stays in clear.
- **Code:** `scripts/engine/lib/pwvault.py` (format, defaults, `reencrypt_file`) and
  `scripts/engine/ui/services/vault_items_svc.py` (CRUD, required-field validation, reveal).
- **API:** `/api/vault/catalog`, `/api/vault/fields`, `/api/vault/templates`, `/api/vault/items`,
  `POST /api/vault/items/<id>/reveal` (only with the vault unlocked and the `vault.reveal` permission).
- `change-password` re-encrypts `vault.yaml` together with `credentials.yaml`.
- **Use in a command/`.env` without exposing the value:** `nvault run -- <cmd>` with the `nvault://item/campo` references (see `scripts/tools/secrets/SKILL.md`).
- **NON-NEGOTIABLE:** the AI never reads nor decrypts the secrets in `vault.yaml`, nor calls the `/reveal` endpoint.
  The human looks them up, on screen. The AI uses the keys only through `nvault`.

## When to use

- Once, to migrate `credentials.yaml` from plain text to encrypted (`init` + `encrypt`).
- At the start of each work session, to unlock (`unlock`).
- To rotate a password (`set`) or change the master password (`change-password`).

The AI does **not** run `init`/`unlock`/`set`/`change-password` (they need a password typed in a real
TTY). The AI may run `status` and `lock`, and the access scripts use the session key
automatically.

> **NON-NEGOTIABLE — the AI never reads the secret in plain text.** Decrypting, reading, printing or
> copying a `password`/`secret` value is forbidden, even with the vault unlocked. Only the access
> scripts (`scripts/tools/access/*`) decrypt, at the moment of connecting. The AI connects
> by invoking those scripts with `--host <nome>`; it never calls `resolve_host(decrypt=True)`,
> `resolve_secret` or `decrypt_value`, nor reads the secret fields. An unlocked vault allows the
> TOOLS to connect — not the AI to read passwords. See `constitution.md` §V.

## How to use

```bash
python3 scripts/engine/vault/cli.py <subcomando> [--file PATH]
```

| Subcommand | Does | Asks (hidden) |
|------------|------|---------------|
| `init` | Creates the `vault:` block (salt + verifier) | master password ×2 |
| `encrypt` (`migrate`) | Plain text → `enc.v1:` (idempotent; `--dry-run` simulates) | master password |
| `set --cred N --field {password,secret}` | Sets/rotates a field | password + value |
| `unlock [--ttl SEG] [--env]` | Unlocks the session | master password |
| `lock` | Locks the session (deletes the cache) | — |
| `status` | Vault/session state (exit 0=unlocked, 1=locked) | — |
| `change-password` | Changes the password and re-encrypts everything | old password + new ×2 |

## Setup

No new dependency: `cryptography` (already in `requirements.txt`, present via `paramiko`) and
`pyyaml`. Requires `$XDG_RUNTIME_DIR` (tmpfs) for the RAM cache; without it, it falls back to `/run/user/<uid>`
and, as a last resort, `/tmp` (with a warning that it may be disk).

## Examples

```bash
# Initial migration (once)
cp network/credentials.yaml ~/creds.backup.$(date +%F).yaml   # backup outside the repo
python3 scripts/engine/vault/cli.py init
python3 scripts/engine/vault/cli.py encrypt --dry-run
python3 scripts/engine/vault/cli.py encrypt

# Day to day
python3 scripts/engine/vault/cli.py unlock      # unlocks (type the master password, no echo)
python3 scripts/engine/lib/inventory.py --list  # works even when locked (does not decrypt)
# ... agents/scripts access the equipment using the session key ...
python3 scripts/engine/vault/cli.py lock        # lock when done

# Terminal-only mode (locks when the terminal closes; not shared with the AI)
eval "$(python3 scripts/engine/vault/cli.py unlock --env)"
```
