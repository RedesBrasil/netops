---
id: localadmin
name: Administração Local (root neste servidor, sem SSH)
type: script
runtime: python
description: Executa operações como root no próprio servidor NetOps pelo host Local, com a senha do admin local no cofre (a IA nunca a vê).
env: []
---

## Modelo

- O NetOps roda como a conta `netops` (sem sudo). Root no **próprio servidor** é **por operação**.
- O instalador cria `netops-admin` (senha aleatória, nunca exibida, só no cofre como `CRED_LOCAL_ADMIN`)
  e `/etc/sudoers.d/netops-admin` (`NOPASSWD: ALL` **só** para ela; SSH bloqueado para ela).
- O serviço de usuário `netops-localadmin@<instância>` (`daemon.py`) autentica `su - netops-admin` num PTY
  privado (eco desligado, senha só em memória), confere o UID efetivo `0` por um marcador, roda o comando com
  ambiente limpo (`env -i`, nada da conta `netops`) e `timeout` do lado root, e devolve a saída.
  Ele é separado do console e da IA: processos da IA não conseguem inspecionar a memória dele.
- O host **Local** (`access.method: local`, ex.: `NETOPS-LOCAL`) é criado pelo instalador, ligado à credencial
  e ao ID desta instalação (`local_instance`) e é **protegido**: não se apaga; acesso/credencial/IP/vínculo não mudam.
- Para usar: **cofre destrancado** + usuário com **`server.admin`** (só admin). Sem isso, falha fechada com código.

## Uso (IA e humano)

```bash
# como root, uma operação por comando (sem SSH; não há shell root persistente)
python3 scripts/tools/access/session.py exec --host-id <ID-LOCAL> --timeout 900 --command "apt-get update && apt-get install -y htop"
# backup antes/depois (obrigatório para alteração, como em qualquer host)
python3 scripts/tools/backup/change.py begin --host-id <ID-LOCAL> && python3 scripts/tools/access/session.py exec --host-id <ID-LOCAL> --command "..." ; python3 scripts/tools/backup/change.py end --host-id <ID-LOCAL>
# estado (sem segredos)
python3 scripts/engine/localadmin/cli.py status
```

`cd`/`export` não passam de um comando para o outro — junte no mesmo (`cd /x && ...`). Comando que não
precisa de root roda direto no Bash. Arquivos como root: menu **Arquivos → 🔓 Abrir como root** (sessão
curta de 5 min, faixa vermelha, auditada; nunca disponível para a IA).

## Erros (falha fechada — informe o humano e pare; nunca tente sudo/su/SSH)

| Código | Significado / o que fazer |
|---|---|
| `vault_locked` | Cofre trancado: o humano roda `python3 scripts/engine/vault/cli.py unlock` (ou entra no console) |
| `authorization_denied` | Usuário sem `server.admin` (ou pedido sem `NETOPS_USER` no modo multiusuário) |
| `local_access_disabled` | Desativado: `sudo python3 -I scripts/engine/localadmin/provision.py enable` |
| `credential_missing` / `authentication_failed` | Senha ausente/recusada: `sudo python3 -I scripts/engine/localadmin/provision.py rotate` (sem retentativa automática; há 2 min de espera após falha) |
| `binding_mismatch` | Clone/restore em outra máquina: `sudo python3 -I scripts/engine/localadmin/provision.py rebind` |
| `backend_unavailable` | Serviço parado: `systemctl --user status netops-localadmin@<instância>` (como netops) |
| `timeout` | Prazo estourado: o efeito parcial precisa ser verificado — **não houve rollback** |

## Administração (root, só stdlib, `python3 -I`)

```bash
sudo python3 -I scripts/engine/localadmin/provision.py install   # conta, sudoers, cofre, host Local, serviço
sudo python3 -I scripts/engine/localadmin/provision.py rotate    # senha nova (também recupera cofre perdido)
sudo python3 -I scripts/engine/localadmin/provision.py disable   # trava netops-admin (passwd -l)
sudo python3 -I scripts/engine/localadmin/provision.py enable
sudo python3 -I scripts/engine/localadmin/provision.py rebind    # revalida vínculo (clone/restore)
sudo python3 -I scripts/engine/localadmin/provision.py status
```

Auditoria: `runs/localadmin/audit.jsonl` (0600) + journal/syslog (`netops-localadmin`, AUTHPRIV) + o log de
autenticação do sistema (`su`). Sem senha, prompt de autenticação ou ambiente.

## Limites (documentados no plano 2026-11-19)

- Root local irrestrito é capacidade administrativa ampla. Com o cofre destrancado, outro processo da **mesma**
  conta `netops` pode pedir operações ao serviço: o UID não é fronteira forte — só pessoas confiáveis com shell/IA.
- Gerenciador de pacotes não tem rollback universal: diga antes o que é irreversível.
- Instalar Docker ≠ dar à aplicação controle do daemon: `netops` nunca entra no grupo `docker` por padrão.
- Tarefa agendada não usa root local (escopo inicial).
