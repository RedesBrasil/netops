# SKILL — Tarefas agendadas (scheduler)

## O que é

Agendador do NetOps: roda tarefas sozinho, no horário, mesmo com o console e o chat fechados.
Console: menu **Sistema → Tarefas agendadas** (`#schedules`). Agente de IA: este `cli.py`.

Há três tipos de tarefa (`kind`):

| kind | Rótulo na tela | O que roda | Quando usar |
|------|----------------|------------|-------------|
| `script` | Determinística / script | um comando/script (`bash`, cwd = raiz do NetOps, venv no PATH) | coleta, backup, verificação com resposta fixa |
| `agent` | Agente de IA | `claude -p` headless com o pedido em linguagem natural | pesquisar, interpretar, decidir ("veja o changelog e me avise se…") |
| `hybrid` | Script + agente | o script coleta; a saída entra no prompt do agente | coleta determinística + análise por IA |

No `hybrid`, saída vazia do script (ou última linha `{"wakeAgent": false}`) **não aciona** o agente (economiza tokens).

## Como funciona (inspirado no cron do Hermes Agent, NousResearch)

- **Cadastro:** `network/schedules.yaml` (git-ignorado). **Estado:** `runs/schedules/state.json`.
  **Execuções:** `runs/schedules/<tarefa>/<run>.json` + `.log` (mantém as 50 últimas por tarefa).
- **Disparo:** o cron do sistema chama o despachante a cada minuto — UMA linha em
  `/etc/cron.d/netops-scheduler` (`cli.py tick`), instalada/atualizada sozinha ao salvar uma tarefa.
  Não é uma linha de cron por tarefa porque o servidor roda em **UTC** e o cron do Debian não tem
  `CRON_TZ`: o despachante avalia cada agenda no fuso do cadastro (`timezone`, padrão `America/Sao_Paulo`).
- **No máximo uma vez por horário:** o próximo horário é avançado **antes** de disparar; trava por
  tarefa impede sobreposição (a 2ª vira `skipped`). Cron parado por mais de 1 h → o horário é pulado
  (`missed`), não acumula.
- **Agente:** sessão nova por execução, `cwd` = raiz (lê `AGENTS.md`, hooks valem), com instrução fixa:
  não mudar nada além do pedido, não perguntar, não criar tarefas, responder `[SILENT]` se não houver
  nada relevante e `[FALHA]` se falhar. Permissões: `restricted` (padrão: Read/Glob/Grep/WebFetch/WebSearch,
  sem shell nem escrita) ou `full` (shell e escrita). Cron* e AskUserQuestion sempre bloqueados.
  A sessão fica no histórico da aba Claude Code ("continuar no Claude Code" no detalhe da execução).
- **Notificação** (`notify`): `auto` (padrão: falha sempre; agente avisa salvo `[SILENT]`; script só em
  falha), `always`, `failure`, `never`. Não lidas aparecem como contador vermelho no menu e na aba
  **Execuções**.
- **Central de Avisos** (`scripts/engine/inbox/SKILL.md`): toda notificação vira mensagem no sino 🔔 do topo
  (falha = alerta; falhas repetidas agrupam). O agente publica alertas/pedidos de aprovação com bloco
  ```` ```netops-inbox {json}``` ```` na resposta (funciona em `restricted`); aprovar retoma a sessão dele.
  Script: `python3 scripts/engine/inbox/cli.py add --kind approval ...` + `wait <id>`.
- **Acesso a equipamentos:** tarefa agendada usa **chave SSH dedicada**, não o cofre (que só fica destrancado com humano
  digitando a senha). Uma vez, com o cofre aberto: `python3 scripts/tools/access/task_key.py provision --task <id> --hosts 16,35 --mode ro`.
  Depois a tarefa/agente acessam com `python3 scripts/tools/access/task_exec.py --task <id> --host-id N --command "..."`.
  - Chave em `network/task-keys/<id>/` (git-ignorada, 0600). `ro` = o equipamento só aceita comandos de leitura
    (`/usr/local/sbin/netops-ro-shell`: lista de permissão, sem redirecionamento, sem arquivos sensíveis; tudo no syslog).
    `rw` só se a tarefa precisar escrever. Fingerprint do equipamento fixada no provisionamento.
  - **Ciclo de vida:** a chave morre com a tarefa — `delete_task` (CLI/console) apaga a pasta e o tick do despachante
    varre pastas sem tarefa (cobre apagar no YAML). A remoção da linha no equipamento fica na fila
    `network/task-keys/_revoke.yaml` e roda com `task_key.py revoke-pending` (cofre aberto). `task_key.py list|test|delete`.

## Instalação nova / atualização

Nada a fazer à mão: o código vem no pacote e no atualizador. O cadastro (`network/schedules.yaml`) é
dado local e nunca é distribuído. A linha do cron é instalada sozinha ao salvar a 1ª tarefa e
reinstalada no arranque do console se houver tarefas e a linha tiver sumido (restore, reinstalação).
- Console como **root** (padrão): `/etc/cron.d/netops-scheduler`.
- Console **sem root**: cai no **crontab do usuário** (bloco `# >>> netops-scheduler`, preserva o resto).
- **Sem o pacote `cron`** (container mínimo): a tela avisa; rode `apt install cron && systemctl enable --now cron`.
- Pré-requisitos: `.venv` do projeto (a linha usa `.venv/bin/python3`). Tarefas de agente também exigem o
  `claude` logado para o mesmo usuário do console (igual à aba Claude Code).
- Manual/diagnóstico: `cli.py install-cron`; `cli.py list` mostra `cron.installed/healthy/last_tick`.

## Uso pelo agente de IA (pedido no chat)

Quando o usuário pedir "agende…", "todo dia…", "a cada N minutos…", "me avise quando…":
**use este CLI** (nunca `crontab -e`, `/etc/cron.d` à mão, nem a ferramenta `CronCreate`, que só vive
na sessão). Escolha o `kind`: comando fixo → `script`; precisa interpretar/pesquisar → `agent`;
coleta + análise → `hybrid`. Confirme com o usuário o horário e o que fará, se houver dúvida.

```bash
P=".venv/bin/python3 scripts/engine/scheduler/cli.py"
$P list                                         # tarefas, próxima/última, saúde do cron
$P add --name "Changelog MikroTik" --kind agent --cron "0 8 * * *" \
   --prompt "Veja https://mikrotik.com/download/changelogs; se houver versão nova citando o bug X, resuma. Senão [SILENT]."
$P add --name "Ping core" --kind script --every 30 --script "python3 scripts/tools/diagnostics/ping_advanced.py --host rt-core-01"
$P add --name "Backup + análise" --kind hybrid --cron "30 3 * * *" --script "..." --prompt "Compare e avise se mudou firewall"
$P add --name "Lembrete" --kind agent --at 2026-11-20T09:00 --prompt "..."     # uma vez
$P edit <id> --cron "0 9 * * 1-5" | $P disable <id> | $P enable <id> | $P rm <id>
$P run <id>                                     # dispara agora (segundo plano)
$P runs [<id>] | $P log <id> <run_id>           # resultados
$P preview --cron "0 9 * * 1-5"                 # próximos horários
```

Agendas: `--cron` (5 campos, fuso do cadastro; `@daily`, `L` = último dia do mês, `1#2` = 2ª segunda — lib `croniter`, a mesma do Hermes), `--every N` (minutos), `--at AAAA-MM-DDTHH:MM`.
Outros: `--notify`, `--permissions restricted|full`, `--model`, `--timeout` (min, padrão 15), `--description`,
`--disabled`. Saída sempre em JSON; erro de validação = exit 2 com `errors[]`.
Tarefas criadas pelo CLI ficam marcadas `created_by: chat` (selo "via chat" na tela) e são editáveis no console.

## Regras

- Uma tarefa agendada **não** cria nem dispara outras (`NETOPS_SCHEDULED_RUN=1` bloqueia o CLI).
- Mudança de configuração em equipamento por tarefa agendada segue a constituição §V (baseline → rollback);
  prefira tarefas de leitura/verificação. Agente `full` só quando o pedido exigir shell.
- Testes usam raiz de dados temporária: o cron vai para `<raiz>/runs/schedules/cron.d-netops-scheduler`,
  nunca para `/etc/cron.d` (`NETOPS_SCHEDULER_CRON_FILE` força outro caminho).
- Testes: `scripts/engine/ui/tests/test_schedules.py`, `tests/schedules.test.mjs`, caso `schedules` em `urls.browser.mjs`.
