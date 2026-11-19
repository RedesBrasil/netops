# NetOps

**Framework multi-agente para operações de redes e infraestrutura.**

## Instalação em uma linha (Linux)

Copie, cole no terminal e pronto:

```bash
# já autenticado como root:
curl -fsSL https://raw.githubusercontent.com/RedesBrasil/netops/main/install.sh | bash
# com uma conta administrativa e sudo:
curl -fsSL https://raw.githubusercontent.com/RedesBrasil/netops/main/install.sh | sudo bash
```

O instalador ([`install.sh`](install.sh)) faz tudo sozinho. Root só **prepara o sistema**: pacotes
(Python, nmap, cron, ping, traceroute, mtr, ssh, git, gh, sudo), a conta operacional `netops` (HOME
`/var/lib/netops`, sem sudo) e o serviço. Depois baixa a última release, confere o SHA256 e extrai em
`/opt/netops`. O `.venv`, o agente `claude` e o cofre são criados **como `netops`**. Pede a
**senha-mestra**, que é o login do console. Registra o serviço systemd do usuário
`netops-console@opt-netops` (sobe no boot, sem login), sobe o console, testa tudo e mostra o endereço
`http://IP:porta/`.

**O NetOps nunca roda como root:** console, IA, subagentes, terminal web, tarefas agendadas e
atualizações usam a conta `netops`. Para administrar **este** servidor como root (ex.: "instale o
Docker aqui"), o instalador cadastra o host **Local** (`NETOPS-LOCAL`, protegido) e a conta de elevação
`netops-admin`, cuja senha aleatória fica só no cofre: com o cofre destrancado, a operação roda como
root sem SSH e sem você digitar senha (ver [`scripts/engine/localadmin/SKILL.md`](scripts/engine/localadmin/SKILL.md)).
Arquivos como root: menu **Arquivos → 🔓 Abrir como root**.

Exige systemd (VM ou CT/LXC com systemd). Testado em Ubuntu 24.04 (CT LXC); Debian 12+, RHEL/Rocky/Alma 9+,
Fedora, openSUSE Tumbleweed e Arch seguem suportados pelo instalador, mas ainda sem validação da conta
dedicada nesta versão.
Rodar de novo é seguro: numa instalação existente ele só confere e repara, sem tocar em código nem
em dados. **Instalação antiga** (console como root) não é migrada sozinha: o instalador avisa e a
migração é um comando próprio, com dry-run e rollback
([`scripts/engine/identity/SKILL.md`](scripts/engine/identity/SKILL.md)).

Opções (`sudo VAR=valor bash` no fim do pipe): `NETOPS_DIR`, `NETOPS_PORT`, `NETOPS_HOST`,
`NETOPS_VERSION`, `NETOPS_NO_LOCALADMIN=1` (não cria o host Local/`netops-admin`).

### Repositório privado: instalação por chave SSH (deploy key)

O repositório oficial é público e usa a linha acima. Esta seção vale para quem mantém uma cópia **privada** do
NetOps: crie uma **deploy key** própria, somente leitura e cadastrada só no seu repositório. Quem a tem consegue
clonar, mas não escrever nem ver outros repositórios. **Nunca publique a chave privada** (README, issue, commit
ou chat): gere a sua pelos passos abaixo e guarde-a só no servidor.

**1. Uma vez por servidor**: prepara o servidor, gera a chave e mostra a parte pública:

```bash
sudo bash <<'EOF'
command -v git >/dev/null && command -v ssh-keygen >/dev/null && command -v curl >/dev/null && command -v python3 >/dev/null || {
  apt-get update -q && apt-get install -y -q git openssh-client curl python3 ca-certificates \
  || dnf install -y git openssh-clients curl python3 ca-certificates \
  || zypper -n install git openssh-clients curl python3 \
  || pacman -Sy --noconfirm git openssh curl python; }
install -d -m 700 /root/.ssh
[ -f /root/.ssh/netops_deploy ] || ssh-keygen -q -t ed25519 -N "" -C "netops-deploy-$(hostname)" -f /root/.ssh/netops_deploy
curl -fsSL https://api.github.com/meta | python3 -c 'import json,sys; [print("github.com", k) for k in json.load(sys.stdin)["ssh_keys"]]' > /root/.ssh/netops_known_hosts
printf '\nCopie a linha abaixo e cadastre em GitHub > RedesBrasil/netops > Settings > Deploy keys > Add deploy key (deixe "Allow write access" DESMARCADO):\n\n'
cat /root/.ssh/netops_deploy.pub
EOF
```

**2. A linha de instalação** (depois de cadastrar a chave; vale também para o próximo servidor com a mesma chave):

```bash
sudo bash -c 'D=$(mktemp -d) && GIT_SSH_COMMAND="ssh -i /root/.ssh/netops_deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/root/.ssh/netops_known_hosts -o StrictHostKeyChecking=yes" git clone -q --depth 1 git@github.com:RedesBrasil/netops.git $D/n && NETOPS_SSH_KEY=/root/.ssh/netops_deploy bash $D/n/install.sh; rm -rf $D'
```

O instalador clona a tag da última release pela chave e monta o mesmo pacote verificado da release (use `NETOPS_VERSION=X.Y.Z`
para outra versão). O botão de atualizar do console usa o `gh`: autentique-o no servidor com `gh auth login`.

Abra esta pasta no Claude Code, Codex, Cursor ou Antigravity e peça, em português, tarefas
de rede — agentes de IA executam de ponta a ponta: leem o inventário, conectam nos
equipamentos (SSH/Telnet/API), coletam dados, consultam a documentação interna, aplicam
mudanças, testam e geram relatórios.

```
"Faça uma avaliação de segurança da minha rede."
"Configure OSPF no MikroTik rt-core-01."
"Gere a documentação atualizada da rede."
```

## Como começar

1. **Instale** com a linha do topo. Instalação manual, sem o instalador:
   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   sudo apt install nmap python-is-python3
   ```
   Pronto: depois disso nenhum pedido precisa preparar ambiente. Todo script se re-executa
   sozinho no `.venv` (`python3 scripts/...` basta, sem `activate`), e o acesso a equipamentos é
   sempre `python3 scripts/tools/access/session.py run --host-id <ID> --command "..."`.
2. **Cadastre seus equipamentos** em `network/hosts.yaml` (copie de
   `network/hosts.example.yaml`). Esse arquivo é git-ignorado.
3. **Cadastre as credenciais** em `network/credentials.yaml` (copie de
   `network/credentials.example.yaml`). Esse arquivo é git-ignorado.
4. **(Recomendado) Criptografe as senhas** com uma senha-mestra:
   ```bash
   python3 scripts/engine/vault/cli.py init       # define a senha-mestra
   python3 scripts/engine/vault/cli.py encrypt     # senhas -> "enc.v1:..."
   python3 scripts/engine/vault/cli.py unlock      # destranca a sessão (no início do trabalho)
   ```
   Os valores ficam criptografados em repouso e são descriptografados só em memória, durante
   a sessão. Ver `scripts/engine/vault/SKILL.md`.
5. **Descreva a topologia** em `network/topology.yaml` (copie de
   `network/topology.example.yaml`). Esse arquivo e o `topology.md` gerado são git-ignorados.
6. **Abra o framework na sua IDE de IA e peça o que precisar.**

Hosts usam IDs inteiros gerados pelo console, permanentes e separados do hostname.
Os scripts aceitam `--host-id 1`; `--host <hostname-ou-alias>` continua disponível para
nomes únicos e automações anteriores. Ao editar o nome, o ID e seus vínculos são mantidos.
Inventários antigos são convertidos automaticamente ao atualizar ou iniciar a versão 2
em modo de escrita, com pré-validação, baseline e recuperação. Referências inválidas
bloqueiam a conversão sem apagar ligações nem inventar hosts. Para conferir os dados
antes ou recuperar uma interrupção, ver `scripts/engine/lib/SKILL.md`.

## Mapas de rede no console

```bash
scripts/engine/ui/start.sh
```

Abra **Mapas** para desenhar a rede no computador ou no celular. O cadastro é o mesmo de
**Hosts**: adicionar em qualquer uma das páginas reflete na outra. O mapa geral inclui todos
os dispositivos; mapas por localidade usam o campo Site. É possível criar mapas adicionais,
referências entre mapas, vários enlaces, dobras de 90 graus, textos e formas.
As ações ficam no botão direito do mapa, dispositivo ou enlace, com alternativa **⋯** no celular.

O layout é salvo no servidor em `network/maps.yaml`, sem duplicar os hosts nem as senhas.
Enlaces e interfaces opcionais continuam em `network/topology.yaml`, editados pela página
**Mapas**. A antiga página Topologia foi removida. A geração Mermaid por script continua
disponível. Ver `scripts/engine/ui/SKILL.md`.

## Atualizações com um clique

Na barra superior do console, use **Verificar atualizações**. O painel mostra a versão instalada
 e o changelog de cada release estável posterior. Depois de salvar formulários e encerrar trabalhos
ativos, escolha **Atualizar para vX.Y.Z** e confirme o backup e a atualização.

O launcher `scripts/engine/ui/start.sh` gerencia a aplicação, o reinício e a recuperação em falha.
Para adotar esse launcher pela primeira vez, reinicie o console manualmente. Depois, o fluxo é pela UI.
O repositório é privado: o GitHub CLI precisa estar autenticado no mesmo usuário/HOME do servidor
(`gh auth login --hostname github.com`). A aplicação exige login no console e não funciona em read-only.

Os pacotes não substituem os dados locais por exemplos da distribuição. Inventário, credenciais,
mapas, memória, configuração local, backups, relatórios, execuções e personalizações são preservados;
a versão 2 converte somente os formatos e referências de identidade necessários. O atualizador
verifica um snapshot privado antes de aplicar e tenta restaurar o código anterior se a nova versão
não iniciar. A conversão dos dados só começa depois da confirmação do código pelo launcher.
Se essa etapa posterior falhar, o código novo permanece e a interface bloqueia as operações com
orientação de recuperação. Código do motor modificado localmente bloqueia a aplicação automática.
Mantenha também um backup externo contra falhas do disco.

Detalhes e recuperação: `scripts/engine/update/SKILL.md`. Para publicar versões, os agentes devem
seguir `core/rules/releases.md`: consultar a última release, incrementar versão e gerar changelog.
O workflow manual **NetOps release** valida testes/pacote antes de publicar; esta implementação
não publica nem atualiza instalações automaticamente sem a ação do operador.

## Estrutura

| Pasta | O que contém |
|-------|--------------|
| `agents/` | Os 5 agentes de IA (coordinator, planner, executor, tester, documenter) |
| `best-practices/` | Boas práticas em texto, por fabricante e gerais |
| `config-examples/` | Exemplos de configuração reais, por fabricante |
| `scripts/` | Scripts de acesso (SSH/Telnet/API) e diagnóstico (portas, ping, tracert) |
| `planning-examples/` | Documentos modelo de planejamento |
| `network/` | Inventário: hosts, credenciais, topologia e config de serviços de backup (`backups.yaml`) |
| `workflows/` | Pipelines que orquestram os agentes |
| `memory/` | Memória e auto-aprendizado — o "projeto vivo" |
| `runs/` · `reports/` | Saída bruta de execuções · relatórios finais |
| `backups/` | Backups de configuração dos equipamentos, um arquivo por host (aba **Backups** do console) |
| `core/` | Config, schemas, templates e regras do framework |

## Princípios

É um **projeto vivo**: cada execução registra o que aprendeu em `memory/`, e esse
conhecimento melhora a documentação para as próximas. Tudo é **padronizado** (ver
`PADRAO.md`) e segue a `constitution.md`.

## Origem

Construído a partir de padrões de três frameworks de referência:
[AIOX](https://github.com/SynkraAI/aiox-core) (autoridade de agentes, handoff, workflows,
multi-IDE), [OpenSquad](https://github.com/renatoasse/opensquad) (estrutura file-based,
formato de agente/skill, catálogo de boas práticas) e
[Hermes](https://github.com/nousresearch/hermes-agent) (memória e auto-aprendizado).
