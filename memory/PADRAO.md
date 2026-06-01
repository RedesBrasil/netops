# PADRÃO — `memory/`

A memória do NetOps. É o que faz o framework ser um **projeto vivo**: cada execução aprende
algo e registra aqui, para a próxima execução ser melhor.

## Arquivos

| Arquivo | O que é | Quem escreve |
|---------|---------|--------------|
| `MEMORY.md` | Fatos curados sobre esta rede (~800 tokens) | `documenter` |
| `USER.md` | Preferências do usuário | `documenter` (e o usuário) |
| `learned-patterns.yaml` | Padrões consolidados (3+ ocorrências) | `documenter` |
| `lessons/*.yaml` | Uma lição por arquivo, append-only | `documenter` |

## Como funciona

Resumido — o protocolo completo está em `core/rules/memory-protocol.md`:

1. **Injeção** — no início do workflow, o `coordinator` injeta a memória relevante no contexto.
2. **Reflexão** — no fim do workflow, o `documenter` registra lições em `lessons/`.
3. **Consolidação** — padrões recorrentes sobem para `learned-patterns.yaml`; conhecimento
   permanente é promovido para `best-practices/` e `config-examples/`.
4. **Curadoria** — lições antigas viram `stale`/`archived`, nunca são apagadas.

## Formato de uma lição

Ver `lessons/_TEMPLATE.yaml`. Campos: `id`, `tipo`, `vendor`, `gatilho`, `licao`,
`correcao`, `ocorrencias`, `estado`, `data`.

## Importante

Os arquivos de memória **não contêm credenciais nem IPs sensíveis** — guardam quirks,
padrões e fatos. Credenciais ficam só em `network/credentials.yaml` (git-ignorado).
