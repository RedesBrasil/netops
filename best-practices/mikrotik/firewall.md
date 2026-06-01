---
id: mikrotik-firewall
titulo: Boas Práticas de Firewall no MikroTik
vendor: mikrotik
tags: [security, mikrotik, firewall]
severidade: alta
---

## Resumo

O firewall do RouterOS tem três chains principais: `input` (tráfego destinado ao próprio
roteador), `forward` (tráfego que passa por ele) e `output` (originado nele). A maioria dos
problemas de segurança em MikroTik vem de uma chain `input` permissiva.

## Checklist

- [ ] Chain `input`: aceitar `established`/`related`, aceitar gerência das sub-redes
      confiáveis, e **dropar o resto** (regra final `action=drop`).
- [ ] Aceitar ICMP de forma controlada (não dropar tudo — quebra PMTUD e diagnóstico).
- [ ] Bloquear acesso de gerência vindo da interface WAN.
- [ ] Address-list para gerência e para redes confiáveis (regras legíveis e reutilizáveis).
- [ ] Proteção contra brute force de SSH/Winbox via address-list dinâmica.
- [ ] `fasttrack` para conexões estabelecidas no `forward` (desempenho), com cuidado.
- [ ] Regras comentadas — cada regra explica o que faz e por quê.
- [ ] Ordem importa: regras mais específicas antes; o `drop` final por último.

## Detalhamento

**Chain input — modelo seguro.** A lógica é: deixar passar o que é legítimo e dropar todo o
resto explicitamente. Sem a regra `drop` final, a chain "aceita por omissão" e o roteador
fica exposto.

**ICMP.** Dropar todo ICMP parece seguro mas quebra Path MTU Discovery e diagnóstico.
Aceite os tipos necessários (echo controlado, fragmentation-needed, time-exceeded).

**WAN.** Identifique a(s) interface(s) WAN numa interface-list e bloqueie gerência vinda
delas — mesmo que o firewall `input` esteja correto, é uma camada extra.

**Brute force.** Conexões novas para a porta de SSH/Winbox alimentam uma address-list
escalonada; após N tentativas, o IP entra numa lista de bloqueio temporário.

**Ordem e lockout.** Adicione a regra de aceitar gerência **antes** da regra de `drop`. Ao
aplicar via API/SSH remoto, use `safe-mode` — se a regra te trancar, o RouterOS reverte.

## Configuração relacionada

- `config-examples/mikrotik/firewall-baseline.rsc` — chain `input` completa e comentada.

## Referências

- MikroTik Wiki — "Building Your First Firewall".
- `best-practices/mikrotik/security-hardening.md`
