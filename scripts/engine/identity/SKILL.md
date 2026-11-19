---
id: identity-migration
name: Migração para a conta dedicada netops
type: script
runtime: python
description: Migra uma instalação legada (console como root) para a conta operacional netops, com dry-run, baseline, journal e rollback.
env: []
---

## Quando usar

Instalação antiga (antes do layout 2) roda o console como **root**: `install.sh` e o console avisam
"instalação LEGADA". A migração deixa console, IA, terminal, agendador e atualizador rodando como `netops`.
**Só root roda** (o humano, numa janela de manutenção) — nunca a IA por conta própria.

## Passo a passo

```bash
sudo python3 -I /opt/netops/scripts/engine/identity/migrate.py plan      # dry-run: inventário + bloqueios
# recomendado em produção: snapshot/backup externo da VM/CT antes (ex.: pct snapshot <CT> antes-netops)
sudo python3 -I /opt/netops/scripts/engine/identity/migrate.py apply     # console cai ~1 min
#   valide: login, aba Claude (/login de novo), conversas e memória, tarefas agendadas
sudo reboot                                                              # confirma o boot sem login
sudo python3 -I /opt/netops/scripts/engine/identity/migrate.py commit
# administração Local (etapa própria, com o cofre destrancado)
sudo python3 -I /opt/netops/scripts/engine/localadmin/provision.py install
```

Antes do `commit`, `migrate.py rollback` devolve dono/modo, unidade e cron antigos e religa o console root.
Dados novos são preservados; o banco **não** é restaurado às cegas (cópia de antes no baseline).

## O que muda

| Antes | Depois |
|---|---|
| console root (`/etc/systemd/system/netops-console.service` ou unidade transitória) | `netops-console@<slug>.service` do usuário `netops` (linger) |
| `/root/.claude` (login + conversas) | `/var/lib/netops/.claude` (memória e conversas copiadas; **login novo** na aba) |
| `/etc/cron.d/netops-scheduler` (root) | crontab de `netops` (bloco `netops-scheduler`) |
| arquivos root/netops misturados | tudo de `netops` (sem seguir links nem atravessar montagens) |
| — | `/etc/netops/instances/<slug>.env` (identidade, root-owned) |

Baseline/journal: `/var/backups/netops-migration/<slug>-<data>/` (root 0700): `ownership.jsonl`, cópia
consistente do SQLite, `network/`, `core/config`, cron e unidade antigos, `SHA256SUMS`, `RESTAURAR.txt`.

## Cuidados

- Várias instalações na mesma máquina: cada uma migra separada; todas usam a conta `netops` e o mesmo
  perfil da IA (conversas separadas por pasta). A que não foi migrada continua root.
- Não migre com atualização pendente (`.netops-update/journal.json`) — o `plan` bloqueia.
- Mantenha acesso de resgate fora do console (ex.: `pct enter` no Proxmox) durante a janela.
