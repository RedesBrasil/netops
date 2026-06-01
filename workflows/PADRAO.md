# PADRÃO — `workflows/`

Um workflow é um pipeline YAML que orquestra os agentes para resolver um tipo de pedido.
O `coordinator` escolhe o workflow e executa os `steps` na ordem.

## Formato

```yaml
workflow:
  id: identificador
  name: Nome legível
  description: O que resolve.
  triggers: [frases/comandos que disparam este workflow]
  steps:
    - id: "01"
      name: Nome do passo
      type: subagent | inline | checkpoint
      agent: planner | executor | tester | documenter | coordinator
      inputFiles: [arquivos lidos]
      outputFiles: [arquivos gerados]
      instructions: O que fazer neste passo.
      qualityCriteria: Como saber se o passo ficou bom.
      vetoConditions: [condições que abortam o passo]
```

## Tipos de passo

- `inline` — o `coordinator` executa direto (decisões rápidas, carregar contexto).
- `subagent` — delega a um agente especializado, com handoff.
- `checkpoint` — pausa e mostra opções ao usuário antes de continuar.

## Regra

Todo workflow termina com um passo de **reflexão** (`documenter`) que registra lições em
`memory/` — é o que mantém o projeto vivo (ver `core/rules/memory-protocol.md`).

## Como criar

Copie `_TEMPLATE.workflow.yaml`, defina os steps, e adicione um exemplo de planejamento
correspondente em `planning-examples/`.
