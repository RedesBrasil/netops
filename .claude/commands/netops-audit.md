---
description: Roda a auditoria de segurança da rede (workflow security-audit)
argument-hint: "[host ou grupo opcional; vazio = toda a rede]"
---

Você está operando o framework NetOps. Leia `CLAUDE.md` na raiz para o contexto completo.

Execute o workflow `workflows/security-audit.workflow.yaml` como o agente `coordinator`.

Escopo: $ARGUMENTS (se vazio, audite todos os hosts de `network/hosts.yaml`).

Siga os passos do workflow: definir escopo → planejar a coleta → coletar dos dispositivos →
avaliar segurança → revisar com o usuário → gerar relatório → reflexão. Adote a persona de
cada agente (`agents/*.agent.md`) em cada passo e respeite `constitution.md`.
