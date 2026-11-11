# Changelog do NetOps

## [2.1.0] - 2026-11-11

### Novidades

- Aba Claude Code com barra única: título da sessão, status, Padrões, Sessões, Nova sessão e estado do cofre ficam na barra superior, liberando espaço na janela. O botão "Copiar link" da página foi removido (continua na lista de Sessões).
- Padrões de modelo e modo de permissão para novas conversas agora têm URL própria (`#claude/<sessão>/padroes`) e um popup no mesmo padrão visual do restante do console.
- "Verificar atualizações" passou para Configuração; a versão instalada continua no canto da barra.
- Pré-visualização de imagens anexadas no chat e persistência dos padrões por conversa.
- Mapas: ordem de camada (z-index) das ligações e melhorias no editor de nós.

- O login do console agora vale 7 dias (configurável em `ui.login_ttl_seconds`) e sobrevive ao reinício do servidor. Os logins são gravados apenas como hash SHA-256, com permissão 0600, em `runs/` (fora do Git).

- Novo `scripts/engine/restart-console.sh`: reinicia o console de forma segura (espera o supervisor e o lock, valida o HTTP), inclusive de dentro da aba Claude.

### Correções

- Corrige a regressão da 2.0.1: durante uma atualização, uma migração de IDs com referências inválidas voltou a provocar o rollback automático para a versão anterior, com os dados antigos intactos e o diagnóstico em `.netops-update/host-migration-preflight.json`. Fora de atualizações, o console continua subindo e registra o erro.

### Compatibilidade

- Sem mudança de formato de dados; o atualizador preserva dados e personalizações. Quem estiver logado precisa entrar uma vez após a atualização, e os logins passam a ser persistentes a partir daí.

## [2.0.1] - 2026-11-11

### Correções

- Startup do console agora é resiliente a erros de pré-validação da migração de hosts, permitindo que o servidor suba mesmo quando há referências inválidas nos dados. O estado de erro é exibido na UI sem bloquear o acesso.

## [2.0.0] - 2026-11-11

### Novidades

- Hosts passam a usar IDs inteiros gerados automaticamente, imutáveis e separados do nome editável. O cadastro não exige informar um ID.
- Atualização pelo botão do console converte automaticamente inventários legados, com manutenção durante a conversão, pré-validação, baseline privado, hashes e journal de recuperação. O pacote continua aceito pelos atualizadores publicados nas versões 1.2.1 e 1.3.0.
- Nomes de identificação antigos ficam reservados como aliases. Os scripts aceitam `--host-id <inteiro>` e continuam aceitando `--host <hostname-ou-alias>` quando o nome é único.
- Mapas, posições, ligações físicas e visuais e alvos de backup usam a mesma identidade inteira. Alterar o nome do host mantém seus vínculos.
- Novos backups usam `backups/by-id/<id>/`; o histórico legado permanece no lugar, com associação explícita ao host correto.

### Correções

- Excluir um host remove seus enlaces físicos e conexões visuais de todos os mapas, incluindo os dois sentidos, e preserva formas, rotas e ligações não afetadas. Novos testes cobrem a API e o navegador em desktop e toque.
- Backups e seu runner respeitam a mesma raiz de dados alternativa do inventário.
- O catálogo de modelos do Claude é descoberto pelo CLI do provedor utilizado. Erros de modelo preservam a conversa e não são confundidos automaticamente com limite HTTP 429.

### Migração e compatibilidade

- Mudança de contrato: inventário, topologia e mapas usam formato v2, com IDs inteiros na API; a configuração de backups usa v3. Integrações que manipulam os YAMLs ou a API diretamente precisam aceitar esses formatos.
- Com um supervisor antigo, a conversão dos dados só começa depois da confirmação do código, evitando que um rollback de código deixe a versão anterior sobre dados novos. O console permanece bloqueado até concluir a conversão.
- Referências inválidas bloqueiam a migração com erro explícito, sem apagar ligações, inventar hosts ou aplicar uma conversão parcial. Os dados originais e o baseline são preservados para correção e recuperação.
- Inventários já migrados não recebem novos IDs ao atualizar ou reiniciar. Credenciais, nomes, IPs, ícones, posições, formas, ligações válidas e históricos são preservados.
- Personalizações locais continuam protegidas pelo atualizador. Código do motor modificado localmente ainda exige revisão antes da aplicação automática.

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
