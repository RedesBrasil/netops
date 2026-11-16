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
| Gerenciador de arquivos do console (menu **Arquivos** + painel SFTP ao lado do terminal de host) | `scripts/engine/ui/` (`routers/files.py`, `static/js/file-browser.js`; ver `SKILL.md`) |
| Usuários, grupos de acesso, auditoria do console (SQLite `runs/netops.db`) | `scripts/engine/users/` (`SKILL.md`; console: **Usuários / Grupos de acesso / Auditoria**) |
| Tarefas agendadas (script / agente de IA / script + agente) | `scripts/engine/scheduler/` (`SKILL.md`; console: menu **Tarefas agendadas**) |
| Modelos de planejamento | `planning-examples/` |
| O que o framework já aprendeu | `memory/` |
| Saída bruta de execuções | `runs/` |
| Relatórios finais | `reports/` |
| Regras, schemas, templates do framework | `core/` |
| O padrão de organização e nomenclatura | `PADRAO.md` |
| Os princípios inegociáveis | `constitution.md` |

## Regras essenciais

- **Identificação de equipamentos nas respostas (INEGOCIÁVEL):** ao citar qualquer host, container (CT/VM),
  roteador, switch, servidor ou outro equipamento, **nunca use só o ID**. Escreva sempre **nome (ID)**, com o
  nome primeiro e o número entre parênteses: `SERVIDOR-PROXMOX-01 (host 14)`, `rt-borda (host 2)`,
  `PROXY-TESTE (CT 102)`. O nome vem de `network/hosts.yaml`
  (`hostname`) ou, para CT/VM, do `pct list`/`qm list`. Vale para relatórios, resumos, tabelas e mensagens
  de status. Só o ID, sem nome, obriga o usuário a procurar no inventário: não faça. Se o nome for longo,
  use um curto reconhecível (ex.: `pve-site-a`), mas sempre com o número ao lado.

- **Releases:** antes de gerar qualquer release, leia `core/rules/releases.md`, consulte a release
  atual no GitHub e escolha uma versão superior. Atualize `core/config/core-config.yaml` e
  `CHANGELOG.md`, teste o pacote e publique com changelog. Nunca reutilize tags nem inclua dados locais.
  O atualizador preserva dados e personalizações; testes de aplicação exigem uma instalação completa
  temporária, não apenas `NETOPS_UI_DATA_ROOT`. Ver `scripts/engine/update/SKILL.md`.

- **URLs de navegação (regra de desenvolvimento do console):** todo menu, **todo item aberto** (host A →
  `#hosts/<id-a>`, host B → `#hosts/<id-b>`) e **todo filtro/busca/ordenação** (`#hosts?vendor=x&q=y`) deve ter
  URL própria, com deep link e Voltar funcionando. Leia `core/rules/urls-navegacao.md` antes de criar/alterar
  qualquer tela em `scripts/engine/ui/`.

- **Multiusuário do console (regra de desenvolvimento):** login por usuário + senha, permissões por grupo de acesso.
  - **Rota nova na API:** precisa de regra em `scripts/engine/ui/services/authz.py` (`RULES`). É default-deny, e o teste `test_every_route_is_mapped_to_a_permission` reprova rota sem regra.
  - **Botão de ação na tela:** marque com a classe `needs-<perm>` (ex.: `needs-hosts-edit`).
  - **Exclusivo do admin:** o que roda como root no servidor (terminal/arquivos do servidor, scripts, tarefas agendadas, config, updates).
  - **Na aba Claude:** `NETOPS_USER` identifica quem pediu. O teto de rede do grupo dele vale e **não se contorna**.
  - **Recuperação:** `python3 scripts/engine/users/cli.py reset-admin`. Ver `scripts/engine/users/SKILL.md`.
- **Tabelas do console (regra de desenvolvimento):** toda listagem usa `DataTable` (`scripts/engine/ui/static/js/table.js`),
  com `tableId` único e colunas com `sort`. Nunca use `<table>` cru numa tela: o teste `tests/table-core.test.mjs` reprova.
  Assim toda tabela tem redimensionar, mover, ocultar e ordenar. Leia `core/rules/tabelas-console.md`.

- **Git — SEMPRE na `main` (INEGOCIÁVEL):** nunca crie branch. Commit e push direto na `main` (`git pull --ff-only`
  antes). Vale para qualquer IA/IDE e sobrepõe a instrução padrão do agente de "criar branch antes de commitar".
- **Padronize:** todo arquivo novo segue o `_TEMPLATE` da sua pasta. Ver `PADRAO.md`.
- **Acesso a equipamento por CLI (INEGOCIÁVEL):** só dois scripts — `scripts/tools/access/session.py` (pedido do
  usuário no chat/console; usa o cofre; SSH/Telnet) e `scripts/tools/access/task_exec.py` (tarefa agendada; chave
  dedicada, ver "Tarefa agendada que acessa equipamento"). `ssh.py`/`telnet.py` foram removidos e
  `ssh`/`sshpass`/`telnet` do sistema são proibidos.
  "Acesse/verifique/rode X no host N" → vá direto, sem preparar ambiente (já está pronto: `python3` ou `python`,
  o script entra sozinho no `.venv`; não ative venv nem instale nada). Ache o ID em `network/hosts.yaml` e rode:
  - **PADRÃO = sessão persistente por host:** `python3 scripts/tools/access/session.py exec --host-id <ID> --command "<c1>" [--command "<c2>"]`.
    A 1ª chamada faz o login e deixa a sessão aberta; as seguintes no mesmo host **reusam** (sem novo login; no Linux é o
    mesmo shell: `export`/`cd`/`source` persistem). Vários dispositivos = uma sessão por host, todas abertas ao mesmo tempo
    (ex.: ver IP em 3 hosts, decidir, depois ARP nos 3 — 3 logins no total). Fecha sozinha após
    `access.session_idle_minutes` (tela **Configuração**; padrão 5 min) sem comando, ou `… close --host-id <ID>` / `close --all`.
  - `run` (conecta, roda, desconecta) só para coleta pontual isolada; `open`/`exec --session` continuam valendo.
  SSH por padrão; `--telnet` só se o usuário pedir/for legado. Detalhes: `scripts/tools/access/SKILL.md`.
- **"Abre/abrir o terminal (ou o acesso) do host X pra mim" = janela do console, NÃO `session.py`:** o humano quer o
  terminal interativo dele. Ache o ID em `network/hosts.yaml`, rode `python3 scripts/tools/access/terminal_link.py --host-id <ID>`
  (`--method telnet` se pedir Telnet; `--all` se ele quiser escolher) e cole a linha impressa **como está** na resposta: a aba
  Claude abre a janela sozinha (ou mostra o link, se o pop-up for bloqueado). O script não conecta em nada. Vários hosts
  ("abre a borda e o core") = um link por host. Ambíguo (2+ hosts batem com o nome) → pergunte qual.
- **Backup antes de alterar equipamento (INEGOCIÁVEL):** qualquer alteração em host (add/set/remove/restart…), mesmo num
  pedido direto sem workflow, começa com `python3 scripts/tools/backup/change.py begin --host-id <ID>` (backup "pré"; falhou =
  não altere) e termina com `... change.py end --host-id <ID>` (backup "pós" + diff; 1 par por host por sessão). Padrão ligado
  p/ mikrotik/cisco/huawei/linux/proxmox; `backup_before_change: false` no host/grupo desliga. Retenção: `backups.keep_versions`
  (10). O hook `guard-netops.sh` bloqueia o `session.py` de alteração sem o `begin` — pode ir encadeado na mesma linha: `change.py begin --host-id N && session.py run ... ; change.py end --host-id N` (o `&&` é exigido; `;` não vale).
- **Nada pesado em `/tmp` (INEGOCIÁVEL):** venv de teste, Node portátil, Playwright/Chromium, `pytest --basetemp`,
  worktree e build de release vão para `/var/tmp/netops-<tarefa>/` (disco) e são **apagados no fim da tarefa**. O
  `/tmp` pode ser tmpfs (RAM) e contar na memória do container: sobras de testes acumulam e derrubam o host por OOM.
  Disco também enche, por isso apague tudo no fim.
- **Permissões de rede da conversa (seletor 🔐 Rede da aba Claude):** Full ou Ler/Criar/Editar/Apagar nos equipamentos.
  Respeite o aviso "[NetOps — permissões de rede]": categoria desmarcada = colete, planeje e entregue os comandos sem aplicar;
  comando fora disso abre aprovação na tela e, negado, **não contorne**. Full = sem pedir aprovação (salvo se o prompt pedir);
  backup/rollback/teste seguem obrigatórios. Ver `scripts/engine/ui/SKILL.md`.
- **Inventário é a verdade:** nunca conecte em host fora de `network/hosts.yaml`.
- **Segurança:** baseline antes de mudar, rollback pronto, rollback automático em falha.
- **Projeto vivo:** toda execução termina registrando o que aprendeu em `memory/`.
- **Memória é VINCULANTE (INEGOCIÁVEL):** no início de cada sessão, leia `memory/MEMORY.md` e as notas
  relevantes; trate toda regra marcada como "nunca rode"/INEGOCIÁVEL como **bloqueio** — não é sugestão.
- **Cofre:** se as credenciais estiverem criptografadas (`enc.v1:`), o cofre precisa estar
  **destrancado** antes de qualquer acesso — o humano roda `python3 scripts/engine/vault/cli.py unlock`
  (a IA não digita a senha-mestra). Se trancado, os scripts falham com instrução clara.
- **Segredos (INEGOCIÁVEL):** a IA **nunca** lê, descriptografa, imprime ou copia o valor de
  `password`/`secret` — nem com o cofre destrancado, nem "por transparência". Para acessar um
  equipamento, invoque os scripts de `scripts/tools/access/` com `--host <nome>` (eles resolvem a
  credencial internamente); nunca chame `resolve_host(decrypt=True)`/`resolve_secret`/`decrypt_value`.
  Ver `constitution.md` §V e `core/rules/connection-safety.md`.
- **Setup (só na instalação, nunca por pedido):** `.venv/` com `requirements.txt` + `apt install python-is-python3 nmap`
  (ver `README.md`). Todo script CLI se re-executa sozinho no `.venv` (`scripts/engine/lib/_venv.py`), então
  `python3 scripts/...` funciona sem ativar nada. Use `python3` nos comandos (existe em todo Debian/Ubuntu).
- **Agendar tarefa ("todo dia…", "a cada N min…", "me avise quando…"):** use **sempre**
  `scripts/engine/scheduler/cli.py add` (ver `scripts/engine/scheduler/SKILL.md`) — a tarefa vai para o cron do
  sistema e aparece no menu **Tarefas agendadas** para editar. Escolha o tipo: `script` (determinística),
  `agent` (agente de IA) ou `hybrid` (script coleta + agente analisa). **Nunca** `crontab -e`, arquivo em
  `/etc/cron.d` à mão nem a ferramenta `CronCreate` (morre com a sessão). Responda com `id`, tipo e próximos horários.
- **Tarefa agendada que acessa equipamento = chave dedicada, nunca o cofre (INEGOCIÁVEL):** o cofre só fica
  destrancado enquanto um humano digita a senha, então tarefa agendada não depende dele. Para cada tarefa que precise
  entrar em equipamento: `python3 scripts/tools/access/task_key.py provision --task <id-da-tarefa> --hosts <IDs> --mode ro`
  (cria o par ed25519 em `network/task-keys/<id>/`, git-ignorado, e autoriza só nos hosts listados, com backup pré/pós).
  **Mínimo de poder:** `ro` (padrão) = o equipamento só executa comandos de leitura (guarda `netops-ro-shell` com lista de
  permissão); `rw` só se a tarefa realmente precisar escrever, e nesse caso diga ao usuário. A tarefa e o agente dela
  acessam com `python3 scripts/tools/access/task_exec.py --task <id> --host-id N --command "..."` (funciona com o cofre
  trancado). A chave morre com a tarefa: apagar a tarefa (CLI, console ou YAML na mão) apaga a pasta da chave, e a linha no
  authorized_keys dos equipamentos sai com `task_key.py revoke-pending` (fila em `network/task-keys/_revoke.yaml`; rode
  quando o cofre estiver aberto). Comando negado pelo equipamento: não contorne, proponha-o como ação recomendada.
  Ver `scripts/engine/scheduler/SKILL.md`.
- **Console web — subir E reiniciar = um script só, `scripts/engine/ui/start.sh` (INEGOCIÁVEL):** rode **SEMPRE** ele —
  **nunca** `python3 scripts/engine/ui/server.py` direto, nem `kill` + `start.sh` à mão, nem `systemd-run` improvisado.
  - Console **parado** → o script **sobe**. Console **já rodando** → o script **reinicia**, preservando host/porta/terminal/claude.
  - Desacopla (funciona de dentro da aba Claude/terminal web), faz **pré-validação** (venv, sintaxe do `server.py`, porta) antes de
    parar qualquer coisa, espera o supervisor sair e o lock liberar, tenta até 3 vezes e só termina OK quando o HTTP responde
    (log: `/tmp/netops-restart.log`). `--yes` pula a confirmação (em terminal interativo ele pergunta); `--foreground` roda em
    primeiro plano, só para depurar. **Não existe script de restart separado** (o `restart-console.sh` foi removido em 12/11/2026).
  - Funciona de dentro da aba Claude/terminal web: os modos internos são escolhidos só por argumento, nunca pelo ambiente herdado do console.
  - **Reiniciar encerra as sessões vivas da aba Claude**, mas o **turno em andamento volta sozinho**: o console anota em
    `runs/claude/resume-on-restart.json` quem estava no meio de um turno e, ao subir, relança a conversa (`resume`) com um
    prompt de continuação "[NetOps — retomada automática]" (até 2 seguidas sem prompt humano; anotação > 30 min é ignorada;
    `NETOPS_UI_CLAUDE_AUTORESUME=0` desliga). Avise o usuário antes: a aba cai ~15 s. Faça do restart a **última ação** do
    turno; ao ser retomado depois de um restart que você disparou, só confirme o HTTP e conclua — **não reinicie de novo**.
  - Liga o **terminal web** e a **página Claude Code** por padrão (sem o script as abas somem), injeta o `claude` no PATH,
    faz bind no IP da máquina e garante uma instância só. Variáveis: `NETOPS_UI_HOST`, `NETOPS_UI_PORT`, `NETOPS_UI_TERMINAL=0`,
    `NETOPS_UI_CLAUDE=0`, `NETOPS_UI_CLAUDE_PERSIST=0`. Acesso protegido pelo **login por usuário e senha** (sem usuários: senha-mestra; sem token na URL).
    Aba nova que não aparece após atualizar = cache: **hard refresh** (`Ctrl+Shift+R`). Ver `scripts/engine/ui/SKILL.md`.
- **Console NUNCA pode ficar parado (INEGOCIÁVEL):** antes de qualquer start/restart ou mudança em `start.sh`/supervisor,
  valide que o console volta (sintaxe, venv, porta) e **nunca** teste contra o ROOT real "em outra porta". Depois,
  confirme HTTP no host:porta real. Perder o acesso web é inaceitável.
- **Login do agente na aba Claude Code:** `/login` (e `/logout`) funcionam **na própria aba** — não são do
  SDK, a aba os resolve sozinha e abre o fluxo OAuth. Logue **por ali**, não pelo terminal web: a credencial
  vai para o `$HOME/.claude/` do **processo do servidor**, e o terminal web roda como outro usuário (`netops`),
  ou seja, outro cofre e outra lista de conversas. Ver `scripts/engine/ui/SKILL.md`.
- **Aba Claude Code — persistência e DÚVIDA (LIGADA por padrão no `start.sh`; `NETOPS_UI_CLAUDE_PERSIST=0` desliga):** a sessão sobrevive à queda
  do socket (standby/troca de aba): o turno **termina** mesmo com a aba fechada e você re-anexa ao voltar (a
  resposta é relida do transcript, sem buffer). Como um turno pode executar **sem ninguém olhando**, vale a
  regra de ouro: **na dúvida, PERGUNTE** — use `AskUserQuestion` em vez de assumir, e **nunca** execute ação
  irreversível sem certeza. Pergunta sem resposta expira (timeout) e é tratada como negação ("não faz").
