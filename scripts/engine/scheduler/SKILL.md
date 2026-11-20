# SKILL — Scheduled tasks (scheduler)

## What it is

NetOps scheduler: runs tasks by itself, on time, even with the console and the chat closed.
Console: menu **System → Scheduled tasks** (`#schedules`). AI agent: this `cli.py`.

There are three task types (`kind`):

| kind | Label on screen | What it runs | When to use |
|------|-----------------|--------------|-------------|
| `script` | Deterministic / script | a command/script (`bash`, cwd = NetOps root, venv in PATH) | collection, backup, check with a fixed answer |
| `agent` | AI agent | headless `claude -p` with the request in natural language | research, interpret, decide ("check the changelog and tell me if…") |
| `hybrid` | Script + agent | the script collects; its output goes into the agent's prompt | deterministic collection + AI analysis |

In `hybrid`, empty script output (or a last line `{"wakeAgent": false}`) **does not trigger** the agent (saves tokens).

## How it works (inspired by the cron of Hermes Agent, NousResearch)

- **Registry:** `network/schedules.yaml` (git-ignored). **State:** `runs/schedules/state.json`.
  **Runs:** `runs/schedules/<tarefa>/<run>.json` + `.log` (keeps the last 50 per task).
- **Trigger:** the system cron calls the dispatcher every minute — ONE line in
  `/etc/cron.d/netops-scheduler` (`cli.py tick`), installed/updated automatically when a task is saved.
  It is not one cron line per task because the server runs in **UTC** and Debian's cron has no
  `CRON_TZ`: the dispatcher evaluates each schedule in the registry's time zone (`timezone`, default `America/Sao_Paulo`).
- **At most once per slot:** the next slot is advanced **before** firing; a per-task
  lock prevents overlap (the 2nd becomes `skipped`). Cron stopped for more than 1 h → the slot is skipped
  (`missed`), it does not pile up.
- **Agent:** new session per run, `cwd` = root (reads `AGENTS.md`, hooks apply), with a fixed instruction:
  change nothing beyond the request, do not ask questions, do not create tasks, answer `[SILENT]` if there is
  nothing relevant and `[FALHA]` if it fails. Permissions: `restricted` (default: Read/Glob/Grep/WebFetch/WebSearch,
  no shell and no writes) or `full` (shell and writes). Cron* and AskUserQuestion always blocked.
  The session stays in the Claude Code tab history ("continue in Claude Code" in the run detail).
- **Notification** (`notify`): `auto` (default: failure always; agent notifies unless `[SILENT]`; script only on
  failure), `always`, `failure`, `never`. Unread ones show as a red counter in the menu and in the
  **Runs** tab.
- **Notification center** (`scripts/engine/inbox/SKILL.md`): every notification becomes a message in the bell 🔔 at the top
  (failure = alert; repeated failures are grouped). The agent publishes alerts/approval requests with a
  ```` ```netops-inbox {json}``` ```` block in its answer (works in `restricted`); approving resumes its session.
  Script: `python3 scripts/engine/inbox/cli.py add --kind approval ...` + `wait <id>`.
- **Access to equipment:** a scheduled task uses a **dedicated SSH key**, not the vault (which is only unlocked while a human
  types the password). Once, with the vault open: `python3 scripts/tools/access/task_key.py provision --task <id> --hosts 16,35 --mode ro`.
  Then the task/agent access with `python3 scripts/tools/access/task_exec.py --task <id> --host-id N --command "..."`.
  - Key in `network/task-keys/<id>/` (git-ignored, 0600). `ro` = the equipment only accepts read commands
    (`/usr/local/sbin/netops-ro-shell`: allowlist, no redirection, no sensitive files; everything to syslog).
    `rw` only if the task needs to write. The equipment fingerprint is pinned at provisioning.
  - **Lifecycle:** the key dies with the task — `delete_task` (CLI/console) deletes the folder and the dispatcher tick
    sweeps folders without a task (covers deleting in the YAML). Removing the line on the equipment goes to the queue
    `network/task-keys/_revoke.yaml` and runs with `task_key.py revoke-pending` (vault open). `task_key.py list|test|delete`.

## New install / update

Nothing to do by hand: the code comes in the package and with the updater. The registry (`network/schedules.yaml`) is
local data and is never distributed. The cron line is installed automatically when the 1st task is saved and
reinstalled at console startup if there are tasks and the line has disappeared (restore, reinstall).
- Console as **root** (default): `/etc/cron.d/netops-scheduler`.
- Console **without root**: falls back to the **user's crontab** (block `# >>> netops-scheduler`, preserves the rest).
- **Without the `cron` package** (minimal container): the screen warns; run `apt install cron && systemctl enable --now cron`.
- Prerequisites: the project's `.venv` (the line uses `.venv/bin/python3`). Agent tasks also require
  `claude` logged in for the same user as the console (same as the Claude Code tab).
- Manual/diagnostics: `cli.py install-cron`; `cli.py list` shows `cron.installed/healthy/last_tick`.

## Use by the AI agent (request in the chat)

When the user asks "schedule…", "every day…", "every N minutes…", "let me know when…":
**use this CLI** (never `crontab -e`, `/etc/cron.d` by hand, nor the `CronCreate` tool, which only lives
in the session). Choose the `kind`: fixed command → `script`; needs to interpret/research → `agent`;
collection + analysis → `hybrid`. Confirm the time and what it will do with the user, if in doubt.

```bash
P=".venv/bin/python3 scripts/engine/scheduler/cli.py"
$P list                                         # tasks, next/last, cron health
$P add --name "Changelog MikroTik" --kind agent --cron "0 8 * * *" \
   --prompt "Veja https://mikrotik.com/download/changelogs; se houver versão nova citando o bug X, resuma. Senão [SILENT]."
$P add --name "Ping core" --kind script --every 30 --script "python3 scripts/tools/diagnostics/ping_advanced.py --host rt-core-01"
$P add --name "Backup + análise" --kind hybrid --cron "30 3 * * *" --script "..." --prompt "Compare e avise se mudou firewall"
$P add --name "Lembrete" --kind agent --at 2026-11-20T09:00 --prompt "..."     # once
$P edit <id> --cron "0 9 * * 1-5" | $P disable <id> | $P enable <id> | $P rm <id>
$P run <id>                                     # fires now (background)
$P runs [<id>] | $P log <id> <run_id>           # results
$P preview --cron "0 9 * * 1-5"                 # next slots
```

Schedules: `--cron` (5 fields, registry time zone; `@daily`, `L` = last day of the month, `1#2` = 2nd Monday — `croniter` lib, the same as Hermes), `--every N` (minutes), `--at AAAA-MM-DDTHH:MM`.
Others: `--notify`, `--permissions restricted|full`, `--model`, `--github-as <usuario>`, `--timeout` (min, default 15), `--description`,
`--disabled`. `--github-as`: the agent uses the GitHub account connected by that console user. With no account connected, it has no GitHub;
without `--github-as`, it uses the server's `gh`. Output always in JSON; validation error = exit 2 with `errors[]`.
Tasks created by the CLI are marked `created_by: chat` ("via chat" badge on screen) and are editable in the console.

## Rules

- A scheduled task does **not** create or trigger others (`NETOPS_SCHEDULED_RUN=1` blocks the CLI).
- A configuration change on equipment by a scheduled task follows constitution §V (baseline → rollback);
  prefer read/check tasks. A `full` agent only when the request requires a shell.
- Tests use a temporary data root: the cron goes to `<raiz>/runs/schedules/cron.d-netops-scheduler`,
  never to `/etc/cron.d` (`NETOPS_SCHEDULER_CRON_FILE` forces another path).
- Tests: `scripts/engine/ui/tests/test_schedules.py`, `tests/schedules.test.mjs`, `schedules` case in `urls.browser.mjs`.
