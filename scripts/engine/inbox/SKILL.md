# SKILL — Notification center (inbox)

## What it is

NetOps' single box for **alerts, notices and approval requests**. Who publishes: scheduled tasks
(script, agent, script + agent), standalone scripts and agents. Who reads and decides: the human, in the console.

- **Bell 🔔 at the top** of every screen, with a red dot counting *unread + awaiting approval*
  (it pulses if there is a critical one). Click = latest messages, quick approve/reject, link to the Center.
- **Menu Output → Notification center** (`#inbox`): full list, filters, detail with Approve / Reject /
  **Discuss in Claude** (takes the notice to the Claude tab prompt, already written in the field; if it came from an agent,
  it opens that agent's SAME conversation). The browser tab title shows `(N)`.
- URLs: `#inbox[?view=pending|unread|alerts|archived|all&kind=&sev=&q=]`, `#inbox/<id>`.

| kind | What for | Stays in the counter until |
|------|----------|----------------------------|
| `info` | information ("backup completed") | it is read |
| `alert` | something deserves attention (`severity` warning/critical) | it is read |
| `approval` | needs the human's decision | it is **approved/rejected** (or expires) |

Data: `runs/inbox.db` (SQLite, git-ignored, 0600). Action log: `runs/inbox/<id>.log`.
Archived messages are deleted after 90 days; cap of 5000 messages (a pending request is never deleted).

## Approval request → what happens on decision

1. **No action** (default for scripts): the requester checks the decision — `cli.py wait <id>` (blocks) or
   `cli.py get <id>` on the next run — and continues from there.
2. **With action** (runs by itself on decision, in a detached process, as the console user):
   - `command`: `--on-approve-command "..."` / `--on-reject-command "..."`. The environment receives
     `NETOPS_INBOX_ID`, `NETOPS_INBOX_DECISION` (approved|rejected), `NETOPS_INBOX_DECIDED_BY`, `NETOPS_INBOX_NOTE`.
   - `agent`: resumes the **same session** of the agent that asked (`claude -p --resume`) with the human's decision
     and note; or opens a new agent with `--on-approve-agent "prompt"`. `permissions` restricted (default) or full.
   - The result goes back into the message and it reappears as unread in the bell.
   - A request **with action** can only be decided by an **administrator** (it runs on the server). Without action: permission `inbox.decide`.
3. Only the first decision counts (the second gets 409). `--expires-hours N`: no decision by then = `expired`.

## Automatic integration with scheduled tasks

- A run that **notifies** (the task's `notify`) becomes a message: failure = `alert` (repeated failures of the same
  task are grouped into one, `×N`); agent finding = `info` with its answer.
- Reading in the Center marks the run as read in **Scheduled tasks** and vice versa.
- The task's agent (even in `restricted` mode, with no shell) publishes notices and requests by writing in its answer
  a ```` ```netops-inbox ```` block with JSON (object or list) — the instruction is already in the system prompt:

```netops-inbox
{"kind": "approval", "severity": "warning", "title": "Apagar 12 arquivos temporários (3,1 GB) em /var/tmp",
 "body": "Lista e motivo…", "dedupe_key": "limpeza-var-tmp",
 "action": {"type": "agent", "permissions": "full", "prompt": "Apague exatamente os arquivos listados."}}
```

  Without `action`, approving resumes the session with restricted permissions. If the agent only published blocks, the run
  does not generate a duplicate notification.

## Use from a script / agent (CLI)

```bash
P="python3 scripts/engine/inbox/cli.py"
$P add --kind alert --severity critical --title "Telnet aberto no RT-BORDA (host 2)" --body-file achados.md --dedupe-key telnet-rt2
$P add --kind info --title "Backup noturno ok (14 hosts)"
$P add --kind approval --title "Apagar 3 snapshots antigos do PVE-SITE-A (host 14)" --body "…" \
   --on-approve-command "python3 scripts/tools/... --apply" --expires-hours 24
ID=$($P add --kind approval --title "Reiniciar serviço X?" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
$P wait "$ID" --timeout-min 120 && echo aprovado   # exit 0 approved, 3 rejected, 4 expired/timeout
$P list --view pending | $P get 12 | $P summary | $P read 12 13 | $P archive 12
```

`add` options: `--severity`, `--body`/`--body-file` (markdown; `-` = stdin), `--dedupe-key` (the same recurring
finding updates the open message instead of duplicating it), `--link "#hosts/2"`, `--session-id`, `--telegram`
(also notifies on Telegram via `network/telegram.yaml`), `--on-approve-agent`, `--agent-permissions`, `--timeout` (min).
Inside a scheduled task the origin (task/run) is filled in automatically; in the Claude tab, `NETOPS_USER`.

## Rules

- The console **does not create** messages (there is no creation route): no browser queues a command to run as root.
- A message never carries a secret (password, token) in the title/body — constitution §V applies.
- An approved request's action that changes equipment follows the usual rules (backup `change.py begin/end`, rollback).
- Permissions (Users → Access groups): `inbox.view` (view/read) and `inbox.decide` (decide without action, archive).
- Code: `scripts/engine/inbox/{store,actions,cli}.py`, `ui/routers/inbox.py`, `ui/static/js/inbox.js` (bell),
  `ui/static/js/pages/inbox.js` (page). Tests: `scripts/engine/ui/tests/test_inbox.py`.
