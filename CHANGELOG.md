# Changelog do NetOps

## [1.3.0] - 2026-11-11

### Novidades

- Ligações entre hosts, formas e referências começam sem texto. A descrição do enlace e o texto da ligação visual são opcionais e podem ser incluídos, alterados ou apagados depois.
- Formas podem ser criadas e editadas sem texto, inclusive com ícones da biblioteca local.
- Botão direito em hosts e formas oferece **Enviar para frente** e **Enviar para trás**, movendo uma camada por clique e preservando a ordem entre todos os itens ao reabrir o mapa.
- Preenchimento e contorno das formas aceitam qualquer cor pelo seletor de cores, com código HEX editável, botão de copiar e prévia das duas cores.
- **Duplicar** no menu da forma cria uma cópia independente com o mesmo formato, tamanho, ícone, texto e cores. **Delete** remove a forma selecionada.
- Clique e arraste no fundo do mapa seleciona hosts e formas por retângulo, permitindo mover, alinhar e remover a seleção. Espaço + arraste ou botão do meio move a visão do mapa.
- A seleção em mapas adicionais remove apenas suas associações visuais. Em mapas automáticos, excluir hosts exige confirmação explícita do impacto no inventário, enlaces e demais mapas.

### Correções

- Selecionar uma ligação por clique, botão direito ou teclado substitui a seleção anterior de hosts/formas; Delete atua sobre a ligação escolhida.
- Tocar no fundo limpa a seleção e permite abrir as ações do mapa. Escape e Delete ficam disponíveis imediatamente após os menus de conexão, seleção múltipla e duplicação.

### Preservação e compatibilidade

- Camadas e cores são campos opcionais de apresentação em `maps.yaml`; mapas existentes continuam válidos sem migração destrutiva. Textos já informados são preservados.
- Dados locais, credenciais, backups, personalizações e conversas continuam preservados pelo atualizador. Nenhum teste usa o inventário real.
- O pacote inclui os assets reconstruídos: não é necessário instalar Node/npm para atualizar. Reinicie pelo launcher após a atualização para carregar o schema compatível.

## [1.2.1] - 2026-11-11

### Correções

- Atualização pelo console não é mais recusada com "encerre: terminal ou sessão interativa aberta" quando nenhuma sessão está visível. A conexão da aba Claude Code fica ativa em todas as páginas e era contada como sessão aberta.
- Terminal web e sessões do agente abertos não bloqueiam a atualização: são encerrados no reinício. Backup de equipamento e workflow em execução continuam impedindo a atualização até terminarem.
- Aviso de confirmação e documentação do atualizador refletem a nova regra.

### Preservação e compatibilidade

- Sem migração de dados. Conversas do Claude Code ficam no transcript em disco e podem ser retomadas após o reinício.
- Instalações em versão anterior ainda aplicam a barreira antiga: para chegar à 1.2.1, encerre a aba Claude Code em todos os navegadores e feche o terminal web antes de clicar em Atualizar.

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
- Conferência dos pacotes antes da publicação reconhece rascunhos e permite retomar um rascunho da mesma revisão.

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
