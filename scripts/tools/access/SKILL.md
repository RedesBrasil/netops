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
| `session.py` | SSH/Telnet **persistente** (1 login, N comandos) | Netmiko + canal exec Paramiko (Linux) |

### Lote (`ssh.py`) × sessão (`session.py`)

- **Já sei todos os comandos** → `ssh.py` com vários `--command` (1 login, sai no fim).
- **Comando → ler saída → decidir o próximo** → `session.py`: abre 1 vez, cada `exec` reaproveita
  o login (medido: Linux 0,05 s/comando, MikroTik ~0,9 s, contra 1,4–1,6 s+ de login a cada `ssh.py`),
  mantém estado (`enable`, contexto) e não enche o log do equipamento de logins.

```bash
S=$(python scripts/tools/access/session.py open --host-id 2)     # stdout = SESSION_ID
python scripts/tools/access/session.py exec --session $S --command "/ip route print count-only"
python scripts/tools/access/session.py exec --session $S --command "/ping 10.8.8.2" --timing --timeout 5
python scripts/tools/access/session.py list
python scripts/tools/access/session.py close --session $S        # ou close --all
```

- Linux (`vendor` linux/proxmox): cada comando é um canal `exec` no mesmo transporte → exit code
  real e stderr, sem parse de prompt (`cd` não persiste: use `cd /x && cmd`). `open --shell` usa o
  shell interativo do Netmiko.
- Comando contínuo/paginado (ping sem count, `/tool torch`): `exec --timing --timeout N` lê por N s,
  manda Ctrl-C e devolve a saída (`status=interrompido`, rc 0).
- `status=timeout` (rc 3): mandou Ctrl-C e reaprendeu o prompt — a sessão segue viva. Com vários
  `--command`, para no primeiro que falha. Queda de conexão: reconecta **antes** do próximo comando e
  **nunca reenvia** o que estava em curso.
- Fecha sozinha após 10 min ocioso / 2 h de vida (`NETOPS_SESSION_IDLE`, `NETOPS_SESSION_MAX`).
  Socket em `$XDG_RUNTIME_DIR` ou `/tmp/netops-sessions-<uid>/` (0700/0600). Auditoria de cada
  comando/saída em `runs/<ts>-session-<id>/session.log`. A credencial só existe dentro do processo
  da sessão; o cofre precisa estar destrancado no `open`.
- Mudança de config pela sessão segue as mesmas regras: baseline + rollback antes.

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
