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
