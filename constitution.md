# Constituição do NetOps

> **Versão:** 1.0.2 | **Ratificada:** 2026-05-18 | **Revisado:** 2026-06-01 (§VII: terminal web opt-in)

Este documento define os princípios inegociáveis do NetOps. Todos os agentes, workflows e
scripts DEVEM respeitá-los. Adaptado da `constitution.md` do AIOX para o domínio de redes e
infraestrutura.

---

## Princípios Fundamentais

### I. Padronização Acima de Tudo (INEGOCIÁVEL)

Tudo no framework segue o `PADRAO.md`. Consistência é o que permite que o agente de IA
sempre saiba onde procurar e onde gravar.

- **DEVE:** Todo arquivo novo segue o template (`_TEMPLATE`) da sua pasta.
- **DEVE:** Nomes de pastas/arquivos técnicos em inglês; conteúdo de documentação em português.
- **DEVE:** Toda pasta de conhecimento tem um `PADRAO.md` e um `_TEMPLATE`.
- **NÃO DEVE:** Criar estruturas fora do padrão sem antes atualizar o `PADRAO.md`.

### II. Projeto Vivo (INEGOCIÁVEL)

Cada execução ensina algo. Esse aprendizado é documentado para que a próxima execução seja
melhor — sem isso, o framework não evolui.

- **DEVE:** Todo workflow termina com um passo de **reflexão** que grava lições em `memory/MEMORY.md`.
- **DEVE:** Erros de conexão, quirks de fabricante e descobertas viram lições registradas.
- **DEVE:** Conhecimento consolidado é promovido para `best-practices/` e `config-examples/`.
- **DEVE:** Lições são bullets datados em `memory/MEMORY.md`, escritos como fato declarativo (não como ordem).

### III. REUSE > ADAPT > CREATE (DEVE)

Antes de gerar qualquer config ou plano do zero, consultar o que já existe.

- **DEVE:** Consultar `best-practices/` e `config-examples/` antes de propor solução.
- **DEVE:** Consultar `memory/MEMORY.md` para quirks já conhecidos.
- **DEVE:** Consultar `planning-examples/` antes de montar um plano novo.
- **PODE:** Criar do zero somente quando nada relevante existir — e então documentar.

### IV. Autoridade de Agente (DEVE)

Cada agente tem uma função principal. Trabalho fora do escopo é delegado.

| Autoridade | Agente exclusivo |
|------------|------------------|
| Orquestrar e delegar | `coordinator` |
| Planejar (decidir o quê/como) | `planner` |
| Conectar em equipamentos | `executor` |
| Validar / auditar / testar | `tester` |
| Documentar e alimentar `memory/` | `documenter` |

- **DEVE:** Apenas o `executor` abre conexão com dispositivos.
- **DEVE:** O `executor` segue o plano — não decide *o que* mudar.

### V. Segurança Operacional (INEGOCIÁVEL)

Mexer em rede de produção pode derrubar serviços. Toda mudança é reversível.

- **DEVE:** Capturar o estado atual (baseline) antes de qualquer mudança de config.
- **DEVE:** Gerar o script de rollback junto com a config proposta.
- **DEVE:** Em falha durante a aplicação, executar o rollback automaticamente.
- **NÃO DEVE:** Conectar em host que não esteja no `network/hosts.yaml`.
- **NÃO DEVE:** Expor credenciais em logs, relatórios ou saídas versionadas.

### VI. Inventário é a Fonte da Verdade (DEVE)

O agente só conhece a rede pelo que está em `network/`.

- **DEVE:** `network/hosts.yaml` lista todo host acessível.
- **DEVE:** `network/topology.yaml` descreve como os hosts se interligam.
- **DEVE:** Credenciais ficam só em `network/credentials.yaml` (git-ignorado).

### VII. Sem Runtime Próprio (DEVE)

A inteligência vive em Markdown/YAML interpretado pela IDE; a execução técnica vive em
scripts Python. Sem banco de dados, sem Docker, sem servidor (princípio do OpenSquad).

- **DEVE:** Estado de execução em arquivos (`runs/<id>/state.json`).
- **DEVE:** Memória em arquivos de texto (`memory/`).
- **PODE:** Existir uma **ferramenta de operador efêmera** — o console web CRUD em
  `scripts/engine/ui/` — desde que: (a) seja *stateless* (cada request lê/escreve só os arquivos
  canônicos; sem cache de estado, sem banco, sem segundo cofre); (b) faça bind em loopback
  por padrão (`127.0.0.1`); (c) o framework funcione 100% com ela desligada (as IDEs de IA
  seguem sendo a interface primária). Ela é uma *ferramenta sobre os arquivos*, no mesmo
  espírito de `scripts/tools/docs/topology_render.py` — **não** é um runtime do framework.
- **NÃO DEVE:** A ferramenta de operador, **por funcionalidade própria de UI** (botões,
  formulários, automações), manter conexão a dispositivo aberta, disparar workflows/mudanças
  que contornem o modelo de `baseline → rollback → veto` (§V), nem devolver segredos em texto
  puro ao navegador.
- **PODE:** Oferecer um **terminal web** (`--enable-terminal`, **DESLIGADO por padrão**) que
  é apenas um *passthrough* para um shell do **humano operador** — equivalente a uma sessão
  SSH na máquina. Isso **não** é o framework/UI operando equipamentos de forma autônoma: é a
  pessoa no teclado. Exigências: opt-in explícito, login com a senha-mestra, nunca em `--read-only`, e
  o framework segue funcionando 100% com ele desligado. O que se digita ali é responsabilidade
  do humano (como em qualquer SSH), fora do automatismo dos agentes.

---

## Governança

- Mudanças nestes princípios exigem atualização de versão e propagação ao `PADRAO.md`.
- **INEGOCIÁVEL:** violação bloqueia a execução. **DEVE:** violação gera alerta.
- Versionamento: MAJOR (redefinição incompatível), MINOR (novo princípio), PATCH (ajuste).

*NetOps Constitution v1.0.1 — Padronizado | Projeto Vivo | Seguro*
