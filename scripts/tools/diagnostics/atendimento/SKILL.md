# SKILL — Monitor de lentidão do atendimento (WhatsBot-pro)

Mede `https://atendimento.coolify.redesbrasil.com.br` a cada 30 s, avisa no Telegram e, ao abrir incidente,
dispara um agente investigador. Cadeia: Traefik → container `whatsbot-*` (+ Evolution API) → COOLIFY-REDES_BRASIL
(host 35, CT 212) → PROXMOX TECHIFY (host 16).

- **Agendado:** tarefa ÚNICA híbrida `monitor-de-lentidao-atendimento` (a cada 1 min; script = 2 ciclos + `investigar.py --prepare`; agente só acorda com incidente).
- `monitor.py`: sondas (health, login, me, channels, connected, unread, labels), limites por sonda, incidente
  (2 ciclos ruins seguidos OU ≥4 ciclos ruins em 20 = lentidão intermitente), Telegram abre/lembra/normaliza.
  Métricas: `runs/atendimento-monitor/metrics-AAAAMMDD.jsonl`; estado: `state.json`. `monitor.py --once` = teste sem alertar.
- `investigar.py`: coleta pronta (hosts 16 e 35, só leitura) + `claude -p` → `reports/atendimento-lentidao-*.md` + resumo no Telegram.
  Manual: `.venv/bin/python3 scripts/tools/diagnostics/atendimento/investigar.py --no-telegram`.
- **Auto-aperfeiçoamento:** o agente termina com um bloco ```` ```coleta-add ```` (JSON) com comandos extras que precisou.
  O script rejeita o que não for leitura (denylist), testa cada comando e grava em `network/atendimento-coleta.yaml`
  (máx. 40/host); a coleta seguinte já os inclui. Edite/remova entradas nesse YAML à vontade.
- Config (git-ignorada): `network/atendimento-monitor.yaml` (credencial de TESTE, limites, mapa da infra),
  `network/telegram.yaml` (bot/grupo do hook de backup, chmod 600).
- Acesso aos hosts 16 e 35 pela chave dedicada da tarefa (`task_exec.py`, somente leitura) — NÃO depende do cofre.
- Achado 16/11: event loop do app trava ~4,5 s a cada ~65 s (suspeito: plugin `vendas_ia`); infra saudável.
