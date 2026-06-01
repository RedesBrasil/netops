# PADRÃO — `core/`

O `core/` guarda a infraestrutura do framework: config, schemas, templates e regras. É a
parte estável — raramente muda. O conhecimento de rede NÃO vive aqui (vive em
`best-practices/`, `config-examples/`, `memory/`).

## Subpastas

| Pasta | Conteúdo |
|-------|----------|
| `config/` | Configuração do framework: `core-config.yaml`, `framework-config.yaml`, `project-config.yaml` |
| `schemas/` | Schemas JSON de validação. Hoje: `inventory.schema.json` (usado por `scripts/lib/inventory.py`). O formato de agente e de workflow é definido pelos `_TEMPLATE` das pastas `agents/` e `workflows/`. |
| `templates/` | Modelos: `agent-handoff.tmpl.yaml`, `run-state.tmpl.json`, `security-report.tmpl.md`, `change-record.tmpl.md` |
| `rules/` | Regras carregadas por todos os agentes: `agent-handoff.md`, `connection-safety.md`, `memory-protocol.md` |

## Regras (`core/rules/`)

São de leitura obrigatória para os agentes nas situações que cobrem:

- `agent-handoff.md` — como o contexto passa entre agentes.
- `connection-safety.md` — como conectar e mudar config com segurança.
- `memory-protocol.md` — como ler/gravar memória e fazer a reflexão (projeto vivo).

## Templates (`core/templates/`)

Modelos a copiar — não os edite ao executar uma tarefa; copie e preencha.
