# SKILL — Console Web (CRUD) do NetOps

## O que é

Uma interface web local para **cadastrar e editar** tudo que normalmente se edita à mão nos
arquivos do NetOps: hosts, grupos, credenciais, topologia, memória, boas práticas, exemplos
de config, workflows, agentes e a configuração do projeto. Também **visualiza** (read-only)
relatórios e execuções.

É uma **ferramenta de operador efêmera** (constituição §VII): *stateless* (cada request lê/
escreve só os arquivos canônicos — sem banco, sem cache, sem segundo cofre), feita para rodar
quando o operador precisa e ser encerrada depois. O framework funciona 100% com ela desligada.

## Como subir

**SEMPRE** pelo script (nunca `python scripts/ui/server.py` direto). Ele fixa o token (a URL não
muda entre reinícios), liga o terminal web e faz bind no IP da máquina, com instância única:

```bash
scripts/ui/start.sh                          # IP da máquina, porta 8765, terminal ON
NETOPS_UI_HOST=127.0.0.1 scripts/ui/start.sh # força loopback (só local)
NETOPS_UI_PORT=9000      scripts/ui/start.sh # outra porta
NETOPS_UI_TERMINAL=0     scripts/ui/start.sh # sobe SEM o terminal web
scripts/ui/start.sh --read-only --no-vault-unlock   # flags extras viram passthrough
```

O script imprime a URL **já com o token de sessão** (`http://<ip>:<porta>/?token=<...>`); sem o
token a API responde **401**. O token persiste em `scripts/ui/.ui-token` (0600, git-ignorado).

> Por baixo o script chama `scripts/ui/server.py` (flags: `--host/--port/--token/--read-only/`
> `--no-vault-unlock/--enable-terminal/--no-browser`). Use o server.py direto só para depurar.

## Setup inicial (uma vez, com internet)

As dependências do frontend são **vendadas localmente** (offline/air-gap-safe):

```bash
bash scripts/ui/vendor_deps.sh     # baixa preact/htm/marked/js-yaml/xterm p/ static/vendor/
.venv/bin/pip install -r requirements.txt   # fastapi + uvicorn + ruamel.yaml + websockets
```

> `websockets` é necessário para o terminal web (uvicorn faz o upgrade WS); sem ele o
> `/api/term` responde 404.

## Segurança (resumo)

- **Bind em loopback por padrão.** `--host <ip-privado>` expõe na rede e imprime um AVISO;
  use só em rede confiável e via token. `0.0.0.0` é recusado.
- **Token de sessão** obrigatório em toda a `/api` (header `Authorization: Bearer` ou `?token=`).
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
  validação de schema antes de gravar host/grupo.
- **Terminal web (`--enable-terminal`):** ⚠ é um **shell real** (PTY) na máquina = execução de
  comando arbitrário como o usuário do servidor. **DESLIGADO por padrão**, nunca liga em
  `--read-only`. O handshake do WebSocket (`/api/term`) é autenticado **à mão** (token + Host +
  Origin) porque o middleware http do app **não** cobre WebSocket. Sobre HTTP não-loopback, o
  token (na URL) trafega em texto puro e dá shell completo — prefira túnel SSH/VPN.

## Fronteira (o que a UI NÃO faz)

Pelo modelo de segurança (§IV/§V), a UI — **por funcionalidade de UI** (botões/formulários) —
**não conecta em equipamentos** nem dispara workflows/mudanças. Coletar, aplicar config,
baseline/rollback continuam sendo do agente `executor` via IDE de IA. A parte CRUD é só
arquivos + visualização.

**Exceção: o terminal web** (`--enable-terminal`, opt-in) é um *passthrough* para um shell do
**humano** — equivalente a um SSH. Não é o framework operando sozinho; é a pessoa no teclado, e o
que ela digita é responsabilidade dela (constituição §VII). Serve, p.ex., para rodar `claude` ou
os `scripts/access/*.py` e acompanhar a execução pelo navegador.

## Estrutura

```
scripts/ui/
  server.py            entrypoint (bind, token, browser)
  app.py               FastAPI (middleware de segurança + handlers + StaticFiles)
  deps.py              caminhos canônicos + estado + exceções de domínio
  models.py            modelos Pydantic (validação de entrada)
  routers/             um router por recurso (hosts, credentials, ..., terminal=WS PTY)
  services/            lógica de I/O: yaml_io (round-trip/atomic/concorrência), *_svc
  static/              SPA Preact (sem build): index.html + js/ (+ pages/terminal.js) + vendor/ (xterm.js, ...)
  tests/               pytest E2E (cofre, concorrência, mascaramento, append-only, terminal WS, ...)
```

## Testes

```bash
.venv/bin/python3 -m pytest scripts/ui/tests/ -q
```

Os testes rodam num diretório temporário isolado — **nunca** tocam nos arquivos reais.
