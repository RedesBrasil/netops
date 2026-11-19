# SKILL — Central de Avisos (inbox)

## O que é

Caixa única de **alertas, avisos e pedidos de aprovação** do NetOps. Quem publica: tarefas agendadas
(script, agente, script + agente), scripts avulsos e agentes. Quem lê e decide: o humano, no console.

- **Sino 🔔 no topo** de todas as telas, com bolinha vermelha contando *não lidas + aguardando aprovação*
  (pulsa se houver crítico). Clique = últimas mensagens, aprovar/reprovar rápido, link para a Central.
- **Menu Saída → Central de Avisos** (`#inbox`): lista completa, filtros, detalhe com Aprovar / Reprovar /
  **Discutir no Claude** (leva o aviso para o prompt da aba Claude, já escrito no campo; se veio de um agente,
  abre a MESMA conversa dele). O título da aba do navegador mostra `(N)`.
- URLs: `#inbox[?view=pending|unread|alerts|archived|all&kind=&sev=&q=]`, `#inbox/<id>`.

| kind | Para quê | Fica no contador até |
|------|----------|----------------------|
| `info` | informação ("backup concluído") | ser lido |
| `alert` | algo merece atenção (`severity` warning/critical) | ser lido |
| `approval` | precisa da decisão do humano | ser **aprovado/reprovado** (ou expirar) |

Dados: `runs/inbox.db` (SQLite, git-ignorado, 0600). Log das ações: `runs/inbox/<id>.log`.
Arquivadas são apagadas após 90 dias; teto de 5000 mensagens (nunca apaga pedido pendente).

## Pedido de aprovação → o que acontece ao decidir

1. **Sem ação** (padrão para scripts): quem pediu consulta a decisão — `cli.py wait <id>` (bloqueia) ou
   `cli.py get <id>` na próxima execução — e segue a partir dela.
2. **Com ação** (roda sozinha ao decidir, num processo destacado, como o usuário do console):
   - `command`: `--on-approve-command "..."` / `--on-reject-command "..."`. Ambiente recebe
     `NETOPS_INBOX_ID`, `NETOPS_INBOX_DECISION` (approved|rejected), `NETOPS_INBOX_DECIDED_BY`, `NETOPS_INBOX_NOTE`.
   - `agent`: retoma a **mesma sessão** do agente que pediu (`claude -p --resume`) com a decisão e a observação
     do humano; ou abre agente novo com `--on-approve-agent "prompt"`. `permissions` restricted (padrão) ou full.
   - O resultado volta para a mensagem e ela reaparece como não lida no sino.
   - Pedido **com ação** só é decidido por **administrador** (roda no servidor). Sem ação: permissão `inbox.decide`.
3. Só a primeira decisão vale (a segunda recebe 409). `--expires-hours N`: sem decisão até lá = `expired`.

## Integração automática com as tarefas agendadas

- Execução que **notifica** (`notify` da tarefa) vira mensagem: falha = `alert` (falhas repetidas da mesma
  tarefa agrupam numa só, `×N`); achado do agente = `info` com a resposta dele.
- Ler na Central marca a execução como lida em **Tarefas agendadas** e vice-versa.
- O agente da tarefa (mesmo em modo `restricted`, sem shell) publica avisos e pedidos escrevendo na resposta
  um bloco ```` ```netops-inbox ```` com JSON (objeto ou lista) — a instrução já vai no prompt de sistema:

```netops-inbox
{"kind": "approval", "severity": "warning", "title": "Apagar 12 arquivos temporários (3,1 GB) em /var/tmp",
 "body": "Lista e motivo…", "dedupe_key": "limpeza-var-tmp",
 "action": {"type": "agent", "permissions": "full", "prompt": "Apague exatamente os arquivos listados."}}
```

  Sem `action`, aprovar retoma a sessão com permissões restritas. Se o agente só publicou blocos, a execução
  não gera notificação duplicada.

## Uso por script / agente (CLI)

```bash
P="python3 scripts/engine/inbox/cli.py"
$P add --kind alert --severity critical --title "Telnet aberto no RT-BORDA (host 2)" --body-file achados.md --dedupe-key telnet-rt2
$P add --kind info --title "Backup noturno ok (14 hosts)"
$P add --kind approval --title "Apagar 3 snapshots antigos do PVE-SITE-A (host 14)" --body "…" \
   --on-approve-command "python3 scripts/tools/... --apply" --expires-hours 24
ID=$($P add --kind approval --title "Reiniciar serviço X?" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
$P wait "$ID" --timeout-min 120 && echo aprovado   # exit 0 aprovado, 3 reprovado, 4 expirou/tempo
$P list --view pending | $P get 12 | $P summary | $P read 12 13 | $P archive 12
```

Opções do `add`: `--severity`, `--body`/`--body-file` (markdown; `-` = stdin), `--dedupe-key` (mesmo achado
recorrente atualiza a mensagem aberta em vez de duplicar), `--link "#hosts/2"`, `--session-id`, `--telegram`
(também avisa no Telegram via `network/telegram.yaml`), `--on-approve-agent`, `--agent-permissions`, `--timeout` (min).
Dentro de tarefa agendada a origem (tarefa/execução) é preenchida sozinha; na aba Claude, `NETOPS_USER`.

## Regras

- O console **não cria** mensagens (não há rota de criação): nenhum navegador enfileira comando para rodar como root.
- Mensagem nunca leva segredo (senha, token) no título/corpo — vale a constituição §V.
- Ação de pedido aprovado que altera equipamento segue as regras de sempre (backup `change.py begin/end`, rollback).
- Permissões (Usuários → Grupos de acesso): `inbox.view` (ver/ler) e `inbox.decide` (decidir sem ação, arquivar).
- Código: `scripts/engine/inbox/{store,actions,cli}.py`, `ui/routers/inbox.py`, `ui/static/js/inbox.js` (sino),
  `ui/static/js/pages/inbox.js` (página). Testes: `scripts/engine/ui/tests/test_inbox.py`.
