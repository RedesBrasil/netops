---
id: linux-server-hardening
titulo: Hardening de Servidor Linux
vendor: linux
tags: [security, linux, hardening, server]
severidade: alta
---

## Resumo

Endurecimento de um servidor Linux de infraestrutura (Ubuntu/Debian/RHEL). Cobre acesso,
superfície de ataque, atualização e auditoria. Vale para hosts físicos, VMs e hosts Proxmox.

## Checklist

- [ ] SSH endurecido: chave em vez de senha, `PermitRootLogin` controlado (ver `ssh-hardening`).
- [ ] Firewall de host ativo (`ufw`/`firewalld`/`nftables`) com política default deny no input.
- [ ] Apenas serviços necessários ouvindo — revisar `ss -tulpn`.
- [ ] Pacotes atualizados; atualizações de segurança automáticas habilitadas (`unattended-upgrades`).
- [ ] Contas de usuário individuais; `sudo` em vez de login direto de `root`.
- [ ] Senhas de contas locais fortes; contas de sistema sem shell de login.
- [ ] Logs centralizados (syslog/journald → coletor remoto) e horário via NTP.
- [ ] `fail2ban` (ou equivalente) protegendo SSH e serviços expostos.
- [ ] Permissões corretas em arquivos sensíveis (`/etc/shadow`, chaves, configs de serviço).
- [ ] Backup definido e testado.

## Detalhamento

**Superfície de ataque.** `ss -tulpn` lista o que está ouvindo. Tudo que não for necessário
deve ser parado e desabilitado (`systemctl disable --now <serviço>`). Cada porta aberta é
uma porta a defender.

**Firewall de host.** Não confie só no firewall de borda. O host deve ter seu próprio
firewall com default deny no input, abrindo só o necessário (SSH da gerência, portas do
serviço que ele provê).

**Atualização.** A maioria dos comprometimentos explora CVE conhecida e já corrigida.
`unattended-upgrades` para correções de segurança reduz drasticamente a janela de exposição.

**Acesso.** Logar como `root` direto elimina rastreabilidade. Cada admin tem sua conta e usa
`sudo` — o log mostra quem fez o quê.

**fail2ban.** Monitora logs e bane temporariamente IPs com muitas falhas de autenticação —
defesa eficaz e barata contra brute force.

## Configuração relacionada

- `config-examples/linux/sshd_config` — SSH endurecido (exemplo seed).
- Firewall de host (ufw/nftables): a adicionar em `config-examples/linux/` conforme o projeto evolui.

## Referências

- CIS Benchmark para a distribuição em uso.
- `best-practices/general/ssh-hardening.md`, `best-practices/linux/services-hardening.md`
