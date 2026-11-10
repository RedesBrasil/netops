# PADRÃO — `scripts/`

Scripts Python que o agente `executor` (acesso) e o `tester` (diagnóstico/análise) invocam
via terminal. A "inteligência" fica nos agentes; o trabalho técnico determinístico fica aqui.

## Stack padrão de acesso

Resposta à pergunta "SSH cru, Paramiko ou Telnet?": **não** use SSH cru nem Telnet como
padrão. A camada padrão é o **Netmiko** — ele usa Paramiko por baixo, mas já trata
prompt/paginação e fala com 100+ fabricantes via `device_type`.

| Camada | Biblioteca | Papel |
|--------|-----------|-------|
| SSH/Telnet multi-fabricante | **Netmiko** | Padrão para rodar comandos CLI |
| Coleta estruturada + diff | **NAPALM** | Cisco/Juniper/Arista — getters e `compare_config` |
| API MikroTik | **librouteros** | RouterOS via API nativa (dados estruturados) |
| Scan de portas/segurança | **nmap** (binário) | `portscan.py`, `security_assessment.py` |

## Estrutura

`scripts/` separa o **motor** do NetOps (infra estática) dos **scripts operacionais**
(o que o usuário cria/edita). Só os operacionais aparecem na página **Scripts** do console.

### `engine/` — motor do NetOps (não aparece na UI)

| Pasta | Conteúdo |
|-------|----------|
| `engine/lib/` | Núcleo reutilizável — `inventory.py`, `vendor_map.py`, `transport.py` |
| `engine/vault/` | Cofre de credenciais — CLI `init`/`encrypt`/`unlock`/`lock`/`status`/`change-password` |
| `engine/ui/` | Console web (FastAPI + SPA). Subir SEMPRE por `scripts/engine/ui/start.sh` |

### `tools/` — scripts operacionais (CRUD pela UI)

| Pasta | Conteúdo |
|-------|----------|
| `tools/access/` | Conexão com equipamentos — `ssh.py`, `telnet.py`, `api_mikrotik.py` |
| `tools/diagnostics/` | Diagnóstico de rede — `portscan.py`, `ping_advanced.py`, `traceroute_advanced.py` |
| `tools/analysis/` | Análise — `security_assessment.py`, `config_diff.py` |
| `tools/docs/` | Geração de documentação — `topology_render.py` |
| `tools/_TEMPLATE/` | Modelo (`SKILL.md` + `script.py`) para criar um script/família novos |

## Padrão de um script

- Python 3, executável como `python scripts/tools/<familia>/<script>.py [args]`.
- `argparse` com `--help` claro. Funciona offline (imports de rede são preguiçosos).
- Lê o inventário sempre via `from lib.inventory import …` (o motor em `engine/lib/`,
  posto no `sys.path` pelo bootstrap do script) — nunca recebe credencial por argumento.
- Saída em JSON ou texto; quando salva, salva em `runs/<id>/`.
- Cada família tem um `SKILL.md` ao lado descrevendo o uso (formato do OpenSquad); ele
  aparece como ícone 📄 ao lado dos scripts da família na UI.

## Como adicionar um script

Copie `scripts/tools/_TEMPLATE/` (tem `SKILL.md` + `script.py`), implemente, e — se for
uma família nova — crie o `SKILL.md` da pasta. Ou crie direto pela página **Scripts** do
console web (botão **+ Novo**, caminho `familia/arquivo.py`).


### Editor visual do console

`engine/ui/maps/` contém o editor JSX e seu build de manutenção. É uma exceção isolada à
SPA sem build: o operador recebe o módulo ESM/CSS já gerado em `static/vendor/`. Não precisa
de npm para subir o console. Mantém Preact compartilhado e dependências locais pinadas.
O padrão de uso e estrutura está em `engine/ui/maps/SKILL.md`.


A biblioteca de imagens do editor fica em `engine/ui/static/icons/network/`, com originais,
catálogo, miniaturas e checksums. `engine/ui/vendor_icons.py` atualiza esses assets a partir
de uma revisão fixa, sem ser executado no servidor. Ver README local e `engine/ui/SKILL.md`.
