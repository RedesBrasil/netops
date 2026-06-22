---
id: docs
name: Geração de Documentação
type: script
runtime: python
description: Gera artefatos de documentação da rede a partir do inventário.
env: []
---

## O que faz

Scripts que o agente `documenter` usa para gerar documentação a partir dos dados do
framework.

| Script | O que gera |
|--------|-----------|
| `topology_render.py` | `network/topology.md` — diagrama Mermaid da topologia |

## Quando usar

Sempre que `network/topology.yaml` ou `network/hosts.yaml` mudar — para manter o diagrama
atualizado. Faz parte do passo de documentação dos workflows.

## Como usar

```bash
python scripts/tools/docs/topology_render.py            # grava network/topology.md
python scripts/tools/docs/topology_render.py --stdout   # só imprime
```

## Setup

`pip install -r requirements.txt` (pyyaml).

## Exemplos

Após cadastrar novos hosts e enlaces, regenere o diagrama:
```bash
python scripts/tools/docs/topology_render.py
```
O `network/topology.md` resultante renderiza o grafo direto na IDE e no GitHub.
