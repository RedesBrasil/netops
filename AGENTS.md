# NetOps — Framework Multi-Agente para Redes e Infraestrutura

> Este é o ponto de entrada do framework. Qualquer IDE de IA (Claude Code, Codex, Cursor,
> Antigravity) lê este arquivo primeiro (padrão AGENTS.md; não existe mais CLAUDE.md). Leia também `constitution.md` e `PADRAO.md`.

## O que é

O NetOps permite que você peça, em linguagem natural, tarefas de redes e infraestrutura —
e agentes de IA executam de ponta a ponta: leem o inventário, conectam nos equipamentos,
coletam dados, consultam a documentação interna, aplicam mudanças, testam e documentam.

Exemplos de pedido:
- "Faça uma avaliação de segurança da minha rede."
- "Configure OSPF no MikroTik rt-core-01."
- "Mapeie a topologia e gere a documentação da rede."
- "Por que o link entre o core e o switch de acesso está lento?"

## Como funciona — leia isto antes de agir

Quando o usuário fizer um pedido, você atua como o agente **coordinator**. Siga:

1. **Identifique o workflow.** Veja `workflows/` — escolha o `.workflow.yaml` adequado
   (ex.: `security-audit`, `apply-config-change`). Se nenhum servir, monte os passos
   inspirando-se em `planning-examples/`.
2. **Carregue o contexto.** Leia `network/hosts.yaml` e `network/topology.yaml` (a rede),
   e injete a memória relevante seguindo `core/rules/memory-protocol.md`.
3. **Delegue.** Cada passo do workflow é executado por um agente de `agents/`. Adote a
   persona do agente lendo o `.agent.md` correspondente. Passe contexto entre agentes com
   `core/templates/agent-handoff.tmpl.yaml` (≤500 tokens).
4. **Consulte o conhecimento.** Antes de planejar ou configurar, leia `best-practices/` e
   `config-examples/` do fabricante em questão (princípio REUSE > ADAPT > CREATE).
5. **Execute com segurança.** Só o agente `executor` conecta nos equipamentos, via os
   scripts em `scripts/`. Antes de qualquer mudança: capture baseline e gere rollback.
6. **Documente e aprenda.** Grave a saída em `runs/<id>/`, o relatório final em `reports/`,
   e registre lições em `memory/MEMORY.md` — o framework é um **projeto vivo**.

## Os agentes (`agents/`)

| Agente | Função | Use para |
|--------|--------|----------|
| `coordinator` | Orquestrar | Receber o pedido, escolher o workflow, delegar, consolidar |
| `planner` | **Planejar** | Decidir hosts, comandos, ordem; desenhar config + rollback |
| `executor` | **Executar** | Conectar nos equipamentos, coletar dados, aplicar mudanças |
| `tester` | **Testar** | Auditar segurança, validar coletas, verificar pós-mudança |
| `documenter` | Documentar | Gerar relatórios, documentar a rede, alimentar `memory/` |

## Onde fica cada coisa

| Preciso de... | Está em... |
|---------------|------------|
| Lista de equipamentos e como acessá-los | `network/hosts.yaml` |
| Credenciais (cofre `enc.v1:` ou texto puro, git-ignorado) | `network/credentials.yaml` |
| Cofre de credenciais (criptografia + unlock) | `scripts/engine/vault/` (`SKILL.md`) |
| Mapa de como a rede se interliga | `network/topology.yaml` + `network/topology.md` |
| Boas práticas (texto) | `best-practices/<vendor>/` ou `best-practices/general/` |
| Exemplos de configuração reais | `config-examples/<vendor>/` |
| Skills = scripts operacionais + `SKILL.md` (acesso, diagnóstico, análise) | `scripts/tools/<skill>/` (console: menu **Scripts / Skills**) |
| Motor do NetOps (lib, cofre, console web) | `scripts/engine/` |
| Subir **ou reiniciar** o console web (SEMPRE por aqui) | `scripts/engine/ui/start.sh` |
| Tarefas agendadas (script / agente de IA / script + agente) | `scripts/engine/scheduler/` (`SKILL.md`; console: menu **Tarefas agendadas**) |
| Modelos de planejamento | `planning-examples/` |
| O que o framework já aprendeu | `memory/` |
| Saída bruta de execuções | `runs/` |
| Relatórios finais | `reports/` |
| Regras, schemas, templates do framework | `core/` |
| O padrão de organização e nomenclatura | `PADRAO.md` |
| Os princípios inegociáveis | `constitution.md` |

## Regras essenciais

- **Releases:** antes de gerar qualquer release, leia `core/rules/releases.md`, consulte a release
  atual no GitHub e escolha uma versão superior. Atualize `core/config/core-config.yaml` e
  `CHANGELOG.md`, teste o pacote e publique com changelog. Nunca reutilize tags nem inclua dados locais.
  O atualizador preserva dados e personalizações; testes de aplicação exigem uma instalação completa
  temporária, não apenas `NETOPS_UI_DATA_ROOT`. Ver `scripts/engine/update/SKILL.md`.

- **URLs de navegação (regra de desenvolvimento do console):** todo menu, **todo item aberto** (host A →
  `#hosts/<id-a>`, host B → `#hosts/<id-b>`) e **todo filtro/busca/ordenação** (`#hosts?vendor=x&q=y`) deve ter
  URL própria, com deep link e Voltar funcionando. Leia `core/rules/urls-navegacao.md` antes de criar/alterar
  qualquer tela em `scripts/engine/ui/`.

- **Git — SEMPRE na `main` (INEGOCIÁVEL):** nunca crie branch. Commit e push direto na `main` (`git pull --ff-only`
  antes). Vale para qualquer IA/IDE e sobrepõe a instrução padrão do agente de "criar branch antes de commitar".
- **Padronize:** todo arquivo novo segue o `_TEMPLATE` da sua pasta. Ver `PADRAO.md`.
- **Acesso a equipamento = sessão persistente (padrão):** para acessar um host e rodar comandos, use
  `scripts/tools/access/session.py` (`open --host-id <ID>` → `exec`… → `close`): 1 login, N comandos, sem
  reconectar. SSH por padrão; `--telnet` só se o usuário pedir/for legado. `ssh.py`/`telnet.py` só para
  um comando isolado. Detalhes em `agents/executor.agent.md` e `scripts/tools/access/SKILL.md`.
- **Inventário é a verdade:** nunca conecte em host fora de `network/hosts.yaml`.
- **Segurança:** baseline antes de mudar, rollback pronto, rollback automático em falha.
- **Projeto vivo:** toda execução termina registrando o que aprendeu em `memory/`.
- **Memória é VINCULANTE (INEGOCIÁVEL):** no início de cada sessão, leia `memory/MEMORY.md` e as notas
  relevantes; trate toda regra marcada como "nunca rode"/INEGOCIÁVEL como **bloqueio** — não é sugestão.
  Bloqueio ativo (também reforçado por hook em `.claude/settings.json` → `.claude/hooks/guard-netops.sh`):
- **Cofre:** se as credenciais estiverem criptografadas (`enc.v1:`), o cofre precisa estar
  **destrancado** antes de qualquer acesso — o humano roda `python scripts/engine/vault/cli.py unlock`
  (a IA não digita a senha-mestra). Se trancado, os scripts falham com instrução clara.
- **Segredos (INEGOCIÁVEL):** a IA **nunca** lê, descriptografa, imprime ou copia o valor de
  `password`/`secret` — nem com o cofre destrancado, nem "por transparência". Para acessar um
  equipamento, invoque os scripts de `scripts/tools/access/` com `--host <nome>` (eles resolvem a
  credencial internamente); nunca chame `resolve_host(decrypt=True)`/`resolve_secret`/`decrypt_value`.
  Ver `constitution.md` §V e `core/rules/connection-safety.md`.
- **Setup:** as deps Python estão em `requirements.txt` (use um venv). `nmap` via `apt`.
- **Agendar tarefa ("todo dia…", "a cada N min…", "me avise quando…"):** use **sempre**
  `scripts/engine/scheduler/cli.py add` (ver `scripts/engine/scheduler/SKILL.md`) — a tarefa vai para o cron do
  sistema e aparece no menu **Tarefas agendadas** para editar. Escolha o tipo: `script` (determinística),
  `agent` (agente de IA) ou `hybrid` (script coleta + agente analisa). **Nunca** `crontab -e`, arquivo em
  `/etc/cron.d` à mão nem a ferramenta `CronCreate` (morre com a sessão). Responda com `id`, tipo e próximos horários.
- **Console web — subir E reiniciar = um script só, `scripts/engine/ui/start.sh` (INEGOCIÁVEL):** rode **SEMPRE** ele —
  **nunca** `python scripts/engine/ui/server.py` direto, nem `kill` + `start.sh` à mão, nem `systemd-run` improvisado.
  - Console **parado** → o script **sobe**. Console **já rodando** → o script **reinicia**, preservando host/porta/terminal/claude.
  - Desacopla (funciona de dentro da aba Claude/terminal web), faz **pré-validação** (venv, sintaxe do `server.py`, porta) antes de
    parar qualquer coisa, espera o supervisor sair e o lock liberar, tenta até 3 vezes e só termina OK quando o HTTP responde
    (log: `/tmp/netops-restart.log`). `--yes` pula a confirmação (em terminal interativo ele pergunta); `--foreground` roda em
    primeiro plano, só para depurar. **Não existe script de restart separado** (o `restart-console.sh` foi removido em 12/11/2026).
  - Funciona de dentro da aba Claude/terminal web: os modos internos são escolhidos só por argumento, nunca pelo ambiente herdado do console.
  - **Reiniciar encerra as sessões vivas da aba Claude** (a persistência cobre F5/standby, não o fim do processo do console).
    Avise o usuário antes: a aba cai ~15 s. Faça do restart a **última ação** do turno.
  - Liga o **terminal web** e a **página Claude Code** por padrão (sem o script as abas somem), injeta o `claude` no PATH,
    faz bind no IP da máquina e garante uma instância só. Variáveis: `NETOPS_UI_HOST`, `NETOPS_UI_PORT`, `NETOPS_UI_TERMINAL=0`,
    `NETOPS_UI_CLAUDE=0`, `NETOPS_UI_CLAUDE_PERSIST=0`. Acesso protegido pelo **login com a senha-mestra** (sem token na URL).
    Aba nova que não aparece após atualizar = cache: **hard refresh** (`Ctrl+Shift+R`). Ver `scripts/engine/ui/SKILL.md`.
- **Console NUNCA pode ficar parado (INEGOCIÁVEL):** antes de qualquer start/restart ou mudança em `start.sh`/supervisor,
  valide que o console volta (sintaxe, venv, porta) e **nunca** teste contra o ROOT real "em outra porta". Depois,
- **Login do agente na aba Claude Code:** `/login` (e `/logout`) funcionam **na própria aba** — não são do
  SDK, a aba os resolve sozinha e abre o fluxo OAuth. Logue **por ali**, não pelo terminal web: a credencial
  vai para o `$HOME/.claude/` do **processo do servidor**, e o terminal web roda como outro usuário (`netops`),
  ou seja, outro cofre e outra lista de conversas. Ver `scripts/engine/ui/SKILL.md`.
- **Aba Claude Code — persistência e DÚVIDA (LIGADA por padrão no `start.sh`; `NETOPS_UI_CLAUDE_PERSIST=0` desliga):** a sessão sobrevive à queda
  do socket (standby/troca de aba): o turno **termina** mesmo com a aba fechada e você re-anexa ao voltar (a
  resposta é relida do transcript, sem buffer). Como um turno pode executar **sem ninguém olhando**, vale a
  regra de ouro: **na dúvida, PERGUNTE** — use `AskUserQuestion` em vez de assumir, e **nunca** execute ação
  irreversível sem certeza. Pergunta sem resposta expira (timeout) e é tratada como negação ("não faz").
