# Changelog do NetOps

## [Não lançado]

### Novidades

- **Multiusuário com grupos de acesso.** Cada pessoa entra com **e-mail e senha**; o e-mail é único e um ID interno derivado dele mantém o histórico quando o e-mail muda. Os grupos definem o que cada um vê e faz no console.
  - **Telas novas:** Usuários, Grupos de acesso, Auditoria e Minha conta.
  - **Permissões:** são por rota, com default-deny. O menu e os botões somem para quem não tem a permissão.
  - **Admin:** só ele usa terminal e arquivos do servidor, configuração, atualização, usuários e auditoria. Também é o único que edita scripts e tarefas agendadas, porque eles rodam como root.
  - **Aba Claude:** liberável por grupo, com dono por conversa e teto de permissões de rede.
  - **Cofre:** o login de cada usuário destranca o cofre pelo keyslot dele, sem ninguém conhecer a senha-mestra.
  - **Segurança:** throttle de login, senha provisória obrigatória e auditoria, que registra inclusive as tentativas negadas.
  - **Banco:** usuários, sessões e auditoria ficam em SQLite (`runs/netops.db`). O que a IA lê continua em arquivo.
  - **Recuperação:** `scripts/engine/users/cli.py` (inclui `reset-admin`).
  - **Migração automática:** sem usuários, a tela pede o e-mail do administrador e a senha-mestra, e o 1º login cria o `admin` com esse e-mail. Quem estava logado continua logado.
- **GitHub por usuário.** No multiusuário, cada pessoa conecta a **própria** conta do GitHub em **Minha conta → GitHub** (`#account/github`), pelo navegador (código do GitHub CLI) ou por token pessoal. O agente das conversas dela (aba Claude Code e Projetos) faz push, PR e `gh` com essa conta, e os commits saem com o nome e o e-mail dela.
  - **Sem conta conectada:** o agente fica sem GitHub e não usa mais a conta do servidor.
  - **Onde fica:** o token fica só em `runs/users/<usuario>/gh/` (0700, git-ignorado).
  - **Telas:** o GitHub só aparece em Minha conta. O admin consulta e revoga pela API (`/api/users/<u>/github`), e a Auditoria tem eventos novos.
  - **Tarefas agendadas:** aceitam `agent.github_as`.
  - **Proteção:** uma guarda impede o agente de não-admin de ler ou trocar o login do GitHub de outra pessoa ou do servidor.
- **Projetos (menu Projetos).** Novo grupo na barra lateral: cada projeto é um **nome + uma pasta do servidor** (escolhida num navegador de pastas ou digitada). Abrir o projeto mostra as sessões do Claude Code daquela pasta e permite abrir sessões novas ali (`#projects/<id>`, `#projects/<id>/new`, `#projects/<id>/<uuid>`). O agente roda com `cwd` na pasta do projeto e usa só o `AGENTS.md`/skills dela, sem herdar as regras do NetOps. A aba **Claude Code** continua igual e segue com as conversas na pasta do NetOps. Remover um projeto só tira o registro (`runs/claude/projects.json`): a pasta e as conversas ficam intactas. A retomada automática pós-restart volta na pasta certa. Sidebar: os grupos do menu passam a abrir e recolher (o estado fica salvo no navegador; começam todos recolhidos). Em instalação com multiusuário, quem tem `claude.use` vê e usa os projetos; criar, remover e escolher a pasta é só do admin (`projects.manage`).
  - **Organizar e arquivos.** Renomear e remover direto na lista; **segurar e arrastar** para mudar a ordem (lista e barra lateral); **arquivar** esconde o projeto só para você (fica em "Arquivados", `#projects?arquivados=1`). Ordem e arquivados são de cada usuário. **Arquivos do projeto** com o mesmo gerenciador do menu Arquivos, preso à pasta do projeto (symlink para fora não sai dela): página `#projects/<id>/files` e painel ao lado do chat do projeto, fechado por padrão e aberto pelo botão 📁 Arquivos. Permissão nova `projects.files`, concedível por grupo.
  - **Segurança no modelo do VS Code.** Dá para **criar uma pasta nova** (padrão em `/opt/projetos`) ou **abrir uma existente**. A conta do agente fica no nível do usuário do servidor (`~/.claude/`) e vale em qualquer pasta; o console não copia token para o projeto. Pasta com configuração que executa ao abrir (`.claude/settings*.json`, `.mcp.json`) abre em **modo restrito** até o admin marcar como confiável. Raiz, diretórios do sistema, o NetOps e as pastas ocultas do home não podem ser projeto. O backup obrigatório antes de alterar equipamento e o teto de rede do grupo continuam valendo dentro dos projetos.

### Correções

- **Aba Claude Code com proxy/gateway de terceiros.** O banner de login deixa de dar falso "deslogado" quando o agente autentica por `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL` no bloco `env` dos settings (o `claude auth status` não lê esse bloco; agora ele é repassado). O catálogo de modelos passa a incluir o `modelPicker` dos settings, e o cache de 7 dias é descartado quando o provedor ou os modelos mudam. Sem proxy (direto na Anthropic) nada muda: sem `env` nem `modelPicker` o comportamento é o anterior.

## [2.4.0] - 2026-11-16

### Novidades

- **Instalador: porta ocupada e falso sucesso.** Se a porta do console já estiver em uso (por exemplo, por outro NetOps em outra pasta), o `install.sh` escolhe a próxima livre e avisa. Se `NETOPS_PORT` foi informada, ele para com erro. No fim, só dá sucesso se quem responde for o console da própria instalação; antes, um console alheio na mesma porta fazia o instalador declarar sucesso sem o novo ter subido.
- **Instalação com repositório privado por chave SSH.** O `install.sh` aceita `NETOPS_SSH_KEY` (deploy key somente leitura): clona a tag da última release por git+SSH, com as chaves de host do GitHub obtidas por HTTPS, e monta o pacote com o motor de release do próprio código. O README traz o passo de preparo e a linha de instalação.
- **Tarefa agendada com acesso a equipamento por chave dedicada.** `task_key.py provision/revoke-pending` cria um par ed25519 por tarefa (git-ignorado) e autoriza só nos hosts escolhidos, com backup pré/pós. O modo `ro` (padrão) restringe o equipamento a comandos de leitura pela guarda `netops-ro-shell` (`ro_shell.py`, lista de permissão). A tarefa e o agente acessam com `task_exec.py`, mesmo com o cofre trancado. A chave morre com a tarefa.
- **Monitor de lentidão do atendimento** (`scripts/tools/diagnostics/atendimento/`): medição periódica, aviso no Telegram e agente investigador. Os arquivos de configuração e credenciais ficam git-ignorados.
- **Aba Claude Code:** comandos de barra na conexão, prompts sintéticos (`/compact`) legíveis no histórico e melhorias de menções.
- **Backup de mudança:** `change.py` reusa a sessão persistente do host, com fallback para login avulso.
- **Atualizador aceita `AGENTS.md`** (substitui `CLAUDE.md` na lista de arquivos distribuídos). Para que instalações 2.3.1 ou anteriores consigam atualizar, o pacote da 2.4.0 **não inclui** `AGENTS.md` (o atualizador antigo recusaria o pacote inteiro); ele passa a ser distribuído na release seguinte.
- Diff de backups com A e B lado a lado; checkboxes de permissões de rede alinhados no modal Padrões.

- **Console como PWA (instalável).** `manifest.webmanifest`, ícones (192/512, maskable, iOS), `sw.js` e `offline.html` em `scripts/engine/ui/static/`; a cor da barra acompanha o tema. O service worker só intercepta navegação (página "sem conexão" quando o servidor cai) e nunca toca em `/api`, WebSockets nem guarda o front em cache. Instalar exige HTTPS (ou localhost). Teste: `tests/test_pwa.py`.
- **Hooks de segurança do Claude Code em toda instalação.** A guarda (backup antes de alterar equipamento) passou para `scripts/engine/hooks/guard-netops.sh` e agora vai no pacote de release. O `install.sh` mescla o hook no `.claude/settings.json` com `scripts/engine/hooks/install_claude_hooks.py`, que é idempotente e preserva tema, permissões e outros hooks. `.claude/hooks/guard-netops.sh` fica como atalho de compatibilidade. O caminho foi escolhido porque o atualizador até a 2.3.1 recusa pacotes com arquivos em `.claude/hooks/` (`protected_path`).
- **Instalação em uma linha (Linux):** `curl -fsSL https://raw.githubusercontent.com/RedesBrasil/netops/main/install.sh | sudo bash`. O `install.sh` instala os pacotes do sistema, baixa a última release e a confere (SHA256 e manifesto), grava `.netops-update/installed.json` para o atualizador e cria o `.venv`. Também cria o usuário `netops`, instala o agente `claude`, pede a senha-mestra e registra o serviço `netops-console` no boot. Depois sobe o console pelo `start.sh`, testa e mostra a URL. Suporta apt, dnf/yum, zypper e pacman. Rodar de novo só repara: não substitui código nem dados e não reinicia um console que já está rodando.

- **Tarefas agendadas** (menu Sistema → Tarefas agendadas, `#schedules`). Permite criar, editar, pausar, remover e executar tarefas. São três tipos: **determinística/script**, **agente de IA** (Claude Code headless) e **script + agente** (o script coleta e o agente analisa; saída vazia não aciona a IA). Quem dispara é o cron do sistema (`/etc/cron.d/netops-scheduler`), mesmo com o console desligado. As agendas são avaliadas no fuso do cadastro (padrão `America/Sao_Paulo`). Há histórico por execução e contador de não lidas no menu. O agente que responde `[SILENT]` não notifica; falha sempre notifica. Pelo chat, o agente agenda via `scripts/engine/scheduler/cli.py`. Desenho inspirado no cron do Hermes Agent.

### Correções

- **Acesso a equipamentos = só `session.py`.** `ssh.py` e `telnet.py` foram removidos. O novo `session.py run --host-id <ID> --command ...` faz o lote em uma chamada (conecta, roda e desconecta, com log em `runs/<ts>-session-<id>/`), e `open/exec/close` seguem para o modo interativo. O motor (backup do console, backup de mudança) passa a usar `scripts/engine/lib/cli_runner.py`.
- **Ambiente pronto, sem preparo por pedido.** Todo script CLI (diagnóstico, análise, backup, cofre, agendador, inventário e `_TEMPLATE`) se re-executa sozinho no `.venv`, e `python3 scripts/...` funciona sem ativar nada. Documentação e mensagens padronizadas em `python3`. O README inclui `python-is-python3`.
- `lib/transport.py`: restaurados `open_routeros_api` e `open_napalm`, removidos por engano em 3a94642 (o `api_mikrotik.py` quebrava na importação).

- Aba Claude Code: a persistência da sessão agora é **padrão** (`start.sh` e `restart-console.sh`). F5, troca de aba ou standby não cancelam mais a tarefa em andamento; ao voltar, a aba re-anexa onde estava. `NETOPS_UI_CLAUDE_PERSIST=0` desliga. Limite: reiniciar ou encerrar o console encerra as sessões vivas.

## [2.3.1] - 2026-11-12

### Correções

- Aba Claude Code no celular: a sessão persistente não depende mais do cookie de dono. Sem ele, a aba caía calada no modo clássico e o turno morria ao bloquear a tela; o acesso continua exigindo login.
- Aba Claude Code: envio ao navegador com limite de 10 s. Uma conexão pendurada (celular sem rede) desanexa a aba e o agente segue trabalhando, em vez de travar.
- Aba Claude Code: a reconexão não desiste após 4 quedas. Tenta até 40 vezes com intervalo crescente (3 s a 60 s) e reconecta na hora quando a aba volta à tela, a rede volta ou a página é restaurada.
- Scripts de acesso (`ssh.py`, `telnet.py`, `api_mikrotik.py`, `session.py`): o re-exec no `.venv` do projeto só acontece quando o script é executado direto. Importados como biblioteca, eles substituíam o processo hospedeiro.
- Suíte de testes: não usa o cofre real (roda com o cofre trancado) e isola as preferências, o cache de modelos, o log do agente e o token de transcrição de `runs/claude/`, que antes eram lidos e podiam ser gravados.

### Compatibilidade

- Sem migração de dados e sem novas dependências.

## [2.3.0] - 2026-11-11

### Novidades

- Aba Claude Code: **ditado por voz**. Um microfone ao lado do botão de enviar grava a fala (OGG/Opus, até 10 minutos), transcreve com o Whisper da Cloudflare Workers AI e acrescenta o texto ao campo de mensagem, sem enviar. Em «Padrões» há a seção *Transcrição de áudio*: basta colar o API Token (o Account ID é descoberto sozinho; se o token enxergar várias contas, você escolhe), com atalho para criar o token, teste e remoção. O token fica em `runs/claude/` (0600), cifrado pelo cofre quando destrancado, e nunca volta ao navegador. O microfone só aparece com a Cloudflare configurada e exige HTTPS ou `localhost`.
- Console atrás de proxy reverso/domínio próprio: com login ativo, qualquer Host/Origin é aceito (o acesso é protegido pela sessão, enviada em header, nunca cookie). Sem login, Host/Origin seguem estritos e podem ser ampliados com `NETOPS_UI_ALLOWED_HOSTS`. O servidor confia em `X-Forwarded-*` (`NETOPS_UI_FORWARDED_ALLOW_IPS`); o proxy precisa repassar WebSocket.
- Aba Claude Code: data/hora discreta em cada mensagem; Ctrl/Cmd+clique em «Nova sessão» e nas sessões abre em nova janela.

### Correções

- O login do console não é mais perdido ao reiniciar: a suíte de testes sobrescrevia o arquivo real de sessões; agora o caminho é resolvido na hora e as gravações fazem merge sob trava.
- O relógio de cache da aba Claude começa limpo ao abrir uma conversa nova ou outra.
- Suíte de testes: o cache de sessão do cofre agora é isolado por teste (antes um teste podia trancar o cofre real do console); o teste de atualização a partir de tags antigas não depende mais de rede quando o `requirements.txt` muda; a release roda os testes em paralelo, com limite por teste e falha imediata quando a atualização simulada já falhou.

### Compatibilidade

- Sem migração de dados. Nova dependência Python: `httpx` (instalada pelo atualizador a partir de `requirements.txt`). O ditado não usa nada além do navegador e da Cloudflare; sem configuração, a interface não muda.

## [2.2.0] - 2026-11-11

### Novidades

- Aba Claude Code: dá para enviar mensagens enquanto o agente trabalha. Ao enviar, a aba pergunta: **Enviar agora** (o agente incorpora na tarefa em andamento) ou **Colocar na fila** (só roda quando a tarefa termina). A fila aparece acima da caixa: arraste pela alça ⠿ para reordenar (mouse, toque ou ↑/↓ no teclado), ⚡ envia um item na hora e × o remove. Interromper ou um erro não disparam a fila: as mensagens voltam para a caixa.
- A fila sobrevive ao recarregamento da página e à aba fechada (com a persistência ligada). Uma cópia fica no navegador e é devolvida se o servidor perder a fila; os itens restaurados não disparam sozinhos.
- Aba Claude Code adaptada para celular; esforço, cache e uso de contexto na barra da caixa de mensagem.
- Todas as telas do console passaram a ter URL própria por item aberto e por filtro/busca/ordenação (Hosts, Grupos, Credenciais, Mapas, Backups, Scripts, Relatórios, Execuções, Workflows, Agentes, Boas práticas, Configurações), com deep link e Voltar funcionando. Busca e filtros em barra única, com contador.
- Painel de atualizações em `#settings/updates`.
- Mapas: qualquer mapa, inclusive os de localidade, pode ser excluído (🗑 na barra). A exclusão é suave e o mapa da localidade não é recriado automaticamente; a Rede geral continua não excluível.
- Acesso: sessão SSH/Telnet persistente (1 login, N comandos) em `scripts/tools/access/`.
- Seletor de ícones do host em dropdown.

### Correções

- Depois de reiniciar o console, a reconexão automática da aba Claude reaproveitava a autorização do processo antigo e a conversa perdia a persistência sem aviso. Um F5 encerrava o turno em andamento. A reconexão agora renova essa autorização.
- O relógio do cache da aba Claude sobrevive ao F5.

### Compatibilidade

- Sem migração de dados. `maps.yaml` ganha o campo opcional `deleted` nos mapas excluídos; versões anteriores ignoram o campo e voltariam a exibir esses mapas. O atualizador preserva dados e personalizações. A fila da aba Claude fica só na memória do servidor e no `localStorage` do navegador, sem gravar nada no projeto.

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
