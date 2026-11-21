# SKILL — NetOps Web Console (CRUD)

## What it is

A local web interface to **create and edit** everything that is normally edited by hand in the
NetOps files: hosts, groups, credentials, topology, memory, best practices, config examples,
workflows, agents and the project configuration. It also **displays** (read-only) reports and
runs.

Hosts use **automatically generated, immutable integer IDs**. The field does not appear in the
form; the hostname is editable and the screens show name/IP. Changing the name keeps all
links. The API rejects IDs sent in POST/PATCH/PUT and the old ID rename route.

You can **rename** groups and credentials, as well as knowledge/workflow/agent files. The
ID/name field is **editable in the item's own edit form** (there is no separate "Rename"
button): on **Save**, if the ID changed, the server renames **with cascade** — renaming a group
updates the `group` field of the hosts that use it; a credential updates `credential` in
hosts/groups. While the field is changed, the form shows **how many references** will be
updated. Segments stay in the canonical files and in the API; lessons are not renamed
(append-only, constitution §II).

It is an **ephemeral operator tool** (constitution §VII): *stateless* (each request reads/
writes only the canonical files — no database, no cache, no second vault), made to run when
the operator needs it and be shut down afterwards. The framework works 100% with it turned off.

## How to start it

**ALWAYS** through the script (never `python3 scripts/engine/ui/server.py` directly). It enables the web
terminal and listens on **all of the machine's IPs** (`0.0.0.0` + `::` if there is IPv6), single instance:

```bash
scripts/engine/ui/start.sh                          # all IPs (0.0.0.0), port 8765, terminal + Claude Code ON
NETOPS_UI_HOST=127.0.0.1 scripts/engine/ui/start.sh # force loopback (local only)
NETOPS_UI_PORT=9000      scripts/engine/ui/start.sh # another port
NETOPS_UI_TERMINAL=0     scripts/engine/ui/start.sh # starts WITHOUT the web terminal
NETOPS_UI_CLAUDE=0       scripts/engine/ui/start.sh # starts WITHOUT the Claude Code page
scripts/engine/ui/start.sh --read-only --no-vault-unlock   # extra flags are passed through
```

The script prints the URL (`http://<ip>:<port>/`). Access is protected by **e-mail and password login**
(multi-user with access groups; with no registered users, the vault master password; see "Security"
and `scripts/engine/users/SKILL.md`); there is no transport token in the URL.

> Under the hood the script calls `scripts/engine/ui/server.py` (flags: `--host/--port/--read-only/`
> `--no-vault-unlock/--enable-terminal/--enable-claude/--no-browser`). The operational entry point,
> including during tests, is still the launcher; do not start the server directly.

## A tab is missing? (read before "it disappeared"/"it broke")

The pages under **SYSTEM** follow rules that are confusing at first sight — **before assuming a deploy
failed**, check here:

- **Feature-flag tabs (Terminal and Claude Code).** They only appear when the feature is **enabled**.
  Through `start.sh` both come **enabled by default**; starting `server.py` by hand **without** `--enable-terminal`/
  `--enable-claude` leaves the tabs **invisible** (not a bug). Check the state at `GET /api/config/meta`
  (`terminal_enabled` / `claude_enabled`). Disabling is opt-out: `NETOPS_UI_TERMINAL=0` / `NETOPS_UI_CLAUDE=0`.
- **New tab does not appear after updating the code?** It is the **SPA cache** in the browser (`index.html` is
  `no-store`, but `main.js` is cached by ETag). Do a **hard refresh**: `Ctrl+Shift+R` (or `Shift+F5`).
- **"Claude Code" tab appears but does not connect?** The page requires the `claude` binary in the **PATH** of the
  server process (`claude_svc.is_available()`). `start.sh` already injects `~/.local/bin` into the PATH; if you start
  `server.py` by hand, make sure `which claude` works in the same environment.
- **Agent logged out ("/login does not exist")?** `/login` is a command of the Claude Code **TUI** — it does **not**
  exist in the SDK protocol, so it never appears in the tab's slash list. The tab handles `/login`,
  `/logout` and `/auth` **on its own** (see `services/claude_auth.py`): it opens the OAuth flow of
  `claude auth login`, shows the URL for you to authorize in the browser and receives the pasted code. The
  message field does **not lock** when the session drops — you can type `/login` even while disconnected.
  After login, "Reload session" relaunches the agent **resuming the same conversation**.
- **I logged in through the web terminal and the tab is still logged out.** In layout 2 (`netops` account, default since
  the 19/11/2026 plan) console, web terminal, tasks and subagents use the SAME account and the SAME
  `$HOME/.claude` (`/var/lib/netops/.claude`): logging in on any of them applies to all. Only in the
  **legacy** install (root console) does the terminal drop to `netops` (see `NETOPS_TERM_USER` in `routers/terminal.py`),
  and then there are two different stores — and two conversation lists. When in doubt, log in **through the tab itself**. The modal shows
  which file/user is involved, and `GET /api/claude/auth/status` answers the same (no token at all).
- **I see NOTHING besides the login?** The vault is initialized and you have not logged in yet — the login gate
  (master password) locks the whole `/api`. There is no longer a transport token in the URL (`?token=`); it was removed.

## Projects (Projects menu)

A **project** is a name + a **server folder**. The Claude Code sessions opened in it run with `cwd` set to that folder,
and "the project's sessions" are the conversations of that folder (Claude Code already separates transcripts by folder in
`~/.claude/projects/`; the SDK receives `directory=<folder>`). There is no session→project table.

- **Registry:** `runs/claude/projects.json` (`services/projects_svc.py`). `id` = slug of the name, immutable on rename. Rejects a
  nonexistent folder, a duplicate folder (two projects would share the same conversations) and a forbidden folder (see Security).
  Removing only deletes the registry entry; never the folder nor the conversations. **Create new folder** (`new_folder`, default inside `~/projects` of the console account = `/var/lib/netops/projects` in
  layout 2; created by the console itself, no root needed; `GET /api/projects` returns it as `default_base`) or **open existing
  folder**, as in VS Code. Visible subfolders of that HOME are allowed even though `/var/lib` is a system tree; hidden ones
  (`~/.claude`, `~/.ssh`) and the HOME itself are not. Projects already registered elsewhere (e.g. old `/opt/projetos`) keep working.
- **API:** `GET/POST /api/projects` (`{name, path, trust?, new_folder?}`), `PATCH /api/projects/<id>` (`{name?}` / `{trusted}`),
  `DELETE /api/projects/<id>`, `GET /api/projects/browse?path=` (subfolders only; returns `allowed`/`reason`/`config`),
  `GET /api/projects/<id>/sessions[/search?q=]`. The routes `/api/claude/sessions/<sid>/…` and `/api/claude/upload` accept `?project=<id>`;
  the WebSocket `/api/claude` accepts `&project=<id>`. **Project given and invalid = 404/4404**, it never falls back to the NetOps folder.
- **Security (VS Code model):**
  - **Agent account = user level** (`~/.claude/`: OAuth in `.credentials.json` or `env` block in `~/.claude/settings.json`).
    The CLI reads it from any folder. The console does **not copy** `ANTHROPIC_*`/`CLAUDE_CODE_OAUTH_TOKEN` into the project session environment.
    Account declared only in the NetOps settings → the Projects list warns to move the `env` to `~/.claude/settings.json`
    (`claude_models.account_only_in_netops`, only looks at key names).
  - **Folder trust (Workspace Trust):** `.claude/settings*.json` (hooks, env, statusLine, apiKeyHelper) and `.mcp.json` execute on open.
    **Untrusted** project = **restricted mode**: `setting_sources=["user"]` (ignores the folder's settings, MCP and CLAUDE.md). Trusted = `user,project,local`.
    A new folder or one without executable config is born trusted; with config, only if the admin marks it. Read at every session start.
  - **Forbidden folders** (`projects_svc.deny_reason`): `/` and system directories (`/etc`, `/usr`, `/proc`, `/var/lib`…), the base folders
    (`/opt`, `/srv`, `/home`, `/root`, `/tmp`, `/var`…) themselves, NetOps (the folder, inside it or above it), the home and its hidden folders (`~/.claude`, `~/.ssh`).
    Symlinks are resolved first; a registry entry hand-edited to a forbidden folder is not used (`path_of` → None).
  - **Permissions:** create/rename/remove/trust and browse folders = `projects.manage` (**admin only**); view projects and use the sessions = `claude.use`.
  - **Network rules apply in the project:** the group ceiling and the 🔐 Network selector (SDK hooks) still apply; `guard-netops.sh` (backup before
    changing equipment), which would not load outside NetOps, runs as a programmatic hook (`_hook_netops_guard`; missing guard = blocks).
  Attachments in a project come back with an absolute path.
- **Post-restart resume:** the note in `resume-on-restart.json` stores the `cwd` only for projects; without it the session would come back in the wrong folder.
- **Order and archived (per user):** `runs/claude/projects-prefs.json` (`{"<user>": {"order": [...], "archived": [...]}}`).
  `PUT /api/projects/order {ids}` (drag and drop in the list and in the sidebar) and `PUT /api/projects/<id>/archived {archived}`
  = `claude.use` (each person's preference, does not touch the registry). Archived disappears from the sidebar and the list; it stays in `#projects?arquivados=1`.
  Removing a project removes the id from everyone's order/archived. Rename (✏) and remove (🗑) also directly in the list (`projects.manage`).
- **Project files:** source `src=project:<id>` of the file manager (`files_svc.ProjectFS`), **confined to the project folder**:
  every path is resolved (symlinks included) and must land inside; content (read/write/chmod/download/copy source) follows the
  link, operations on the entry (create/rename/delete/destination) look at the real parent folder; links to outside do not go into the zip; the project root is not
  deleted/renamed. Permission **`projects.files`** (grantable per group; admin has it). Full page `#projects/<id>/files?path=&open=`
  (📁 Files button on the project page) and **panel beside the project chat**: **closed by default**, opens/closes via the
  📁 Files button in the bar (state and folder per project in `localStorage` `netops_pjfiles_<id>`, the conversation URL does not change).
- **Front:** `pages/projects.js` (list, new, project page, folder picker) and `claude-sessions.js` (`#projects/<proj>/<id|new>`).
  The chat is the same `ClaudeProvider`; `?project=` on the WebSocket binds the agent to the folder.
- **Tests:** `tests/test_projects.py` (registry, HTTP, `cwd`, resume, forbidden folders, trust, guard, account) and `tests/projects-routes.test.mjs` (routes).

## Initial setup (once, with internet)

The frontend dependencies are **vendored locally** (offline/air-gap-safe):

```bash
bash scripts/engine/ui/vendor_deps.sh     # downloads preact/htm/marked/js-yaml/xterm to static/vendor/
.venv/bin/pip install -r requirements.txt   # fastapi + uvicorn + ruamel.yaml + websockets
```

> `websockets` is required for the web terminal and the Claude Code page (uvicorn does the WS
> upgrade); without it `/api/term` and `/api/claude` respond 404. The Claude Code page needs
> `claude-agent-sdk` (in `requirements.txt`) **and** the `claude` binary in the PATH; the SDK reuses
> the existing subscription login (`~/.claude/.credentials.json`) — it does not require `ANTHROPIC_API_KEY`.

## Security (summary)

- **Listening:** `server.py` run directly binds to loopback; `start.sh`/the installer use **`0.0.0.0`** = all IPs
  (one IPv4 socket + one IPv6 `::` socket with `IPV6_V6ONLY`, so the client IP does not become `::ffff:x`). The configuration stores only
  the wildcard. The checks (supervisor, `start.sh`, installer) connect via `127.0.0.1`. To restrict to one IP:
  `NETOPS_UI_HOST=<ip>` in the identity (`/etc/netops/instances/<slug>.env`) or `NETOPS_HOST=<ip>` in the installer.
- **First access (#setup):** outside loopback, with no vault and no user (new install), the console is NOT left open:
  the whole `/api` responds `setup_required`, except `/api/setup/status|complete`, `/api/auth/status` and `/api/config/meta`.
  `POST /api/setup/complete` requires the single-use token (`lib/setup_token.py`, `runs/setup/token.json` = only the hash,
  24 h; to generate again: `users/cli.py setup-link`) and creates vault + admin + `instance.language` (`project-config.yaml`), logs
  in and writes `runs/setup/finish-request`. The root unit `netops-setup-finish-<slug>.path` then runs
  `/usr/local/sbin/netops-setup-finish <slug>` ONCE: it pins the vault verifier in sudo and generates the Local host password.
  State at `GET /api/setup/finish` (`services/setup_svc.py`). Loopback without token (dev/tests) stays open as before.
- **Host/Origin checked** on the whole `/api` and on WebSockets (anti DNS-rebinding and anti CSRF/CSWSH) — single policy in
  `deps.host_origin_allowed`. **Reverse proxy / any domain:** with login active (vault initialized) any
  Host/Origin is accepted, because the gate is the session (token in header/query, never a cookie). Without login the console is open and Host/Origin
  stay strict (loopback, bind IP or `NETOPS_UI_ALLOWED_HOSTS=dom.com,.outro.com,*`). uvicorn trusts
  `X-Forwarded-*` (`NETOPS_UI_FORWARDED_ALLOW_IPS`, default `*`). The proxy must forward WebSocket (`Upgrade`/`Connection`).
- **Multi-user (e-mail + password, access groups) — see `scripts/engine/users/SKILL.md`.**
  - **Database:** users, groups, sessions and audit live in the SQLite `runs/netops.db` (`lib/accessdb.py`).
  - **Permission per route:** lives in `services/authz.py`, default-deny. The test fails a new route without a rule.
    - New route: add the rule to `authz.RULES`.
    - Action button: mark it with the class `needs-<perm>`.
  - **Login:** each user's login unlocks the vault through their keyslot.
  - **GitHub per user:** `#account/github` connects each person's account, and the conversation's agent uses only that one (`GH_CONFIG_DIR`
    and git identity in the env of `claude_svc._options`). Details in `scripts/engine/users/SKILL.md`.
  - **No users:** the old mode (master password) applies, described below. The 1st login creates the `admin`.
  - **Admin only** (they run with the server account, `netops`):
    - server terminal and files, settings, updates, users, audit;
    - editing scripts and scheduled tasks;
    - `server.admin`: Local administration as root (Local host and Files → 🔓 Open as root).
  - **Claude tab:** can be granted per group, with an owner per conversation and a `net_perms` ceiling.
    - It is protection against mistakes, not a security boundary: the agent has a shell on the server.
  - **Endpoints:** `GET /api/auth/me`, `POST /api/auth/password`, `/api/users*`, `/api/access-groups*`, `/api/access-catalog`, `/api/audit`.
- **Login with the master password (legacy mode, no users) is the access gate:** when the vault is **initialized**, the whole console sits behind
  a login screen. The master password (same `derive_key`+`verify_key` as the vault) issues its own **login
  session** (sid in process memory, header `X-Netops-Session`, sliding TTL); every `/api`
  then requires it, except the bootstrap allow-list (`/api/auth/{login,status,logout}`,
  `/api/config/meta`). The same login **also unlocks the vault** (unless `--no-vault-unlock`).
  Endpoints: `GET /api/auth/status`, `POST /api/auth/login`, `POST /api/auth/logout` ("Log out" button).
  ⚠ **With no initialized vault there is no master password — therefore no login, and the console is open** to
  anyone who reaches the address (only Host/Origin protect it). Initialize the vault
  (`scripts/engine/vault/cli.py init`) to protect access with a password. The terminal/Claude WS uses
  the same gate (`?auth=<sid>`). Session in memory ⇒ valid only while the server is up (uvicorn single-process).
  The browser shares only the sid in `localStorage`, on the same origin (protocol, host and
  port), with automatic migration from the old `sessionStorage`. Opening/reloading other tabs
  reuses the session; login, logout and expiration are synchronized between tabs. Late
  responses from a previous session do not erase a new login. The password is not stored;
  expiration on the server or a restart still require a new login.
- **Anti DNS-rebinding:** without login, the `Host` header must match loopback/bind IP/`NETOPS_UI_ALLOWED_HOSTS` (otherwise 403 `forbidden_host`); with login active any Host passes (see above).
- **Vault:** the UI **reads the status** (`session_status()` — does not renew the TTL) and **encrypts on write**
  (`encrypt_value` with the session key) and **never** returns a plaintext password to the browser.
- **Unlocking via the web:** the vault banner has **"Unlock here"** — the typed master password
  goes in one request (`POST /api/vault/unlock`), derives the key (`derive_key` Argon2id, same path
  as `cli.py unlock`) and is discarded: **it is not stored, logged or returned**. The resulting session
  also applies to the CLI and the agents. There is also **"Lock"** (`POST /api/vault/lock`).
  ⚠ On a **non-loopback** bind over HTTP, the master password travels in **plaintext** on the network — use only
  behind an SSH tunnel/VPN. To require the terminal and disable web unlock: `--no-vault-unlock`.
- **Password vault (`#vault`, `pages/vault.js`, `routers/vault_items.py`, `services/vault_items_svc.py`):** secrets that
  are not host secrets, stored in `network/vault.yaml` (0600). Tabs Items, Templates and Fields (`#vault`, `#vault/<id>[/edit]`,
  `#vault/templates[/<id>]`, `#vault/fields[/<name>]`). Plain text always appears; secrets only with the vault unlocked
  (`423`). Permissions `vault.view|reveal|edit|templates`. Browser test: `tests/vault.browser.mjs` (needs `NETOPS_E2E_VAULT`).
- **Integrity:** atomic write (tmp + replace), `credentials.yaml` in mode `0600`,
  comments preserved (ruamel round-trip), optimistic concurrency by hash (`409` on conflict),
  schema validation before writing a host/group. Renames that touch **two files**
  (credential→hosts.yaml, host→topology.yaml) are written in a **transaction** (`yaml_io.write_many`):
  it validates the revs of both before writing and **rolls back** if the second write fails.
- **Web terminal (`--enable-terminal`):** ⚠ it is a **real shell** (PTY) on the machine = arbitrary
  command execution as the server user. **OFF by default** in server.py (`start.sh`
  enables it; `NETOPS_UI_TERMINAL=0` disables it), never enabled in `--read-only`. The WebSocket
  handshake (`/api/term`) is authenticated **by hand** (token + Host + Origin) because the app's http middleware
  does **not** cover WebSocket. Over non-loopback HTTP, the token (in the URL) travels in plaintext
  and gives a full shell — prefer an SSH tunnel/VPN.
- **HOST terminal (SSH/Telnet) — "⌨ Access" button in Hosts:** same gate as `/api/term`
  (`--enable-terminal`, outside `--read-only`, login + Host + Origin). WS `/api/term/host/<id>?method=&port=`;
  opens in its own window `#hostterm/<id>?method=ssh&port=22` (full screen, no menu). Methods = main `access`
  + `extra_access` (ssh/telnet only, in registration order): 1 method → opens directly; 2+ → choice popup
  (`#hosts?access=<id>`). SSH = `asyncssh` (PTY xterm-256color, resize, legacy algorithms at the end
  of the list); Telnet = `telnetlib3` (NAWS, automatic login detecting `login:`/`Password:`, Enter CR LF).
  The credential is decrypted **on the server** (vault unlocked) and never goes to the browser. **Vault locked**
  → status `vault_locked` and the window opens the "Unlock the vault" popup (`UnlockModal`); unlocked → the
  client sends `{"vault":"retry"}` and the login proceeds automatically; cancelled → `{"vault":"manual"}` and the terminal
  asks for the password. No credential (or `--no-vault-unlock`) → the terminal asks for user/password (not stored). SSH host key: accepted and the
  fingerprint is logged. Audit in `runs/<ts>-terminal-<id>/session.log` (keystrokes are not recorded).
  Code: `routers/host_term.py`, `services/host_term_svc.py`, `static/js/pages/host-term.js`.
- **Files (`#files` menu) and the host terminal SFTP panel:** full file manager, with
  browsing, uploading files and folders, downloading WITHOUT zip (several files = one download each; folder = recreated in a folder
  on the PC chosen in the picker — File System Access API, Chrome/Edge on HTTPS or localhost; without it, the screen offers
  a .zip or loose `folder_file` files; `GET /api/files/download-plan` expands the folders; "Download as .zip" in the
  context menu), create, rename,
  copy, cut, paste, edit text (up to 5 MiB) and change permissions. It has **the same trust level as the
  web terminal**: it is only enabled with the terminal enabled (`deps.files_enabled()`; `start.sh` enables it) and never in
  `--read-only`. `NETOPS_UI_FILES=0` disables only the files. The menu runs **as the server user (root in the
  default install)** and has no directory jail, not even for secrets (user decision, 13/11/2026). Protections:
  - deleting, moving or renaming `/` and the 1st-level system folders (`/etc`, `/usr`, ...) is refused;
  - delete does not follow symbolic links and is permanent; the screen requires typing the item name (or the count);
  - upload in 8 MiB parts writes to a `.netops-upload-<uid>` and only renames at the end; editing writes to a
    temporary file and checks mtime+size (409 `changed` if the file changed);
  - every write and download goes to `runs/files/audit.log` (without content).
  Download uses a **single-use link** (`GET /api/files/download-link` → `/api/files/dl/<ticket>`, 120 s).
  This is the only `/api` path allowed without the session header (`app.py`, `AUTH_TICKET_PREFIX`), and the ticket is only
  issued to someone who is logged in. **SFTP panel:** when connecting via SSH, the host terminal registers the connection in
  `files_svc.SFTP_SESSIONS` and sends the token in the `conectado` status (`sftp`). The panel uses `src=<token>` on the same
  routes, so it does not do a second login, even with a password typed by hand. The session goes away when the terminal closes.
  The panel ALWAYS starts collapsed; it opens and collapses via the round ‹/› button on the edge or via "Files" at the top.
  Telnet and hosts without SFTP (Cisco/Huawei, in general) show "unavailable". Code: `routers/files.py`,
  `services/files_svc.py`, `static/js/file-browser.js`, `files-core.js`, `pages/files.js`, panel in
  `pages/host-term.js`.
- **Claude Code page (`--enable-claude`):** ⚠ drives an **AI agent** (via `claude-agent-sdk`)
  that **runs commands and edits files** as the server user, with `cwd=NETOPS_ROOT` and
  inheriting `AGENTS.md`/skills/agents. Same posture as the terminal: OFF by default in server.py
  (`start.sh` enables it; `NETOPS_UI_CLAUDE=0` disables it), **never** enabled in `--read-only`. The WebSocket
  (`/api/claude`) and the upload (`POST /api/claude/upload`) use the **same auth** (token + Host +
  Origin + session). The UI exposes **all modes** (`plan/default/acceptEdits/dontAsk/bypassPermissions`)
  and an on-screen approval prompt (`can_use_tool`); each tab opens its own `claude` subprocess,
  terminated on disconnect. Attachments go to `runs/claude/uploads/`.
- **Agent login (`/api/claude/auth/*`, `/api/claude/login`):** the OAuth flow of `claude auth login`
  driven by the tab (`services/claude_auth.py`), in a PTY, in the **same env/HOME** as the agent — that is what
  guarantees the credential lands in the store the tab reads. Same gating as the others (`--enable-claude`, never
  in `--read-only`, Host + Origin + session). The status is **metadata** (`loggedIn`, e-mail, plan, file
  path): token and refresh token **never** leave through the API. The pasted OAuth code is treated as a secret —
  PTY echo off and redaction in the output; it goes to no log.

## Boundary (what the UI does NOT do)

By the security model (§IV/§V), the UI — **as a UI feature** (buttons/forms) —
**does not connect to equipment** nor trigger workflows/changes. Collecting, applying config,
baseline/rollback remain the job of the `executor` agent via the AI IDE. The CRUD part is only
files + display.

**Exception: the web terminal** (`--enable-terminal`, opt-in) is a *passthrough* to a shell of the
**human** — equivalent to SSH. It is not the framework operating on its own; it is the person at the keyboard, and
what they type is their responsibility (constitution §VII). It serves, e.g., to run `claude` or
the `scripts/tools/access/*.py` scripts and follow the execution in the browser.

**Exception 2: the Claude Code page** (`--enable-claude`, opt-in) takes that same human passthrough
to a **graphical interface**: instead of typing `claude` in the terminal, the person talks
to the agent directly on the web — with mode switching, on-screen approval of each tool, slash
commands and attachments. It is still the person in charge (they approve/choose the mode), just without the TUI.

**Exception 3: Scheduled tasks** (`#schedules`, `routers/schedules.py`). The screen only edits
`network/schedules.yaml` and reads `runs/schedules/`. What executes is the **system cron**
(`/etc/cron.d/netops-scheduler` → `scripts/engine/scheduler/cli.py tick`), with the console running or
not. "▶ Run" uses the same executor, in a detached process. Each task is an explicit request
from the human (they registered the command/prompt and the schedule). The scheduled agent comes with
`restricted` permission by default and never creates other tasks. The unread counter in the menu polls
`GET /api/schedules/notifications` every 30 s. Details in `scripts/engine/scheduler/SKILL.md`.

**Notification center** (`#inbox`, 🔔 bell at the top, `routers/inbox.py`, `static/js/inbox.js` + `pages/inbox.js`).
Reads `runs/inbox.db`; messages are born outside the console (scheduled tasks, scripts and agents via
`scripts/engine/inbox/cli.py`) — **there is no create route**. Approving/rejecting a request with an action triggers that action
(command or agent resuming the session) in a detached process; only the admin decides requests with an action. The counter
(`GET /api/inbox/summary`, a single 30 s poll shared by the bell, the menu and the tab title) adds unread +
pending requests. "Discuss in Claude" writes the prefill to `localStorage["cc-fork-prefill"]` and opens `#claude/<sid>`
or `#claude/new` (event `netops:claude-prefill` if the conversation is already open). Details in `scripts/engine/inbox/SKILL.md`.

## Structure

```
scripts/engine/ui/
  server.py            entrypoint (bind, token, browser)
  app.py               FastAPI (security middleware + handlers + StaticFiles)
  deps.py              canonical paths + state + domain exceptions
  models.py            Pydantic models (input validation)
  routers/             one router per resource (hosts, credentials, ..., terminal=WS PTY, claude=WS agent)
  services/            I/O logic: yaml_io (round-trip/atomic/concurrency), *_svc (claude_svc=SDK session)
  static/              Preact SPA (no build): index.html + js/ (+ pages/terminal.js, pages/claude.js) + vendor/ (xterm.js, ...)
  tests/               pytest E2E (vault, concurrency, masking, append-only, terminal WS, Claude flag, ...)
```

## Updates through releases

The topbar offers **Check for updates**, the installed version and the full notes of all
later stable releases. Applying requires login to the console, write mode and a managed
launcher. Save changes before confirming. Open interactive sessions do not block:
the restart ends them, keeping the conversation transcripts for resuming. Equipment
backups and running workflows must finish before applying.

`start.sh` now keeps a supervisor with a per-install lock. The package is prepared with a
verified backup; the server is restarted on the same URL and may require a new login. Failures
before confirmation restore the previous code and environment. The package examples do not
replace data and customizations. Version 2 converts the required identity formats
with its own transaction, only after the supervisor confirms the code.

While that conversion is pending, **Preparing NetOps** prevents opening the editors
or interactive connections; `GET /api/config/meta` reports `host_migration`. A failure in the pre-validation
of the candidate keeps the legacy data and triggers the return to the previous code. A later failure
keeps the new code and shows **ID migration blocked**, without announcing success or allowing
writes. Recovery on the next start uses the baseline/journal; external conflicts require
human review. The private state lives in `.netops-update/`, never in the runs/backups APIs.

The first adoption requires restarting the console through the updated launcher. GitHub CLI must
be authenticated in the server user/HOME to access the private repository. Do not send
or request tokens through the UI. Details and recovery: `scripts/engine/update/SKILL.md`.

## Tests

```bash
.venv/bin/python3 -m pytest scripts/engine/ui/tests/ -q
```

The tests run in an isolated temporary directory — they **never** touch the real files.

Session across tabs: `node --test scripts/engine/ui/tests/auth-session.test.mjs`.
The `tests/auth.browser.mjs` scenario validates three tabs on desktop/mobile, single login,
reload, logout and expiration; it requires a temporary console on loopback via
`NETOPS_E2E_URL`, with `PLAYWRIGHT_MODULE` and `CHROMIUM_EXECUTABLE` if needed.

## Links and reopening of Claude Code sessions

### Catalog and model errors

`GET /api/claude/models` discovers models through the handshake of the same CLI, HOME, directory
and settings used by the conversation. It does not send a prompt nor read tokens directly.
This respects local gateways/providers; querying Anthropic's public catalog
does not prove access through the provider that runs the tab. The default is the latest Sonnet
announced by the CLI, falling back to Claude Code's own default, with no pinned versions.
The weekly cache uses `source: claude-cli-v1` and ignores the old API cache; a failure
keeps the last catalog and limits automatic attempts for 60 seconds.
**Check models** forces a new discovery without inference.

The SDK keeps `AssistantMessage.error`, `ResultMessage.errors` and `api_error_status`.
A generic "issue with the selected model" error opens the choice of another model and
keeps the conversation UUID. Only explicit evidence of a limit (HTTP 429/code `rate_limit`)
opens the usage warning; being listed in the catalog does not prove the quota is exhausted. HTTP 529 indicates
overload, not 429. Both model/limit cases prevent automatic reconnection in a loop.

Tests: `tests/test_claude_models.py`, `tests/test_claude_sessions.py`,
`node --test scripts/engine/ui/tests/claude-errors.test.mjs` and
`tests/claude-sessions.browser.mjs` with fake WebSockets.

Each conversation has the URL `/#claude/<UUID>`. **Copy link**, in the header or in the
**Sessions** list, lets you reference it separately. The conversation title in the list is also
a link that can be opened in another tab. The link requires the normal console login;
it contains only the conversation reference, no authentication credentials.

Opening **Claude Code** (`/#claude`) resumes the last conversation selected in that browser.
Only the UUID is stored in `localStorage` (`netops_claude_last_session`); messages stay
in the Claude Code transcripts on the server. With no saved preference, or after the preferred
conversation is deleted, it opens the project's most recent one. With no conversations, it starts a new one.
An explicit link takes priority over the preference. **New session** (`/#claude/new`)
still opens an empty conversation and receives its UUID when the agent reports it.

Reloading, going back/forward and switching between the dock and the full page keep the selected
reference. Each tab keeps its own conversation; changing the last saved selection does not
automatically switch the conversation in the other tabs. With persistence enabled, opening the same
conversation in another tab transfers the socket to it; the previous one reports the transfer and
stops reconnecting. To resume it in the previous tab, reload.

The lookup `GET /api/claude/sessions/<UUID>` checks existence in the project, including for
conversations older than the recent list. Invalid/removed links show guidance
to choose another conversation or create a new one. Invalid or missing UUIDs are refused
before starting the agent. HTTP responses and events from old sockets cannot replace
the selected conversation; the history is loaded before streaming starts.

Tests: `node --test scripts/engine/ui/tests/*.test.mjs`, `tests/test_claude_sessions.py`
and `tests/claude-sessions.browser.mjs`. The browser scenario uses fake APIs and WebSockets,
in a temporary console; it does not start the real agent nor access personal conversations.


## Sending a message while the agent is working (now × queue)

With a turn in progress, the message box keeps accepting text. On send (Enter or ↑),
the tab **asks** what to do:

- **Send now** (Enter or `A`): goes straight to the agent, which **incorporates it into the current turn** and takes it
  into account in what it is doing (native CLI behavior, measured: it answers both texts
  in a single `result`). The bubble gets the label "during execution".
- **Add to queue** (`F`): the message stays in the **server queue** and only becomes a turn when the
  current task **finishes completely** (`ResultMessage`). Several items run in order, one turn
  each. The queue appears above the box: drag by the ⠿ handle to reorder (mouse or touch; with the handle focused, keyboard ↑/↓; the top one is next), ⚡ sends an item right away, × removes it from the queue. The bubble gets the label "from the queue".
- **Cancel** (Esc): back to editing without interrupting the agent.

Rules: the queue is **per session** and lives on the server (`ClaudeWebSession._queue`, ceiling `MAX_QUEUE`=20).
With persistence (default in `start.sh`; `NETOPS_UI_CLAUDE_PERSIST=0` disables it), it **keeps moving with the tab closed** and the state comes back on
re-attach. In classic mode, it dies with the socket. **Interrupt** or a turn with an **error** does not
trigger the queue on its own: the texts go back to the box (`queue_restored`) for you to decide what to do,
including when the tab was closed at that moment. Protocol: `prompt{queue:bool}`, `queue_remove`,
`queue_send_now`, `queue_move{id,to}`, `queue_add{texts}` → `queue`, `queue_dispatched`, `queue_restored` (see the docstring of `services/claude_svc.py`).
If the turn ends between choosing "queue" and the message reaching the server, the message runs right away.

**The queue survives F5 even if the server loses it.** The tab mirrors the queue in `localStorage`
(`cc-queue:<conversation UUID>`, text only, valid for 24 h). When the server opens a **new** session
for the socket (`queue` with `fresh:true`: console restart, classic mode), the tab returns the
cache with `queue_add`. The items go back to the queue **without triggering** and run at the end of the next turn or
via ⚡. On **re-attach**, the server is the truth: what disappeared was actually executed, and resending would duplicate it.
After restarting the console, the reconnection renews the `attach-ticket` (owner cookie) before opening the socket;
without that the server would silently fall into classic mode and F5 would kill the session, taking the turn and the queue with it.

Tests: `tests/test_claude_queue.py` (pytest, fake client/WebSocket) and
`tests/claude-queue.browser.mjs` (Playwright, desktop + mobile, fake WebSocket).

### Automatic resume after a console restart

Restarting the console kills the `claude` subprocess mid-turn. For the turn to come back **without a manual
message**, every persistent session with a running turn (or queue) is noted in `runs/claude/resume-on-restart.json`
at every turn start/end and queue change (it holds even for `kill -9`). `shutdown_all` does **not** delete the
note; `bye`/grace period delete it. At startup (`app.py` → `claude_svc.resume_after_restart`, 3 s later; 12 s
after an update) each session noted as `busy` is relaunched with `resume=<sid>`, receives the `RESUME_PROMPT`
(check the state before repeating an action; if you were the one who restarted, only validate the HTTP) and the queue resumes
afterwards. The tab re-attaches on reconnect (3 s backoff) and rereads the transcript. If the tab reconnects **before**, the
new session is already in `_LIVE` from creation and the resume injects the prompt into it, without a second `claude`.
Static limits: notes older than 30 min are ignored; up to 2 consecutive resumes without a human prompt
(anti-loop); respects `claude_max_sessions`. Kill-switch: `NETOPS_UI_CLAUDE_AUTORESUME=0`.
Tests: `tests/test_claude_autoresume.py`.

## Network permissions (🔐 Network) in the Claude tab

Selector beside the mode (Bypass/Plan): **Full** or the 4 categories **Read, Create, Edit, Delete**, only for what the
agent does **on the equipment** (`session.py run|exec`). The Claude mode still governs the local server.

- Classifier: `scripts/engine/lib/net_perms.py` (dialect from the inventory: `ros` MikroTik, `netcli` Cisco/Huawei/…,
  `shell` Linux/Proxmox). Criterion: "does it change state?"; ping/traceroute = Read. Unknown = Edit. Cisco/Huawei config
  without `no`/`undo` requires Create+Edit (they cannot be told apart). Reboot/restart = Edit.
- Hook `PreToolUse(Bash)` `_hook_netperms` in `services/claude_svc.py`: missing category → "Outside permissions" card
  (approve only that command). Denied, session ended or question timeout with the tab closed = blocks with a reason.
  The hook timeout is huge on purpose: a hook that times out would let the tool proceed.
- `UserPromptSubmit` injects the permissions into the turn context when restricted (or when they go back to Full).
- State per conversation in `runs/claude/prefs.json` (`netperms`), default in `default_netperms` (**Defaults** modal).
  A new conversation sends `?netperms=` on the WebSocket; live change `set_netperms` → `netperms_changed`. No record = Full.
- It is a guard against agent mistakes, not a security boundary. Claude Code in the terminal (outside the console) = Full.
- Tests: `tests/test_claude_netperms.py`.

## Network maps

### Integer host identity

`hosts.yaml` v2 contains a list of records with a positive integer `id`, a persistent `next_host_id`
and reserved old aliases. The field is not editable. A v1 inventory is still
readable; start/update in write mode converts the legacy before allowing
operations. `--read-only` does not migrate. Invalid references block the conversion without deleting
links; checking and manual recovery in `scripts/engine/lib/SKILL.md`.

The maps contract is also v2: `hosts` in the snapshot is a list with integer IDs,
`members` and `host_ids` are lists of integers, `positions` is a list of
`{host_id, x, y, z_index?}`. Visual endpoints use `{kind: host, host_id: 42}` or
`{kind: object, object_id: forma-a}`. Links keep `a.host`/`b.host` as integers.
The helper `static/js/host-identity.js` adapts only the editor view to its textual
nodes `host:42`; all writes return the canonical numeric format.

Backups use configuration v3, `targets.hosts` with integers and `legacy_sources` to
associate old folders without rewriting history. New collections go to
`backups/by-id/<id>/`, separate from numeric legacy folders. The runner delegates collection
to the access script; it does not read or decrypt credentials on its own.
Console writes and the migrator share the inventory lock; an interrupted
migration blocks use until recovery through the launcher or the manual command,
without mixing versions.

The **Maps** page integrates the React Flow editor with the **Hosts** registry and with the links of
`network/topology.yaml`. The old `/#topology` page and its exclusive module were removed;
old links open Maps. The link APIs are shared by the editor and remain.
It is not the temporary demo and does not use localStorage as a network database.

- The screen keeps a single row with map selector, new map and export. No duplicated
  title, long toolbar or permanent footer.
- Right-click on the background: add host, include existing, connect devices, texts,
  shapes, reference between maps, rename/delete an additional map and fit to view. New map
  and export are only in the top bar; speed is edited in the link form.
- Right-click on a host/object: edit, start a link and remove the visual association when
  allowed. On a link: bends, straight line, automatic position, edit and delete.
- On mobile, selecting an item and tapping **⋯** opens the same actions. With no item selected,
  **⋯** opens the background actions. With the keyboard: **Shift+F10**, arrows and **Escape**.
- The save state is still announced to screen readers. A failure or conflict opens an
  actionable warning only when needed, without occupying a permanent bar.
- Created a host on the map: it appears immediately in Hosts.
- Created it from the list: it appears on the general map and on the map of its site (`site`, with inheritance).
  When all hosts are on the same site, there is only **General network**, with no
  second identical automatic view. Additional maps created by the operator are preserved.
- Additional maps reuse existing hosts; the host form also offers association
  to an additional map. Position, notes, shapes and references live in `network/maps.yaml`.
- "Connect hosts" opens the A/B port form. The real links live in `topology.yaml`.
- Several links of the same pair keep independent lines, including in the reverse direction.
- "+ Bend" adds a 90-degree corner per click; A/B leave perpendicular to the edges.
  With aligned hosts, shift one of them to form an L. The host's four handle points stay hidden.
- The general map does not allow hiding a host. Additional maps allow "Remove from map", without
  deleting it from the inventory. Deleting the host is confirmed and removes all physical links with
  the host on A or B and the visual links with it as source or target, on all maps,
  as well as affected members, positions and routes. The other hosts, shapes and links remain.
- Data is shared between computer and mobile, with refresh when returning to the window and
  periodic polling while no edit is in progress. Late responses do not
  overwrite the current drag; autosave keeps the nodes' dimensions and visibility.
- A diverging revision returns 409 and shows "Version conflict". Reloading requires confirmation
  to discard unsaved adjustments. A network failure keeps the queue and allows retrying.
- The page respects the login and the `--read-only` mode. It never reads or decrypts passwords.

The editor is distributed as local assets. The console still has no mandatory build at
install time and works offline. For editor maintenance, see `maps/SKILL.md`.

### Running with isolated fake data

`NETOPS_UI_DATA_ROOT=/caminho/temporario` points the canonical network files and the config
to a test directory. It must contain `network/hosts.yaml`, `network/topology.yaml`
and `core/config/project-config.yaml`, all fake. Never copy real credentials.
Run the launcher from a **full temporary copy of the code**: changing only
`DATA_ROOT` does not isolate the install, the supervisor lock or the update engine.

```bash
NETOPS_UI_DATA_ROOT=/tmp/netops-teste NETOPS_UI_HOST=127.0.0.1 NETOPS_UI_PORT=8771 \
  NETOPS_UI_CLAUDE=0 NETOPS_UI_TERMINAL=0 scripts/engine/ui/start.sh
```

The launcher uses `flock` per data directory/address and the supervisor has a per-install lock,
without killing processes of another console.
If it is already running on the same address, it reports the conflict. To restart, stop the
desired instance first. Tests must not operate on the real inventory.


### Link validation

In the link form of the Maps page (`LinkForm` in `static/js/components.js`),
only Host A/B are required.
Port A/B are optional, both when creating and when editing; empty fields are not stored.
Port is the equipment interface name, such as `ether2` or `sfp1`, not a TCP port.
The form flags missing hosts before submitting, keeps the values and highlights the first
pending item. The 422 response uses `detail` in FastAPI or `errors` in the domain; `api.js` normalizes
both into per-field errors, without showing the `input` values returned by validation.

Isolated test: `tests/link-validation.browser.mjs` (same Playwright/Chromium variables and
`NETOPS_E2E_URL` as the maps tests). Parser test: `node --test
scripts/engine/ui/tests/api-errors.test.mjs`.


## Device icons

The **New host** form and host editing offer the **Host icon** selector on the Hosts
page and inside Maps. The ten options come from the Redes Brasil library: router, switch,
Linux/Windows servers, access point, OLT, cloud, PC, Proxmox and VMware.

The choice is optional and stored in the host's `icon` field in `network/hosts.yaml`. All maps
use the same inventory choice. **Default** removes the field and keeps the previous symbol,
without rewriting existing hosts. The backend only accepts IDs available in the local catalog,
never URLs or paths sent by the browser. An image load failure keeps
a fallback symbol on the map, without hiding the device.

Originals and catalog are in `static/icons/network/`. The thumbnails of up to 128 px used
by the UI are in `static/icons/network/thumbnails/`, with no external access at runtime.
Provenance, commit, checksums and update instructions in `static/icons/network/README.md`.
`vendor_icons.py` is a maintenance tool, with Pillow optional only at that step.

Tests: `tests/test_host_icons.py` and `tests/host-icons.browser.mjs`, the latter run
only against a console with a temporary `NETOPS_UI_DATA_ROOT` and fixtures.


### Persistence in text files

The map data are UTF-8 YAML files on the server:

- `network/maps.yaml`: maps, positions, notes, shapes, references, anchors and link bends.
- `network/hosts.yaml`: devices and icon choice (`icon` field).
- `network/topology.yaml`: links, hosts at each end, optional interfaces, medium and speed.

None of this depends on localStorage or a database. Restarting the server or switching
computer/mobile does not erase the data. The console rereads these files on every query and saves
with hash revision, atomic write and backups. The real files are git-ignored because
they contain network information; only the `*.example.yaml` templates are versioned.

Removing the Topology screen does not remove its data, the services used by Maps nor the
script `scripts/tools/docs/topology_render.py` that generates the Mermaid documentation.


## Shapes without IP and group alignment

The same **Connect hosts** accepts hosts, shapes and references between maps. Shapes represent
equipment without management/IP or visual elements, with no parallel registration in Hosts. They also
offer **Connect to another device** on right-click. Annotation text is not an endpoint
offered by the connection flow.

In the **Add shape/Edit shape** form, the **Shape icon** selector uses the local
network library, with a **No icon** option. The `icon` field lives in the object in `maps.yaml`. Host to
host still creates a real link; host-shape and shape-shape go into the map's `visual_links`,
with the same A/B controls, bends, dragging and deletion. Resizing the shape adjusts the line
endpoint without losing the icon. Removing the shape clears only its visual connections.

Selection and alignment:

- Computer: **Ctrl/Cmd + click** adds/removes devices from the selection; **left-button drag
  on the background** selects a rectangle, without modifiers (Shift also
  works). The rectangle selects items fully contained in it; middle button or Space
  let you move the map. Right-clicking a member/group keeps the
  selection and offers **Align horizontally** and **Align vertically**.
- Mobile: in the **⋯** menu, choose **Select multiple**, tap the devices and open **⋯**
  to align. Cancel/Escape or tapping the background ends the temporary selection.
- Alignment forms a row/column with aligned centers and **24 free map units
  between edges**, taking the node sizes into account. Hosts and shapes can take part together.
- The whole group is saved in one edit, without moving the other objects or deleting bends.
  Only positions are persisted; the selection does not change the inventory.
- **Clear selection** lets you go back to individual editing. Read-only mode does not offer
  alignment, shape changes or link creation.

Tests: `tests/test_shape_connections.py`, helper tests in `maps/node-state.test.mjs` and
`tests/shapes-align.browser.mjs` (same Playwright/Chromium variables as the other scenarios,
always in a temporary `NETOPS_UI_DATA_ROOT`).

`tests/test_host_delete_cascade.py` checks the deletion in the written YAMLs, at both
ends and on several maps, including preservation of unaffected items and a 409 conflict
without writing. `tests/host-delete-cascade.browser.mjs` covers details, menus, delete
confirmation and persistence on desktop/touch, always on a fake full install.

### Failure saving a shape icon after updating files

HTTP 422 with `extra_forbidden` on `map/objects/N/icon` indicates that the active backend still
does not recognize the icon field, even if the selector already appears in the interface. The static
files are read from disk; the Python models are loaded when the process starts.
A file copy or `git pull` without a restart can mix the two versions.

Check that the backend and the assets belong to the same version, stop the correct instance
and start it again via `scripts/engine/ui/start.sh`. Reloading only the browser does not
fix an old model in memory. The restart may require a new login; note the unsaved
adjustments before leaving the page. Do not remove the `icon` field nor relax validation to
work around the error. The persistent save warning guides the update/restart without
discarding the queue; an invalid icon is still treated as an ordinary validation error.


## Restarting the console

Use `scripts/engine/ui/start.sh --yes` (the same script that starts it; detaches, keeps host/flags, waits for the lock, validates HTTP, log in `/tmp/netops-restart.log`). Never a manual `kill` + `start.sh`.

## Navigation URLs (rule)

Every opened item and every filter in the console has its own URL (`#menu/<id>?filtro=valor`). Full rule and
checklist in `core/rules/navigation-urls.md` — read it before creating or changing any page.

### URL test (browser)

`tests/e2e-env.sh up` starts an isolated console (copy of the code + fake data) at `127.0.0.1:8771`
(`sync` recopies the code; `down` stops it). Then:
`PLAYWRIGHT_MODULE=... CHROMIUM_EXECUTABLE=... node tests/urls.browser.mjs [menu ...]` (no args = all).
Covers opened item, deep link (F5), Back, nonexistent id, filters in the URL and clearing. Unit: `tests/route.test.mjs`.

**Exception 4: Files** (`#files` and the host terminal SFTP panel). It is the same human passthrough
as the terminal: the person browses and changes server files (or host files, through the SSH session they opened themselves)
with their own hands. See "Files" under Security. Tests: `tests/test_files.py`,
`tests/files-core.test.mjs`, `tests/files.browser.mjs` and the `files` case of `tests/urls.browser.mjs`.

## Tables: DataTable (standard for all listings)

All console tables use `DataTable` (`static/js/table.js`; `ResourceTable` is an old alias).
There are 16 tables: hosts, groups, credentials, best practices, configs, workflows, agents, reports, runs,
memory notes, skills, scripts, scheduled runs and the four backup tables. It is our own code, no library:
the console is Preact+htm, offline and without a build. A ready-made grid would bring its own DOM and break the Preact
cells, the theme and the URLs.

- **For the user:** resize by dragging the border (double-click fits the content), move by dragging the
  header (or ↑↓ in the menu), show/hide and "Restore default" in **⚙ Columns**. The header stays fixed at the
  top and the actions column stays fixed on the right.
- **Persistence:** `localStorage["netops.table.<tableId>"]` = `{order, vis, widths}`, per browser. Sorting
  stays in the URL when the table uses `urlSort`.
- **Rule for new screens:** `core/rules/console-tables.md` (no raw `<table>`, unique `tableId`, `sort` on columns).
- **Tests:** `node --test tests/table-core.test.mjs` (pure core + pattern guard), `tests/tables-all.browser.mjs`
  (smoke on all screens) and `tests/table-columns.browser.mjs` (interactions, desktop and mobile), against `tests/e2e-env.sh up`.

## Web access firewall (IP/network allowlist)

Screen **Settings → Web access**; config in `core/config/project-config.yaml` → `web_access`
(`enabled`, `allowed_networks`, `trusted_proxies`). Code: `services/web_access_svc.py` + `_WebAccessGate` in `app.py`
(outermost layer: HTTP, static files and WebSocket; outside the list = 403 / WS 4403). Takes effect immediately (rereads the file by mtime).

- **Real IP behind a proxy:** the socket is always the proxy's (e.g. a Traefik at 10.0.0.10, which falls in the allowed 10.0.0.0/8 network!).
  The visitor IP comes from `X-Forwarded-For` **only** if the socket is in `trusted_proxies` (or loopback); the rightmost entry
  that is not a proxy wins. From any other origin the header is ignored. Unreadable IP = denied.
  uvicorn's `proxy_headers` was turned OFF (with `"*"` it accepted forged IPs and erased the socket IP).
  If you forget to list the proxy, everyone looks like the proxy IP and the 10/8 rule lets the world in: keep `trusted_proxies` right.
- **Anti self-lockout:** `PUT /config` refuses (422) to save if the IP of whoever is saving would be outside the list, or an empty list enabled.
  Loopback (127.0.0.1/::1) is always allowed (start.sh, scheduler, local shell).
- **Emergency (access locked out):** from the 10.x network or on the server, `enabled: false` in `web_access` in project-config.yaml
  (takes effect without restart). Code default when the section does not exist: off.
- **Code default:** only private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`); each company registers its own public prefixes. `project-config.yaml` is not distributed by the updater: the instance list stays there.
- `GET /api/web-access`: policy, the IP the server sees for whoever asks and recent blocks (RAM, since the restart).
- An OS firewall in the console CT does NOT solve it: it only sees the proxy IP. Blocking before the app = allowlist in the reverse proxy itself (e.g. Traefik's `ipAllowList`).
- **Tests:** `tests/test_web_access.py` (the `conftest` removes `web_access` from the test config: TestClient has no IP).

## HTTPS by IP (self-signed certificate)
Besides HTTP, the console opens an **HTTPS listener on the HTTP port + 1000** (e.g. 8765 → `https://<IP>:9765/`), in the same
app and the same process. It exists because the browser only allows the microphone (voice dictation) in a secure context.
- Certificate: `services/tls_svc.py` generates it in `runs/tls/` (cert.pem/key.pem, git-ignored), with a SAN for all of the machine's
  IPs; it regenerates on its own if missing, if an IP is missing or if it expires in < 30 days (validity 825 days).
- The browser warning the 1st time is expected (self-signed): "Advanced → proceed". The microphone works after that.
  To make the warning go away, import `runs/tls/cert.pem` as a trusted authority in the OS/browser.
- `--https-port N` / `NETOPS_UI_HTTPS_PORT=N` changes the port; `0` disables it. A cert/port failure disables only HTTPS, never HTTP.
