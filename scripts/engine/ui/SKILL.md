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
atualizadas. Os segmentos continuam nos arquivos canônicos e na API; lições não se
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


## Mapas de rede

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
  excluir do inventário. Excluir em Hosts é confirmado e limpa os enlaces/referências afetados.
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

```bash
NETOPS_UI_DATA_ROOT=/tmp/netops-teste NETOPS_UI_HOST=127.0.0.1 NETOPS_UI_PORT=8771 \
  NETOPS_UI_CLAUDE=0 NETOPS_UI_TERMINAL=0 scripts/engine/ui/start.sh
```

O launcher usa `flock` por diretório de dados/endereço, sem matar processos de outro console.
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

- Computador: **Ctrl/Cmd + clique** adiciona/remove dispositivos da seleção, ou **Shift +
  arraste no fundo** seleciona um retângulo. Clique direito sobre um membro/grupo mantém a
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
