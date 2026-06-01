# PADRÃO — `agents/`

Cada agente é um arquivo `.agent.md` que descreve **um papel** com **uma função principal**.
Quando um workflow delega um passo a um agente, a IDE adota a persona daquele arquivo.

## Os 5 agentes

| Arquivo | Função principal | Papel |
|---------|------------------|-------|
| `coordinator.agent.md` | orquestrar | Recebe o pedido, escolhe o workflow, delega, consolida |
| `planner.agent.md` | **planejar** | Decide hosts, comandos, ordem; desenha config + rollback |
| `executor.agent.md` | **executar** | Único que conecta nos equipamentos; coleta e aplica |
| `tester.agent.md` | **testar** | Audita segurança, valida coletas, verifica pós-mudança |
| `documenter.agent.md` | documentar | Gera relatórios, documenta a rede, alimenta `memory/` |

## Formato `.agent.md` (8 seções obrigatórias)

Front-matter YAML + 8 seções, nesta ordem:

```
---
id:        slug-do-agente
name:      Nome
icon:      emoji
function:  planejar | executar | testar | orquestrar | documentar
scope:     uma linha resumindo o que o agente faz
---

## Persona              — quem é o agente, sua mentalidade
## Princípios           — regras inegociáveis do agente
## Modo de Operação     — passo a passo de como trabalha; quais scripts/pastas usa
## Tom de Voz           — como se comunica (PT-BR, técnico, conciso)
## Exemplos de Saída    — exemplos concretos do que produz
## Anti-Padrões         — o que o agente NUNCA faz
## Critérios de Qualidade — como saber se o trabalho ficou bom
## Integração           — autoridade, de/para quais agentes faz handoff, arquivos que toca
```

## Como criar um agente novo

Copie `_TEMPLATE.agent.md`, preencha as 8 seções, e registre-o aqui na tabela.
Mantenha **uma função principal por agente** (princípio YAGNI do OpenSquad).
