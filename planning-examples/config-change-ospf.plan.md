# Plano: Configurar OSPF em um MikroTik

## Objetivo

Habilitar o roteamento OSPF em um roteador MikroTik para que ele troque rotas com os
vizinhos da rede, com baseline e rollback garantidos.

## Contexto

Ler antes: `network/hosts.yaml` (o host-alvo), `network/topology.yaml` (vizinhos e enlaces),
`best-practices/mikrotik/security-hardening.md`, `config-examples/mikrotik/ospf-basic.rsc`,
`memory/learned-patterns.yaml` (quirks de OSPF no RouterOS).

## Escopo

- **Inclui:** o roteador MikroTik indicado e a configuração da instância/área OSPF.
- **Fora do escopo:** mudança de firewall, de endereçamento IP ou de outros hosts.

## Passos

1. **coordinator** — confirmar host-alvo, áreas/redes desejadas e janela de manutenção.
2. **executor** — baseline: coletar `/routing/ospf/...` e `/ip/route` atuais.
3. **planner** — adaptar `config-examples/mikrotik/ospf-basic.rsc` ao host (router-id,
   redes, interfaces); gerar `change.txt` e o `rollback.txt` (remover a instância criada).
4. **tester** — validar a sintaxe contra o exemplo MikroTik; conferir impacto na topologia.
5. **executor** — aplicar em `safe-mode`; capturar o estado pós-mudança.
6. **tester** — confirmar adjacências (`/routing/ospf/neighbor`) e rotas aprendidas.
7. **documenter** — registrar a mudança e as lições.

## Riscos e mitigação

| Risco | Mitigação |
|-------|-----------|
| Sintaxe RouterOS 6 vs 7 diferente | Usar o exemplo v7; confirmar `/system/resource` |
| Loop/rota inesperada | Começar com interfaces passivas onde não há vizinho OSPF |
| Perda de gerência | Aplicar em `safe-mode`; rollback automático em falha |

## Rollback

`runs/<id>/proposals/<host>.rollback.txt` — remove a instância, a área e os
interface-templates criados, voltando ao estado do baseline.

## Critérios de sucesso

- Adjacências OSPF formadas com os vizinhos esperados.
- Rotas OSPF presentes em `/ip/route`.
- Conectividade de gerência preservada.
