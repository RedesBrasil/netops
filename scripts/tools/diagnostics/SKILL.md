---
id: diagnostics
name: Diagnóstico de Rede
type: script
runtime: python
description: Testes de conectividade — scan de portas, ping avançado e traceroute.
env: []
---

## O que faz

Scripts de diagnóstico que o agente `tester` usa para validar conectividade e mapear
exposição de serviços — sem precisar logar no equipamento.

| Script | O que mede |
|--------|-----------|
| `portscan.py` | Portas TCP abertas / serviços expostos (nmap, fallback socket) |
| `ping_advanced.py` | Perda de pacotes e latência (RTT min/avg/max) |
| `traceroute_advanced.py` | Caminho de rede salto a salto |

## Quando usar

- Auditoria de segurança: `portscan.py` revela Telnet/SNMP/HTTP expostos.
- Troubleshooting: `ping_advanced.py` e `traceroute_advanced.py` localizam onde está a perda.
- Verificação pós-mudança: confirmar que um serviço subiu/caiu como esperado.

## Como usar

```bash
python scripts/tools/diagnostics/portscan.py --host rt-core-01
python scripts/tools/diagnostics/ping_advanced.py --target 8.8.8.8 --count 20
python scripts/tools/diagnostics/traceroute_advanced.py --host srv-web-01
```

Todos aceitam `--host` (nome no inventário) ou `--target` (IP/nome direto).

## Setup

`ping` já vem no sistema. Para o melhor resultado instale:
`sudo apt install nmap traceroute`.

## Exemplos

Checar se um MikroTik tem Telnet (23) ou API sem TLS (8728) expostos:
```bash
python scripts/tools/diagnostics/portscan.py --host rt-core-01 --ports 22,23,8728,8729
```
