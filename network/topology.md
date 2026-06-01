# Topologia da Rede

> Arquivo **gerado** por `scripts/docs/topology_render.py`. Não edite à mão.

```mermaid
graph TD
    rt-core-01["rt-core-01<br/>mikrotik · core"]
    rt-dist-01["rt-dist-01<br/>mikrotik · distribution"]
    srv-web-01["srv-web-01<br/>linux · server"]
    sw-access-01["sw-access-01<br/>cisco · access"]

    rt-core-01 ---|"10G fiber"| rt-dist-01
    rt-dist-01 ---|"1G copper"| sw-access-01
    sw-access-01 ---|"1G copper"| srv-web-01
```

## Segmentos lógicos

| Segmento | VLAN | Sub-rede |
|----------|------|----------|
| Gerência | 99 | 10.0.0.0/24 |
| Acesso | 10 | 10.0.10.0/24 |
| Servidores | 20 | 10.0.20.0/24 |

_Gerado em: 2026-05-18 21:02 UTC — 4 host(s), 3 enlace(s)._
