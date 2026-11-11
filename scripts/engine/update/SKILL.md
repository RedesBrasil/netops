# Atualizações do NetOps

## Uso

Inicie sempre por `scripts/engine/ui/start.sh`. Na barra superior, clique em **Verificar atualizações**, leia as notas de todas as versões posteriores e escolha **Atualizar para vX.Y.Z**. Salve formulários e encerre terminais, agentes e backups em execução antes de confirmar.

O repositório oficial é `RedesBrasil/netops`, atualmente privado. Instale GitHub CLI e rode `gh auth login --hostname github.com` como o mesmo usuário e HOME do servidor. Não passe tokens pela interface. O atualizador usa `gh api`; não imprime nem exporta credenciais.

A aplicação exige login com a senha-mestra, mesmo em instalações em que o restante do console esteja aberto por falta de cofre. Modo somente leitura permite consultar, mas não aplicar. Não é necessário destrancar ou descriptografar as credenciais para fazer um backup da instalação.

## O que é preservado

- Inventário, credenciais cifradas, mapas, topologia, backups de equipamentos, relatórios e execuções.
- Configuração local do projeto, memória, arquivos desconhecidos, ambientes e históricos pessoais.
- Personalizações de agentes, workflows, conhecimento e scripts operacionais. Edições e exclusões locais não são substituídas por versões da distribuição.
- `.git/` e HOME externo ao projeto não são alterados. O atualizador não faz checkout, reset, clean, pull nem stash.

Código do motor modificado localmente ou novos caminhos colidindo com arquivos existentes impedem a atualização automática. A referência inicial de um clone legado é o conteúdo de `HEAD`; depois, é o manifesto privado `.netops-update/installed.json`. Por isso, após instalar um pacote, `git status` pode mostrar mudanças de distribuição: o atualizador não usa o working tree como referência de instalação.

## Backup e limites

`.netops-update/` contém jobs, pacotes, snapshot e journal. Ambientes Python novos vivem em
`.netops-venvs/`, git-ignorado, sem dados privados e acessível ao usuário reduzido do terminal. É privado (`0700`, backups `0600`), git-ignorado e não servido pela API. Não copiar esse diretório para relatórios nem publicá-lo. O arquivo `snapshot.json` registra hashes e permissões originais, sem conteúdo de segredos.

O snapshot inclui arquivos regulares da instalação e DATA_ROOT externo, com links registrados sem seguir seus destinos. Exclusões regeneráveis: `.git`, `.venv`, `.netops-venvs`, `node_modules`, `__pycache__`, `.pytest_cache` e o próprio diretório de atualização. O ambiente Python anterior é mantido separadamente quando houver troca. Links externos e arquivos fora desses diretórios permanecem intocados, mas não estão cobertos pelo snapshot.

Backups não são apagados automaticamente. Reserve espaço para snapshot, pacote e ambiente Python novo. Mantenha também backup em outro disco: nenhuma atualização pode garantir recuperação de falha física, corrupção do armazenamento ou alterações concorrentes de processos externos. Pause editores, CLIs, cron e outros escritores externos durante a atualização. O console bloqueia seus próprios escritores e sessões, não todos os processos do sistema.

Pacotes são limitados a 256 MiB comprimidos, 512 MiB descomprimidos e 10 mil arquivos, sem links, entradas especiais ou execução de scripts pós-instalação. O digest do asset vem da API autenticada do GitHub e cada arquivo é conferido contra o manifesto. Checksums não substituem confiança nos mantenedores do repositório. Releases sem pacote compatível, drafts, prereleases e downgrades não são aplicados.

## Recuperação

O supervisor roda a partir de uma cópia privada do atualizador. Primeiro prepara pacote, snapshot e dependências enquanto o console informa progresso em manutenção. Depois encerra somente seu processo, aplica o código e inicia a versão candidata na mesma porta. Só confirma a instalação depois de receber uma resposta HTTP com versão e identidade de inicialização corretas.

Falha de inicialização restaura código e ambiente anteriores automaticamente. Não restaura dados vivos por cima dos existentes, pois a aplicação não os modifica. O login do console pode ser solicitado novamente após reinício.

Após interrupção inesperada, execute novamente `scripts/engine/ui/start.sh`: journals não confirmados são revertidos antes de abrir o console. Se o processo anterior ainda estiver vivo, o launcher recusa a recuperação até o operador encerrá-lo; não mata processos por PID reutilizado. Se o status for `recovery_failed`, o launcher recusa iniciar para não esconder uma recuperação incompleta. Não apague o journal nem o snapshot. Com os processos parados, um operador deve verificar os arquivos listados em `journal.json`, recuperar os originais de `jobs/<id>/backup/installation/` respeitando as permissões de `snapshot.json`, e restaurar a seleção de `.venv` se necessário. Só depois de validar toda a instalação pode encerrar manualmente o incidente. Conflito de arquivo alterado externamente exige comparação humana, nunca sobrescrita forçada.

## Releases e testes

Antes de gerar uma versão, siga `core/rules/releases.md`. O comando `python3 scripts/engine/update/release.py --output /tmp/netops-release-NOVO` consulta o GitHub e prepara um pacote de `HEAD` sem publicar. Exige versão e changelog commitados.

Testes: `.venv/bin/python3 -m pytest scripts/engine/ui/tests/ -q`. Testes de aplicação devem usar uma **cópia completa temporária do código e dados fictícios**. Apenas mudar `NETOPS_UI_DATA_ROOT` não isola o motor que seria atualizado. Nunca testar aplicação contra o console real.
