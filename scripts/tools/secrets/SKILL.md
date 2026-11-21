---
id: secrets-run
name: Password vault secrets in environment variables (nvault)
type: script
runtime: python
description: Runs a command with keys/passwords from the Password vault injected only into the process environment, without writing them to a file and with masked output.
env: []
---

## What it does

The script resolves `nvault://<ID>/<field>` references to the value stored in the **Password vault**
(console **Inventory → Password vault**, `network/vault.yaml`). The values go **only into the environment of the
child process**. Any secret that shows up in the output (stdout/stderr) is replaced by `***`.

This way `.env`, `wrangler.toml`, scripts and the AI use the key **without the value being on disk or appearing in the
conversation**. It requires the **vault unlocked**. Each use is recorded in the console Audit, with the action `vault.run`.

- **Whole reference:** `API_KEY=nvault://3/api-key`.
- **Embedded reference:** `DATABASE_URL=postgres://app:{{nvault://7/senha}}@db:5432/app`.
- **Item and field:** the item is its **numeric ID** (ID column in the list, URL `#vault/<ID>`). The ID **does not change** if
  the title changes. The field is its name as a slug: "API key" becomes `api-key`, "Usuário" becomes `usuario`.
  Old references keep working: the slug ID of the previous format (e.g. `nvault://simple-api/...`) and the old
  name of a renamed field are kept as aliases. Each item's screen shows the ready-made reference, with
  the **copy reference** button, and `list` prints them all. In the Claude tab, the user can mention the item with
  `#senha:<ID>`; the message arrives with the "[NetOps — menções]" block listing the item's references.

## When to use

Use it whenever a command, system or API needs a key from the Password vault: Cloudflare/Wrangler, the Coolify
API, an application's `.env`, an authenticated `curl`.

**The AI never reads the value**: no `cat network/vault.yaml`, no `/reveal` endpoint, no decrypting by hand. It
builds the command with the reference and runs it through `nvault`.

- **Scheduled tasks do NOT use** `nvault`, because the vault stays locked without a human around.
- **Masking:** covers accidental leaks (log, error, `env`). It does not hide a transformed value
  (base64, reversed etc.). Never transform the secret nor send it anywhere other than its own service.

## How to use

```bash
nvault run [--env-file F] [--no-dotenv] [--set VAR=REF] [--item ID --prefix P_] -- <comando> [args]
nvault list                      # items and references (never shows values)
nvault check [--env-file F]      # checks the .env references (does not decrypt)
```

`nvault` is the shortcut for `python3 scripts/tools/secrets/run.py`, installed in `~/.local/bin/nvault`.
If the shortcut is missing, use the full path or install it with
`ln -sf /opt/netops/scripts/tools/secrets/nvault ~/.local/bin/nvault`.

| Argument | Description |
|-----------|-----------|
| `--env-file F` | `.env` with references (repeatable). Without it, reads `./.env` if it exists. |
| `--no-dotenv` | Does not read `./.env`. |
| `--set VAR=REF` | Sets a variable from `nvault://<ID>/<field>`; accepts the shortcut `<ID>/<field>` (e.g. `T=3/api-key`). |
| `--item <ID>` | Exports all fields of the item ("API key" becomes `API_KEY`). Use with `--prefix COOLIFY_`. |

Exit codes: the command's own. `2` = invalid reference, `3` = vault locked (the command does **not** run),
`4` = console user without the `vault.use` permission.

## Setup

No new dependencies. The `vault.use` permission applies to whoever asks through the Claude tab and the console terminal
(`NETOPS_USER`); the admin already has it.

## Examples

```bash
# Cloudflare Workers (Wrangler reads CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID from the environment)
# project .env:     CLOUDFLARE_API_TOKEN=nvault://4/api-key
#                   CLOUDFLARE_ACCOUNT_ID=nvault://4/account-id
cd ~/projects/my-worker && nvault run -- npx wrangler deploy

# The Worker's own secret (the value is stored at Cloudflare)
nvault run --set V=4/webhook-secret -- sh -c 'printf %s "$V" | npx wrangler secret put WEBHOOK_SECRET'

# Coolify API
nvault run --no-dotenv --item 3 --prefix COOLIFY_ -- \
  sh -c 'curl -s -H "Authorization: Bearer $COOLIFY_API_KEY" "$COOLIFY_URL/api/v1/applications"'

# Application with a .env full of references
nvault check --env-file app/.env && nvault run --env-file app/.env -- npm start
```
