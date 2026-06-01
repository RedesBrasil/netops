---
id: ssh-hardening
titulo: Hardening de Acesso SSH
vendor: general
tags: [security, ssh, hardening, access]
severidade: alta
---

## Resumo

SSH é o canal de administração padrão. Mal configurado, vira a porta de entrada do atacante.
Este guia cobre o endurecimento do SSH em equipamentos de rede e servidores Linux.

## Checklist

- [ ] Telnet desabilitado — SSH é o único acesso CLI.
- [ ] Autenticação por chave preferida à senha (obrigatório em servidores Linux).
- [ ] Login direto de `root`/`admin` restrito ou desabilitado quando o equipamento permite.
- [ ] Acesso SSH restrito por IP/sub-rede de gerência (firewall ou `allowed-address`).
- [ ] Porta padrão (22) aceitável se houver ACL; trocar a porta é ofuscação, não segurança.
- [ ] Algoritmos fracos desabilitados (sem `ssh-rsa` legado, sem ciphers CBC obsoletos).
- [ ] Timeout de sessão ociosa configurado.
- [ ] Tentativas de login limitadas (proteção contra brute force).
- [ ] Banner de aviso configurado (requisito legal/compliance em muitos casos).

## Detalhamento

**Chave vs senha.** Senha é adivinhável e sujeita a brute force. Chave (ed25519 de
preferência) elimina esse vetor. Em servidores Linux, o padrão deve ser
`PasswordAuthentication no` após distribuir as chaves.

**Restrição por origem.** Mesmo com SSH bem configurado, expô-lo à internet inteira é risco
desnecessário. Restrinja à sub-rede de gerência — no MikroTik via `/ip/firewall` e
`/ip/service address`; no Linux via firewall + `AllowUsers`/`Match Address`.

**Algoritmos.** Equipamentos antigos negociam ciphers/MACs fracos. Verifique com
`nmap --script ssh2-enum-algos` e desabilite o que for obsoleto.

**Brute force.** Limite tentativas: `MaxAuthTries` no Linux; address-list dinâmica no
MikroTik (ver `config-examples/mikrotik/firewall-baseline.rsc`).

## Configuração relacionada

- `config-examples/linux/sshd_config`
- `config-examples/mikrotik/security-hardening.rsc`

## Referências

- Mozilla OpenSSH Guidelines.
- `best-practices/general/network-security-audit.md`
