# Changelog do NetOps

## [1.1.0] - 2026-11-10

### Novidades

- Botão Verificar atualizações no console, com versão instalada e notas de cada release estável posterior.
- Atualização por pacote oficial das GitHub Releases, inclusive em repositório privado com autenticação local do GitHub CLI.
- Backup privado verificado, manutenção durante atualização, reinício gerenciado e rollback de código e ambiente em falha de inicialização.
- Manifesto de distribuição com hashes por arquivo, validação de caminhos e preservação de personalizações.
- Ferramenta e workflow de publicação com consulta da release corrente, changelog obrigatório e validação do digest antes de publicar.

### Preservação e compatibilidade

- Inventário, credenciais, mapas, memória, configuração local, backups, relatórios, execuções e históricos não são substituídos pelo pacote.
- Agentes, workflows, conhecimento e scripts operacionais personalizados mantêm as edições e exclusões locais.
- Código do motor alterado localmente, conflitos de caminho, sessões em atividade e backup inválido bloqueiam aplicação automática.
- É necessário iniciar o console pelo launcher e autenticar o GitHub CLI no mesmo usuário/HOME do servidor. Aplicação exige login no console e modo de escrita.
- O atualizador não modifica o histórico Git, não faz migrações destrutivas de dados e não instala prereleases ou downgrades.
- A primeira adoção do launcher atualizado requer um reinício manual. Atualizações seguintes podem reiniciar automaticamente.

### Base inicial de distribuição

- Console de inventário, cofre, conhecimento, backups e operações assistidas.
- Mapas integrados ao inventário com ícones locais, ligações visuais e alinhamento de seleção múltipla.
