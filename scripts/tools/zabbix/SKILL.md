---
id: zabbix
name: Zabbix
type: script
runtime: python
description: Consulta a API do Zabbix — lista itens e triggers de um template.
env: []
---

## O que faz

Lê a API JSON-RPC do Zabbix (`10.8.200.10`) e imprime um raio-X de um template:
itens monitorados agrupados por categoria (chave, tipo, unidade, intervalo) e triggers
com prioridade, status e expressão. **Somente leitura** — não altera nada no Zabbix.

## Quando usar

- Entender o que um template monitora antes de aplicá-lo a um host.
- Auditar alertas (triggers) de um template ou comparar templates.

Para consultas a hosts/itens/histórico de um equipamento, veja também
`scripts/tools/diagnostics/zabbix_api.py` (skill Diagnóstico de Rede).

## Scripts

| Script | Função |
|--------|--------|
| `analise_template.py` | Itens + triggers de um template (padrão: `SNMP LINUX`) |

## Uso

```bash
python3 scripts/tools/zabbix/analise_template.py "SNMP LINUX"
python3 scripts/tools/zabbix/analise_template.py "Mikrotik by SNMP"
```

## Pendência

O token da API está fixo no código (`API_TOKEN`). O certo é ler de `network/credentials.yaml`
(cofre) ou de variável de ambiente, como os scripts de `access/` — e girar o token atual.
