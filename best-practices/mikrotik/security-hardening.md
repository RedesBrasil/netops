---
id: mikrotik-security-hardening
titulo: Hardening de Segurança no MikroTik RouterOS
vendor: mikrotik
tags: [security, mikrotik, routeros, hardening]
severidade: alta
---

## Resumo

Endurecimento de um roteador/switch MikroTik (RouterOS 7.x). MikroTik vem de fábrica
permissivo — vários serviços ligados e o usuário `admin` sem senha. Este guia lista o que
revisar e endurecer.

## Checklist

- [ ] Usuário `admin` com senha forte (ou removido em favor de um usuário nomeado).
- [ ] Serviços não usados desabilitados em `/ip service` — desligar `telnet`, `ftp`, `www`,
      `api` (sem TLS); manter `ssh`, `winbox` e `api-ssl` conforme necessidade.
- [ ] `/ip service` com `address` restrito à sub-rede de gerência.
- [ ] MAC-server (Winbox/Telnet por MAC) restrito ou desabilitado:
      `/tool mac-server` e `/tool mac-server mac-winbox`.
- [ ] Descoberta de vizinhos (`/ip neighbor discovery-settings`) só nas interfaces internas.
- [ ] Bandwidth-test, romon e proxy desabilitados se não forem usados.
- [ ] SNMP: sem community `public`; restrito por `address`; SNMPv3 quando possível.
- [ ] Firewall `input` com política restritiva (ver `best-practices/mikrotik/firewall.md`).
- [ ] RouterOS atualizado (canal `stable`); verificar `/system package update`.
- [ ] NTP/cliente de horário configurado e logging para syslog remoto.
- [ ] Backup automático da config (`/system backup` e export `.rsc`).

## Detalhamento

**Serviços.** `/ip service print` mostra o estado de cada serviço de gerência. Telnet (23),
FTP (21) e www (80) devem ficar `disabled`. A API na 8728 é sem TLS — prefira `api-ssl`
(8729). Cada serviço mantido recebe um `address` com a sub-rede de gerência.

**MAC-server.** O Winbox por MAC ignora o IP — um atacante na mesma L2 acessa mesmo sem IP
roteável. Restrinja a uma interface-list de gerência.

**Neighbor discovery.** Por padrão o MikroTik anuncia identidade/versão por MNDP em todas as
interfaces, inclusive a WAN. Limite às interfaces internas.

**Atenção ao lockout.** Mudar `/ip service`, firewall ou endereço de gerência pode cortar a
sua própria sessão. Use sempre `/system reboot` agendado ou o `safe-mode` do RouterOS ao
aplicar mudanças sensíveis remotamente.

## Configuração relacionada

- `config-examples/mikrotik/security-hardening.rsc`
- `config-examples/mikrotik/firewall-baseline.rsc`

## Referências

- MikroTik Wiki — "Securing your router".
- `best-practices/general/network-security-audit.md`
