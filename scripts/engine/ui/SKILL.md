# SKILL — Console Web (CRUD) do NetOps

## O que é

Uma interface web local para **cadastrar e editar** tudo que normalmente se edita à mão nos
arquivos do NetOps: hosts, grupos, credenciais, topologia, memória, boas práticas, exemplos
de config, workflows, agentes e a configuração do projeto. Também **visualiza** (read-only)
relatórios e execuções.

Dá pra **renomear o ID/nome** de hosts, grupos, credenciais e padrões da memória, além de
arquivos de conhecimento/workflows/agentes. O campo de ID/nome é **editável no próprio
formulário de edição** do item (não há botão "Renomear" à parte): ao **Salvar**, se o ID mudou,
o servidor renomeia **com cascade** — renomear um grupo atualiza o campo `group` dos hosts que o
usam; uma credencial atualiza `credential` em hosts/grupos; um host atualiza as pontas de enlace
em `topology.yaml`. Enquanto o campo está alterado, o form mostra **quantas referências** serão
atualizadas. Segmentos da topologia já têm o nome editável no formulário; lições **não** se
renomeiam (append-only, constituição §II).

É uma **ferramenta de operador efêmera** (constituição §VII): *stateless* (cada request lê/
escreve só os arquivos canônicos — sem banco, sem cache, sem segundo cofre), feita para rodar
quando o operador precisa e ser encerrada depois. O framework funciona 100% com ela desligada.

## Como subir

**SEMPRE** pelo script (nunca `python scripts/engine/ui/server.py` direto). Ele liga o terminal web
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
> `--no-vault-unlock/--enable-terminal/--enable-claude/--no-browser`). Use o server.py direto só para depurar.

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
- **Host/Origin checados** em toda a `/api` e nos WebSockets (anti DNS-rebinding e anti CSRF/CSWSH).
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
- **Anti DNS-rebinding:** o header `Host` precisa bater com o IP de bind (senão 403).
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
- **Página Claude Code (`--enable-claude`):** ⚠ dirige um **agente de IA** (via `claude-agent-sdk`)
  que **executa comandos e edita arquivos** como o usuário do servidor, com `cwd=NETOPS_ROOT` e
  herdando `CLAUDE.md`/skills/agentes. Mesma postura do terminal: DESLIGADA por padrão no server.py
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

## Testes

```bash
.venv/bin/python3 -m pytest scripts/engine/ui/tests/ -q
```

Os testes rodam num diretório temporário isolado — **nunca** tocam nos arquivos reais.
