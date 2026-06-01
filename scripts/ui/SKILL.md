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

```bash
cd /home/francisco/netops
.venv/bin/python3 scripts/ui/server.py            # 127.0.0.1, porta livre, abre o navegador
.venv/bin/python3 scripts/ui/server.py --port 8765 --no-browser
.venv/bin/python3 scripts/ui/server.py --read-only            # desliga toda escrita
.venv/bin/python3 scripts/ui/server.py --no-vault-unlock      # cofre só destranca pelo terminal
.venv/bin/python3 scripts/ui/server.py --host 192.0.2.10    # acesso pela rede (ver AVISO)
```

O servidor imprime (e abre) a URL **já com o token de sessão**: `http://127.0.0.1:<porta>/?token=<...>`.
Sem o token, a API responde **401**.

## Setup inicial (uma vez, com internet)

As dependências do frontend são **vendadas localmente** (offline/air-gap-safe):

```bash
bash scripts/ui/vendor_deps.sh     # baixa preact/htm/marked/js-yaml p/ static/vendor/
.venv/bin/pip install -r requirements.txt   # fastapi + uvicorn + ruamel.yaml
```

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

## Fronteira (o que a UI NÃO faz)

Pelo modelo de segurança (§IV/§V), a UI **não conecta em equipamentos** nem dispara workflows/
mudanças. Coletar, aplicar config, baseline/rollback continuam sendo do agente `executor` via
IDE de IA. A UI é só CRUD de arquivos + visualização.

## Estrutura

```
scripts/ui/
  server.py            entrypoint (bind, token, browser)
  app.py               FastAPI (middleware de segurança + handlers + StaticFiles)
  deps.py              caminhos canônicos + estado + exceções de domínio
  models.py            modelos Pydantic (validação de entrada)
  routers/             um router por recurso (hosts, credentials, topology, memory, ...)
  services/            lógica de I/O: yaml_io (round-trip/atomic/concorrência), *_svc
  static/              SPA Preact (sem build): index.html + js/ + vendor/ (ESM vendado)
  tests/               pytest E2E (cofre, concorrência, mascaramento, append-only, ...)
```

## Testes

```bash
.venv/bin/python3 -m pytest scripts/ui/tests/ -q
```

Os testes rodam num diretório temporário isolado — **nunca** tocam nos arquivos reais.
