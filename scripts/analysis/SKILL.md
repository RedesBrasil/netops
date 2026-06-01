---
id: analysis
name: Análise
type: script
runtime: python
description: Avaliação de segurança e diff de configuração.
env: []
---

## O que faz

Scripts de análise que o agente `tester` usa para auditar e comparar.

| Script | O que faz |
|--------|-----------|
| `security_assessment.py` | Confronta hosts contra o catálogo `checks.yaml` (portas + config) |
| `config_diff.py` | Diff unificado entre dois arquivos de config (antes × proposta) |

## Quando usar

- `security_assessment.py`: no workflow `security-audit`, para gerar achados priorizados.
- `config_diff.py`: antes de aplicar uma mudança (revisar o diff) e depois (antes × depois).

## Como usar

```bash
# Avaliação de segurança de todos os hosts
python scripts/analysis/security_assessment.py --all

# Avaliação com checagens de configuração (precisa da config coletada)
python scripts/analysis/security_assessment.py --host rt-core-01 \
  --config-file runs/2026-05-18-1430-security-audit/collected/rt-core-01.txt

# Diff de configuração
python scripts/analysis/config_diff.py --before baseline.txt --after proposta.txt
```

## Setup

`pip install -r requirements.txt` (pyyaml). Para o scan completo: `sudo apt install nmap`.
O catálogo de checagens fica em `scripts/analysis/checks.yaml` — adicione checagens lá.

## Exemplos

As checagens cobrem: Telnet/FTP/RDP expostos, SNMP exposto e community padrão, gerência
HTTP sem TLS, API RouterOS sem TLS, SNMP v1/v2c. Os achados saem ordenados por severidade
(CRÍTICO → INFO) e cada um cita a boa prática de referência.
