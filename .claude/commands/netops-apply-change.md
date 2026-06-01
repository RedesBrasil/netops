---
description: Planeja e aplica uma mudança de configuração (workflow apply-config-change)
argument-hint: "<descrição da mudança e host-alvo>"
---

Você está operando o framework NetOps. Leia `CLAUDE.md` na raiz para o contexto completo.

Execute o workflow `workflows/apply-config-change.workflow.yaml` como o agente `coordinator`.

Mudança pedida: $ARGUMENTS

Siga os passos do workflow: entender a mudança → capturar baseline → desenhar a config
proposta + rollback → revisão técnica → aplicar → verificar → registrar → reflexão.
Respeite `core/rules/connection-safety.md`: sempre baseline + rollback, rollback automático
em falha. Adote a persona de cada agente (`agents/*.agent.md`) em cada passo.
