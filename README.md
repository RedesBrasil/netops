# NetOps

**Framework multi-agente para operações de redes e infraestrutura.**

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

1. **Instale as dependências** (camada de acesso aos equipamentos):
   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   sudo apt install nmap
   ```
2. **Cadastre seus equipamentos** em `network/hosts.yaml` (copie de
   `network/hosts.example.yaml`). Esse arquivo é git-ignorado.
3. **Cadastre as credenciais** em `network/credentials.yaml` (copie de
   `network/credentials.example.yaml`). Esse arquivo é git-ignorado.
4. **(Recomendado) Criptografe as senhas** com uma senha-mestra:
   ```bash
   python scripts/engine/vault/cli.py init       # define a senha-mestra
   python scripts/engine/vault/cli.py encrypt     # senhas -> "enc.v1:..."
   python scripts/engine/vault/cli.py unlock      # destranca a sessão (no início do trabalho)
   ```
   Os valores ficam criptografados em repouso e são descriptografados só em memória, durante
   a sessão. Ver `scripts/engine/vault/SKILL.md`.
5. **Descreva a topologia** em `network/topology.yaml` (copie de
   `network/topology.example.yaml`). Esse arquivo e o `topology.md` gerado são git-ignorados.
6. **Abra o framework na sua IDE de IA e peça o que precisar.**

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

Os pacotes não substituem inventário, credenciais, mapas, memória, configuração local, backups,
relatórios, execuções ou personalizações. O atualizador verifica um snapshot privado antes de aplicar
e tenta restaurar o código anterior se a nova versão não iniciar. Código do motor modificado localmente
bloqueia a aplicação automática. Mantenha também um backup externo contra falhas do disco.

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
