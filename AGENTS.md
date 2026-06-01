# NetOps — Instruções para Agentes (Codex / Antigravity / genérico)

Este projeto é o **NetOps**, um framework multi-agente para operações de redes e
infraestrutura. As instruções completas estão em **`CLAUDE.md`** — leia esse arquivo
primeiro; ele vale para qualquer IDE.

## Resumo rápido

O usuário pede tarefas de rede em linguagem natural ("avalie a segurança da minha rede",
"configure OSPF no MikroTik"). Você orquestra agentes que leem o inventário, conectam nos
equipamentos, consultam a documentação interna, executam e documentam.

**Fluxo:** escolher workflow em `workflows/` → carregar `network/` + `memory/` → delegar
aos agentes de `agents/` → consultar `best-practices/` e `config-examples/` → executar via
`scripts/` → gravar saída em `runs/` e relatório em `reports/` → registrar lições em `memory/`.

## Agentes (`agents/`)

- `coordinator` — orquestra e delega.
- `planner` — **planeja** (hosts, comandos, ordem, config + rollback).
- `executor` — **executa** (único que conecta nos equipamentos).
- `tester` — **testa** (audita segurança, valida, verifica pós-mudança).
- `documenter` — documenta e alimenta o `memory/` (projeto vivo).

## Mapa de pastas

`agents/` `best-practices/` `config-examples/` `scripts/` `planning-examples/`
`network/` (inventário) `workflows/` `memory/` `runs/` `reports/` `core/`

## Regras

Leia `constitution.md` (princípios inegociáveis) e `PADRAO.md` (padrão de organização).
Nunca conecte em host fora de `network/hosts.yaml`. Antes de mudar config: baseline +
rollback. Toda execução termina registrando o que aprendeu em `memory/`.
