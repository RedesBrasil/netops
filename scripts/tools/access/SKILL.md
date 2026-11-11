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
python scripts/tools/access/ssh.py --host-id 4 --command "show running-config" --save

# Telnet — equipamento legado sem SSH
python scripts/tools/access/telnet.py --host-id 5 --command "show version"

# API MikroTik — dados estruturados
python scripts/tools/access/api_mikrotik.py --host-id 1 --path /ip/service --path /user
```

`--host-id` recebe o ID inteiro, automático e imutável do cadastro. `--host` continua
aceitando nome único ou alias legado, para compatibilidade com automações existentes.
As opções são exclusivas; texto numérico passado a `--host` continua sendo um nome/alias.
A conexão usa IP de gerência e porta do cadastro, nunca o ID como endereço.

`--save` grava a saída em `runs/<execução>/collected/<id-inteiro>.txt` (ou `.json`),
mesmo quando a seleção foi feita pelo nome ou alias. Renomear o host não muda esse caminho.

## Setup

`pip install -r requirements.txt` (netmiko, librouteros). As credenciais vêm de
`network/credentials.yaml` — nunca passe senha por argumento.

## Exemplos

Coletar a configuração de firewall de um MikroTik para auditoria:
```bash
python scripts/tools/access/api_mikrotik.py --host rt-core-01 \
  --path /ip/firewall/filter --path /ip/service --path /snmp --save
```
