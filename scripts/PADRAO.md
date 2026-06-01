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

| Pasta | Conteúdo |
|-------|----------|
| `lib/` | Núcleo reutilizável — `inventory.py`, `vendor_map.py`, `transport.py` |
| `access/` | Conexão com equipamentos — `ssh.py`, `telnet.py`, `api_mikrotik.py` |
| `diagnostics/` | Diagnóstico de rede — `portscan.py`, `ping_advanced.py`, `traceroute_advanced.py` |
| `analysis/` | Análise — `security_assessment.py`, `config_diff.py` |
| `docs/` | Geração de documentação — `topology_render.py` |
| `vault/` | Cofre de credenciais — CLI `init`/`encrypt`/`unlock`/`lock`/`status`/`change-password` |

## Padrão de um script

- Python 3, executável como `python scripts/<familia>/<script>.py [args]`.
- `argparse` com `--help` claro. Funciona offline (imports de rede são preguiçosos).
- Lê o inventário sempre via `lib/inventory.py` — nunca recebe credencial por argumento.
- Saída em JSON ou texto; quando salva, salva em `runs/<id>/`.
- Cada família de scripts tem um `SKILL.md` ao lado descrevendo uso (formato do OpenSquad).

## Como adicionar um script

Copie `scripts/_TEMPLATE/` (tem `SKILL.md` + `script.py`), implemente, e — se for uma
família nova — crie o `SKILL.md` da pasta.
