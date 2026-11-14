# SKILL — Console Web (CRUD) do NetOps

## O que é

Uma interface web local para **cadastrar e editar** tudo que normalmente se edita à mão nos
arquivos do NetOps: hosts, grupos, credenciais, topologia, memória, boas práticas, exemplos
de config, workflows, agentes e a configuração do projeto. Também **visualiza** (read-only)
relatórios e execuções.

Hosts usam **IDs inteiros gerados automaticamente e imutáveis**. O campo não aparece no
cadastro; o hostname é editável e as telas mostram nome/IP. Alterar o nome preserva todos
os vínculos. A API rejeita IDs enviados no POST/PATCH/PUT e a antiga rota de rename de ID.

Dá pra **renomear o nome** de grupos e credenciais, além de
arquivos de conhecimento/workflows/agentes. O campo de ID/nome é **editável no próprio
formulário de edição** do item (não há botão "Renomear" à parte): ao **Salvar**, se o ID mudou,
o servidor renomeia **com cascade** — renomear um grupo atualiza o campo `group` dos hosts que o
usam; uma credencial atualiza `credential` em hosts/grupos. Enquanto o campo está alterado,
o form mostra **quantas referências** serão
atualizadas. Os segmentos continuam nos arquivos canônicos e na API; lições não se
renomeiam (append-only, constituição §II).

É uma **ferramenta de operador efêmera** (constituição §VII): *stateless* (cada request lê/
escreve só os arquivos canônicos — sem banco, sem cache, sem segundo cofre), feita para rodar
quando o operador precisa e ser encerrada depois. O framework funciona 100% com ela desligada.

## Como subir

**SEMPRE** pelo script (nunca `python3 scripts/engine/ui/server.py` direto). Ele liga o terminal web
e faz bind no IP da máquina, com instância única:

```bash
scripts/engine/ui/start.sh                          # IP da máquina, porta 8765, terminal + Claude Code ON
NETOPS_UI_HOST=127.0.0.1 scripts/engine/ui/start.sh # força loopback (só local)
NETOPS_UI_PORT=9000      scripts/engine/ui/start.sh # outra porta
NETOPS_UI_TERMINAL=0     scripts/engine/ui/start.sh # sobe SEM o terminal web
NETOPS_UI_CLAUDE=0       scripts/engine/ui/start.sh # sobe SEM a página Claude Code
scripts/engine/ui/start.sh --read-only --no-vault-unlock   # flags extras viram passthrough
```

O script imprime a URL (`http://<ip>:<porta>/`). O acesso é protegido pelo **login com a senha-mestra
do cofre** (ver "Segurança"); não há token de transporte na URL.

> Por baixo o script chama `scripts/engine/ui/server.py` (flags: `--host/--port/--read-only/`
> `--no-vault-unlock/--enable-terminal/--enable-claude/--no-browser`). A entrada operacional,
> inclusive durante testes, continua sendo o launcher; não inicie o servidor diretamente.

## Não aparece uma aba? (leia antes de "sumiu"/"quebrou")

As páginas em **SISTEMA** seguem regras que confundem à primeira vista — **antes de achar que um deploy
falhou**, cheque aqui:

- **Abas por feature-flag (Terminal e Claude Code).** Só aparecem quando a feature está **ligada**.
  Pelo `start.sh` ambas vêm **ligadas por padrão**; subir o `server.py` na mão **sem** `--enable-terminal`/
  `--enable-claude` deixa as abas **invisíveis** (não é bug). Confira o estado em `GET /api/config/meta`
  (`terminal_enabled` / `claude_enabled`). Desligar é opt-out: `NETOPS_UI_TERMINAL=0` / `NETOPS_UI_CLAUDE=0`.
- **Aba nova não aparece após atualizar o código?** É **cache do SPA** no navegador (o `index.html` é
  `no-store`, mas o `main.js` é cacheado por ETag). Faça **hard refresh**: `Ctrl+Shift+R` (ou `Shift+F5`).
- **Aba "Claude Code" aparece mas não conecta?** A página exige o binário `claude` no **PATH** do processo
  do servidor (`claude_svc.is_available()`). O `start.sh` já injeta `~/.local/bin` no PATH; se subir o
  `server.py` na mão, garanta que `which claude` funciona no mesmo ambiente.
- **Agente deslogado ("/login não existe")?** `/login` é comando da **TUI** do Claude Code — ele **não**
  existe no protocolo do SDK, então nunca aparece na lista de slash da aba. A aba resolve `/login`,
  `/logout` e `/auth` **por conta própria** (ver `services/claude_auth.py`): abre o fluxo OAuth do
  `claude auth login`, mostra a URL para você autorizar no navegador e recebe o código colado. O
  campo de mensagem **não trava** quando a sessão cai — dá para digitar `/login` mesmo desconectado.
  Depois do login, "Recarregar sessão" relança o agente **retomando a mesma conversa**.
- **Loguei pelo terminal web e a aba continua deslogada.** Esperado, e é a pegadinha mais cara aqui: a
  credencial mora em `$HOME/.claude/.credentials.json` **do processo que roda o `claude`**. A aba lança o
  agente com o env do **servidor**; o terminal web **dropa privilégio** para `netops` (ver `NETOPS_TERM_USER`
  em `routers/terminal.py`). Com o servidor subindo como root, são dois stores diferentes — e duas listas de
  conversas (`$HOME/.claude/projects/`). Logue **pela própria aba**: aí cai no store certo. O modal mostra
  qual arquivo/usuário está em jogo, e `GET /api/claude/auth/status` responde o mesmo (sem token nenhum).
- **Não vejo NADA além do login?** O cofre está inicializado e você ainda não logou — o gate de login
  (senha-mestra) trava todo o `/api`. Não há mais token de transporte na URL (`?token=`); foi removido.

## Setup inicial (uma vez, com internet)

As dependências do frontend são **vendadas localmente** (offline/air-gap-safe):

```bash
bash scripts/engine/ui/vendor_deps.sh     # baixa preact/htm/marked/js-yaml/xterm p/ static/vendor/
.venv/bin/pip install -r requirements.txt   # fastapi + uvicorn + ruamel.yaml + websockets
```

> `websockets` é necessário para o terminal web e a página Claude Code (uvicorn faz o upgrade
> WS); sem ele o `/api/term` e o `/api/claude` respondem 404. A página Claude Code precisa de
> `claude-agent-sdk` (no `requirements.txt`) **e** do binário `claude` no PATH; o SDK reaproveita
> o login de assinatura já existente (`~/.claude/.credentials.json`) — não exige `ANTHROPIC_API_KEY`.

## Segurança (resumo)

- **Bind em loopback por padrão.** `--host <ip-privado>` expõe na rede e imprime um AVISO;
  use só em rede confiável. `0.0.0.0` é recusado.
- **Host/Origin checados** em toda a `/api` e nos WebSockets (anti DNS-rebinding e anti CSRF/CSWSH) — política única em
  `deps.host_origin_allowed`. **Proxy reverso / qualquer domínio:** com login ativo (cofre inicializado) aceita qualquer
  Host/Origin, pois o gate é a sessão (token em header/query, nunca cookie). Sem login o console está aberto e Host/Origin
  seguem estritos (loopback, IP de bind ou `NETOPS_UI_ALLOWED_HOSTS=dom.com,.outro.com,*`). O uvicorn confia em
  `X-Forwarded-*` (`NETOPS_UI_FORWARDED_ALLOW_IPS`, default `*`). O proxy precisa repassar WebSocket (`Upgrade`/`Connection`).
- **Login com a senha-mestra é o gate de acesso:** quando o cofre está **inicializado**, o console inteiro fica atrás de
  uma tela de login. A senha-mestra (mesmo `derive_key`+`verify_key` do cofre) emite uma **sessão de
  login** própria (sid em memória do processo, header `X-Netops-Session`, TTL deslizante); todo `/api`
  passa a exigi-la, exceto a allow-list de bootstrap (`/api/auth/{login,status,logout}`,
  `/api/config/meta`). O mesmo login **também destranca o cofre** (a não ser com `--no-vault-unlock`).
  Endpoints: `GET /api/auth/status`, `POST /api/auth/login`, `POST /api/auth/logout` (botão "Sair").
  ⚠ **Sem cofre inicializado não há senha-mestra — logo, não há login e o console fica aberto** a
  quem alcançar o endereço (só Host/Origin protegem). Inicialize o cofre
  (`scripts/engine/vault/cli.py init`) para proteger o acesso por senha. O WS do terminal/Claude usa
  o mesmo gate (`?auth=<sid>`). Sessão em memória ⇒ vale só com o servidor no ar (uvicorn single-process).
  O navegador compartilha apenas o sid em `localStorage`, na mesma origem (protocolo, host e
  porta), com migração automática do antigo `sessionStorage`. Abrir/recarregar outras abas
  reutiliza a sessão; login, logout e expiração são sincronizados entre abas. Respostas
  atrasadas de uma sessão anterior não apagam um login novo. A senha não é armazenada;
  expiração no servidor ou reinício continuam exigindo novo login.
- **Anti DNS-rebinding:** sem login, o header `Host` precisa bater com loopback/IP de bind/`NETOPS_UI_ALLOWED_HOSTS` (senão 403 `forbidden_host`); com login ativo qualquer Host passa (ver acima).
- **Cofre:** a UI **lê o status** (`session_status()` — não renova o TTL) e **cifra na escrita**
  (`encrypt_value` com a chave da sessão) e **nunca** devolve senha em texto puro ao navegador.
- **Destrancar pela web:** o banner do cofre tem **"Destrancar aqui"** — a senha-mestra digitada
  vai numa request (`POST /api/vault/unlock`), deriva a chave (`derive_key` Argon2id, mesmo caminho
  do `cli.py unlock`) e é descartada: **não é gravada, logada nem devolvida**. A sessão resultante
  vale também para a CLI e os agentes. Há também **"Trancar"** (`POST /api/vault/lock`).
  ⚠ Em bind **não-loopback** sobre HTTP, a senha-mestra trafega em **texto puro** na rede — use só
  atrás de túnel SSH/VPN. Para exigir o terminal e desabilitar o unlock web: `--no-vault-unlock`.
- **Integridade:** escrita atômica (tmp + replace), `credentials.yaml` em modo `0600`,
  comentários preservados (ruamel round-trip), concorrência otimista por hash (`409` em conflito),
  validação de schema antes de gravar host/grupo. Renames que tocam **dois arquivos**
  (credencial→hosts.yaml, host→topology.yaml) gravam numa **transação** (`yaml_io.write_many`):
  valida as revs dos dois antes de escrever e faz **rollback** se a segunda escrita falhar.
- **Terminal web (`--enable-terminal`):** ⚠ é um **shell real** (PTY) na máquina = execução de
  comando arbitrário como o usuário do servidor. **DESLIGADO por padrão** no server.py (o
  `start.sh` liga; `NETOPS_UI_TERMINAL=0` desliga), nunca liga em `--read-only`. O handshake do
  WebSocket (`/api/term`) é autenticado **à mão** (token + Host + Origin) porque o middleware http
  do app **não** cobre WebSocket. Sobre HTTP não-loopback, o token (na URL) trafega em texto puro
  e dá shell completo — prefira túnel SSH/VPN.
- **Terminal de HOST (SSH/Telnet) — botão "⌨ Acessar" em Hosts:** mesmo gate do `/api/term`
  (`--enable-terminal`, fora de `--read-only`, login + Host + Origin). WS `/api/term/host/<id>?method=&port=`;
  abre em janela própria `#hostterm/<id>?method=ssh&port=22` (tela cheia, sem menu). Métodos = `access`
  principal + `extra_access` (só ssh/telnet, ordem do cadastro): 1 método → abre direto; 2+ → popup de
  escolha (`#hosts?access=<id>`). SSH = `asyncssh` (PTY xterm-256color, resize, algoritmos legados no fim
  da lista); Telnet = `telnetlib3` (NAWS, login automático detectando `login:`/`Password:`, Enter CR LF).
  A credencial é decifrada **no servidor** (cofre destrancado) e nunca vai ao navegador. **Cofre trancado**
  → status `vault_locked` e a janela abre o popup "Destrancar o cofre" (`UnlockModal`); destrancou → o
  cliente manda `{"vault":"retry"}` e o login segue automático; cancelou → `{"vault":"manual"}` e o terminal
  pede a senha. Sem credencial (ou `--no-vault-unlock`) → o terminal pede usuário/senha (não grava). Chave do host SSH: aceita e registra o
  fingerprint no log. Auditoria em `runs/<ts>-terminal-<id>/session.log` (sem gravar teclas).
  Código: `routers/host_term.py`, `services/host_term_svc.py`, `static/js/pages/host-term.js`.
- **Arquivos (menu `#files`) e painel SFTP do terminal de host:** gerenciador de arquivos completo, com
  navegar, enviar arquivos e pastas, baixar (vários itens ou pastas viram `.zip` em fluxo), criar, renomear,
  copiar, recortar, colar, editar texto (até 5 MiB) e mudar permissões. Tem **o mesmo nível de confiança do
  terminal web**: só liga com o terminal ligado (`deps.files_enabled()`; o `start.sh` liga) e nunca em
  `--read-only`. `NETOPS_UI_FILES=0` desliga só os arquivos. O menu roda **como o usuário do servidor (root na
  instalação padrão)** e não tem jaula de diretório, nem para segredos (decisão do usuário, 13/11/2026). Proteções:
  - apagar, mover ou renomear `/` e as pastas de sistema de 1º nível (`/etc`, `/usr`, ...) é recusado;
  - apagar não segue link simbólico e é definitivo; a tela exige digitar o nome do item (ou a quantidade);
  - upload em partes de 8 MiB grava num `.netops-upload-<uid>` e só renomeia no fim; a edição grava num
    temporário e confere mtime+tamanho (409 `changed` se o arquivo mudou);
  - toda escrita e download vai para `runs/files/audit.log` (sem conteúdo).
  O download usa um **link de uso único** (`GET /api/files/download-link` → `/api/files/dl/<ticket>`, 120 s).
  Esse é o único caminho de `/api` liberado sem o header de sessão (`app.py`, `AUTH_TICKET_PREFIX`), e o ticket só
  é emitido para quem está logado. **Painel SFTP:** ao conectar por SSH, o terminal de host registra a conexão em
  `files_svc.SFTP_SESSIONS` e manda o token no status `conectado` (`sftp`). O painel usa `src=<token>` nas mesmas
  rotas, então não faz um segundo login, inclusive com senha digitada à mão. A sessão some quando o terminal fecha.
  Telnet e hosts sem SFTP (Cisco/Huawei, em geral) mostram "indisponível". Código: `routers/files.py`,
  `services/files_svc.py`, `static/js/file-browser.js`, `files-core.js`, `pages/files.js`, painel em
  `pages/host-term.js`.
- **Página Claude Code (`--enable-claude`):** ⚠ dirige um **agente de IA** (via `claude-agent-sdk`)
  que **executa comandos e edita arquivos** como o usuário do servidor, com `cwd=NETOPS_ROOT` e
  herdando `AGENTS.md`/skills/agentes. Mesma postura do terminal: DESLIGADA por padrão no server.py
  (o `start.sh` liga; `NETOPS_UI_CLAUDE=0` desliga), **nunca** liga em `--read-only`. O WebSocket
  (`/api/claude`) e o upload (`POST /api/claude/upload`) usam a **mesma auth** (token + Host +
  Origin + sessão). A UI expõe **todos os modos** (`plan/default/acceptEdits/dontAsk/bypassPermissions`)
  e um prompt de aprovação na tela (`can_use_tool`); cada aba abre um subprocesso `claude` próprio,
  encerrado no disconnect. Anexos vão para `runs/claude/uploads/`.
- **Login do agente (`/api/claude/auth/*`, `/api/claude/login`):** o fluxo OAuth do `claude auth login`
  conduzido pela aba (`services/claude_auth.py`), num PTY, no **mesmo env/HOME** do agente — é o que
  garante que a credencial caia no store que a aba lê. Mesmo gating dos demais (`--enable-claude`, nunca
  em `--read-only`, Host + Origin + sessão). O status é **metadado** (`loggedIn`, e-mail, plano, caminho do
  arquivo): token e refresh token **nunca** saem pela API. O código OAuth colado é tratado como segredo —
  eco do PTY desligado e redação na saída; não vai para log nenhum.

## Fronteira (o que a UI NÃO faz)

Pelo modelo de segurança (§IV/§V), a UI — **por funcionalidade de UI** (botões/formulários) —
**não conecta em equipamentos** nem dispara workflows/mudanças. Coletar, aplicar config,
baseline/rollback continuam sendo do agente `executor` via IDE de IA. A parte CRUD é só
arquivos + visualização.

**Exceção: o terminal web** (`--enable-terminal`, opt-in) é um *passthrough* para um shell do
**humano** — equivalente a um SSH. Não é o framework operando sozinho; é a pessoa no teclado, e o
que ela digita é responsabilidade dela (constituição §VII). Serve, p.ex., para rodar `claude` ou
os `scripts/tools/access/*.py` e acompanhar a execução pelo navegador.

**Exceção 2: a página Claude Code** (`--enable-claude`, opt-in) leva esse mesmo passthrough do
humano para uma **interface gráfica**: em vez de digitar `claude` no terminal, a pessoa conversa
com o agente direto na web — com troca de modo, aprovação de cada ferramenta na tela, slash
commands e anexos. Continua sendo a pessoa no comando (ela aprova/escolhe o modo), só que sem TUI.

**Exceção 3: Tarefas agendadas** (`#schedules`, `routers/schedules.py`). A tela só edita
`network/schedules.yaml` e lê `runs/schedules/`. Quem executa é o **cron do sistema**
(`/etc/cron.d/netops-scheduler` → `scripts/engine/scheduler/cli.py tick`), com o console ligado ou
não. "▶ Executar" usa o mesmo executor, em processo destacado. Cada tarefa é um pedido explícito
do humano (ele cadastrou o comando/prompt e o horário). O agente agendado vem com permissão
`restricted` por padrão e nunca cria outras tarefas. O contador de não lidas no menu faz polling
de `GET /api/schedules/notifications` a cada 30 s. Detalhes em `scripts/engine/scheduler/SKILL.md`.

## Estrutura

```
scripts/engine/ui/
  server.py            entrypoint (bind, token, browser)
  app.py               FastAPI (middleware de segurança + handlers + StaticFiles)
  deps.py              caminhos canônicos + estado + exceções de domínio
  models.py            modelos Pydantic (validação de entrada)
  routers/             um router por recurso (hosts, credentials, ..., terminal=WS PTY, claude=WS agente)
  services/            lógica de I/O: yaml_io (round-trip/atomic/concorrência), *_svc (claude_svc=sessão SDK)
  static/              SPA Preact (sem build): index.html + js/ (+ pages/terminal.js, pages/claude.js) + vendor/ (xterm.js, ...)
  tests/               pytest E2E (cofre, concorrência, mascaramento, append-only, terminal WS, Claude flag, ...)
```

## Atualizações pelas releases

A topbar oferece **Verificar atualizações**, versão instalada e notas completas de todas as
releases estáveis posteriores. A aplicação exige login no console, modo de escrita e launcher
gerenciado. Salve alterações antes de confirmar. Sessões interativas abertas não bloqueiam:
o reinício as encerra, preservando os transcripts das conversas para retomada. Backups de
equipamento e workflows em execução precisam terminar antes da aplicação.

`start.sh` agora mantém um supervisor com trava por instalação. O pacote é preparado com
backup verificado; o servidor é reiniciado na mesma URL e pode exigir novo login. Falhas
antes da confirmação restauram código e ambiente anteriores. Os exemplos do pacote não
substituem dados e personalizações. A versão 2 converte os formatos de identidade necessários
com uma transação própria, somente após a confirmação do código pelo supervisor.

Enquanto essa conversão estiver pendente, **Preparando o NetOps** impede abrir os editores
ou conexões interativas; `GET /api/config/meta` informa `host_migration`. Falha na pré-validação
do candidato preserva os dados legados e aciona o retorno do código anterior. Falha posterior
mantém o código novo e mostra **Migração de IDs bloqueada**, sem anunciar sucesso ou liberar
escritas. A recuperação no próximo início usa o baseline/journal; conflitos externos exigem
revisão humana. O estado privado fica em `.netops-update/`, nunca nas APIs de runs/backups.

A primeira adoção requer reiniciar o console pelo launcher atualizado. O GitHub CLI precisa
estar autenticado no usuário/HOME do servidor para acessar o repositório privado. Não envie
nem solicite tokens pela UI. Detalhes e recuperação: `scripts/engine/update/SKILL.md`.

## Testes

```bash
.venv/bin/python3 -m pytest scripts/engine/ui/tests/ -q
```

Os testes rodam num diretório temporário isolado — **nunca** tocam nos arquivos reais.

Sessão entre abas: `node --test scripts/engine/ui/tests/auth-session.test.mjs`.
O cenário `tests/auth.browser.mjs` valida três abas em desktop/celular, login único,
recarregamento, logout e expiração; exige console temporário em loopback via
`NETOPS_E2E_URL`, com `PLAYWRIGHT_MODULE` e `CHROMIUM_EXECUTABLE` se necessário.

## Links e reabertura das sessões Claude Code

### Catálogo e erros de modelo

`GET /api/claude/models` descobre modelos pelo handshake do mesmo CLI, HOME, diretório
e configurações usados pela conversa. Não envia prompt nem lê tokens diretamente.
Isso respeita gateways/provedores locais; consultar o catálogo público da Anthropic
não comprova acesso pelo provedor que executa a aba. O padrão é o Sonnet mais recente
anunciado pelo CLI, com fallback no padrão do próprio Claude Code, sem versões fixas.
O cache semanal usa `source: claude-cli-v1` e ignora o antigo cache da API; uma falha
preserva o último catálogo e limita tentativas automáticas por 60 segundos.
**Verificar modelos** força nova descoberta sem inferência.

O SDK preserva `AssistantMessage.error`, `ResultMessage.errors` e `api_error_status`.
Um erro genérico “issue with the selected model” abre a escolha de outro modelo e
mantém o UUID da conversa. Só evidência explícita de limite (HTTP 429/código `rate_limit`)
abre o aviso de uso; constar no catálogo não comprova cota esgotada. HTTP 529 indica
sobrecarga, não 429. Ambos os casos de modelo/limite impedem reconexão automática em loop.

Testes: `tests/test_claude_models.py`, `tests/test_claude_sessions.py`,
`node --test scripts/engine/ui/tests/claude-errors.test.mjs` e
`tests/claude-sessions.browser.mjs` com WebSockets fictícios.

Cada conversa tem a URL `/#claude/<UUID>`. **Copiar link**, no cabeçalho ou na lista
**Sessões**, permite referenciá-la separadamente. O título da conversa na lista também
é um link que pode ser aberto em outra aba. O link exige o login normal do console;
contém apenas a referência da conversa, sem credenciais de autenticação.

Abrir **Claude Code** (`/#claude`) retoma a última conversa selecionada nesse navegador.
Somente o UUID fica em `localStorage` (`netops_claude_last_session`); mensagens continuam
nos transcripts do Claude Code no servidor. Sem preferência salva, ou após a exclusão da
conversa preferida, abre a mais recente do projeto. Sem conversas, inicia uma nova.
Um link explícito tem prioridade sobre a preferência. **Nova sessão** (`/#claude/new`)
continua abrindo uma conversa vazia e recebe seu UUID quando o agente o informar.

Recarregar, voltar/avançar e alternar entre o dock e a página cheia preservam a referência
selecionada. Cada aba mantém sua própria conversa; alterar a última seleção salva não
troca automaticamente a conversa nas outras abas. Com persistência ligada, abrir a mesma
conversa em outra aba transfere o socket para ela; a anterior informa a transferência e
para de reconectar. Para retomá-la na aba anterior, recarregue.

O lookup `GET /api/claude/sessions/<UUID>` verifica a existência no projeto, inclusive para
conversas mais antigas que a lista recente. Links inválidos/removidos mostram orientação
para escolher outra conversa ou criar uma nova. UUIDs inválidos ou ausentes são recusados
antes de iniciar o agente. Respostas HTTP e eventos de sockets antigos não podem substituir
a conversa selecionada; o histórico é carregado antes de iniciar o streaming.

Testes: `node --test scripts/engine/ui/tests/*.test.mjs`, `tests/test_claude_sessions.py`
e `tests/claude-sessions.browser.mjs`. O cenário de navegador usa APIs e WebSockets
fictícios, em console temporário; não inicia o agente real nem acessa conversas pessoais.


## Enviar mensagem com o agente trabalhando (agora × fila)

Com um turno em andamento, a caixa de mensagem continua aceitando texto. Ao enviar (Enter ou ↑),
a aba **pergunta** o que fazer:

- **Enviar agora** (Enter ou `A`): vai direto ao agente, que **incorpora no turno atual** e leva
  em conta no que está fazendo (comportamento nativo do CLI, medido: ele responde aos dois textos
  num único `result`). A bolha leva a etiqueta "durante a execução".
- **Colocar na fila** (`F`): a mensagem fica na **fila do servidor** e só vira turno quando a
  tarefa atual **terminar por completo** (`ResultMessage`). Vários itens rodam em ordem, um turno
  cada. A fila aparece acima da caixa: arraste pela alça ⠿ para reordenar (mouse ou toque; com a alça focada, ↑/↓ do teclado; o de cima é o próximo), ⚡ manda um item já, × tira da fila. A bolha leva a etiqueta "da fila".
- **Cancelar** (Esc): volta a editar sem interromper o agente.

Regras: a fila é **por sessão** e vive no servidor (`ClaudeWebSession._queue`, teto `MAX_QUEUE`=20).
Com a persistência (padrão no `start.sh`; `NETOPS_UI_CLAUDE_PERSIST=0` desliga), ela **continua andando com a aba fechada** e o estado volta no
re-anexo. Em modo clássico, ela morre junto com o socket. **Interromper** ou um turno com **erro** não
dispara a fila sozinha: os textos voltam para a caixa (`queue_restored`) para você decidir o que fazer,
inclusive quando a aba estava fechada nesse momento. Protocolo: `prompt{queue:bool}`, `queue_remove`,
`queue_send_now`, `queue_move{id,to}`, `queue_add{texts}` → `queue`, `queue_dispatched`, `queue_restored` (ver docstring de `services/claude_svc.py`).
Se o turno termina entre a escolha "fila" e a chegada ao servidor, a mensagem roda na hora.

**A fila sobrevive ao F5 mesmo se o servidor a perder.** A aba espelha a fila no `localStorage`
(`cc-queue:<UUID da conversa>`, só o texto, validade de 24 h). Quando o servidor abre uma sessão
**nova** para o socket (`queue` com `fresh:true`: reinício do console, modo clássico), a aba devolve o
cache com `queue_add`. Os itens voltam para a fila **sem disparar** e rodam no fim do próximo turno ou
via ⚡. No **re-anexo**, o servidor é a verdade: o que sumiu foi executado de fato, e reenviar duplicaria.
antigo. O servidor caía calado no modo clássico e o F5 matava a sessão, levando o turno e a fila. Agora a
reconexão renova o `attach-ticket` antes de abrir o socket.

Testes: `tests/test_claude_queue.py` (pytest, client/WebSocket fictícios) e
`tests/claude-queue.browser.mjs` (Playwright, desktop + celular, WebSocket fictício).

### Retomada automática após restart do console

Reiniciar o console mata o subprocesso `claude` no meio do turno. Para o turno voltar **sem mensagem
manual**, toda sessão persistente com turno rodando (ou fila) é anotada em `runs/claude/resume-on-restart.json`
a cada início/fim de turno e mudança de fila (vale até para `kill -9`). O `shutdown_all` **não** apaga a
anotação; `bye`/carência apagam. No startup (`app.py` → `claude_svc.resume_after_restart`, 3 s depois; 12 s
pós-atualização) cada sessão anotada como `busy` é relançada com `resume=<sid>`, recebe o `RESUME_PROMPT`
(confira o estado antes de repetir ação; se foi você que reiniciou, só valide o HTTP) e a fila volta a rodar
depois. A aba re-anexa ao reconectar (backoff 3 s) e relê o transcript. Se a aba reconectar **antes**, a
sessão nova já fica em `_LIVE` desde a criação e a retomada injeta o prompt nela, sem um segundo `claude`.
Limites estáticos: anotação com mais de 30 min é ignorada; até 2 retomadas seguidas sem prompt humano
(anti-loop); respeita `claude_max_sessions`. Kill-switch: `NETOPS_UI_CLAUDE_AUTORESUME=0`.
Testes: `tests/test_claude_autoresume.py`.

## Mapas de rede

### Identidade inteira dos hosts

`hosts.yaml` v2 contém uma lista de registros com `id` inteiro positivo, `next_host_id`
persistente e aliases antigos reservados. O campo não é editável. Inventário v1 continua
legível; o início/atualização em modo de escrita converte o legado antes de liberar as
operações. `--read-only` não migra. Referências inválidas bloqueiam a conversão sem apagar
ligações; conferência e recuperação manual em `scripts/engine/lib/SKILL.md`.

O contrato dos mapas também é v2: `hosts` no snapshot é uma lista com IDs inteiros,
`members` e `host_ids` são listas de inteiros, `positions` é uma lista de
`{host_id, x, y, z_index?}`. Pontas visuais usam `{kind: host, host_id: 42}` ou
`{kind: object, object_id: forma-a}`. Enlaces mantêm `a.host`/`b.host` como inteiros.
O helper `static/js/host-identity.js` adapta somente a visão do editor para seus nós
textuais `host:42`; todas as gravações retornam o formato numérico canônico.

Backups usam configuração v3, `targets.hosts` com inteiros e `legacy_sources` para
associar pastas antigas sem reescrever o histórico. Novas coletas ficam em
`backups/by-id/<id>/`, separadas de pastas legadas numéricas. O runner delega a coleta
ao script de acesso; ele não lê nem descriptografa credenciais por conta própria.
Gravações do console e o migrador compartilham a trava de inventário; migração
interrompida bloqueia o uso até a recuperação pelo launcher ou pelo comando manual,
sem misturar versões.

A página **Mapas** integra o editor React Flow ao cadastro de **Hosts** e aos enlaces de
`network/topology.yaml`. A antiga página `/#topology` e seu módulo exclusivo foram removidos;
links antigos abrem Mapas. As APIs de enlaces são compartilhadas pelo editor e permanecem.
Não é a demo temporária e não usa localStorage como banco de rede.

- A tela mantém uma única linha com seletor de mapa, novo mapa e exportação. Sem título
  duplicado, barra de ferramentas extensa ou rodapé permanente.
- Botão direito no fundo: adicionar host, incluir existente, ligar dispositivos, textos,
  formas, referência entre mapas, renomear/excluir mapa adicional e enquadrar. Novo mapa
  e exportação ficam somente na barra superior; a velocidade é editada no cadastro do enlace.
- Botão direito no host/objeto: editar, iniciar ligação e remover a associação visual quando
  permitido. No enlace: dobras, linha reta, posição automática, edição e exclusão.
- No celular, selecionar um item e tocar em **⋯** abre as mesmas ações. Sem item selecionado,
  **⋯** abre as ações do fundo. Pelo teclado: **Shift+F10**, setas e **Escape**.
- Estado de salvamento continua anunciado para leitores de tela. Falha ou conflito abre
  aviso acionável somente quando necessário, sem ocupar uma barra permanente.
- Criou um host no mapa: aparece imediatamente em Hosts.
- Criou pela lista: aparece no mapa geral e no mapa de sua localidade (`site`, com herança).
  Quando todos os hosts estão na mesma localidade, existe apenas **Rede geral**, sem uma
  segunda visão automática idêntica. Mapas adicionais criados pelo operador são preservados.
- Mapas adicionais reutilizam hosts existentes; o cadastro de host também oferece associação
  a um mapa adicional. Posição, notas, formas e referências ficam em `network/maps.yaml`.
- “Ligar hosts” abre o cadastro de portas A/B. As ligações reais ficam em `topology.yaml`.
- Vários enlaces da mesma dupla mantêm linhas independentes, inclusive no sentido inverso.
- “+ Dobra” acrescenta um canto de 90 graus por clique; A/B saem perpendicularmente às bordas.
  Com hosts alinhados, desloque um deles para formar um L. Os quatro pontos do host ficam ocultos.
- O mapa geral não permite ocultar host. Mapas adicionais permitem “Remover do mapa”, sem
  excluir do inventário. Excluir o host é confirmado e remove todos os enlaces físicos com
  o host em A ou B e as ligações visuais com ele na origem ou no destino, em todos os mapas,
  além de membros, posições e rotas afetadas. Os demais hosts, formas e ligações permanecem.
- Dados são compartilhados entre computador e celular, com atualização ao voltar à janela e
  consulta periódica enquanto não houver edição em andamento. Respostas atrasadas não
  sobrescrevem o arraste atual; autosave mantém as dimensões e a visibilidade dos nós.
- Revisão divergente retorna 409 e exibe “Conflito de versão”. Recarregar exige confirmação
  para descartar ajustes não salvos. Falha de rede mantém a fila e permite tentar novamente.
- A página respeita o login e o modo `--read-only`. Nunca lê nem descriptografa senhas.

O editor é distribuído como assets locais. O console continua sem build obrigatório na
instalação e funciona offline. Para manutenção do editor, ver `maps/SKILL.md`.

### Rodar com dados fictícios isolados

`NETOPS_UI_DATA_ROOT=/caminho/temporario` aponta os arquivos canônicos de rede e o config
para um diretório de teste. Ele precisa conter `network/hosts.yaml`, `network/topology.yaml`
e `core/config/project-config.yaml`, todos fictícios. Nunca copiar credenciais reais.
Execute o launcher a partir de uma **cópia completa temporária do código**: mudar somente
`DATA_ROOT` não isola a instalação, a trava do supervisor ou o motor de atualização.

```bash
NETOPS_UI_DATA_ROOT=/tmp/netops-teste NETOPS_UI_HOST=127.0.0.1 NETOPS_UI_PORT=8771 \
  NETOPS_UI_CLAUDE=0 NETOPS_UI_TERMINAL=0 scripts/engine/ui/start.sh
```

O launcher usa `flock` por diretório de dados/endereço e o supervisor tem trava por instalação,
sem matar processos de outro console.
Se já estiver rodando no mesmo endereço, ele informa o conflito. Para reiniciar, encerre a
instância desejada primeiro. Testes não devem operar o inventário real.


### Validação de enlaces

No formulário de enlace da página Mapas (`LinkForm` em `static/js/components.js`),
somente Host A/B são obrigatórios.
Porta A/B são opcionais, tanto na criação quanto na edição; campos vazios não são gravados.
Porta é o nome da interface do equipamento, como `ether2` ou `sfp1`, não uma porta TCP.
O formulário indica hosts ausentes antes de enviar, mantém os valores e destaca a primeira
pendência. A resposta 422 usa `detail` no FastAPI ou `errors` no domínio; `api.js` normaliza
ambos para erros por campo, sem exibir os valores `input` devolvidos pela validação.

Teste isolado: `tests/link-validation.browser.mjs` (mesmas variáveis Playwright/Chromium e
`NETOPS_E2E_URL` dos testes de mapas). Teste do parser: `node --test
scripts/engine/ui/tests/api-errors.test.mjs`.


## Ícones dos dispositivos

O formulário **Novo host** e a edição de host oferecem o seletor **Ícone do host** na página
Hosts e dentro de Mapas. As dez opções são da biblioteca Redes Brasil: roteador, switch,
servidores Linux/Windows, access point, OLT, cloud, PC, Proxmox e VMware.

A escolha é opcional e fica no campo `icon` do host em `network/hosts.yaml`. Todos os mapas
usam a mesma escolha do inventário. **Padrão** remove o campo e mantém o símbolo anterior,
sem reescrever hosts existentes. O backend só aceita IDs disponíveis no catálogo local,
nunca URLs ou caminhos enviados pelo navegador. Falha de carregamento da imagem mantém
um símbolo de fallback no mapa, sem esconder o dispositivo.

Originais e catálogo estão em `static/icons/network/`. As miniaturas de até 128 px usadas
pela UI estão em `static/icons/network/thumbnails/`, sem acesso externo em execução.
Proveniência, commit, checksums e instruções de atualização em `static/icons/network/README.md`.
`vendor_icons.py` é uma ferramenta de manutenção, com Pillow opcional somente nessa etapa.

Testes: `tests/test_host_icons.py` e `tests/host-icons.browser.mjs`, este último executado
somente contra console com `NETOPS_UI_DATA_ROOT` temporário e fixtures.


### Persistência em arquivos de texto

Os dados dos mapas são arquivos YAML UTF-8 no servidor:

- `network/maps.yaml`: mapas, posições, notas, formas, referências, âncoras e dobras dos enlaces.
- `network/hosts.yaml`: dispositivos e escolha de ícone (campo `icon`).
- `network/topology.yaml`: enlaces, hosts de cada ponta, interfaces opcionais, meio e velocidade.

Nada disso depende de localStorage nem de um banco de dados. Reiniciar o servidor ou trocar
computador/celular não apaga os dados. O console relê esses arquivos a cada consulta e salva
com revisão por hash, escrita atômica e backups. Os arquivos reais são git-ignorados por
conterem informações da rede; apenas os modelos `*.example.yaml` são versionados.

A remoção da tela de Topologia não remove seus dados, os serviços usados por Mapas nem o
script `scripts/tools/docs/topology_render.py` para gerar a documentação Mermaid.


## Formas sem IP e alinhamento de grupo

O mesmo **Ligar hosts** aceita hosts, formas e referências entre mapas. Formas representam
equipamentos sem gerência/IP ou elementos visuais, sem cadastro paralelo em Hosts. Também
oferecem **Ligar a outro dispositivo** no botão direito. Texto de anotação não é uma ponta
oferecida pelo fluxo de ligação.

No formulário **Adicionar forma/Editar forma**, o seletor **Ícone da forma** usa a biblioteca
local de rede, com opção **Sem ícone**. O campo `icon` fica no objeto em `maps.yaml`. Host com
host continua criando enlace real; host-forma e forma-forma ficam em `visual_links` do mapa,
com os mesmos controles A/B, dobras, arraste e exclusão. Redimensionar a forma ajusta a ponta
da linha sem perder o ícone. Remover a forma limpa só suas conexões visuais.

Seleção e alinhamento:

- Computador: **Ctrl/Cmd + clique** adiciona/remove dispositivos da seleção; **arraste com
  o botão esquerdo no fundo** seleciona um retângulo, sem modificadores (Shift também
  funciona). O retângulo seleciona itens inteiramente contidos; botão central ou Espaço
  permitem mover o mapa. Clique direito sobre um membro/grupo mantém a
  seleção e oferece **Alinhar horizontalmente** e **Alinhar verticalmente**.
- Celular: no menu **⋯**, escolha **Selecionar vários**, toque nos dispositivos e abra **⋯**
  para alinhar. Cancelar/Escape ou tocar no fundo encerra a seleção temporária.
- O alinhamento forma uma fila/coluna com centros alinhados e **24 unidades de mapa livres
  entre bordas**, considerando os tamanhos dos nós. Hosts e formas podem participar juntos.
- O grupo inteiro é salvo em uma edição, sem mover os outros objetos nem apagar dobras.
  Apenas posições são persistidas; seleção não altera o inventário.
- **Limpar seleção** permite voltar à edição individual. Modo somente leitura não oferece
  alinhamento, alterações de formas ou criação de ligações.

Testes: `tests/test_shape_connections.py`, testes do helper em `maps/node-state.test.mjs` e
`tests/shapes-align.browser.mjs` (mesmas variáveis Playwright/Chromium dos demais cenários,
sempre em `NETOPS_UI_DATA_ROOT` temporário).

`tests/test_host_delete_cascade.py` verifica a exclusão nos YAMLs gravados, em ambas as
pontas e em vários mapas, incluindo preservação dos itens não afetados e conflito 409
sem escrita. `tests/host-delete-cascade.browser.mjs` cobre detalhes, menus, confirmação
de exclusão e persistência em desktop/toque, sempre numa instalação completa fictícia.

### Falha ao salvar ícone de forma após atualizar arquivos

HTTP 422 com `extra_forbidden` em `map/objects/N/icon` indica que o backend ativo ainda
não reconhece o campo de ícone, mesmo que o seletor já apareça na interface. Os arquivos
estáticos são lidos do disco; os modelos Python são carregados ao iniciar o processo.
Uma cópia de arquivos ou `git pull` sem reinício pode misturar as duas versões.

Verifique que o backend e os assets pertencem à mesma versão, encerre a instância correta
e inicie novamente por `scripts/engine/ui/start.sh`. Recarregar apenas o navegador não
resolve um modelo antigo em memória. O reinício pode exigir novo login; registre os ajustes
não salvos antes de sair da página. Não remova o campo `icon` nem relaxe a validação para
contornar o erro. O aviso persistente de salvamento orienta a atualização/reinício sem
descartar a fila; ícone inválido continua sendo tratado como erro de validação comum.


## Reiniciar o console

Use `scripts/engine/ui/start.sh --yes` (o mesmo script que sobe; desacopla, preserva host/flags, espera o lock, valida HTTP, log em `/tmp/netops-restart.log`). Nunca `kill` + `start.sh` manual.

## URLs de navegação (regra)

Todo item aberto e todo filtro do console tem URL própria (`#menu/<id>?filtro=valor`). Regra completa e
checklist em `core/rules/urls-navegacao.md` — leia antes de criar ou alterar qualquer página.

### Teste de URLs (navegador)

`tests/e2e-env.sh up` sobe um console isolado (cópia do código + dados fictícios) em `127.0.0.1:8771`
(`sync` recopia o código; `down` encerra). Depois:
`PLAYWRIGHT_MODULE=... CHROMIUM_EXECUTABLE=... node tests/urls.browser.mjs [menu ...]` (sem args = todos).
Cobre item aberto, deep link (F5), Voltar, id inexistente, filtros na URL e limpeza. Unitário: `tests/route.test.mjs`.

**Exceção 4: Arquivos** (`#files` e painel SFTP do terminal de host). É o mesmo passthrough do humano
que o terminal: ele navega e altera arquivos do servidor (ou do host, pela sessão SSH que ele mesmo abriu)
com as próprias mãos. Ver "Arquivos" em Segurança. Testes: `tests/test_files.py`,
`tests/files-core.test.mjs`, `tests/files.browser.mjs` e o caso `files` de `tests/urls.browser.mjs`.

## Tabelas: DataTable (padrão de todas as listagens)

Todas as tabelas do console usam `DataTable` (`static/js/table.js`; `ResourceTable` é um alias antigo).
São 16 tabelas: hosts, grupos, credenciais, boas práticas, configs, workflows, agentes, relatórios, execuções,
notas da memória, skills, scripts, execuções agendadas e as quatro de backups. É código próprio, sem biblioteca:
o console é Preact+htm, offline e sem build. Uma grade pronta traria o próprio DOM e quebraria as células
Preact, o tema e as URLs.

- **Para o usuário:** redimensionar arrastando a borda (duplo clique ajusta ao conteúdo), mover arrastando o
  cabeçalho (ou ↑↓ no menu), mostrar/ocultar e "Restaurar padrão" no **⚙ Colunas**. O cabeçalho fica fixo no
  topo e a coluna de ações fica fixa à direita.
- **Persistência:** `localStorage["netops.table.<tableId>"]` = `{order, vis, widths}`, por navegador. A ordenação
  fica na URL quando a tabela usa `urlSort`.
- **Regra para telas novas:** `core/rules/tabelas-console.md` (sem `<table>` cru, `tableId` único, `sort` nas colunas).
- **Testes:** `node --test tests/table-core.test.mjs` (núcleo puro + guarda do padrão), `tests/tables-all.browser.mjs`
  (smoke em todas as telas) e `tests/table-columns.browser.mjs` (interações, desktop e celular), contra `tests/e2e-env.sh up`.
