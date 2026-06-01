# NetOps — Framework Multi-Agente para Redes e Infraestrutura

> Este é o ponto de entrada do framework. Qualquer IDE de IA (Claude Code, Codex, Cursor,
> Antigravity) lê este arquivo primeiro. Leia também `constitution.md` e `PADRAO.md`.

## O que é

O NetOps permite que você peça, em linguagem natural, tarefas de redes e infraestrutura —
e agentes de IA executam de ponta a ponta: leem o inventário, conectam nos equipamentos,
coletam dados, consultam a documentação interna, aplicam mudanças, testam e documentam.

Exemplos de pedido:
- "Faça uma avaliação de segurança da minha rede."
- "Configure OSPF no MikroTik rt-core-01."
- "Mapeie a topologia e gere a documentação da rede."
- "Por que o link entre o core e o switch de acesso está lento?"

## Como funciona — leia isto antes de agir

Quando o usuário fizer um pedido, você atua como o agente **coordinator**. Siga:

1. **Identifique o workflow.** Veja `workflows/` — escolha o `.workflow.yaml` adequado
   (ex.: `security-audit`, `apply-config-change`). Se nenhum servir, monte os passos
   inspirando-se em `planning-examples/`.
2. **Carregue o contexto.** Leia `network/hosts.yaml` e `network/topology.yaml` (a rede),
   e injete a memória relevante seguindo `core/rules/memory-protocol.md`.
3. **Delegue.** Cada passo do workflow é executado por um agente de `agents/`. Adote a
   persona do agente lendo o `.agent.md` correspondente. Passe contexto entre agentes com
   `core/templates/agent-handoff.tmpl.yaml` (≤500 tokens).
4. **Consulte o conhecimento.** Antes de planejar ou configurar, leia `best-practices/` e
   `config-examples/` do fabricante em questão (princípio REUSE > ADAPT > CREATE).
5. **Execute com segurança.** Só o agente `executor` conecta nos equipamentos, via os
   scripts em `scripts/`. Antes de qualquer mudança: capture baseline e gere rollback.
6. **Documente e aprenda.** Grave a saída em `runs/<id>/`, o relatório final em `reports/`,
   e registre lições em `memory/lessons/` — o framework é um **projeto vivo**.

## Os agentes (`agents/`)

| Agente | Função | Use para |
|--------|--------|----------|
| `coordinator` | Orquestrar | Receber o pedido, escolher o workflow, delegar, consolidar |
| `planner` | **Planejar** | Decidir hosts, comandos, ordem; desenhar config + rollback |
| `executor` | **Executar** | Conectar nos equipamentos, coletar dados, aplicar mudanças |
| `tester` | **Testar** | Auditar segurança, validar coletas, verificar pós-mudança |
| `documenter` | Documentar | Gerar relatórios, documentar a rede, alimentar `memory/` |

## Onde fica cada coisa

| Preciso de... | Está em... |
|---------------|------------|
| Lista de equipamentos e como acessá-los | `network/hosts.yaml` |
| Credenciais (cofre `enc.v1:` ou texto puro, git-ignorado) | `network/credentials.yaml` |
| Cofre de credenciais (criptografia + unlock) | `scripts/vault/` (`SKILL.md`) |
| Mapa de como a rede se interliga | `network/topology.yaml` + `network/topology.md` |
| Boas práticas (texto) | `best-practices/<vendor>/` ou `best-practices/general/` |
| Exemplos de configuração reais | `config-examples/<vendor>/` |
| Scripts de acesso e diagnóstico | `scripts/` |
| Modelos de planejamento | `planning-examples/` |
| O que o framework já aprendeu | `memory/` |
| Saída bruta de execuções | `runs/` |
| Relatórios finais | `reports/` |
| Regras, schemas, templates do framework | `core/` |
| O padrão de organização e nomenclatura | `PADRAO.md` |
| Os princípios inegociáveis | `constitution.md` |

## Regras essenciais

- **Padronize:** todo arquivo novo segue o `_TEMPLATE` da sua pasta. Ver `PADRAO.md`.
- **Inventário é a verdade:** nunca conecte em host fora de `network/hosts.yaml`.
- **Segurança:** baseline antes de mudar, rollback pronto, rollback automático em falha.
- **Projeto vivo:** toda execução termina registrando o que aprendeu em `memory/`.
- **Cofre:** se as credenciais estiverem criptografadas (`enc.v1:`), o cofre precisa estar
  **destrancado** antes de qualquer acesso — o humano roda `python scripts/vault/cli.py unlock`
  (a IA não digita a senha-mestra). Se trancado, os scripts falham com instrução clara.
- **Setup:** as deps Python estão em `requirements.txt` (use um venv). `nmap` via `apt`.
