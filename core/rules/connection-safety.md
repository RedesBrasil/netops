# Regra — Segurança de Conexão e Mudança

Regras obrigatórias para qualquer acesso a equipamentos. Vale principalmente para o agente
`executor`. Deriva do §V e §VI da `constitution.md`.

## Antes de conectar

- Conectar **somente** em hosts presentes em `network/hosts.yaml`. Host fora do inventário
  é proibido — registre como bloqueio e pare.
- Resolver o método de acesso e o **nome** da credencial via `scripts/engine/lib/inventory.py`
  (`--show` mascara segredos) — ou deixar o próprio script de acesso resolver. Nunca digitar
  credenciais soltas e **nunca** descriptografar o segredo você mesmo (ver "Manuseio de segredos").
- Usar `timeout` em toda conexão. Falha de conexão não trava a execução: registra-se o erro
  e segue-se para o próximo host.

## Coleta (read-only)

- Comandos de coleta são **read-only**. Na dúvida se um comando altera estado, trate-o como
  mudança (ver abaixo).
- Salvar a saída em `runs/<id>/collected/<host>.txt`. Nunca em pasta versionada.

## Mudança de configuração

A escrita direta é permitida (decisão do projeto), mas **sempre reversível**:

1. **Baseline.** Capturar o estado atual da área afetada → `runs/<id>/collected/<host>.before.txt`.
2. **Rollback pronto.** Confirmar que existe `runs/<id>/proposals/<host>.rollback.txt`.
   Sem rollback, não aplique.
3. **Aplicar.** Executar a config de `runs/<id>/proposals/<host>.change.txt`.
4. **Pós-estado.** Capturar `runs/<id>/collected/<host>.after.txt`.
5. **Falha = rollback automático.** Se qualquer comando falhar, ou se a conectividade de
   gerência cair, executar o rollback imediatamente e parar.

## Risco de lockout

Antes de mudar regras de firewall, endereço de gerência, ACL ou serviços de acesso (SSH/API),
verificar se a mudança pode cortar a própria conexão de gerência. Em caso de risco, o
`planner` deve incluir um mecanismo de segurança (ex.: `safe-mode` no MikroTik, agendamento
de rollback automático).

## Credenciais e manuseio de segredos (INEGOCIÁVEL)

**A IA nunca manuseia segredo em texto puro.** Descriptografar, ler, imprimir, salvar ou copiar
o valor de um campo `password`/`secret` e **proibido** — mesmo com o cofre destrancado, mesmo
"para conferir" ou "por transparencia". Quem descriptografa sao **exclusivamente** os scripts de
acesso (`scripts/tools/access/*`), no instante de conectar, e o backend **Local**
(`scripts/engine/localadmin/`), que autentica o `su` de `netops-admin` no proprio servidor.

## Host Local (este servidor NetOps)

- E o host com `access.method: local` (criado pelo instalador, protegido: nao se apaga nem se troca
  acesso/credencial). Nao usa rede: `session.py exec|run --host-id <ID-LOCAL> --command "..."` roda
  **como root**, uma operacao por comando (sem shell root persistente: junte `cd`/`export` no mesmo comando).
- Comando que nao precisa de root: rode direto no Bash (a IA ja e `netops`). Root so quando o pedido exigir.
- Pre-requisitos: cofre destrancado e usuario com `server.admin`. Falta algo -> o script diz o que (codigo
  `vault_locked`, `authorization_denied`, `local_access_disabled`...): **informe o humano e pare**; nunca tente
  `sudo`, `su`, SSH em 127.0.0.1 ou ler a credencial.
- Backup antes/depois (`change.py begin/end --host-id <ID-LOCAL>`) vale igual: o baseline do Local inclui
  pacotes, servicos, portas, grupos e firewall. Gerenciador de pacotes **nao** tem rollback universal: diga
  antes o que e irreversivel. Instalar Docker nao inclui `netops` no grupo `docker`.
- Nunca trate o IP de um host remoto como local, nem `127.0.0.1` como prova de que e o Local.

- Para conectar/coletar/mudar, **invoque o script de acesso** com `--host-id <inteiro>`
  (ou `--host <hostname-ou-alias>` para compatibilidade). Ele resolve a
  credencial internamente e usa o segredo sem devolvê-lo — você recebe a SAÍDA do comando, nunca
  a senha.
- **Nunca** escreva código que chame `resolve_host(decrypt=True)`, `resolve_secret()` ou
  `decrypt_value()`, nem leia os campos `password`/`secret` do `credentials.yaml`.
- **Nunca** imprima/ecoe uma senha (`print`, `echo`, `log`) nem a passe por argumento de shell
  (fica visível em `ps`/histórico). Se um comando devolver um segredo, **mascare** antes de exibir.
- Cofre destrancado é permissão para as **ferramentas** conectarem — **não** para a IA ler
  segredos. Se você acha que precisa do valor da senha, você não precisa: a ferramenta precisa,
  não você. Pare e use a ferramenta.

Credenciais **nunca** entram em `runs/`, `reports/`, `memory/` ou logs (só em `credentials.yaml`,
git-ignorado). A descriptografia acontece só em memória, **dentro do script de acesso**, via
`scripts/engine/lib/inventory.py:resolve_secret()`; a chave da sessão vive em RAM (tmpfs, `0600`),
nunca em disco. O cofre é destrancado pelo humano (`python3 scripts/engine/vault/cli.py unlock`);
a IA não digita a senha-mestra.
