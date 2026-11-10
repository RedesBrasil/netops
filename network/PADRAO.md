# PADRÃO — `network/` (Inventário e Topologia)

Esta pasta é a **fonte da verdade da rede**. O agente só conhece equipamentos descritos aqui.

## Arquivos

| Arquivo | Versionado? | O que é |
|---------|-------------|---------|
| `hosts.yaml` | não | Inventário de equipamentos e como acessá-los |
| `credentials.yaml` | **NÃO** (git-ignorado) | Credenciais (cofre criptografado `enc.v1:`, ou texto puro) |
| `credentials.example.yaml` | sim | Modelo de credenciais, sem segredos reais |
| `topology.yaml` | não | Enlaces entre hosts (mapa lógico/físico) |
| `topology.md` | não | Diagrama Mermaid gerado de `topology.yaml` |
| `maps.yaml` | não | Apresentação dos mapas, posições, formas, textos e trajetos |
| `maps.example.yaml` | sim | Modelo de apresentação, sem dados reais |

## `hosts.yaml`

Estrutura: `groups` (defaults herdados) + `hosts`. Um host herda os campos do seu `group`
e pode sobrescrever qualquer um.

Campos de um host:

| Campo | Obrigatório | Valores |
|-------|-------------|---------|
| `hostname` | sim | FQDN ou nome |
| `mgmt_ip` | sim | IP de gerência |
| `vendor` | sim (host ou grupo) | `mikrotik`, `unifi`, `ubiquiti`, `cisco`, `huawei`, `proxmox`, `vmware`, `datacom`, `linux`, `fiberhome`, `intelbras` |
| `model` | recomendado | Modelo do equipamento |
| `icon` | opcional | ID da biblioteca local: `router`, `switch`, `linux-server`, `windows-server`, `access-point`, `olt`, `cloud`, `pc`, `proxmox`, `vmware` |
| `role` | recomendado | `core`, `distribution`, `access`, `firewall`, `wireless`, `server`, `other` |
| `access.method` | sim (host ou grupo) | `ssh`, `telnet`, `api`, `winbox` |
| `access.port` | sim (host ou grupo) | Porta TCP |
| `credential` | sim (host ou grupo) | Nome da credencial em `credentials.yaml` |
| `site` | recomendado | Local físico |
| `group` | opcional | Nome do grupo do qual herda |
| `notes` | opcional | Observações livres |

Validar: `python scripts/engine/lib/inventory.py --validate` (usa `core/schemas/inventory.schema.json`).

## `credentials.yaml`

Credenciais **nomeadas** (`cred_<algo>`) que os hosts referenciam pelo nome — assim a mesma
senha não se repete.

Campos de uma credencial: `username`, `password`, e opcionais `secret` (enable do Cisco),
`key_file` (chave SSH), `api_ssl`.

**Criptografia (cofre).** As senhas podem ser criptografadas com uma senha-mestra: cada valor
secreto vira `enc.v1:<token>` e é descriptografado só em memória, durante a sessão. Gerencie com
`scripts/engine/vault/cli.py` (`init` → `encrypt` → `unlock`/`lock`); ver `scripts/engine/vault/SKILL.md`. A
descriptografia acontece só em `scripts/engine/lib/inventory.py:resolve_secret()` — os hosts nunca mudam,
e arquivos mistos (parte texto puro, parte `enc.v1:`) são válidos.

## `topology.yaml`

Lista de `links`: cada link tem `a` e `b` com `host` obrigatório e `port` opcional.
`media`, `speed` e `desc` também são opcionais. É possível informar as interfaces depois.
Opcionalmente `segments` (VLANs/sub-redes). O script `scripts/tools/docs/topology_render.py` lê
este arquivo + `hosts.yaml` e regenera `topology.md` com um diagrama Mermaid.

## Como adicionar um equipamento

1. Adicione o host em `hosts.yaml` (use um `group` existente ou crie um).
2. Se a credencial for nova, adicione-a em `credentials.yaml`.
3. Adicione os enlaces dele em `topology.yaml`.
4. Rode `python scripts/tools/docs/topology_render.py` para atualizar `topology.md`.


## `maps.yaml`

A página **Mapas** do console lê o cadastro único de `hosts.yaml` e os enlaces de
`topology.yaml`. O arquivo de mapas guarda somente apresentação e referências:

- `kind: all`: mapa geral, sempre com todos os hosts.
- `kind: site`: mapa automático por `site` efetivo do host, incluindo herança de grupo.
  Se uma única localidade contém todos os hosts, sua visão é unificada em `all`, sem
  duplicar o seletor. O layout geral tem precedência, e ajustes exclusivos da localidade
  são incorporados. Referências antigas apontam para o geral; mapas `custom` são mantidos.
- `kind: custom`: mapa adicional, com associação explícita em `members`.
- `positions`: coordenadas por ID de host. O cadastro não é duplicado.
- `objects`: textos (`note`), formas (`shape`) e atalhos para outros mapas (`reference`).
- `edges`: layout por ID estável do enlace real: `anchors` e `route`.
- `visual_links`: conexões visuais entre referências de mapas e hosts. Não representam
  enlace físico nem entram no diagrama Mermaid.

Os IDs de enlaces legados são fixados em `topology.yaml` na primeira edição gráfica.
Editar um enlace no mapa preserva o ID; remover um enlace limpa seus trajetos.
Renomear host atualiza os mapas e a topologia. Excluir host remove também seus enlaces e
referências visuais, após confirmação na UI. Remover um host de um mapa adicional apenas
remove a associação: o dispositivo continua no inventário e no mapa geral.

Criar dispositivo pelo mapa e posicioná-lo é uma operação coordenada sobre hosts e mapas,
com revisão, backup e rollback em falha. O mapa não conecta em equipamentos.

`network/maps.yaml` real é git-ignorado. Só os exemplos são versionados. GET não cria
arquivos; sem layout salvo, a posição inicial é calculada pelo console.
