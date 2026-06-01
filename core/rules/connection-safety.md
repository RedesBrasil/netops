# Regra — Segurança de Conexão e Mudança

Regras obrigatórias para qualquer acesso a equipamentos. Vale principalmente para o agente
`executor`. Deriva do §V e §VI da `constitution.md`.

## Antes de conectar

- Conectar **somente** em hosts presentes em `network/hosts.yaml`. Host fora do inventário
  é proibido — registre como bloqueio e pare.
- Resolver método de acesso e credencial sempre via `scripts/lib/inventory.py` — nunca
  digitar credenciais soltas.
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

## Credenciais

Credenciais **nunca** entram em `runs/` (exceto `credentials.yaml`, que é git-ignorado),
`reports/`, `memory/` ou logs. Mascare segredos em qualquer saída.

Se as credenciais estiverem criptografadas (cofre `enc.v1:`), o cofre precisa estar
**destrancado** na sessão antes de conectar — o humano roda `python scripts/vault/cli.py unlock`.
A descriptografia acontece só em memória (em `scripts/lib/inventory.py:resolve_secret()`); a chave
da sessão vive em RAM (tmpfs, `0600`), nunca em disco versionado.
