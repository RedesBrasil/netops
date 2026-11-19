# SKILL — Usuários, grupos de acesso e auditoria (multiusuário)

## O que é

O console NetOps é **multiusuário**: cada pessoa entra com **e-mail + senha**. Cada usuário
pertence a um ou mais **grupos de acesso**, que definem o que ele vê e faz no console.
- Uso normal: menu **Sistema → Usuários / Grupos de acesso / Auditoria** (`#users`, `#access-groups`, `#audit`).
- Cada um troca a própria senha em **Minha conta** (`#account`, botão com o nome no topo).
- Este `cli.py` é o caminho de **recuperação** (admin trancado fora) e de automação.

## Onde fica (SQLite, não YAML)

`runs/netops.db` (git-ignorado, `0600`, modo WAL), via `scripts/engine/lib/accessdb.py`:
`users`, `access_groups`, `user_groups`, `sessions`, `login_failures`, `audit`, `claude_owners`.

**Por que banco aqui e arquivo no resto:** isto é estado do sistema, escrito a cada login e a cada
request por vários processos. Precisa de transação ("não apague o último admin") e de consulta
(auditoria). O que a IA lê e edita (inventário, skills, memória) continua em arquivo.

**Nunca copie o `.db` com o console no ar.** Use `cli.py snapshot <destino>` (API de backup do SQLite).
O backup completo (`scripts/tools/backup/full_mirror.sh`) já espelha `runs/netops.db.snapshot`.

## Login = e-mail

- O e-mail é obrigatório e único, sem diferenciar maiúsculas (é gravado em minúsculo).
- Cada usuário também tem um **ID interno** (`username`), derivado do e-mail (`joao.silva@x.com` → `joao.silva`; repetido → `joao.silva-2`).
  - Ele aparece na auditoria, no dono das conversas Claude e no CLI.
  - **Trocar o e-mail não muda o ID** e não quebra o histórico.
- O login também aceita o ID interno. É o caso do `admin` migrado sem e-mail, de scripts e do CLI.
- A API recebe `POST /api/auth/login {email, password}`. `username` continua aceito.
- **Recuperar senha por e-mail ainda NÃO existe:** precisaria de SMTP configurado. Quem redefine é o admin (tela ou `cli.py passwd`).

## Modelo de permissões

- **Permissões efetivas** = união dos grupos do usuário. O catálogo está em `accessdb.PERMISSIONS`.
- **Rota → permissão:** `scripts/engine/ui/services/authz.py` (`RULES`).
  - É **default-deny**: rota sem regra só passa para admin.
  - O teste `test_every_route_is_mapped_to_a_permission` reprova rota nova sem regra.
- **Grupo `admin` (fixo):** tem `*`. Só ele tem as permissões `admin_only`:
  terminal e arquivos do servidor, configuração, atualização, usuários, auditoria,
  **editar scripts/skills** e **criar/editar tarefas agendadas**. Essas duas últimas rodam com a conta do servidor (`netops`; root só na instalação legada). `server.admin` = administração Local como root (só admin).
- **Grupos sugeridos** (editáveis): `operador` e `leitura`.
- **Sem escopo por host:** quem tem `hosts.view` vê todos os hosts.
- **Aba Claude:** liberável por grupo (`claude.use`).
  - O teto `net_perms` do grupo limita o que ela faz nos **equipamentos**. Acima do teto, nem a aprovação na tela libera.
  - Isso é proteção contra erro, **não fronteira de segurança**: o agente tem shell no servidor.
  - Cada conversa tem **dono**. Quem não é admin só vê as próprias conversas; conversas sem dono (anteriores ao multiusuário) ficam só para admin.
  - O agente recebe `NETOPS_USER`.
- **Botões no front:** as páginas marcam botões com a classe `needs-<perm>` (ex.: `needs-hosts-edit`), e o shell esconde quando falta a permissão.
  Isso é só visual: quem bloqueia é o backend (403 `forbidden`).

## Cofre por usuário (keyslot)

- A senha do usuário usa o mesmo esquema do cofre (Argon2id + verifier, `lib/vault.build_meta`).
- A chave derivada dela **embrulha a chave do cofre**. Por isso o login de cada usuário destranca o cofre sem ninguém conhecer a senha-mestra.
- O slot é criado sozinho quando o usuário entra com o cofre **já destrancado**. Isso cobre o usuário novo e a troca da senha-mestra.
- Desativar o usuário apaga o slot. Trocar a senha reembrulha o slot.

## Migração (instalação que já existia)

- **Sem usuários:** o login continua com a senha-mestra, como antes.
  - A tela pede o **e-mail do administrador** + senha-mestra. O 1º login cria o usuário `admin` (grupo admin) com esse e-mail, essa senha e o keyslot.
  - Senha-mestra com menos de 8 caracteres continua no modo legado: crie o admin pela tela ou pelo CLI.
- **Sessões antigas:** quem estava logado (arquivo `runs/.ui-auth-sessions.json`) continua logado, como `admin`. A importação acontece uma vez.
- **Compatibilidade:** `POST /api/auth/login {master_password}` sem `username` = senha do `admin`.

## GitHub por usuário

Cada usuário conecta a **própria** conta do GitHub em **Minha conta → GitHub** (`#account/github`). O agente das
conversas que **ele** abre (aba Claude Code, Projetos) usa essa conta para push, PR e `gh`, e os commits saem com o
nome e o e-mail dele. Código: `scripts/engine/lib/github_identity.py`, `ui/services/github_auth.py`, `ui/routers/github.py`.

- **Como conecta:** login por dispositivo do GitHub CLI (código + `github.com/login/device`, autorizado no navegador
  da pessoa) ou um token pessoal. A senha do GitHub nunca passa pelo NetOps.
- **Onde fica:** `runs/users/<username>/gh/` (GH_CONFIG_DIR do `gh`, token em `hosts.yml` com `--insecure-storage`,
  pasta 0700) e `runs/users/<username>/github.json` (login, nome, e-mail escolhido, sem token). Tudo git-ignorado.
- **Ambiente do agente** (`claude_svc._options` → `github_identity.env_for`): `GH_CONFIG_DIR` dele,
  `GIT_AUTHOR_*`/`GIT_COMMITTER_*`, credential helper do github.com por `GIT_CONFIG_*` (vale sobre qualquer gitconfig),
  `GIT_TERMINAL_PROMPT=0`; `GH_TOKEN`/`GITHUB_TOKEN` herdados são removidos.
- **Sem conta conectada:** `GH_CONFIG_DIR` aponta para `runs/users/_sem-github/gh` (vazia). Push, PR e `gh` falham e
  **nunca** usam a conta do servidor. Os commits saem com o nome e o e-mail do cadastro no console.
- **Vale para conversas novas ou reabertas:** o ambiente é fixado quando o processo do agente nasce. Quem retoma
  a conversa de outra pessoa (admin) usa o GitHub **dele próprio**.
- **Guarda** (`_hook_github_guard`, só para não-admin): bloqueia ler `/root/.config/gh`, `runs/users/`, `gh auth token`,
  trocar `GH_CONFIG_DIR`/`GH_TOKEN`, `env -i/-u`, `git config credential/user.*` e `--author`. É uma grade contra
  erro, **não** uma fronteira: o agente tem shell com a conta do servidor.
- **Onde aparece:** só em **Minha conta → GitHub**. Não aparece na aba Claude nem na lista de Usuários (decisão do
  usuário, 19/11). O admin consulta e revoga só pela API: `GET`/`DELETE /api/users/<u>/github`.
  Apagar o usuário apaga a pasta dele. A auditoria registra `github_connected`, `github_disconnected`, `github_email`
  e `github_revoked`.
- **Modo sem usuários:** nada muda; o agente usa o `gh` do servidor.
- **Servidor:** o atualizador e o backup completo continuam com o `gh` do root (`/root/.config/gh`). O ideal é uma
  conta de serviço, não a pessoal de alguém.
- **Tarefas agendadas:** `agent.github_as: <username>` (CLI `--github-as`) faz o agente da tarefa usar o GitHub
  desse usuário. Vazio mantém o `gh` do servidor.
- **Testes:** `scripts/engine/ui/tests/test_github_per_user.py`.

## CLI

```bash
python3 scripts/engine/users/cli.py list                       # usuários, grupos, último login, sessões
python3 scripts/engine/users/cli.py groups
python3 scripts/engine/users/cli.py reset-admin [--email a@b.com]   # RECUPERAÇÃO: cria/reativa admin + senha nova
python3 scripts/engine/users/cli.py add joao@empresa.com --groups operador --name "João" --temp
python3 scripts/engine/users/cli.py passwd joao@empresa.com --temp         # senha provisória, derruba as sessões
python3 scripts/engine/users/cli.py disable joao | enable joao | delete joao
python3 scripts/engine/users/cli.py sessions [--user joao] ; logout joao | logout --all
python3 scripts/engine/users/cli.py audit --user joao --limit 100
python3 scripts/engine/users/cli.py snapshot /caminho/netops.db
```

A senha nunca vai por argumento. Use `getpass` (terminal interativo) ou `--password-stdin`.

## Segurança

- **Throttle:**
  - Depois de 5 falhas seguidas de um usuário+IP (ou 20 de um IP), a espera cresce (15 s × 2ⁿ, máx. 15 min).
  - A falha vale mesmo com a senha certa durante o bloqueio.
- **Senha provisória (`must_change_password`):** a API devolve 403 `password_change_required` até a troca.
- **Auditoria:**
  - Registra login/logout/falha, toda escrita na API (inclusive as **negadas**, com o status), abertura de terminais e mudanças de usuário/grupo.
  - Nunca grava o corpo da requisição.
  - Retenção em `ui.audit_keep_days` (padrão 365).
- **Testes:** `scripts/engine/ui/tests/test_multiuser.py` e `tests/multiuser.browser.mjs`.
  - O browser test precisa de uma instância com cofre fictício: `NETOPS_E2E_VAULT=... tests/e2e-env.sh up`.
