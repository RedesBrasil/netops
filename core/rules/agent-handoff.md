# Regra — Handoff entre Agentes

Como o contexto passa de um agente para o outro dentro de um workflow. Adaptado do modelo
de handoff do AIOX.

## Princípio

Quando o `coordinator` delega um passo, o agente que entra recebe **apenas duas coisas**:

1. **Seu próprio perfil completo** — o `.agent.md` correspondente (persona, princípios,
   modo de operação).
2. **O artefato de handoff** do agente anterior — preenchido a partir de
   `core/templates/agent-handoff.tmpl.yaml`.

O agente que entra **não** recebe a persona nem o histórico completo do agente anterior —
só o resumo compacto. Isso mantém o contexto enxuto e barato.

## Procedimento

1. Ao terminar seu passo, o agente preenche o template de handoff: o que decidiu, quais
   arquivos tocou, bloqueios em aberto e o que o próximo deve fazer.
2. O artefato preenchido **deve ter menos de 500 tokens**. Se passar, resuma mais.
3. O `coordinator` adota a persona do próximo agente e entrega a ele o artefato.
4. O artefato vivo da execução fica em `runs/<id>/handoff.yaml` (sobrescrito a cada passo).

## Limites

- Decisões: máx. 5 · Arquivos modificados: máx. 10 · Bloqueios: máx. 3.
- `next_action`: no máximo 2 frases.
- Retêm-se no máximo 3 resumos encadeados; o mais antigo é descartado.

## Cadeia padrão

```
coordinator → planner → executor → tester → documenter → coordinator
```

Desvios possíveis: `tester → planner/executor` (quando algo precisa ser corrigido) e
`planner → tester` (quando uma proposta de config deve ser revisada antes de aplicar).
