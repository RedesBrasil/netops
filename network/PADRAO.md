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

O inventário v2 usa `hosts` como lista de registros com `id` inteiro positivo e imutável.
`next_host_id` é incrementado na mesma gravação de criação e nunca diminui, mesmo após
exclusões. O console gera o ID; o operador informa somente o hostname e os demais campos.
`legacy_aliases` associa nomes anteriores ao inteiro para compatibilidade dos scripts,
inclusive reservando aliases de hosts excluídos. IDs são valores numéricos no YAML/JSON.
Arquivos v1 permanecem legíveis, mas precisam de migração explícita antes de editar.

Enlaces v2 usam inteiros em `a.host`/`b.host`. Mapas v2 usam membros inteiros, posições
como lista de `{host_id, x, y, z_index?}` e pontas visuais tipadas por `kind`.
A configuração de backups v3 usa `targets.hosts` com inteiros e `legacy_sources` para
associar pastas históricas ao cadastro. Novas coletas ficam em `backups/by-id/<id>/`.
O inventário continua sendo a única fonte dos equipamentos; arquivos históricos não
criam hosts. A trava `.inventory.lock` e o journal `.host-id-migration.json` são privados
e git-ignorados; não contêm credenciais.

Campos de um host:

| Campo | Obrigatório | Valores |
|-------|-------------|---------|
| `id` | sim, gerado | Inteiro positivo, único, permanente; não editável pela UI/API |
| `hostname` | sim | FQDN ou nome |
| `mgmt_ip` | sim | IP de gerência |
| `extra_ips` | opcional | Até 20 IPs adicionais, cada um `{ip, role?, description?}` (ex.: público, interno, VIP). `ip` aceita IPv4/IPv6 com máscara opcional; sem repetir entre si nem o `mgmt_ip`. Apenas informativo: os scripts conectam pelo `mgmt_ip` |
| `vendor` | sim (host ou grupo) | `mikrotik`, `unifi`, `ubiquiti`, `cisco`, `huawei`, `proxmox`, `vmware`, `datacom`, `linux`, `fiberhome`, `intelbras`, `zabbix` |
| `model` | recomendado | Modelo do equipamento |
| `os` | recomendado | Sistema operacional/firmware **como o próprio equipamento informa** (`/etc/os-release`, `/system resource`): `ROUTEROS`, `DEBIAN`, `UBUNTU`. Herdável do grupo |
| `os_version` | recomendado | Versão do SO (`7.23.4`, `12.15`, `22.04.5`). Herdável do grupo |
| `apps` | opcional | Lista do que roda **em cima** do SO, a 1ª é a principal: `[{name: ZABBIX SERVER, version: 7.0.32}]` (máx. 10). Ex.: CT Debian com Zabbix → `os: DEBIAN`, `apps: [ZABBIX SERVER]`; Proxmox → `os: DEBIAN` + `apps: [PROXMOX VE]`; MikroTik → só `os: ROUTEROS` |
| `runs_on` | opcional | ID do host que hospeda este (CT/VM → hypervisor). Só informativo; excluir o hospedeiro limpa a referência |
| `version` | legado | Campo antigo (SO **ou** app num texto só). Ainda é lido; a tela mostra em cinza e remove ao salvar com SO/aplicações preenchidos |
| `icon` | opcional | ID da biblioteca local: `router`, `switch`, `linux-server`, `windows-server`, `access-point`, `olt`, `cloud`, `pc`, `proxmox`, `vmware` |
| `role` | recomendado | `core`, `distribution`, `access`, `firewall`, `wireless`, `server`, `other` |
| `access.method` | sim (host ou grupo) | `ssh`, `telnet`, `api`, `winbox` |
| `access.port` | sim (host ou grupo) | Porta TCP |
| `credential` | sim (host ou grupo) | Nome da credencial em `credentials.yaml` |
| `site` | recomendado | Local físico |
| `group` | opcional | Nome do grupo do qual herda |
| `notes` | opcional | Observações livres |

Validar: `python3 scripts/engine/lib/inventory.py --validate` (usa `core/schemas/inventory.schema.json`).

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
4. Rode `python3 scripts/tools/docs/topology_render.py` para atualizar `topology.md`.


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
  Formas aceitam `icon` opcional do catálogo local, sem IP ou cadastro no inventário.
- `edges`: layout por ID estável do enlace real: `anchors` e `route`.
- `visual_links`: conexões visuais entre hosts, formas e referências de mapas. Quando uma
  ponta é uma forma, a ligação fica só neste mapa, sem criar host ou enlace físico no
  inventário. Ligações entre dois hosts continuam em `topology.yaml`. Não entram no Mermaid.

Os IDs de enlaces legados são fixados em `topology.yaml` na primeira edição gráfica.
Editar um enlace no mapa preserva o ID; remover um enlace limpa seus trajetos.
Renomear host atualiza os mapas e a topologia. Excluir host remove também seus enlaces e
referências visuais, após confirmação na UI. Remover um host de um mapa adicional apenas
remove a associação: o dispositivo continua no inventário e no mapa geral.

Criar dispositivo pelo mapa e posicioná-lo é uma operação coordenada sobre hosts e mapas,
com revisão, backup e rollback em falha. O mapa não conecta em equipamentos.

`network/maps.yaml` real é git-ignorado. Só os exemplos são versionados. GET não cria
arquivos; sem layout salvo, a posição inicial é calculada pelo console.


As ações de alinhar horizontal/vertical salvam as posições de todo o grupo em uma única
edição do mapa, com 24 unidades de intervalo entre as bordas. A seleção de dispositivos é
transitória e não é gravada no YAML. O alinhamento usa as dimensões medidas, mantém a ordem
visual e não altera nós fora do grupo nem os trajetos/âncoras das conexões.
