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
   e registre lições em `memory/MEMORY.md` — o framework é um **projeto vivo**.

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
| Cofre de credenciais (criptografia + unlock) | `scripts/engine/vault/` (`SKILL.md`) |
| Mapa de como a rede se interliga | `network/topology.yaml` + `network/topology.md` |
| Boas práticas (texto) | `best-practices/<vendor>/` ou `best-practices/general/` |
| Exemplos de configuração reais | `config-examples/<vendor>/` |
| Scripts operacionais (acesso, diagnóstico, análise) | `scripts/tools/<familia>/` |
| Motor do NetOps (lib, cofre, console web) | `scripts/engine/` |
| Subir o console web (SEMPRE por aqui) | `scripts/engine/ui/start.sh` |
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
- **Memória é VINCULANTE (INEGOCIÁVEL):** no início de cada sessão, leia `memory/MEMORY.md` e as notas
  relevantes; trate toda regra marcada como "nunca rode"/INEGOCIÁVEL como **bloqueio** — não é sugestão.
  Bloqueio ativo (também reforçado por hook em `.claude/settings.json` → `.claude/hooks/guard-netops.sh`):
  **NUNCA rode `unl_wrapper -a fixpermissions`** — ele zera o `+x` do `first_login.sh` e derruba todos os
  nós de aluno nos 4 hosts (ver `memory/eve-ng-firstlogin-execbit.md`). Se um workflow o exigir, reaplique
  `chmod 755 /opt/unetlab/local-scripts/first_login.sh` no lab-250 logo depois e valide.
- **Cofre:** se as credenciais estiverem criptografadas (`enc.v1:`), o cofre precisa estar
  **destrancado** antes de qualquer acesso — o humano roda `python scripts/engine/vault/cli.py unlock`
  (a IA não digita a senha-mestra). Se trancado, os scripts falham com instrução clara.
- **Segredos (INEGOCIÁVEL):** a IA **nunca** lê, descriptografa, imprime ou copia o valor de
  `password`/`secret` — nem com o cofre destrancado, nem "por transparência". Para acessar um
  equipamento, invoque os scripts de `scripts/tools/access/` com `--host <nome>` (eles resolvem a
  credencial internamente); nunca chame `resolve_host(decrypt=True)`/`resolve_secret`/`decrypt_value`.
  Ver `constitution.md` §V e `core/rules/connection-safety.md`.
- **Setup:** as deps Python estão em `requirements.txt` (use um venv). `nmap` via `apt`.
- **Console web:** para subir a interface web, rode **SEMPRE** `scripts/engine/ui/start.sh` — **nunca**
  `python scripts/engine/ui/server.py` direto. O script liga o **terminal web** e a **página Claude Code**
  por padrão (são opt-in — sem o script as abas somem), injeta o `claude` no PATH e faz bind no IP da
  máquina, garantindo uma instância só. Variáveis: `NETOPS_UI_HOST`, `NETOPS_UI_PORT`, `NETOPS_UI_TERMINAL=0`,
  `NETOPS_UI_CLAUDE=0`. O acesso é protegido pelo **login com a senha-mestra** (sem token na URL). Se uma aba
  nova não aparecer após atualizar, é cache do navegador: **hard refresh** (`Ctrl+Shift+R`). Ver `scripts/engine/ui/SKILL.md`.
