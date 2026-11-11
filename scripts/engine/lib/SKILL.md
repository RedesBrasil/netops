# SKILL — Inventário e migração de identidade

O núcleo `inventory.py` resolve herança e seleciona hosts sem alterar os arquivos.
`host_identity.py` mantém IDs inteiros positivos até `2^53 - 1`, contador e aliases
legados reservados. IDs não são editáveis. `load_inventory(include_credentials=False)`
lê exclusivamente metadados; somente os transportes de acesso precisam de credenciais.

## Conversão automática no console

A partir da versão 2, atualizar ou iniciar o console em modo de escrita pelo
`scripts/engine/ui/start.sh` recupera e converte inventários legados automaticamente.
O console aguarda a conclusão antes de liberar suas operações. Não há migração por GET,
acesso a equipamentos ou leitura de `credentials.yaml`; `--read-only` não converte dados.

Durante uma atualização, o candidato pré-valida os documentos sem escrita. Referências
inválidas impedem sua inicialização e o supervisor anterior restaura o código. O diagnóstico
privado fica em `.netops-update/host-migration-preflight.json`. Se a pré-validação passar,
a conversão aguarda o commit do código pelo supervisor, a publicação do PID do novo servidor
e a retirada do marcador de recuperação. Só então executa `apply` com os hashes esperados.

`/api/config/meta` informa `host_migration.phase`, `detail` e `blocking`. As fases bloqueantes
são `waiting_for_commit`, `running` e `failed`; API e WebSockets não observam dados parcialmente
convertidos. `completed`, `not_required` e `read_only` encerram essa etapa sem bloqueio próprio.
Falha depois do commit mantém o código novo, com erro visível e escrita bloqueada; um reinício
normal recupera a transação interrompida e tenta novamente. Conflitos ou baselines corrompidos
continuam bloqueados, sem sobrescrita forçada. Ver também `scripts/engine/update/SKILL.md`.

## Conferência e migração manual

Executar a partir da raiz da instalação; não há acesso à rede nem leitura do cofre:

```bash
.venv/bin/python scripts/engine/lib/host_id_migration.py dry-run
.venv/bin/python scripts/engine/lib/host_id_migration.py apply
.venv/bin/python scripts/engine/lib/host_id_migration.py recover
.venv/bin/python scripts/engine/lib/host_id_migration.py rollback
```

`--root /caminho/instalacao` aponta outra instalação. O dry-run não grava arquivos.
Referências ausentes bloqueiam a migração e são listadas por arquivo/campo; nenhum
enlace é excluído e nenhum equipamento é inventado. Comentários YAML e IDs dos enlaces
são preservados; nomes antigos viram aliases e pastas antigas de backup são associadas
explicitamente. Novas coletas usam `backups/by-id/<inteiro>/`.

Antes do commit, a ferramenta guarda baseline, documentos preparados e hashes em
`runs/<data>-host-id-migration-<id>/`. O journal privado em
`network/.host-id-migration.json` permite recuperar interrupções. `recover` restaura
automaticamente uma aplicação incompleta; `rollback` também desfaz uma aplicação
concluída, desde que nenhum dos quatro arquivos tenha sido editado depois. Os baselines
ficam preservados. Novas coletas em `backups/by-id/` também impedem o rollback completo,
pois reaproveitar a identidade poderia associar o histórico a outro equipamento.
O rollback nunca substitui edições posteriores silenciosamente.

Console e migrador usam o mesmo `flock` por diretório de inventário. Ferramentas externas
que editam YAML diretamente devem estar paradas durante a migração. Se uma execução
ficar incompleta, recupere antes de liberar novas escritas. Para vincular uma aplicação a
um dry-run específico, salve o JSON retornado e forneça `apply --expected-plan plano.json`.
