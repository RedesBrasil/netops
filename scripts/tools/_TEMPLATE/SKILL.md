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
python3 scripts/<familia>/<script>.py --opcao valor
```

| Argumento | Obrigatório | Descrição |
|-----------|-------------|-----------|
| `--host-id` | um dos dois | ID inteiro em `network/hosts.yaml` |
| `--host` | um dos dois | Hostname único ou alias legado |

## Setup

Dependências (já em `requirements.txt`) e binários externos, se houver.

## Exemplos

```bash
python3 scripts/tools/<familia>/<script>.py --host-id 1
```
