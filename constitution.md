# Constituição do NetOps

> **Versão:** 1.2.0 | **Ratificada:** 2026-05-18 | **Revisado:** 2026-11-19 (§V: conta operacional `netops` e backend de acesso Local; antes 2026-11-13, §VII: exceção Zabbix no acesso web)

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
- **DEVE:** O NetOps roda como a conta Linux dedicada `netops` (console, IA, subagentes, terminal,
  agendador, atualizador) — nunca como root. Root neste servidor é **por operação**, pelo host Local
  (sem SSH, cofre destrancado, permissão `server.admin`); nunca sudo/grupo administrativo para `netops`,
  nunca serviço ou cron root executando código gravável por `netops`.
- **NÃO DEVE:** Expor credenciais em logs, relatórios ou saídas versionadas.
- **NÃO DEVE:** A IA obter, descriptografar, ler, imprimir ou copiar o valor em texto puro de
  qualquer campo `password`/`secret` — nem "por transparência", nem com o cofre destrancado. A
  descriptografia é **exclusiva** dos scripts de acesso (`scripts/tools/access/*`), no instante de
  conectar, e do backend **Local** (`scripts/engine/localadmin/`, serviço `netops-localadmin`), que usa a
  senha do admin local (`CRED_LOCAL_ADMIN`) só para autenticar o `su` no próprio servidor — a IA o aciona
  pelo `session.py --host-id <ID do host Local>`, nunca lê, pede ou imprime essa senha. A IA conecta **só** invocando esses scripts com `--host <nome>`; **nunca** escreve
  código que chame `resolve_host(decrypt=True)`, `resolve_secret` ou `decrypt_value`, nem lê os
  campos `password`/`secret`. Cofre destrancado = permissão para as FERRAMENTAS conectarem, não
  para a IA ler segredos.

### VI. Inventário é a Fonte da Verdade (DEVE)

O agente só conhece a rede pelo que está em `network/`.

- **DEVE:** `network/hosts.yaml` lista todo host acessível.
- **DEVE:** `network/topology.yaml` descreve como os hosts se interligam.
- **DEVE:** Credenciais de host ficam só em `network/credentials.yaml` (git-ignorado). Segredos que não são de
  host (portais, APIs, tokens, para pessoas) ficam no Cofre de senhas, `network/vault.yaml` (git-ignorado, mesma
  chave do cofre). A IA nunca lê nem decifra os segredos de nenhum dos dois (§V). Ela usa as chaves do Cofre de
  senhas só pelo `nvault run` (`scripts/tools/secrets/`), que injeta o valor no processo e mascara a saída.

### VII. Sem Runtime Próprio (DEVE)

A inteligência vive em Markdown/YAML interpretado pela IDE; a execução técnica vive em
scripts Python. Sem banco de dados, sem Docker, sem servidor (princípio do OpenSquad).

- **DEVE:** Estado de execução em arquivos (`runs/<id>/state.json`).
- **DEVE:** Memória em arquivos de texto (`memory/`).
- **PODE:** Existir uma **ferramenta de operador efêmera** — o console web CRUD em
  `scripts/engine/ui/` — desde que: (a) seja *stateless* (cada request lê/escreve só os arquivos
  canônicos; sem cache de estado, sem banco, sem segundo cofre); (b) faça bind em loopback
  por padrão (`127.0.0.1`) quando rodada direto; o launcher oficial (`start.sh`) pode escutar em todos os
  IPs (`0.0.0.0`) **desde que** nada abra sem login (sem cofre/usuário = só o assistente de primeiro
  acesso, com token de uso único); (c) o framework funcione 100% com ela desligada (as IDEs de IA
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
- **PODE:** Oferecer **"Acessar → Web"** (`POST /api/hosts/<id>/web-launch`, mesmo gate do terminal web) que abre a
  interface web do host numa aba nova já autenticada (`scripts/engine/lib/web_login/`, um provedor por app). O login
  roda no servidor; destino e credencial saem só do inventário/cofre. **Proxmox:** o navegador recebe só o *ticket*
  (válido ~2 h), nunca a senha.
- **EXCEÇÃO ÚNICA (autorizada em 13/11/2026) — Zabbix:** o cookie `zbx_session` não pode ser gravado de fora, então o
  `Handoff` do provedor `zabbix` leva a senha ao navegador do operador, **uma vez**, em resposta a um clique explícito
  (`Cache-Control: no-store`, formulário enviado direto ao Zabbix e removido da página, sem log nem auditoria do valor).
  Vale **só** para o provedor `zabbix`; outro app que exija isso precisa de nova emenda aqui.

---

## Governança

- Mudanças nestes princípios exigem atualização de versão e propagação ao `PADRAO.md`.
- **INEGOCIÁVEL:** violação bloqueia a execução. **DEVE:** violação gera alerta.
- Versionamento: MAJOR (redefinição incompatível), MINOR (novo princípio), PATCH (ajuste).

*NetOps Constitution v1.1.0 — Padronizado | Projeto Vivo | Seguro*
