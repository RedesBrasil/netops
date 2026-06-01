# PADRÃO — `network/` (Inventário e Topologia)

Esta pasta é a **fonte da verdade da rede**. O agente só conhece equipamentos descritos aqui.

## Arquivos

| Arquivo | Versionado? | O que é |
|---------|-------------|---------|
| `hosts.yaml` | sim | Inventário de equipamentos e como acessá-los |
| `credentials.yaml` | **NÃO** (git-ignorado) | Credenciais (cofre criptografado `enc.v1:`, ou texto puro) |
| `credentials.example.yaml` | sim | Modelo de credenciais, sem segredos reais |
| `topology.yaml` | sim | Enlaces entre hosts (mapa lógico/físico) |
| `topology.md` | sim | Diagrama Mermaid gerado de `topology.yaml` |

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
| `role` | recomendado | `core`, `distribution`, `access`, `firewall`, `wireless`, `server`, `other` |
| `access.method` | sim (host ou grupo) | `ssh`, `telnet`, `api`, `winbox` |
| `access.port` | sim (host ou grupo) | Porta TCP |
| `credential` | sim (host ou grupo) | Nome da credencial em `credentials.yaml` |
| `site` | recomendado | Local físico |
| `group` | opcional | Nome do grupo do qual herda |
| `notes` | opcional | Observações livres |

Validar: `python scripts/lib/inventory.py --validate` (usa `core/schemas/inventory.schema.json`).

## `credentials.yaml`

Credenciais **nomeadas** (`cred_<algo>`) que os hosts referenciam pelo nome — assim a mesma
senha não se repete.

Campos de uma credencial: `username`, `password`, e opcionais `secret` (enable do Cisco),
`key_file` (chave SSH), `api_ssl`.

**Criptografia (cofre).** As senhas podem ser criptografadas com uma senha-mestra: cada valor
secreto vira `enc.v1:<token>` e é descriptografado só em memória, durante a sessão. Gerencie com
`scripts/vault/cli.py` (`init` → `encrypt` → `unlock`/`lock`); ver `scripts/vault/SKILL.md`. A
descriptografia acontece só em `scripts/lib/inventory.py:resolve_secret()` — os hosts nunca mudam,
e arquivos mistos (parte texto puro, parte `enc.v1:`) são válidos.

## `topology.yaml`

Lista de `links` — cada link tem `a` e `b` (`{host, port}`), `media`, `speed`, `desc`.
Opcionalmente `segments` (VLANs/sub-redes). O script `scripts/docs/topology_render.py` lê
este arquivo + `hosts.yaml` e regenera `topology.md` com um diagrama Mermaid.

## Como adicionar um equipamento

1. Adicione o host em `hosts.yaml` (use um `group` existente ou crie um).
2. Se a credencial for nova, adicione-a em `credentials.yaml`.
3. Adicione os enlaces dele em `topology.yaml`.
4. Rode `python scripts/docs/topology_render.py` para atualizar `topology.md`.
