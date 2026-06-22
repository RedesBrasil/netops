---
id: nome-do-script
name: Nome Legível do Script
type: script
runtime: python
description: Uma linha — o que o script faz.
env: []
---

## O que faz

Descrição do que o script resolve.

## Quando usar

Em que situação o agente deve chamar este script.

## Como usar

```bash
python scripts/<familia>/<script>.py --opcao valor
```

| Argumento | Obrigatório | Descrição |
|-----------|-------------|-----------|
| `--host`  | sim         | Nome do host em `network/hosts.yaml` |

## Setup

Dependências (já em `requirements.txt`) e binários externos, se houver.

## Exemplos

```bash
python scripts/<familia>/<script>.py --host rt-core-01
```
