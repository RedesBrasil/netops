# Regra permanente: releases do NetOps

Todo agente deve ler esta regra antes de preparar ou publicar uma release.

## Antes de escolher a versão

1. Consulte o GitHub oficial: `gh release list --repo RedesBrasil/netops --limit 100` e, havendo releases, veja a última estável com `gh release view <tag> --repo RedesBrasil/netops`.
2. Erro de autenticação, conexão ou permissão não significa ausência de releases. Resolva a consulta antes de continuar. O repositório pode ser privado.
3. Compare a última estável com `metadata.version` em `core/config/core-config.yaml`. Essa é a única versão manual do produto. A versão da constituição é independente.
4. Escolha SemVer `X.Y.Z` superior à última estável: PATCH para correções compatíveis, MINOR para recursos compatíveis, MAJOR para incompatibilidades. Nunca mova nem reutilize uma tag publicada.

## Preparação

- Revise commits e mudanças desde a última tag publicada. Na primeira release, descreva o conjunto inicial honestamente.
- Atualize a versão central e `CHANGELOG.md` com `## [X.Y.Z] - AAAA-MM-DD`, novidades, correções e notas de compatibilidade/preservação de dados. Não inclua dados de clientes, IPs privados, credenciais ou histórico pessoal.
- Execute testes Python/JS e valide a extração do pacote em diretório temporário.
- Verifique explicitamente o diff e a lista de arquivos distribuídos. O pacote inclui somente caminhos autorizados e objetos de `HEAD`; arquivos ignorados e conteúdo local não podem entrar por uma varredura indiscriminada do disco.
- Assets do frontend devem estar prontos no repositório. O operador não precisa de npm para atualizar.
- Não publique uma migração destrutiva de dados. Alterações de formato precisam de compatibilidade comprovada ou protocolo específico com backup e rollback antes de serem aceitas pelo atualizador.

## Publicação autorizada

Implementar código não autoriza automaticamente commit, push, criação de tag ou publicação externa. Confirme essa etapa quando ela não tiver sido explicitamente solicitada.

Depois do código aprovado, commitado e integrado em `main`, execute manualmente o workflow **NetOps release** no GitHub Actions, informando `X.Y.Z`. O workflow:

1. Confere branch e versão, roda testes e consulta novamente as releases existentes.
2. Gera `netops-X.Y.Z.tar.gz` com manifesto, hashes e permissões, além de `SHA256SUMS` e notas.
3. Cria um draft com a tag e o changelog da versão, sem substituir release existente.
4. Confere o digest devolvido pelo GitHub e só então publica a release estável.

Se falhar depois de criar o draft, mantenha-o privado e investigue. Não crie automaticamente outra tag nem publique um pacote parcial para contornar a falha. Releases sem pacote verificável não são instaláveis pelo console.

O workflow pode retomar um draft da **mesma revisão**, substituindo seus assets privados e
conferindo novamente os dois digests. Draft de outra revisão exige investigação e ajuste
explícito do destino antes da nova execução; uma tag já publicada nunca é movida.
A conferência usa `gh release view`, pois `/releases/tags/<tag>` retorna 404 para drafts
cuja tag ainda não existe. Release publicada ou assets desconhecidos bloqueiam a retomada.

## Validação final

Consulte a release publicada, confira tag, changelog e assets. Verifique no console a listagem de todas as versões superiores e faça um teste de atualização em cópia isolada, comparando dados antes/depois. Informe claramente o que foi publicado, o que foi apenas preparado e quais testes realmente rodaram.
