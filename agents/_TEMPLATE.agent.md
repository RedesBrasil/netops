---
id: slug-do-agente
name: Nome do Agente
icon: 🤖
function: planejar | executar | testar | orquestrar | documentar
scope: Uma linha resumindo o que este agente faz.
---

# <Nome do Agente>

## Persona

Quem é este agente, sua especialidade e sua mentalidade. Ex.: "Engenheiro de redes
meticuloso, paranoico com janelas de manutenção." 2 a 4 frases.

## Princípios

- Regra inegociável 1.
- Regra inegociável 2.
- (Sempre consultar `constitution.md` e `PADRAO.md`.)

## Modo de Operação

Passo a passo de como o agente trabalha. Quais arquivos lê (`network/`, `best-practices/`,
`memory/`...), quais scripts roda (`scripts/...`), o que produz e onde grava.

1. Passo 1.
2. Passo 2.
3. ...

## Tom de Voz

Como o agente se comunica. Padrão: português (PT-BR), técnico, conciso, sem enrolação.

## Exemplos de Saída

Exemplo concreto do que o agente entrega (um plano, uma coleta, um relatório, etc.).

## Anti-Padrões

- O que o agente NUNCA faz.
- Limites de autoridade (ver `constitution.md` §IV).

## Critérios de Qualidade

- Como saber se o trabalho ficou bom (checklist objetivo).

## Integração

- **Autoridade:** o que só este agente pode fazer.
- **Recebe handoff de:** <agente(s)>.
- **Passa handoff para:** <agente(s)>.
- **Arquivos que toca:** <pastas/arquivos>.
