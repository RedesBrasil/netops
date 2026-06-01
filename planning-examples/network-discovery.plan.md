# Plano: Descoberta e Documentação da Rede

## Objetivo

Levantar o estado real da rede (hosts ativos, vizinhos, enlaces) e gerar/atualizar a
documentação de topologia.

## Contexto

Ler antes: `network/hosts.yaml`, `network/topology.yaml` e `memory/MEMORY.md`.

## Escopo

- **Inclui:** hosts do inventário e a descoberta dos vizinhos diretos deles.
- **Fora do escopo:** mudança de configuração; varredura de faixas de IP não autorizadas.

## Passos

1. **coordinator** — definir o escopo da descoberta a partir do inventário.
2. **executor** — em cada host, coletar tabela de vizinhos (LLDP/CDP/MNDP), interfaces e
   rotas; salvar em `runs/<id>/collected/`.
3. **tester** — opcional: `scripts/diagnostics/portscan.py` e `ping_advanced.py` para
   confirmar quem está ativo.
4. **planner** — comparar o descoberto com `network/topology.yaml`; apontar divergências.
5. **documenter** — atualizar `network/topology.yaml`, rodar
   `scripts/docs/topology_render.py` e registrar lições.

## Riscos e mitigação

| Risco | Mitigação |
|-------|-----------|
| Vizinho descoberto fora do inventário | Reportar ao usuário; não conectar nele |
| Divergência inventário × realidade | Documentar a divergência, não sobrescrever sem aval |

## Rollback

Não aplicável — tarefa somente leitura (só atualiza documentação local).

## Critérios de sucesso

- Vizinhos e enlaces coletados de todos os hosts acessíveis.
- `network/topology.yaml` e `network/topology.md` atualizados.
- Divergências entre inventário e realidade documentadas.
