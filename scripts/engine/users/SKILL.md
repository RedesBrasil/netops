# SKILL — Users, access groups and audit (multi-user)

## What it is

The NetOps console is **multi-user**: each person signs in with **e-mail + password**. Each user
belongs to one or more **access groups**, which define what they see and do in the console.
- Normal use: menu **System → Users / Access groups / Audit** (`#users`, `#access-groups`, `#audit`).
- Each person changes their own password in **My account** (`#account`, the button with the name at the top).
- This `cli.py` is the **recovery** path (admin locked out) and the automation path.

## Where it lives (SQLite, not YAML)

`runs/netops.db` (git-ignored, `0600`, WAL mode), via `scripts/engine/lib/accessdb.py`:
`users`, `access_groups`, `user_groups`, `sessions`, `login_failures`, `audit`, `claude_owners`.

**Why a database here and files everywhere else:** this is system state, written on every login and on every
request by several processes. It needs transactions ("do not delete the last admin") and queries
(audit). What the AI reads and edits (inventory, skills, memory) stays in files.

**Never copy the `.db` while the console is running.** Use `cli.py snapshot <destino>` (SQLite backup API).
The full backup (`scripts/tools/backup/full_mirror.sh`) already mirrors `runs/netops.db.snapshot`.

## Login = e-mail

- The e-mail is required and unique, case-insensitive (it is stored in lowercase).
- Each user also has an **internal ID** (`username`), derived from the e-mail (`joao.silva@x.com` → `joao.silva`; repeated → `joao.silva-2`).
  - It appears in the audit log, as the owner of Claude conversations and in the CLI.
  - **Changing the e-mail does not change the ID** and does not break the history.
- Login also accepts the internal ID. That is the case of the `admin` migrated without an e-mail, of scripts and of the CLI.
- The API receives `POST /api/auth/login {email, password}`. `username` is still accepted.
- **Password recovery by e-mail does NOT exist yet:** it would need SMTP configured. The admin resets passwords (screen or `cli.py passwd`).

## Permission model

- **Effective permissions** = union of the user's groups. The catalog is in `accessdb.PERMISSIONS`.
- **Route → permission:** `scripts/engine/ui/services/authz.py` (`RULES`).
  - It is **default-deny**: a route without a rule only passes for admin.
  - The test `test_every_route_is_mapped_to_a_permission` fails a new route without a rule.
- **`admin` group (fixed):** has `*`. Only it has the `admin_only` permissions:
  server terminal and files, settings, updates, users, audit,
  **editing scripts/skills** and **creating/editing scheduled tasks**. These last two run with the server account (`netops`; root only on the legacy install). `server.admin` = Local administration as root (admin only).
- **Suggested groups** (editable): `operador` and `leitura`.
- **No per-host scope:** whoever has `hosts.view` sees all hosts.
- **Claude tab:** can be enabled per group (`claude.use`).
  - The group's `net_perms` ceiling limits what it does on **equipment**. Above the ceiling, not even the on-screen approval allows it.
  - This is protection against mistakes, **not a security boundary**: the agent has a shell on the server.
  - Each conversation has an **owner**. Non-admins only see their own conversations; conversations without an owner (from before multi-user) are admin-only.
  - **Projects** are the exception: a project is private to its owner (admins included) and shared per user/access group with a level
    (view/participate/manage/owner); every member sees every conversation of the project. See `scripts/engine/ui/SKILL.md` → Projects.
    `projects.create` (grantable) lets a group create projects in a new folder of the default base.
  - The agent receives `NETOPS_USER` of **whoever sent the current message** (someone else continuing a conversation relaunches it with
    their network ceiling and GitHub account).
- **Frontend buttons:** pages mark buttons with the class `needs-<perm>` (e.g. `needs-hosts-edit`), and the shell hides them when the permission is missing.
  This is only visual: the backend is what blocks (403 `forbidden`).

## Per-user vault (keyslot)

- The user's password uses the same scheme as the vault (Argon2id + verifier, `lib/vault.build_meta`).
- The key derived from it **wraps the vault key**. That is why each user's login unlocks the vault without anyone knowing the master password.
- The slot is created automatically when the user signs in with the vault **already unlocked**. This covers new users and master-password changes.
- Disabling the user deletes the slot. Changing the password rewraps the slot.

## Migration (existing installation)

- **No users:** login keeps using the master password, as before.
  - The screen asks for the **administrator's e-mail** + master password. The 1st login creates the `admin` user (admin group) with that e-mail, that password and the keyslot.
  - A master password shorter than 8 characters stays in legacy mode: create the admin through the screen or the CLI.
- **Old sessions:** whoever was logged in (file `runs/.ui-auth-sessions.json`) stays logged in, as `admin`. The import happens once.
- **Compatibility:** `POST /api/auth/login {master_password}` without `username` = the `admin` password.

## GitHub per user

Each user connects **their own** GitHub account in **My account → GitHub** (`#account/github`). The agent of the
conversations that **they** open (Claude Code tab, Projects) uses that account for push, PR and `gh`, and commits carry their
name and e-mail. Code: `scripts/engine/lib/github_identity.py`, `ui/services/github_auth.py`, `ui/routers/github.py`.

- **How to connect:** GitHub CLI device login (code + `github.com/login/device`, authorized in the person's
  browser) or a personal token. The GitHub password never goes through NetOps.
- **Where it lives:** `runs/users/<username>/gh/` (`gh`'s GH_CONFIG_DIR, token in `hosts.yml` with `--insecure-storage`,
  folder 0700) and `runs/users/<username>/github.json` (login, name, chosen e-mail, no token). All git-ignored.
- **Agent environment** (`claude_svc._options` → `github_identity.env_for`): their `GH_CONFIG_DIR`,
  `GIT_AUTHOR_*`/`GIT_COMMITTER_*`, github.com credential helper via `GIT_CONFIG_*` (overrides any gitconfig),
  `GIT_TERMINAL_PROMPT=0`; inherited `GH_TOKEN`/`GITHUB_TOKEN` are removed.
- **No account connected:** `GH_CONFIG_DIR` points to `runs/users/_sem-github/gh` (empty). Push, PR and `gh` fail and
  **never** use the server account. Commits carry the name and e-mail of the console record.
- **Applies to new or reopened conversations:** the environment is fixed when the agent process starts. Whoever resumes
  someone else's conversation (admin) uses **their own** GitHub.
- **Guard** (`_hook_github_guard`, non-admins only): blocks reading `/root/.config/gh`, `runs/users/`, `gh auth token`,
  changing `GH_CONFIG_DIR`/`GH_TOKEN`, `env -i/-u`, `git config credential/user.*` and `--author`. It is a rail against
  mistakes, **not** a boundary: the agent has a shell with the server account.
- **Where it shows:** only in **My account → GitHub**. It does not show in the Claude tab nor in the Users list (user's
  decision, 19/11). The admin checks and revokes only through the API: `GET`/`DELETE /api/users/<u>/github`.
  Deleting the user deletes their folder. The audit log records `github_connected`, `github_disconnected`, `github_email`
  and `github_revoked`.
- **No-users mode:** nothing changes; the agent uses the server's `gh`.
- **Server:** the updater and the full backup keep using root's `gh` (`/root/.config/gh`). Ideally this is a
  service account, not someone's personal one.
- **Scheduled tasks:** `agent.github_as: <username>` (CLI `--github-as`) makes the task's agent use that user's
  GitHub. Empty keeps the server's `gh`.
- **Tests:** `scripts/engine/ui/tests/test_github_per_user.py`.

## CLI

```bash
python3 scripts/engine/users/cli.py list                       # users, groups, last login, sessions
python3 scripts/engine/users/cli.py groups
python3 scripts/engine/users/cli.py reset-admin [--email a@b.com]   # RECOVERY: creates/reactivates admin + new password
sudo -u netops python3 scripts/engine/users/cli.py setup-link [--hours 24]   # new install: (re)generates the FIRST ACCESS link
python3 scripts/engine/users/cli.py add joao@empresa.com --groups operador --name "João" --temp
python3 scripts/engine/users/cli.py passwd joao@empresa.com --temp         # temporary password, drops the sessions
python3 scripts/engine/users/cli.py disable joao | enable joao | delete joao
python3 scripts/engine/users/cli.py sessions [--user joao] ; logout joao | logout --all
python3 scripts/engine/users/cli.py audit --user joao --limit 100
python3 scripts/engine/users/cli.py snapshot /caminho/netops.db
python3 scripts/engine/users/cli.py project-owner --project meu-site [--user joao]   # show/set a Project owner (ownerless project)
```

The password never goes as an argument. Use `getpass` (interactive terminal) or `--password-stdin`.

## Security

- **Throttle:**
  - After 5 consecutive failures for a user+IP (or 20 for an IP), the wait grows (15 s × 2ⁿ, max. 15 min).
  - A failure counts even with the correct password during the lockout.
- **Temporary password (`must_change_password`):** the API returns 403 `password_change_required` until it is changed.
- **Audit:**
  - Records login/logout/failure, every write to the API (including the **denied** ones, with the status), terminal openings and user/group changes.
  - Never stores the request body.
  - Retention in `ui.audit_keep_days` (default 365).
- **Tests:** `scripts/engine/ui/tests/test_multiuser.py` and `tests/multiuser.browser.mjs`.
  - The browser test needs an instance with a fake vault: `NETOPS_E2E_VAULT=... tests/e2e-env.sh up`.
