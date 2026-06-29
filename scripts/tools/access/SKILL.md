---
id: device-access
name: Acesso a Equipamentos
type: script
runtime: python
description: Conecta em equipamentos do inventário via SSH, Telnet ou API e roda comandos.
env: []
---

## O que faz

Família de scripts que o agente `executor` usa para conectar nos equipamentos de rede e
rodar comandos — de coleta (read-only) ou de mudança de configuração.

| Script | Acesso | Biblioteca |
|--------|--------|-----------|
| `ssh.py` | SSH multi-fabricante | Netmiko |
| `telnet.py` | Telnet (legado) | Netmiko |
| `api_mikrotik.py` | API RouterOS | librouteros |

## Quando usar

Sempre que precisar executar comandos num host. O método (`ssh`/`telnet`/`api`) já está
definido em `network/hosts.yaml` — escolha o script correspondente.

## Como usar

```bash
# SSH — roda comandos de coleta
python scripts/tools/access/ssh.py --host sw-access-01 --command "show running-config" --save

# Telnet — equipamento legado sem SSH
python scripts/tools/access/telnet.py --host olt-legada-01 --command "show version"

# API MikroTik — dados estruturados
python scripts/tools/access/api_mikrotik.py --host rt-core-01 --path /ip/service --path /user
```

`--save` grava a saída em `runs/<id>/collected/<host>.txt` (ou `.json`).

## Setup

`pip install -r requirements.txt` (netmiko, librouteros). As credenciais vêm de
`network/credentials.yaml` — nunca passe senha por argumento.

## Exemplos

Coletar a configuração de firewall de um MikroTik para auditoria:
```bash
python scripts/tools/access/api_mikrotik.py --host rt-core-01 \
  --path /ip/firewall/filter --path /ip/service --path /snmp --save
```
