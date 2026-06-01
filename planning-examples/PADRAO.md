# PADRÃO — `planning-examples/`

Documentos modelo de planejamento. O agente `planner` consulta esta pasta antes de montar
um plano novo — para reusar a estrutura e o raciocínio de planos parecidos (REUSE > ADAPT >
CREATE). Não são planos de uma execução real; são **modelos** de como planejar cada tipo de tarefa.

## Formato (`<nome>.plan.md`)

```markdown
# Plano: <título>

## Objetivo
O que se quer alcançar.

## Contexto
O que o planner precisa ler antes (inventário, topologia, best-practices, memória).

## Escopo
Hosts/serviços envolvidos e o que está fora do escopo.

## Passos
Sequência de passos, cada um com o agente responsável.

## Riscos e mitigação
O que pode dar errado e como evitar.

## Rollback
Como desfazer, se a tarefa alterar configuração.

## Critérios de sucesso
Como saber que a tarefa terminou bem.
```

## Como adicionar

Copie `_TEMPLATE.plan.md`. Sempre que um tipo novo de tarefa for planejado, salve o modelo
aqui — assim o próximo planejamento parecido já começa pronto (projeto vivo).
