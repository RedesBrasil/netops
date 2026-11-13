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
| (console) **Acessar → Web** | Não é script: botão do console abre Proxmox/Zabbix já logados (`lib/web_login`, ver `memory/web-launch-acessar-web-login-automatico.md`). Pedido "abre a interface web do host X" = peça ao humano clicar em Acessar → Web | — |
| `terminal_link.py` | **Não conecta**: gera o link que abre o terminal web do host numa janela do console (pedido "abre a borda pra mim") | — |

`ssh.py` e `telnet.py` **não existem mais** (removidos em 12/11/2026): o `session.py` faz tudo o que
eles faziam. O motor (backup do console etc.) usa a biblioteca `scripts/engine/lib/cli_runner.py`.

## Receita — copie e rode (sem preparar nada)

`python3` (ou `python`) do sistema; o script **entra sozinho** no `.venv` do projeto — não ative venv,
não instale nada. Sempre a partir de `/opt/netops` (ou caminho absoluto). Host por `--host-id <ID>`
(ID de `network/hosts.yaml`) ou `--host <nome/alias>`.

```bash
# PADRÃO — sessão persistente por host (1 login por host, N comandos, estado mantido)
python3 scripts/tools/access/session.py exec --host-id 21 --command "/ip address print"   # login + abre
python3 scripts/tools/access/session.py exec --host-id 22 --command "ip -br addr"         # outro host, outra sessão
python3 scripts/tools/access/session.py exec --host-id 21 --command "/ip arp print"       # REUSA (sem login)
python3 scripts/tools/access/session.py exec --host-id 21 --command "/ping 10.8.8.2" --timing --timeout 5
python3 scripts/tools/access/session.py list                       # abertas, ocioso/limite
python3 scripts/tools/access/session.py close --host-id 21         # ou close --all (ou espera o idle)

# Lote isolado (conecta, roda, desconecta — sem reuso): só p/ coleta pontual
python3 scripts/tools/access/session.py run --host-id 21 --command "/system identity print"

# SESSION_ID explícito (raro): S=$(... open --host-id 21) [--new força outra] → exec --session $S → close --session $S
# Telnet (só se o usuário pedir / equipamento legado): acrescente --telnet no exec/open/run
```

Qual usar: **`exec --host-id`** sempre que houver mais de um comando no mesmo host, mesmo em chamadas
separadas (comando → ler saída → decidir o próximo) e mesmo alternando entre vários hosts: cada host
mantém sua sessão aberta (medido: Linux 0,02–0,05 s/comando, MikroTik ~0,9 s, contra 1,4–1,6 s+ de
login a cada conexão nova). Mantém estado (`enable`, contexto, variáveis/`cd` no Linux) e não enche o
log do equipamento de logins. `run` só para uma coleta isolada. Não use `ssh`/`sshpass`/`telnet` do
sistema: só o `session.py` resolve a credencial do cofre sem expô-la.

## Comportamento

- Linux (`vendor` linux/proxmox): **1 login + 1 shell persistente** (`bash -l`, ou `sh -l`) por
  sessão/`run`. Todos os comandos rodam no MESMO shell (mesmo `$$`): `export`, `cd`, funções,
  `source` (ex.: `. ~/.nvm/nvm.sh`) e venv **persistem** entre `exec`s — com exit code real e stderr
  separado (sem PTY; fim do comando detectado por marcador aleatório). `modo=shell-persistente`.
  - stdin dos comandos = `/dev/null` (nada de prompt interativo; `read` retorna na hora).
  - `exit`/`set -e` que derruba o shell: devolve a saída e o exit code; o próximo comando sobe um
    shell novo **no mesmo login** e avisa `AVISO: shell novo — variáveis/cd anteriores foram perdidos`.
  - Processo em background que deve sobreviver ao `close`: `setsid nohup cmd >/tmp/x.log 2>&1 &`.
  - Host sem `base64`/shell restrito: cai sozinho para `modo=exec-por-comando` (sem estado).
  - `--shell` força o shell do Netmiko com PTY (raro: só p/ comando que exige terminal; sem exit code).
- Rede (MikroTik/Cisco/Huawei...): shell Netmiko único por sessão — contexto/`enable` persistem.
- Comando contínuo/paginado (ping sem count, `/tool torch`): `--timing --timeout N` lê por N s,
  manda Ctrl-C e devolve a saída (`status=interrompido`, rc 0).
- `status=timeout` (rc 3): interrompe (Ctrl-C na rede; SIGINT nos filhos do shell no Linux) — a
  sessão e o estado seguem vivos. Se nem assim volta (loop em builtin), o shell é morto e o próximo
  comando abre outro (com o aviso de estado perdido). Com vários
  `--command`, para no primeiro que falha. Queda de conexão: reconecta **antes** do próximo comando e
  **nunca reenvia** o que estava em curso.
- Comando multilinha/aspas complexas: mande em base64 (`echo <b64> | base64 -d | sh`) ou use
  `--commands-file` (um comando por linha, no `run`).
- Sessão persistente fecha sozinha após **`access.session_idle_minutes`** sem comando (padrão **5 min**;
  `core/config/project-config.yaml` ou console → **Configuração** → "Sessão de acesso aos equipamentos").
  Relido a cada 5 s pelas sessões: mudar a config vale na hora, até para as já abertas.
  `NETOPS_SESSION_IDLE=<segundos>` sobrepõe (testes). Vida máxima 2 h (`NETOPS_SESSION_MAX`). O cofre
  precisa estar destrancado só para ABRIR; sessão já aberta segue funcionando se ele re-trancar.
  Socket em `$XDG_RUNTIME_DIR` ou `/tmp/netops-sessions-<uid>/` (0700/0600); reuso sob trava por host.
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
