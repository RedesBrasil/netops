---
id: device-access
name: Acesso a Equipamentos
type: script
runtime: python
description: Conecta em equipamentos do inventário (SSH/Telnet via session.py, API MikroTik) e roda comandos.
env: []
---

## O que faz

Família de scripts que o agente `executor` usa para conectar nos equipamentos de rede e
rodar comandos — de coleta (read-only) ou de mudança de configuração.

| Script | Acesso | Biblioteca |
|--------|--------|-----------|
| `session.py` | **SSH/Telnet — o ÚNICO script de CLI** (`run` = lote; `open`/`exec`/`close` = persistente) | Netmiko + canal exec Paramiko (Linux) |
| `api_mikrotik.py` | API RouterOS (dados estruturados, só se `access.method: api`) | librouteros |

`ssh.py` e `telnet.py` **não existem mais** (removidos em 12/11/2026): o `session.py` faz tudo o que
eles faziam. O motor (backup do console etc.) usa a biblioteca `scripts/engine/lib/cli_runner.py`.

## Receita — copie e rode (sem preparar nada)

`python3` (ou `python`) do sistema; o script **entra sozinho** no `.venv` do projeto — não ative venv,
não instale nada. Sempre a partir de `/opt/netops` (ou caminho absoluto). Host por `--host-id <ID>`
(ID de `network/hosts.yaml`) ou `--host <nome/alias>`.

```bash
# 1) Lote numa chamada só (já sei os comandos) — o caso mais comum
python3 scripts/tools/access/session.py run --host-id 21 --command "/system identity print" \
  --command "/ip address print"

# 2) Interativo (comando -> ler saída -> decidir o próximo): 1 login, N comandos
S=$(python3 scripts/tools/access/session.py open --host-id 21)    # stdout = SESSION_ID
python3 scripts/tools/access/session.py exec --session $S --command "/ip route print count-only"
python3 scripts/tools/access/session.py exec --session $S --command "/ping 10.8.8.2" --timing --timeout 5
python3 scripts/tools/access/session.py close --session $S        # ou close --all; list = abertas

# Telnet (só se o usuário pedir / equipamento legado): acrescente --telnet no run ou no open
```

Qual usar: **`run`** quando já sei todos os comandos (1 login, sai no fim). **`open/exec`** quando o
próximo comando depende da saída do anterior (medido: Linux 0,05 s/comando, MikroTik ~0,9 s, contra
1,4–1,6 s+ de login a cada nova conexão) — mantém estado (`enable`, contexto) e não enche o log do
equipamento de logins. Não use `ssh`/`sshpass`/`telnet` do sistema: só o `session.py` resolve a
credencial do cofre sem expô-la.

## Comportamento

- Linux (`vendor` linux/proxmox): cada comando é um canal `exec` no mesmo transporte → exit code
  real e stderr, sem parse de prompt (`cd` não persiste: use `cd /x && cmd`). `--shell` usa o
  shell interativo do Netmiko.
- Comando contínuo/paginado (ping sem count, `/tool torch`): `--timing --timeout N` lê por N s,
  manda Ctrl-C e devolve a saída (`status=interrompido`, rc 0).
- `status=timeout` (rc 3): mandou Ctrl-C e reaprendeu o prompt — a sessão segue viva. Com vários
  `--command`, para no primeiro que falha. Queda de conexão: reconecta **antes** do próximo comando e
  **nunca reenvia** o que estava em curso.
- Comando multilinha/aspas complexas: mande em base64 (`echo <b64> | base64 -d | sh`) ou use
  `--commands-file` (um comando por linha, no `run`).
- Sessão persistente fecha sozinha após 10 min ocioso / 2 h de vida (`NETOPS_SESSION_IDLE`,
  `NETOPS_SESSION_MAX`). Socket em `$XDG_RUNTIME_DIR` ou `/tmp/netops-sessions-<uid>/` (0700/0600).
- Auditoria: todo comando/saída (run ou sessão) vai para `runs/<ts>-session-<id>/session.log` — o
  `run` imprime o caminho no fim (`[log] ...`). Esse é o "salvar a coleta"; não há `--save`.
- A credencial só existe dentro do processo; o cofre precisa estar destrancado (senão falha com
  instrução clara — o humano roda `python3 scripts/engine/vault/cli.py unlock`).
- Mudança de config segue as mesmas regras: baseline + rollback antes (workflow apply-config-change).

## Códigos de saída

`0` ok · `1` host fora do inventário / falha de login / cofre trancado · `2` sem comando ·
`3` comando com status ≠ ok (parou a sequência) · `4` sessão inexistente/morta (rode `open` de novo) ·
outro = exit code do comando Linux.

## Host

`--host-id` recebe o ID inteiro, automático e imutável do cadastro. `--host` aceita nome único ou
alias legado. As opções são exclusivas; texto numérico passado a `--host` é tratado como nome/alias.
A conexão usa IP de gerência e porta do cadastro (`access.port`), nunca o ID como endereço.
Nunca conecte em host fora de `network/hosts.yaml`.

## API MikroTik

```bash
python3 scripts/tools/access/api_mikrotik.py --host-id 1 --path /ip/service --path /user
python3 scripts/tools/access/api_mikrotik.py --host rt-core-01 \
  --path /ip/firewall/filter --path /ip/service --path /snmp --save
```

`--save` grava em `runs/<execução>/collected/<id-inteiro>.json`.

## Setup

Nenhum por chamada. Na instalação: `.venv` com `requirements.txt` (netmiko, librouteros) — ver
`README.md`. As credenciais vêm de `network/credentials.yaml` — nunca passe senha por argumento.
