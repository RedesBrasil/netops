---
id: privileges
name: Permissões da conta operacional (rede sem root; root só com o cofre destrancado)
type: script
runtime: python
description: Prepara o servidor para a conta netops fazer diagnóstico de rede sem root e virar root (sudo ou direto) apenas enquanto o cofre estiver destrancado.
env: []
---

## Modelo

| O quê | Como fica | Precisa do cofre? |
|---|---|---|
| `ping`, `traceroute -I/-T`, `mtr`, `nmap -sS/-O`, `nping`, `tcpdump`, `arping`, `fping`, `arp-scan` | roda direto como `netops` | **não** |
| `sudo <qualquer comando>` | root, sem senha | **sim** — trancado = negado |
| `apt`, `systemctl`/`journalctl` (sem `--user`), `nft`, `iptables`, `docker`, `mount`, `sysctl`, `ss`, `lsof`… digitados no shell | viram root sozinhos ("sudo automático") | **sim** — trancado = rodam como `netops` |
| `rootcat <arq>`, `rootedit <arq>`, `rootsh '<pipeline>'` | ler/editar/redirecionar arquivo do sistema como root | **sim** |
| `git`, `python3`, edição em `/opt/netops` | sempre `netops` (nunca cria arquivo de root na árvore) | — |

Peças (todas root-owned, criadas por `provision.py install`, chamado pelo `install.sh` em toda instalação/reparo):

- `/etc/sysctl.d/60-netops-ping.conf` — `net.ipv4.ping_group_range` na faixa de GIDs mapeada. Em CT LXC não
  privilegiado o padrão do Debian (`0 2147483647`) é recusado pelo kernel e o ping fica só para root.
- `/usr/local/sbin/netops-netcaps` — capabilities de arquivo (`cap_net_raw`/`cap_net_admin`, não setuid) nas
  ferramentas de rede; reaplicado após todo apt (`/etc/apt/apt.conf.d/80netops-netcaps`) e pelo timer
  `netops-netcaps.timer` (boot + 1 h, outras distros). Wrappers `/usr/local/bin/nmap|nping` passam `--privileged`.
- `/etc/sudoers.d/netops-cofre` (`netops ALL=(ALL:ALL) ALL`, `timestamp_timeout=0`) + linha `pam_exec` no topo do
  auth de `/etc/pam.d/sudo` → `/usr/local/sbin/netops-sudo-cofre`. A conta não tem senha: o PAM só libera se a
  sessão do cofre (`/run/user/<uid>/netops/session.key`) for válida — dono/modo, mesmo boot, não expirada e chave
  que abre o **verificador fixado pelo root** em `/etc/netops/vault-verifier.d/<slug>.pin` (HMAC do token Fernet,
  só stdlib). Cada liberação/negação vai para o syslog AUTHPRIV (`netops-sudo-cofre`).
- `/usr/local/share/netops/auto-sudo.bash`, carregado no **topo** do `~/.bashrc` da conta (antes do teste de
  shell interativo, para o Claude Code também carregar). Scripts não interativos não carregam: neles use `sudo`.
- `/etc/netops/privileges.conf` — qual é a conta operacional (lido pelo `netops-sudo-cofre`).

## Uso (root)

```bash
sudo python3 -I -B scripts/engine/privileges/provision.py install --root /opt/netops   # instala/repara (idempotente)
sudo python3 -I -B scripts/engine/privileges/provision.py status  --root /opt/netops   # o que está ativo + cofre agora
sudo python3 -I -B scripts/engine/privileges/provision.py pin     --root /opt/netops   # refixa o verificador
sudo python3 -I -B scripts/engine/privileges/provision.py remove  --root /opt/netops   # desfaz tudo
```

- **Trocou a senha-mestra?** Destranque o cofre e rode `pin` (senão o sudo passa a ser negado).
- `install --trust-creds` só é usado pelo `install.sh` numa instalação **nova** (o cofre acabou de ser criado por
  ele). Fora disso o `pin` exige o cofre destrancado, porque o `credentials.yaml` pertence à conta operacional.
- `sudo -n` **não** funciona (o sudo recusa antes de chamar o PAM). Use `sudo` comum.

## Limites (honestos)

- O cofre é um **portão operacional**, não uma fronteira contra a própria conta `netops`: enquanto destrancado, a
  chave fica num arquivo que a conta lê; um processo malicioso dela poderia guardá-la e liberar o sudo depois.
- O sudo não aplica as permissões por usuário do console (`server.admin`): quem tem terminal/aba Claude no console
  vira root enquanto o cofre estiver destrancado. O host Local (`scripts/engine/localadmin/`) continua aplicando.
- Usar `sudo` não renova o TTL do cofre (15 min sem uso, `vault.session_ttl_seconds`).
