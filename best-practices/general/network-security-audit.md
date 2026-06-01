---
id: network-security-audit
titulo: Auditoria de Segurança de Rede
vendor: general
tags: [security, audit, hardening]
severidade: alta
---

## Resumo

Roteiro cross-vendor para avaliar a postura de segurança de qualquer equipamento de rede.
O agente `tester` usa este guia para classificar os achados de uma auditoria. Cada item
abaixo é uma checagem objetiva — quando falha, vira um achado com severidade.

## Checklist

- [ ] Telnet desabilitado (só SSH para acesso CLI).
- [ ] Acesso de gerência (SSH/API/HTTPS) restrito a sub-redes de gerência.
- [ ] Sem credenciais padrão de fábrica; sem usuário sem senha.
- [ ] SNMP: sem community `public`/`private`; preferir SNMPv3; restringir por ACL.
- [ ] Interface web de gerência só em HTTPS (nunca HTTP puro), e restrita.
- [ ] Firmware/SO em versão suportada e sem CVEs críticas conhecidas.
- [ ] Firewall com política de `input` restritiva (default drop) na borda.
- [ ] Logs habilitados e enviados para um coletor central (syslog).
- [ ] NTP configurado (horário correto é pré-requisito de log confiável).
- [ ] Serviços não usados desligados (reduzir superfície de ataque).
- [ ] Contas administrativas individuais (sem login compartilhado quando possível).

## Detalhamento

**Acesso administrativo.** Telnet trafega senha em texto puro — qualquer um na rede captura.
Use SSH. Restrinja de onde a gerência é aceita: um roteador que aceita SSH de qualquer IP é
um convite. Liste explicitamente as sub-redes de gerência.

**Credenciais.** O vetor de ataque nº 1 é a senha padrão de fábrica. Toda auditoria começa
verificando se `admin/admin`, `admin` sem senha, ou a senha conhecida do fabricante ainda
funcionam.

**SNMP.** Community `public` permite a qualquer um ler a configuração e a topologia. Troque
por uma string única, restrinja por ACL e, idealmente, migre para SNMPv3 (autenticado e
criptografado).

**Exposição.** Um scan de portas do IP de gerência revela o que está exposto. Portas como
23 (Telnet), 21 (FTP), 80 (HTTP), 3389 (RDP) abertas são achados. Use
`scripts/diagnostics/portscan.py`.

**Firmware.** Equipamento desatualizado acumula vulnerabilidades. Compare a versão coletada
com a recomendada pelo fabricante.

## Severidades sugeridas

| Achado | Severidade |
|--------|-----------|
| Credencial padrão / sem senha | CRÍTICO |
| Telnet habilitado e exposto | ALTO |
| SNMP community public | ALTO |
| Gerência aberta para qualquer IP | ALTO |
| Firmware desatualizado | MÉDIO |
| HTTP de gerência sem TLS | MÉDIO |
| Serviço não usado ligado | BAIXO |

## Configuração relacionada

- `config-examples/mikrotik/security-hardening.rsc`
- `config-examples/mikrotik/firewall-baseline.rsc`
- `config-examples/linux/sshd_config`

## Referências

- CIS Benchmarks (por fabricante/SO).
- `best-practices/general/ssh-hardening.md`
