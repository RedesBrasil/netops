<!-- Template of the AGENTS.md of a NetOps installation in English (core/templates/en/AGENTS.tmpl.md).
     The installer and start.sh create the installation's AGENTS.md from here ONLY when it does not exist.
     The installation's AGENTS.md is LOCAL: it does not go to git or to the package and is never overwritten
     by an update — add this installation's rules and reminders to it (Memory menu). -->
# NetOps — Multi-Agent Framework for Networks and Infrastructure

> This is the entry point of the framework. Any AI IDE (Claude Code, Codex, Cursor,
> Antigravity) reads this file first (AGENTS.md standard; there is no CLAUDE.md anymore). Also read `constitution.md` and `core/rules/standard.md`.

## What it is

NetOps lets you ask, in natural language, for network and infrastructure tasks —
and AI agents carry them out end to end: they read the inventory, connect to the devices,
collect data, consult the internal documentation, apply changes, test and document.

Request examples:
- "Run a security assessment of my network."
- "Configure OSPF on the MikroTik rt-core-01."
- "Map the topology and generate the network documentation."
- "Why is the link between the core and the access switch slow?"

## How it works — read this before acting

When the user makes a request, you act as the **coordinator** agent. Follow:

1. **Identify the workflow.** See `workflows/` — pick the matching `.workflow.yaml`
   (e.g.: `security-audit`, `apply-config-change`). If none fits, build the steps
   inspired by `planning-examples/`.
2. **Load the context.** Read `network/hosts.yaml` and `network/topology.yaml` (the network),
   and inject the relevant memory following `core/rules/memory-protocol.md`.
3. **Delegate.** Each workflow step is run by an agent from `agents/`. Adopt the
   agent's persona by reading the matching `.agent.md`. Pass context between agents with
   `core/templates/agent-handoff.tmpl.yaml` (≤500 tokens).
4. **Consult the knowledge.** Before planning or configuring, read `best-practices/` and
   `config-examples/` of the vendor in question (REUSE > ADAPT > CREATE principle).
5. **Execute safely.** Only the `executor` agent connects to the devices, through the
   scripts in `scripts/`. Before any change: capture a baseline and generate a rollback.
6. **Document and learn.** Save the output in `runs/<id>/`, the final report in `reports/`,
   and record lessons in `memory/MEMORY.md` — the framework is a **living project**.

## The agents (`agents/`)

| Agent | Function | Use for |
|-------|----------|---------|
| `coordinator` | Orchestrate | Receive the request, pick the workflow, delegate, consolidate |
| `planner` | **Plan** | Decide hosts, commands, order; design config + rollback |
| `executor` | **Execute** | Connect to the devices, collect data, apply changes |
| `tester` | **Test** | Audit security, validate collections, verify after changes |
| `documenter` | Document | Generate reports, document the network, feed `memory/` |

## Where everything is

| I need... | It is in... |
|-----------|-------------|
| List of devices and how to access them | `network/hosts.yaml` |
| Host credentials (device access; vault `enc.v1:` or plaintext, git-ignored) | `network/credentials.yaml` |
| Credential vault (encryption + unlock) | `scripts/engine/vault/` (`SKILL.md`) |
| Use a key/password from the Password vault in a command or `.env` without exposing the value (`nvault://item/field`) | `scripts/tools/secrets/` (`SKILL.md`; `nvault run -- <cmd>`) |
| **Password vault**: secrets that are NOT for a host (portals, APIs, tokens) with reusable templates and fields (console: **Inventory → Password vault**) | `network/vault.yaml` (git-ignored, `enc.v1:`); `scripts/engine/lib/pwvault.py`, `ui/services/vault_items_svc.py` (see `scripts/engine/vault/SKILL.md`) |
| Map of how the network interconnects | `network/topology.yaml` + `network/topology.md` |
| Best practices (text) | `best-practices/<vendor>/` or `best-practices/general/` |
| Real configuration examples | `config-examples/<vendor>/` |
| Skills = operational scripts + `SKILL.md` (access, diagnostics, analysis) | `scripts/tools/<skill>/` (console: **Scripts / Skills** menu) |
| NetOps engine (lib, vault, web console) | `scripts/engine/` |
| Start **or restart** the web console (ALWAYS through here) | `scripts/engine/ui/start.sh` |
| Console file manager (**Files** menu + SFTP panel next to the host terminal) | `scripts/engine/ui/` (`routers/files.py`, `static/js/file-browser.js`; see `SKILL.md`) |
| Users, access groups, console audit (SQLite `runs/netops.db`) | `scripts/engine/users/` (`SKILL.md`; console: **Users / Access groups / Audit**) |
| Each user's GitHub (own account in the agent; **My account → GitHub**) | `scripts/engine/lib/github_identity.py` (see `scripts/engine/users/SKILL.md`, "GitHub per user") |
| Console projects (name + folder; Claude Code sessions per folder; **private by default, shared with users/groups** at `#projects/<id>/share`; **Projects** menu) | `scripts/engine/ui/` (`routers/projects.py`, `services/projects_svc.py`, `services/project_acl.py`, `static/js/pages/projects.js`; see `SKILL.md`) |
| Scheduled tasks (script / AI agent / script + agent) | `scripts/engine/scheduler/` (`SKILL.md`; console: **Scheduled tasks** menu) |
| **Notification center**: alerts, notices and approval requests (🔔 bell at the top + **Output → Notification center** menu) | `scripts/engine/inbox/` (`SKILL.md`; `inbox/cli.py add`) |
| Discover the CTs/VMs of a Proxmox, register them and organize them on the map | `scripts/tools/inventory/` (`SKILL.md`; `map_place.py register` / `place`) |
| Planning templates | `planning-examples/` |
| What the framework has already learned | `memory/` |
| Raw output of runs | `runs/` |
| Final reports | `reports/` |
| Rules, schemas, templates of the framework | `core/` |
| The organization and naming standard | `core/rules/standard.md` |
| The non-negotiable principles | `constitution.md` |

## Essential rules

- **Language (NON-NEGOTIABLE):** **always answer in the language the person writes in** (Portuguese → Portuguese,
  English → English, Spanish → Spanish), whatever the language of the installation. Files generated **without a conversation**
  (scheduled task report, Notification center, memory) come out in the installation's language
  (`core/config/project-config.yaml` → `instance.language`); a report requested in a conversation comes out in the conversation's language.
- **Texts of the console, the API and the CLIs (development rule):** every visible string goes through `t()` and into
  `core/locales/<language>/*.json` (English is the source); code, file names and keys in English. Read `core/rules/i18n.md`.

- **Identifying devices in answers (NON-NEGOTIABLE):** when mentioning any host, container (CT/VM),
  router, switch, server or other device, **never use only the ID**. Always write **name (ID)**, with the
  name first and the number in parentheses: `SERVIDOR-PROXMOX-01 (host 14)`, `RT-BORDA (host 2)`,
  `PROXY-TESTE (CT 102)`. The name comes from `network/hosts.yaml`
  (`hostname`) or, for a CT/VM, from `pct list`/`qm list`. This applies to reports, summaries, tables and status
  messages. Only the ID, without a name, forces the user to look it up in the inventory: do not do it. If the name is long,
  use a short recognizable one (e.g.: `PVE-SITE-A`), but always with the number next to it.

- **Multi-user (Claude tab):** each person signs in with their own login; what they can do comes from their group.
  - **In the Claude tab:** `NETOPS_USER` identifies who asked. Their group's network ceiling applies and **cannot be bypassed**.
  - **GitHub per user:** in the Claude tab and in Projects, git/gh use the GitHub account **of whoever sent the message** (someone else continuing the conversation = the agent relaunches with their account, network ceiling and `NETOPS_USER`).
    Without a connected account, push, PR and `gh` fail: ask them to connect in **My account → GitHub** (`#account/github`) and
    reopen the conversation. Never use the server account nor change `GH_CONFIG_DIR`, `GH_TOKEN` or the git identity.
- **Standardize:** every new file follows the `_TEMPLATE` of its folder. See `core/rules/standard.md`.
- **Server account (NON-NEGOTIABLE):** NetOps runs as the Linux account `netops` (HOME `/var/lib/netops`), never root:
  console, AI, subagents, terminal, scheduler and updater. Never use `su`.
  **Root on THIS server = `sudo <command>` directly, allowed ONLY with the vault unlocked** (no password; PAM checks the
  vault on each call via `/usr/local/sbin/netops-sudo-cofre`). Use plain `sudo` — **never `sudo -n`** (`-n` refuses
  before the check). If it answers "a password is required" = vault locked: ask the human to unlock it and stop.
  **Automatic sudo:** with the vault unlocked, `apt`, `apt-get`, `dpkg`, `systemctl`/`journalctl` (without `--user`), `nft`,
  `iptables`, `conntrack`, `docker`, `mount`, `useradd`, `sysctl`, `ss`, `lsof`, `reboot`... already run as root without
  typing `sudo` (functions in `/usr/local/share/netops/auto-sudo.bash`, loaded by `~/.bashrc`). For a system
  file: `rootcat <file>` (read), `rootedit <file>` (edit), `rootsh '<pipeline>'` (redirection/pipe as root). Non-interactive
  scripts do not load the functions: in them write `sudo` explicitly.
  Only use root when the request requires it (install a package, touch a system service/file, read a system log); the
  rest runs directly as `netops`. Alternative (e.g.: task without a terminal) = **Local host** (`access.method: local`, protected):
  `python3 scripts/tools/access/session.py exec --host-id <ID-LOCAL> --command "..."` runs as root, per operation,
  without SSH, with the local admin password in the vault (the AI never sees it). Requires the vault unlocked and `server.admin`; if missing,
  report it and stop.
  **Network diagnostics run DIRECTLY as `netops`, without root and without the vault** (the server is already prepared:
  `net.ipv4.ping_group_range` + capabilities via `/usr/local/sbin/netops-netcaps`): `ping`, `traceroute` (including
  `-I`/`-T`), `mtr`, `nmap` (SYN scan `-sS`, `-O`), `nping`, `tcpdump`, `arping`, `fping`, `arp-scan`, `iperf3`,
  `dig`, `snmpwalk`, `curl`. Never send these tools to the Local host; if one of them gives "Operation not
  permitted", tell the human to run `sudo /usr/local/sbin/netops-netcaps` (do not work around it through the Local host).
  See `scripts/engine/localadmin/SKILL.md`. An old installation (root console) migrates with `scripts/engine/identity/`.
- **Device access through the CLI (NON-NEGOTIABLE):** only two scripts — `scripts/tools/access/session.py` (user request
  in the chat/console; uses the vault; SSH/Telnet; and the Local host of this server) and `scripts/tools/access/task_exec.py` (scheduled task; dedicated
  key, see "Scheduled task that accesses a device"). `ssh.py`/`telnet.py` were removed and
  the system's `ssh`/`sshpass`/`telnet` are forbidden.
  "Access/check/run X on host N" → go straight to it, without preparing an environment (it is already ready: `python3` or `python`,
  the script enters the `.venv` by itself; do not activate a venv or install anything). Find the ID in `network/hosts.yaml` and run:
  - **DEFAULT = persistent session per host:** `python3 scripts/tools/access/session.py exec --host-id <ID> --command "<c1>" [--command "<c2>"]`.
    The 1st call logs in and leaves the session open; the following ones on the same host **reuse** it (no new login; on Linux it is the
    same shell: `export`/`cd`/`source` persist). Several devices = one session per host, all open at the same time
    (e.g.: see the IP on 3 hosts, decide, then ARP on the 3 — 3 logins in total). It closes by itself after
    `access.session_idle_minutes` (**Settings** screen; default 5 min) without a command, or `… close --host-id <ID>` / `close --all`.
  - `run` (connects, runs, disconnects) only for an isolated one-off collection; `open`/`exec --session` remain valid.
  SSH by default; `--telnet` only if the user asks for it/it is legacy. Details: `scripts/tools/access/SKILL.md`.
- **"Open the terminal (or the access) of host X for me" = console window, NOT `session.py`:** the human wants their
  interactive terminal. Find the ID in `network/hosts.yaml`, run `python3 scripts/tools/access/terminal_link.py --host-id <ID>`
  (`--method telnet` if they ask for Telnet; `--all` if they want to choose) and paste the printed line **as is** in the answer: the Claude
  tab opens the window by itself (or shows the link, if the pop-up is blocked). The script does not connect to anything. Several hosts
  ("open the edge and the core") = one link per host. Ambiguous (2+ hosts match the name) → ask which one.
- **Backup before changing a device (NON-NEGOTIABLE):** any change on a host (add/set/remove/restart…), even in a
  direct request without a workflow, starts with `python3 scripts/tools/backup/change.py begin --host-id <ID>` ("pre" backup; failed =
  do not change) and ends with `... change.py end --host-id <ID>` ("post" backup + diff; 1 pair per host per session). On by default
  for mikrotik/cisco/huawei/linux/proxmox; `backup_before_change: false` on the host/group turns it off. Retention: `backups.keep_versions`
  (10). **Proxmox CT/VM = snapshot, not a config backup:** `change.py begin --host-id <CT>` exits with code 4 and says
  **ask the user with `AskUserQuestion`** ("Take a snapshot first?"). Yes → `change.py begin --host-id <CT> --mode snapshot [--tag x]`
  (`scripts/tools/backup/snapshot.py`: checks the pool storage/space, runs fstrim, rereads the space, blocks if the pool goes over 90 %, creates
  `netops-pre-AAAAMMDD-HHMM`); No → `--mode none`. At the end, `change.py end` does NOT delete anything: say that it finished and **ask** whether to delete it
  (`snapshot.py delete --host-id <CT>`, only after the "yes"; `snapshot.py pending` lists the forgotten ones). The `guard-netops.sh` hook blocks a change through `session.py` without the `begin` — it can be chained on the same line: `change.py begin --host-id N && session.py run ... ; change.py end --host-id N` (the `&&` is required; `;` does not count).
- **Nothing heavy in `/tmp` (NON-NEGOTIABLE):** test venv, portable Node, Playwright/Chromium, `pytest --basetemp`,
  worktree and release build go to `/var/tmp/netops-<task>/` (disk) and are **deleted at the end of the task**. The
  `/tmp` may be tmpfs (RAM) and count against the container's memory: test leftovers pile up and bring the host down through OOM.
  The disk also fills up, so delete everything at the end.
- **Network permissions of the conversation (🔐 Network selector of the Claude tab):** Full or Read/Create/Edit/Delete on the devices.
  Respect the "[NetOps — permissões de rede]" notice: unchecked category = collect, plan and deliver the commands without applying them;
  a command outside that opens an approval on the screen and, if denied, **do not work around it**. Full = no approval asked (unless the prompt asks for it);
  backup/rollback/test remain mandatory. See `scripts/engine/ui/SKILL.md`.
- **Device name in UPPERCASE (NON-NEGOTIABLE):** every `hostname` registered in `network/hosts.yaml` (physical host, CT, VM,
  router, switch, server) is written **ALL IN UPPERCASE**, with a hyphen instead of space/underscore when it is a technical name
  (e.g.: `9ROUTER-TEST`, `COOLIFY-FRANCISCO`, `PROXY-TESTE`). This applies to new records **and** to renaming existing ones; the name
  also appears in uppercase in the answers (`name (ID)`). Never register `9router-test`, `Proxy-Teste` etc.
  Before writing to `hosts.yaml`, check `hostname == hostname.upper()`.
- **The inventory is the truth:** never connect to a host outside `network/hosts.yaml`.
- **Safety:** baseline before changing, rollback ready, automatic rollback on failure.
- **Living project:** every run ends by recording what it learned in `memory/`.
- **Memory is BINDING (NON-NEGOTIABLE):** at the start of each session, read `memory/MEMORY.md` and the relevant
  notes; treat every rule marked as "never run"/NON-NEGOTIABLE as a **block** — it is not a suggestion.
- **Vault:** if the credentials are encrypted (`enc.v1:`), the vault must be
  **unlocked** before any access — the human runs `python3 scripts/engine/vault/cli.py unlock`
  (the AI does not type the master password). If locked, the scripts fail with a clear instruction.
- **Secrets (NON-NEGOTIABLE):** the AI **never** reads, decrypts, prints or copies the value of
  `password`/`secret` nor the secrets of the Password vault (`network/vault.yaml`) — not with the vault unlocked, not "for transparency". To access a
  device, invoke the scripts in `scripts/tools/access/` with `--host <name>` (they resolve the
  credential internally); never call `resolve_host(decrypt=True)`/`resolve_secret`/`decrypt_value`.
  See `constitution.md` §V and `core/rules/connection-safety.md`.
- **API key/password from the Password vault in a command, `.env` or script = `nvault` (NON-NEGOTIABLE):** to use a secret from the
  Password vault (Cloudflare/Wrangler, Coolify API, application `.env`...), write the **reference** `nvault://<ID>/<field>` (numeric ID of the item, stable)
  (in the `.env`, with `--set` or `--item`) and run `nvault run -- <command>` (`scripts/tools/secrets/run.py`). The value goes only into the
  process environment and comes out masked (`***`). Never write the value to a file, never read `network/vault.yaml`, never call
  `/reveal` and never transform or send the secret elsewhere. `nvault list` shows the references. Requires the vault unlocked
  (code 3 = locked: ask the human to unlock it) and the `vault.use` permission (code 4). A scheduled task does not use `nvault`.
  See `scripts/tools/secrets/SKILL.md`.
- **Setup (only at installation, never on request):** `.venv/` with `requirements.txt` + `apt install python-is-python3 nmap`
  (see `README.md`). Every CLI script re-executes itself in the `.venv` (`scripts/engine/lib/_venv.py`), so
  `python3 scripts/...` works without activating anything. Use `python3` in the commands (it exists on every Debian/Ubuntu).
- **Scheduling a task ("every day…", "every N min…", "let me know when…"):** **always** use
  `scripts/engine/scheduler/cli.py add` (see `scripts/engine/scheduler/SKILL.md`) — the task goes to the system
  cron and appears in the **Scheduled tasks** menu for editing. Anything that needs attention or the user's **approval**
  (alert, "may I delete these files?") goes to the **Notification center**: `scripts/engine/inbox/cli.py add`
  (script/chat) or a ```netops-inbox``` block in the answer of the task's agent — never run the action before the approval. Pick the type: `script` (deterministic),
  `agent` (AI agent) or `hybrid` (script collects + agent analyzes). **Never** `crontab -e`, a hand-written file in
  `/etc/cron.d` or the `CronCreate` tool (it dies with the session). Answer with the `id`, type and next run times.
- **Scheduled task that accesses a device = dedicated key, never the vault (NON-NEGOTIABLE):** the vault only stays
  unlocked while a human types the password, so a scheduled task does not depend on it. For each task that needs to
  get into a device: `python3 scripts/tools/access/task_key.py provision --task <task-id> --hosts <IDs> --mode ro`
  (creates the ed25519 pair in `network/task-keys/<id>/`, git-ignored, and authorizes it only on the listed hosts, with pre/post backup).
  **Least privilege:** `ro` (default) = the device only runs read commands (`netops-ro-shell` guard with an allow
  list); `rw` only if the task really needs to write, and in that case tell the user. The task and its agent
  access with `python3 scripts/tools/access/task_exec.py --task <id> --host-id N --command "..."` (works with the vault
  locked). The key dies with the task: deleting the task (CLI, console or YAML by hand) deletes the key folder, and the line in the
  devices' authorized_keys is removed with `task_key.py revoke-pending` (queue in `network/task-keys/_revoke.yaml`; run it
  when the vault is open). Command denied by the device: do not work around it, propose it as a recommended action.
  See `scripts/engine/scheduler/SKILL.md`.
- **Web console — start AND restart = a single script, `scripts/engine/ui/start.sh` (NON-NEGOTIABLE):** **ALWAYS** run it —
  **never** `python3 scripts/engine/ui/server.py` directly, nor `kill` + `start.sh` by hand, nor an improvised `systemd-run`.
  - Console **stopped** → the script **starts** it. Console **already running** → the script **restarts** it, preserving host/port/terminal/claude.
  - It detaches (works from inside the Claude tab/web terminal), does a **pre-validation** (venv, `server.py` syntax, port) before
    stopping anything, waits for the supervisor to exit and the lock to be released, tries up to 3 times and only finishes OK when HTTP answers
    (log: `~/.local/state/netops/restart-<instance>.log`; legacy: `/tmp/netops-restart.log`). As root, the script
    delegates to the `netops` account (systemd user service `netops-console@<instance>`, starts on boot). `--yes` skips the confirmation (in an interactive terminal it asks); `--foreground` runs in
    the foreground, only for debugging. **There is no separate restart script** (`restart-console.sh` was removed on 12/11/2026).
  - It works from inside the Claude tab/web terminal: the internal modes are chosen only by argument, never by the environment inherited from the console.
  - **Restarting ends the live sessions of the Claude tab**, but the **turn in progress comes back by itself**: the console writes down in
    `runs/claude/resume-on-restart.json` who was in the middle of a turn and, when it comes up, relaunches the conversation (`resume`) with a
    continuation prompt "[NetOps — retomada automática]" (up to 2 in a row without a human prompt; a note > 30 min old is ignored;
    `NETOPS_UI_CLAUDE_AUTORESUME=0` turns it off). Warn the user beforehand: the tab drops for ~15 s. Make the restart the **last action** of the
    turn; when resumed after a restart you triggered, only confirm HTTP and finish — **do not restart again**.
  - It turns on the **web terminal** and the **Claude Code page** by default (without the script the tabs disappear), injects `claude` into the PATH,
    binds to the machine's IP and guarantees a single instance. Variables: `NETOPS_UI_HOST`, `NETOPS_UI_PORT`, `NETOPS_UI_TERMINAL=0`,
    `NETOPS_UI_CLAUDE=0`, `NETOPS_UI_CLAUDE_PERSIST=0`. Access protected by the **e-mail and password login** (new installation: **first access** wizard `#setup?token=...`, which creates the admin + vault + language; reprint the link: `users/cli.py setup-link`). The console listens on all IPs (`0.0.0.0`).
    A new tab that does not appear after updating = cache: **hard refresh** (`Ctrl+Shift+R`). See `scripts/engine/ui/SKILL.md`.
- **The console must NEVER stay down (NON-NEGOTIABLE):** before any start/restart or change to `start.sh`/supervisor,
  validate that the console comes back (syntax, venv, port) and **never** test against the real ROOT "on another port". Afterwards,
  confirm HTTP on the real host:port. Losing web access is unacceptable.
- **Agent login in the Claude Code tab:** `/login` (and `/logout`) work **in the tab itself** — they are not from the
  SDK, the tab resolves them by itself and opens the OAuth flow. The credential goes to `$HOME/.claude/` of the server account
  (`/var/lib/netops/.claude`); console, web terminal, tasks and subagents use the SAME account and the SAME profile.
  (Legacy installation, root console: the profile is `/root/.claude` and the web terminal is another account.) See `scripts/engine/ui/SKILL.md`.
- **Claude Code tab — persistence and DOUBT (ON by default in `start.sh`; `NETOPS_UI_CLAUDE_PERSIST=0` turns it off):** the session survives the drop
  of the socket (standby/tab switch): the turn **finishes** even with the tab closed and you re-attach when you come back (the
  answer is reread from the transcript, no buffer). Since a turn may run **with nobody watching**, the
  golden rule applies: **when in doubt, ASK** — use `AskUserQuestion` instead of assuming, and **never** run an irreversible
  action without certainty. A question without an answer expires (timeout) and is treated as a denial ("do not do it").
