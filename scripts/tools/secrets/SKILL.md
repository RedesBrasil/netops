---
id: secrets-run
name: Segredos do Cofre de senhas em variáveis de ambiente (nvault)
type: script
runtime: python
description: Roda um comando com chaves/senhas do Cofre de senhas injetadas só no ambiente do processo, sem gravar em arquivo e com a saída mascarada.
env: []
---

## O que faz

O script resolve referências `nvault://<item>/<campo>` para o valor guardado no **Cofre de senhas**
(console **Inventário → Cofre de senhas**, `network/vault.yaml`). Os valores vão **só para o ambiente do
processo filho**. Qualquer segredo que apareça na saída (stdout/stderr) é trocado por `***`.

Assim, `.env`, `wrangler.toml`, scripts e a IA usam a chave **sem que o valor fique em disco nem apareça na
conversa**. Exige o **cofre destrancado**. Cada uso entra na Auditoria do console, com a ação `vault.run`.

- **Referência inteira:** `API_KEY=nvault://coolify-producao/api-key`.
- **Referência embutida:** `DATABASE_URL=postgres://app:{{nvault://banco-app/senha}}@db:5432/app`.
- **Item e campo:** o item é o ID que aparece na URL do console (`#vault/<id>`). O campo é o nome dele em
  slug: "API key" vira `api-key`, "Usuário" vira `usuario`. A tela de cada item mostra a referência pronta, com
  o botão **copiar referência**, e `list` imprime todas. Na aba Claude, o usuário pode mencionar o item com
  `#senha:<id>`; a mensagem chega com o bloco "[NetOps — menções]" listando as referências do item.

## Quando usar

Use sempre que um comando, sistema ou API precisar de uma chave do Cofre de senhas: Cloudflare/Wrangler, API
do Coolify, `.env` de uma aplicação, `curl` autenticado.

**A IA nunca lê o valor**: nada de `cat network/vault.yaml`, nem o endpoint `/reveal`, nem decifrar à mão. Ela
monta o comando com a referência e roda pelo `nvault`.

- **Tarefa agendada NÃO usa** o `nvault`, porque o cofre fica trancado sem um humano por perto.
- **Mascaramento:** cobre vazamento acidental (log, erro, `env`). Ele não esconde o valor transformado
  (base64, invertido etc.). Nunca transforme nem envie o segredo para outro lugar que não o serviço dele.

## Como usar

```bash
nvault run [--env-file F] [--no-dotenv] [--set VAR=REF] [--item ID --prefix P_] -- <comando> [args]
nvault list                      # itens e referências (nunca mostra valores)
nvault check [--env-file F]      # confere as referências do .env (não decifra)
```

`nvault` é o atalho de `python3 scripts/tools/secrets/run.py`, instalado em `~/.local/bin/nvault`.
Na falta do atalho, use o caminho completo ou instale com
`ln -sf /opt/netops/scripts/tools/secrets/nvault ~/.local/bin/nvault`.

| Argumento | Descrição |
|-----------|-----------|
| `--env-file F` | `.env` com referências (repetível). Sem ele, lê o `./.env` se existir. |
| `--no-dotenv` | Não lê o `./.env`. |
| `--set VAR=REF` | Define uma variável a partir de `nvault://item/campo`; aceita o atalho `item/campo`. |
| `--item ID` | Exporta todos os campos do item ("API key" vira `API_KEY`). Use com `--prefix COOLIFY_`. |

Códigos de saída: o do comando. `2` = referência inválida, `3` = cofre trancado (o comando **não** roda),
`4` = usuário do console sem a permissão `vault.use`.

## Setup

Sem dependências novas. A permissão `vault.use` vale para quem pede pela aba Claude e pelo terminal do console
(`NETOPS_USER`); o admin já tem.

## Exemplos

```bash
# Cloudflare Workers (Wrangler lê CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID do ambiente)
# .env do projeto:  CLOUDFLARE_API_TOKEN=nvault://cloudflare-workers/api-key
#                   CLOUDFLARE_ACCOUNT_ID=nvault://cloudflare-workers/account-id
cd /opt/projetos/meu-worker && nvault run -- npx wrangler deploy

# Secret do próprio Worker (o valor fica guardado na Cloudflare)
nvault run --set V=cloudflare-workers/webhook-secret -- sh -c 'printf %s "$V" | npx wrangler secret put WEBHOOK_SECRET'

# API do Coolify
nvault run --no-dotenv --item coolify-producao --prefix COOLIFY_ -- \
  sh -c 'curl -s -H "Authorization: Bearer $COOLIFY_API_KEY" "$COOLIFY_URL/api/v1/applications"'

# Aplicação com .env cheio de referências
nvault check --env-file app/.env && nvault run --env-file app/.env -- npm start
```
