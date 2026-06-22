# Plano: Auditoria de Segurança da Rede

## Objetivo

Avaliar a postura de segurança de todos os equipamentos do inventário e produzir um
relatório priorizado com recomendações.

## Contexto

Ler antes: `network/hosts.yaml`, `network/topology.yaml`,
`best-practices/general/network-security-audit.md`, `best-practices/general/ssh-hardening.md`,
os guias `best-practices/<vendor>/` dos fabricantes presentes, e `memory/MEMORY.md`.

## Escopo

- **Inclui:** todos os hosts de `network/hosts.yaml` (ou o subconjunto pedido).
- **Fora do escopo:** qualquer mudança de configuração — esta tarefa é **somente leitura**.

## Passos

1. **coordinator** — validar inventário, definir escopo, criar `runs/<id>/`.
2. **planner** — montar, por host/fabricante, a lista de comandos read-only de auditoria
   (firewall, serviços, usuários, SNMP, versão de firmware).
3. **executor** — conectar e coletar; salvar em `runs/<id>/collected/`.
4. **tester** — rodar `scripts/tools/analysis/security_assessment.py`, confrontar com as boas
   práticas, classificar achados por severidade.
5. **documenter** — gerar o relatório em `reports/` e registrar lições em `memory/`.

## Riscos e mitigação

| Risco | Mitigação |
|-------|-----------|
| Comando de coleta que altera estado | O planner só inclui comandos comprovadamente read-only |
| Falha de conexão em um host | Registrar e seguir; o host vira "não avaliado" no relatório |
| Scan disparar alarme de IDS | Avisar o usuário; usar scan moderado |

## Rollback

Não aplicável — tarefa somente leitura.

## Critérios de sucesso

- Todos os hosts do escopo foram coletados ou marcados como "não avaliados".
- Relatório gerado em `reports/`, com achados priorizados e referências.
- Pelo menos uma lição registrada em `memory/MEMORY.md`.
