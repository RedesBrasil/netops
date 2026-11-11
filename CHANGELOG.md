# Changelog do NetOps

## [1.2.0] - 2026-11-11

### Novidades

- Cada conversa do Claude Code tem um link próprio (`#claude/<id>`), com opção de copiar na conversa e na lista de sessões.
- Abrir Claude Code retoma a última conversa selecionada no navegador; sem preferência salva, abre a conversa mais recente do projeto.
- Links diretos, recarregamento e os botões voltar/avançar preservam a sessão escolhida. Nova sessão continua disponível explicitamente.

### Correções

- Histórico, tickets de conexão e eventos atrasados de uma conversa anterior não substituem a sessão atual.
- Links inválidos ou de sessões removidas mostram uma orientação sem iniciar o agente em repetição.
- Abrir a mesma sessão persistente em outra aba informa a transferência e evita disputa de reconexão.
- Login do console compartilhado entre abas, com sincronização de entrada, saída e expiração, sem persistir a senha.

### Preservação e compatibilidade

- Conversas existentes continuam no histórico do Claude Code, sem migração ou alteração dos transcripts.
- A preferência local guarda somente o identificador da conversa. Os links exigem o login normal do console.
- Esta primeira release publicada inclui também o atualizador, os mapas e os recursos descritos em 1.1.0. Inventário, credenciais, memória e personalizações são preservados pelo atualizador.

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
