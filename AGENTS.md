# NetOps — Framework Multi-Agente para Redes e Infraestrutura

> Este é o ponto de entrada do framework. Qualquer IDE de IA (Claude Code, Codex, Cursor,
> Antigravity) lê este arquivo primeiro (padrão AGENTS.md; não existe mais CLAUDE.md). Leia também `constitution.md` e `PADRAO.md`.

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

- **Releases:** antes de gerar qualquer release, leia `core/rules/releases.md`, consulte a release
  atual no GitHub e escolha uma versão superior. Atualize `core/config/core-config.yaml` e
  `CHANGELOG.md`, teste o pacote e publique com changelog. Nunca reutilize tags nem inclua dados locais.
  O atualizador preserva dados e personalizações; testes de aplicação exigem uma instalação completa
  temporária, não apenas `NETOPS_UI_DATA_ROOT`. Ver `scripts/engine/update/SKILL.md`.

- **URLs de navegação (regra de desenvolvimento do console):** todo menu, **todo item aberto** (host A →
  `#hosts/<id-a>`, host B → `#hosts/<id-b>`) e **todo filtro/busca/ordenação** (`#hosts?vendor=x&q=y`) deve ter
  URL própria, com deep link e Voltar funcionando. Leia `core/rules/urls-navegacao.md` antes de criar/alterar
  qualquer tela em `scripts/engine/ui/`.

- **Padronize:** todo arquivo novo segue o `_TEMPLATE` da sua pasta. Ver `PADRAO.md`.
- **Inventário é a verdade:** nunca conecte em host fora de `network/hosts.yaml`.
- **Segurança:** baseline antes de mudar, rollback pronto, rollback automático em falha.
- **Projeto vivo:** toda execução termina registrando o que aprendeu em `memory/`.
- **Memória é VINCULANTE (INEGOCIÁVEL):** no início de cada sessão, leia `memory/MEMORY.md` e as notas
  relevantes; trate toda regra marcada como "nunca rode"/INEGOCIÁVEL como **bloqueio** — não é sugestão.
  Bloqueio ativo (também reforçado por hook em `.claude/settings.json` → `.claude/hooks/guard-netops.sh`):
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
- **Reiniciar o console (INEGOCIÁVEL):** quando pedirem para reiniciar o NetOps/console web, rode **SEMPRE**
  `scripts/engine/restart-console.sh` — **nunca** `kill` + `start.sh` à mão nem `systemd-run` improvisado. O script
  captura host/porta/flags atuais, se desacopla (funciona de dentro da aba Claude), espera o supervisor sair e o
  lock liberar, sobe com tentativas e só termina OK quando o HTTP responde (log: `/tmp/netops-restart.log`).
  ainda segurava o flock, `start.sh` recusou e o console ficou fora até subir à mão.
- **Console NUNCA pode ficar parado (INEGOCIÁVEL):** antes de qualquer start/restart ou mudança em `start.sh`/supervisor,
  valide que o console volta (sintaxe, venv, porta) e **nunca** teste contra o ROOT real "em outra porta". Depois,
- **Login do agente na aba Claude Code:** `/login` (e `/logout`) funcionam **na própria aba** — não são do
  SDK, a aba os resolve sozinha e abre o fluxo OAuth. Logue **por ali**, não pelo terminal web: a credencial
  vai para o `$HOME/.claude/` do **processo do servidor**, e o terminal web roda como outro usuário (`netops`),
  ou seja, outro cofre e outra lista de conversas. Ver `scripts/engine/ui/SKILL.md`.
- **Aba Claude Code — persistência e DÚVIDA (LIGADA por padrão no `start.sh`; `NETOPS_UI_CLAUDE_PERSIST=0` desliga):** a sessão sobrevive à queda
  do socket (standby/troca de aba): o turno **termina** mesmo com a aba fechada e você re-anexa ao voltar (a
  resposta é relida do transcript, sem buffer). Como um turno pode executar **sem ninguém olhando**, vale a
  regra de ouro: **na dúvida, PERGUNTE** — use `AskUserQuestion` em vez de assumir, e **nunca** execute ação
  irreversível sem certeza. Pergunta sem resposta expira (timeout) e é tratada como negação ("não faz").
