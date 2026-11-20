# SKILL — Customer service slowness monitor (WhatsBot-pro)

Measures `https://atendimento.coolify.redesbrasil.com.br` every 30 s, alerts on Telegram and, when it opens an incident,
triggers an investigator agent. Chain: Traefik → `whatsbot-*` container (+ Evolution API) → COOLIFY-REDES_BRASIL
(host 35, CT 212) → PROXMOX TECHIFY (host 16).

- **Scheduled:** a SINGLE hybrid task `monitor-de-lentidao-atendimento` (every 1 min; script = 2 cycles + `investigar.py --prepare`; the agent only wakes up on an incident).
- `monitor.py`: probes (health, login, me, channels, connected, unread, labels), per-probe limits, incident
  (2 bad cycles in a row OR ≥4 bad cycles in 20 = intermittent slowness), Telegram opens/reminds/normalizes.
  Metrics: `runs/atendimento-monitor/metrics-AAAAMMDD.jsonl`; state: `state.json`. `monitor.py --once` = test without alerting.
- `investigar.py`: ready-made collection (hosts 16 and 35, read-only) + `claude -p` → `reports/atendimento-lentidao-*.md` + summary on Telegram.
  Manual: `.venv/bin/python3 scripts/tools/diagnostics/atendimento/investigar.py --no-telegram`.
- **Self-improvement:** the agent ends with a ```` ```coleta-add ```` block (JSON) with the extra commands it needed.
  The script rejects anything that is not read-only (denylist), tests each command and writes it to `network/atendimento-coleta.yaml`
  (max. 40/host); the next collection already includes them. Edit/remove entries in that YAML freely.
- Config (git-ignored): `network/atendimento-monitor.yaml` (TEST credential, limits, infra map),
  `network/telegram.yaml` (bot/group of the backup hook, chmod 600).
- Access to hosts 16 and 35 through the task's dedicated key (`task_exec.py`, read-only) — does NOT depend on the vault.
- Finding 16/11: the app's event loop stalls ~4.5 s every ~65 s (suspect: `vendas_ia` plugin); infra healthy.
