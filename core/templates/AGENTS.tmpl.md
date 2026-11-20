<!-- Modelo do AGENTS.md de uma instalação NetOps (core/templates/AGENTS.tmpl.md).
     O instalador e o start.sh criam o AGENTS.md da instalação a partir daqui SÓ quando ele não existe.
     O AGENTS.md da instalação é LOCAL: não vai para o git nem para o pacote e nunca é sobrescrito
     por atualização — acrescente nele as regras e lembretes desta instalação (menu Memória). -->
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
| Credenciais de hosts (acesso a equipamento; cofre `enc.v1:` ou texto puro, git-ignorado) | `network/credentials.yaml` |
| Cofre de credenciais (criptografia + unlock) | `scripts/engine/vault/` (`SKILL.md`) |
| Usar chave/senha do Cofre de senhas num comando ou `.env` sem expor o valor (`nvault://item/campo`) | `scripts/tools/secrets/` (`SKILL.md`; `nvault run -- <cmd>`) |
| **Cofre de senhas**: segredos que NÃO são de host (portais, APIs, tokens) com templates e campos reutilizáveis (console: **Inventário → Cofre de senhas**) | `network/vault.yaml` (git-ignorado, `enc.v1:`); `scripts/engine/lib/pwvault.py`, `ui/services/vault_items_svc.py` (ver `scripts/engine/vault/SKILL.md`) |
| Mapa de como a rede se interliga | `network/topology.yaml` + `network/topology.md` |
| Boas práticas (texto) | `best-practices/<vendor>/` ou `best-practices/general/` |
| Exemplos de configuração reais | `config-examples/<vendor>/` |
| Skills = scripts operacionais + `SKILL.md` (acesso, diagnóstico, análise) | `scripts/tools/<skill>/` (console: menu **Scripts / Skills**) |
| Motor do NetOps (lib, cofre, console web) | `scripts/engine/` |
| Subir **ou reiniciar** o console web (SEMPRE por aqui) | `scripts/engine/ui/start.sh` |
| Gerenciador de arquivos do console (menu **Arquivos** + painel SFTP ao lado do terminal de host) | `scripts/engine/ui/` (`routers/files.py`, `static/js/file-browser.js`; ver `SKILL.md`) |
| Usuários, grupos de acesso, auditoria do console (SQLite `runs/netops.db`) | `scripts/engine/users/` (`SKILL.md`; console: **Usuários / Grupos de acesso / Auditoria**) |
| GitHub de cada usuário (conta própria no agente; **Minha conta → GitHub**) | `scripts/engine/lib/github_identity.py` (ver `scripts/engine/users/SKILL.md`, "GitHub por usuário") |
| Projetos do console (nome + pasta; sessões do Claude Code por pasta; menu **Projetos**) | `scripts/engine/ui/` (`routers/projects.py`, `services/projects_svc.py`, `static/js/pages/projects.js`; ver `SKILL.md`) |
| Tarefas agendadas (script / agente de IA / script + agente) | `scripts/engine/scheduler/` (`SKILL.md`; console: menu **Tarefas agendadas**) |
| **Central de Avisos**: alertas, avisos e pedidos de aprovação (sino 🔔 no topo + menu **Saída → Central de Avisos**) | `scripts/engine/inbox/` (`SKILL.md`; `inbox/cli.py add`) |
| Descobrir CTs/VMs de um Proxmox, cadastrar e organizar no mapa | `scripts/tools/inventory/` (`SKILL.md`; `map_place.py register` / `place`) |
| Modelos de planejamento | `planning-examples/` |
| O que o framework já aprendeu | `memory/` |
| Saída bruta de execuções | `runs/` |
| Relatórios finais | `reports/` |
| Regras, schemas, templates do framework | `core/` |
| O padrão de organização e nomenclatura | `PADRAO.md` |
| Os princípios inegociáveis | `constitution.md` |

## Regras essenciais

- **Idioma (INEGOCIÁVEL):** responda **sempre no idioma em que a pessoa escreve** (português → português,
  inglês → inglês, espanhol → espanhol), qualquer que seja o idioma da instalação. Arquivos gerados **sem conversa**
  (relatório de tarefa agendada, Central de Avisos, memória) saem no idioma da instalação
  (`core/config/project-config.yaml` → `instance.language`); relatório pedido numa conversa sai no idioma da conversa.
- **Textos do console, da API e das CLIs (regra de desenvolvimento):** toda string visível passa por `t()` e vai para
  `core/locales/<idioma>/*.json` (inglês é a fonte); código, nomes de arquivo e chaves em inglês. Leia `core/rules/i18n.md`.

- **Identificação de equipamentos nas respostas (INEGOCIÁVEL):** ao citar qualquer host, container (CT/VM),
  roteador, switch, servidor ou outro equipamento, **nunca use só o ID**. Escreva sempre **nome (ID)**, com o
  nome primeiro e o número entre parênteses: `SERVIDOR-PROXMOX-01 (host 14)`, `RT-BORDA (host 2)`,
  `PROXY-TESTE (CT 102)`. O nome vem de `network/hosts.yaml`
  (`hostname`) ou, para CT/VM, do `pct list`/`qm list`. Vale para relatórios, resumos, tabelas e mensagens
  de status. Só o ID, sem nome, obriga o usuário a procurar no inventário: não faça. Se o nome for longo,
  use um curto reconhecível (ex.: `PVE-SITE-A`), mas sempre com o número ao lado.

- **Multiusuário (aba Claude):** cada pessoa entra com o próprio login; o que ela pode fazer vem do grupo dela.
  - **Na aba Claude:** `NETOPS_USER` identifica quem pediu. O teto de rede do grupo dele vale e **não se contorna**.
  - **GitHub por usuário:** na aba Claude e nos Projetos, git/gh usam a conta do GitHub **de quem abriu a conversa**.
    Sem conta conectada, push, PR e `gh` falham: peça para conectar em **Minha conta → GitHub** (`#account/github`) e
    reabrir a conversa. Nunca use a conta do servidor nem troque `GH_CONFIG_DIR`, `GH_TOKEN` ou a identidade do git.
- **Padronize:** todo arquivo novo segue o `_TEMPLATE` da sua pasta. Ver `PADRAO.md`.
- **Conta do servidor (INEGOCIÁVEL):** o NetOps roda como a conta Linux `netops` (HOME `/var/lib/netops`), nunca root:
  console, IA, subagentes, terminal, agendador e atualizador. Nunca use `su`.
  **Root NESTE servidor = `sudo <comando>` direto, liberado SÓ com o cofre destrancado** (sem senha; o PAM confere o
  cofre a cada chamada via `/usr/local/sbin/netops-sudo-cofre`). Use `sudo` comum — **nunca `sudo -n`** (o `-n` recusa
  antes da checagem). Se responder "a password is required" = cofre trancado: peça ao humano para destrancar e pare.
  **Sudo automático:** com o cofre destrancado, `apt`, `apt-get`, `dpkg`, `systemctl`/`journalctl` (sem `--user`), `nft`,
  `iptables`, `conntrack`, `docker`, `mount`, `useradd`, `sysctl`, `ss`, `lsof`, `reboot`... já rodam como root sem
  digitar `sudo` (funções em `/usr/local/share/netops/auto-sudo.bash`, carregadas pelo `~/.bashrc`). Para arquivo do
  sistema: `rootcat <arq>` (ler), `rootedit <arq>` (editar), `rootsh '<pipeline>'` (redireção/pipe como root). Scripts
  não interativos não carregam as funções: neles escreva `sudo` explícito.
  Só use root quando o pedido exigir (instalar pacote, mexer em serviço/arquivo do sistema, ler log do sistema); o
  resto roda direto como `netops`. Alternativa (ex.: tarefa sem terminal) = **host Local** (`access.method: local`, protegido):
  `python3 scripts/tools/access/session.py exec --host-id <ID-LOCAL> --command "..."` roda como root, por operação,
  sem SSH, com a senha do admin local no cofre (a IA nunca a vê). Exige cofre destrancado e `server.admin`; se faltar,
  informe e pare.
  **Diagnóstico de rede roda DIRETO como `netops`, sem root e sem cofre** (o servidor já está preparado:
  `net.ipv4.ping_group_range` + capabilities via `/usr/local/sbin/netops-netcaps`): `ping`, `traceroute` (inclusive
  `-I`/`-T`), `mtr`, `nmap` (SYN scan `-sS`, `-O`), `nping`, `tcpdump`, `arping`, `fping`, `arp-scan`, `iperf3`,
  `dig`, `snmpwalk`, `curl`. Nunca mande essas ferramentas para o host Local; se uma delas der "Operation not
  permitted", avise o humano para rodar `sudo /usr/local/sbin/netops-netcaps` (não contorne pelo Local).
  Ver `scripts/engine/localadmin/SKILL.md`. Instalação antiga (console root) migra com `scripts/engine/identity/`.
- **Acesso a equipamento por CLI (INEGOCIÁVEL):** só dois scripts — `scripts/tools/access/session.py` (pedido do
  usuário no chat/console; usa o cofre; SSH/Telnet; e o host Local deste servidor) e `scripts/tools/access/task_exec.py` (tarefa agendada; chave
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
  (10). **CT/VM de Proxmox = snapshot, não backup de config:** `change.py begin --host-id <CT>` sai com código 4 e manda
  **perguntar ao usuário com `AskUserQuestion`** ("Fazer snapshot antes?"). Sim → `change.py begin --host-id <CT> --mode snapshot [--tag x]`
  (`scripts/tools/backup/snapshot.py`: confere storage/espaço do pool, roda fstrim, relê o espaço, bloqueia se o pool passar de 90 %, cria
  `netops-pre-AAAAMMDD-HHMM`); Não → `--mode none`. No fim, `change.py end` NÃO apaga nada: avise que concluiu e **pergunte** se apaga
  (`snapshot.py delete --host-id <CT>`, só após o "sim"; `snapshot.py pending` lista os esquecidos). O hook `guard-netops.sh` bloqueia o `session.py` de alteração sem o `begin` — pode ir encadeado na mesma linha: `change.py begin --host-id N && session.py run ... ; change.py end --host-id N` (o `&&` é exigido; `;` não vale).
- **Nada pesado em `/tmp` (INEGOCIÁVEL):** venv de teste, Node portátil, Playwright/Chromium, `pytest --basetemp`,
  worktree e build de release vão para `/var/tmp/netops-<tarefa>/` (disco) e são **apagados no fim da tarefa**. O
  `/tmp` pode ser tmpfs (RAM) e contar na memória do container: sobras de testes acumulam e derrubam o host por OOM.
  Disco também enche, por isso apague tudo no fim.
- **Permissões de rede da conversa (seletor 🔐 Rede da aba Claude):** Full ou Ler/Criar/Editar/Apagar nos equipamentos.
  Respeite o aviso "[NetOps — permissões de rede]": categoria desmarcada = colete, planeje e entregue os comandos sem aplicar;
  comando fora disso abre aprovação na tela e, negado, **não contorne**. Full = sem pedir aprovação (salvo se o prompt pedir);
  backup/rollback/teste seguem obrigatórios. Ver `scripts/engine/ui/SKILL.md`.
- **Nome de equipamento em MAIÚSCULAS (INEGOCIÁVEL):** todo `hostname` cadastrado em `network/hosts.yaml` (host físico, CT, VM,
  roteador, switch, servidor) é escrito **TUDO EM MAIÚSCULAS**, com hífen no lugar de espaço/underscore quando for nome técnico
  (ex.: `9ROUTER-TEST`, `COOLIFY-FRANCISCO`, `PROXY-TESTE`). Vale para cadastro novo **e** para renomear existente; o nome
  também aparece em maiúsculas nas respostas (`nome (ID)`). Nunca cadastre `9router-test`, `Proxy-Teste` etc.
  Antes de gravar em `hosts.yaml`, confira `hostname == hostname.upper()`.
- **Inventário é a verdade:** nunca conecte em host fora de `network/hosts.yaml`.
- **Segurança:** baseline antes de mudar, rollback pronto, rollback automático em falha.
- **Projeto vivo:** toda execução termina registrando o que aprendeu em `memory/`.
- **Memória é VINCULANTE (INEGOCIÁVEL):** no início de cada sessão, leia `memory/MEMORY.md` e as notas
  relevantes; trate toda regra marcada como "nunca rode"/INEGOCIÁVEL como **bloqueio** — não é sugestão.
- **Cofre:** se as credenciais estiverem criptografadas (`enc.v1:`), o cofre precisa estar
  **destrancado** antes de qualquer acesso — o humano roda `python3 scripts/engine/vault/cli.py unlock`
  (a IA não digita a senha-mestra). Se trancado, os scripts falham com instrução clara.
- **Segredos (INEGOCIÁVEL):** a IA **nunca** lê, descriptografa, imprime ou copia o valor de
  `password`/`secret` nem os segredos do Cofre de senhas (`network/vault.yaml`) — nem com o cofre destrancado, nem "por transparência". Para acessar um
  equipamento, invoque os scripts de `scripts/tools/access/` com `--host <nome>` (eles resolvem a
  credencial internamente); nunca chame `resolve_host(decrypt=True)`/`resolve_secret`/`decrypt_value`.
  Ver `constitution.md` §V e `core/rules/connection-safety.md`.
- **Chave de API/senha do Cofre de senhas em comando, `.env` ou script = `nvault` (INEGOCIÁVEL):** para usar um segredo do
  Cofre de senhas (Cloudflare/Wrangler, API do Coolify, `.env` de aplicação...), escreva a **referência** `nvault://<ID>/<campo>` (ID numérico do item, estável)
  (no `.env`, com `--set` ou `--item`) e rode `nvault run -- <comando>` (`scripts/tools/secrets/run.py`). O valor vai só para o
  ambiente do processo e sai mascarado (`***`). Nunca grave o valor em arquivo, nunca leia o `network/vault.yaml`, nunca chame
  `/reveal` e nunca transforme nem envie o segredo para outro lugar. `nvault list` mostra as referências. Precisa do cofre destrancado
  (código 3 = trancado: peça ao humano para destrancar) e da permissão `vault.use` (código 4). Tarefa agendada não usa o `nvault`.
  Ver `scripts/tools/secrets/SKILL.md`.
- **Setup (só na instalação, nunca por pedido):** `.venv/` com `requirements.txt` + `apt install python-is-python3 nmap`
  (ver `README.md`). Todo script CLI se re-executa sozinho no `.venv` (`scripts/engine/lib/_venv.py`), então
  `python3 scripts/...` funciona sem ativar nada. Use `python3` nos comandos (existe em todo Debian/Ubuntu).
- **Agendar tarefa ("todo dia…", "a cada N min…", "me avise quando…"):** use **sempre**
  `scripts/engine/scheduler/cli.py add` (ver `scripts/engine/scheduler/SKILL.md`) — a tarefa vai para o cron do
  sistema e aparece no menu **Tarefas agendadas** para editar. Algo que precise de atenção ou da **aprovação** do
  usuário (alerta, "posso apagar estes arquivos?") vai para a **Central de Avisos**: `scripts/engine/inbox/cli.py add`
  (script/chat) ou bloco ```netops-inbox``` na resposta do agente da tarefa — nunca execute a ação antes da aprovação. Escolha o tipo: `script` (determinística),
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
    (log: `~/.local/state/netops/restart-<instância>.log`; legado: `/tmp/netops-restart.log`). Como root, o script
    delega para a conta `netops` (serviço systemd do usuário `netops-console@<instância>`, sobe no boot). `--yes` pula a confirmação (em terminal interativo ele pergunta); `--foreground` roda em
    primeiro plano, só para depurar. **Não existe script de restart separado** (o `restart-console.sh` foi removido em 12/11/2026).
  - Funciona de dentro da aba Claude/terminal web: os modos internos são escolhidos só por argumento, nunca pelo ambiente herdado do console.
  - **Reiniciar encerra as sessões vivas da aba Claude**, mas o **turno em andamento volta sozinho**: o console anota em
    `runs/claude/resume-on-restart.json` quem estava no meio de um turno e, ao subir, relança a conversa (`resume`) com um
    prompt de continuação "[NetOps — retomada automática]" (até 2 seguidas sem prompt humano; anotação > 30 min é ignorada;
    `NETOPS_UI_CLAUDE_AUTORESUME=0` desliga). Avise o usuário antes: a aba cai ~15 s. Faça do restart a **última ação** do
    turno; ao ser retomado depois de um restart que você disparou, só confirme o HTTP e conclua — **não reinicie de novo**.
  - Liga o **terminal web** e a **página Claude Code** por padrão (sem o script as abas somem), injeta o `claude` no PATH,
    faz bind no IP da máquina e garante uma instância só. Variáveis: `NETOPS_UI_HOST`, `NETOPS_UI_PORT`, `NETOPS_UI_TERMINAL=0`,
    `NETOPS_UI_CLAUDE=0`, `NETOPS_UI_CLAUDE_PERSIST=0`. Acesso protegido pelo **login por e-mail e senha** (instalação nova: assistente de **primeiro acesso** `#setup?token=...`, que cria o admin + cofre + idioma; reimprimir o link: `users/cli.py setup-link`). O console escuta em todos os IPs (`0.0.0.0`).
    Aba nova que não aparece após atualizar = cache: **hard refresh** (`Ctrl+Shift+R`). Ver `scripts/engine/ui/SKILL.md`.
- **Console NUNCA pode ficar parado (INEGOCIÁVEL):** antes de qualquer start/restart ou mudança em `start.sh`/supervisor,
  valide que o console volta (sintaxe, venv, porta) e **nunca** teste contra o ROOT real "em outra porta". Depois,
  confirme HTTP no host:porta real. Perder o acesso web é inaceitável.
- **Login do agente na aba Claude Code:** `/login` (e `/logout`) funcionam **na própria aba** — não são do
  SDK, a aba os resolve sozinha e abre o fluxo OAuth. A credencial vai para `$HOME/.claude/` da conta do servidor
  (`/var/lib/netops/.claude`); console, terminal web, tarefas e subagentes usam a MESMA conta e o MESMO perfil.
  (Instalação legada, console root: o perfil é `/root/.claude` e o terminal web é outra conta.) Ver `scripts/engine/ui/SKILL.md`.
- **Aba Claude Code — persistência e DÚVIDA (LIGADA por padrão no `start.sh`; `NETOPS_UI_CLAUDE_PERSIST=0` desliga):** a sessão sobrevive à queda
  do socket (standby/troca de aba): o turno **termina** mesmo com a aba fechada e você re-anexa ao voltar (a
  resposta é relida do transcript, sem buffer). Como um turno pode executar **sem ninguém olhando**, vale a
  regra de ouro: **na dúvida, PERGUNTE** — use `AskUserQuestion` em vez de assumir, e **nunca** execute ação
  irreversível sem certeza. Pergunta sem resposta expira (timeout) e é tratada como negação ("não faz").
