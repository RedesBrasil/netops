# PADRÃO — O Padrão-Mestre do NetOps

Este é o documento que define **como tudo é organizado e nomeado** no NetOps. Sempre que
houver dúvida sobre onde colocar algo ou como nomear, a resposta está aqui. Todo agente de
IA lê este arquivo antes de criar qualquer coisa.

> **Regra de ouro:** estrutura/pastas/arquivos em **inglês**; conteúdo de documentação em
> **português**. Quando em dúvida, prefira REUSE > ADAPT > CREATE (ver `constitution.md`).

---

## 1. Estrutura de diretórios

```
netops/
├── agents/            Definições dos agentes de IA (escopo + função: planejar/executar/testar)
├── best-practices/    Boas práticas em TEXTO descritivo (pouca ou nenhuma config)
├── config-examples/   Exemplos de configuração REAIS, por fabricante
├── scripts/           Scripts Python: acesso (ssh/telnet/api), diagnóstico, cofre e UI
│   └── ui/            Console web CRUD (FastAPI + Preact sem build) — ferramenta de operador
│                      efêmera, loopback, stateless. Ver scripts/engine/ui/SKILL.md e constitution.md §VII.
├── planning-examples/ Documentos modelo de planejamento de tarefas
├── network/           Inventário: hosts, credenciais e mapa de topologia
├── workflows/         Pipelines YAML que orquestram os agentes (planejar→executar→testar)
├── memory/            Memória e auto-aprendizado — o "projeto vivo"
├── runs/              Saída bruta por execução (git-ignorado)
├── reports/           Relatórios finais curados (versionados)
└── core/              Config, schemas, templates e regras do framework
```

### Distribuição e atualização

Tarefas agendadas vivem em `scripts/engine/scheduler/` (`SKILL.md`): cadastro em `network/schedules.yaml`,
execuções em `runs/schedules/`, disparo pelo cron do sistema.

O motor de atualização vive em `scripts/engine/update/`, com `SKILL.md`. Estado e snapshots
privados ficam em `.netops-update/` (git-ignorado). Releases seguem `core/rules/releases.md`,
com versão única em `core/config/core-config.yaml`, notas em `CHANGELOG.md` e workflow em
`.github/workflows/release.yml`. Pacotes distribuem somente caminhos autorizados, nunca dados locais.

## 2. Convenções de nomenclatura

| Item | Padrão | Exemplo |
|------|--------|---------|
| Pasta | `kebab-case`, inglês | `config-examples/` |
| Arquivo de agente | `<nome>.agent.md` | `executor.agent.md` |
| Arquivo de workflow | `<nome>.workflow.yaml` | `security-audit.workflow.yaml` |
| Boa prática | `<topico>.md` em `best-practices/<vendor-ou-general>/` | `best-practices/mikrotik/firewall.md` |
| Exemplo de config | `<topico>.<ext-nativa>` em `config-examples/<vendor>/` | `config-examples/mikrotik/ospf.rsc` |
| Plano modelo | `<nome>.plan.md` | `security-audit.plan.md` |
| Lição aprendida | bullet datado `AAAA-MM-DD — fato` em `memory/MEMORY.md` | `2026-06-01 — Cofre antes do acesso` |
| Pasta de execução | `runs/YYYY-MM-DD-HHMM-<tarefa>/` | `runs/2026-05-18-1430-security-audit/` |
| Vendor (identificador) | minúsculo, sem espaço | `mikrotik`, `cisco`, `linux`, `unifi` |

Arquivos especiais (prefixo `_`):
- `_TEMPLATE.*` / `_TEMPLATE/` — modelo a copiar ao criar item novo na pasta.
- `_catalog.yaml` / `_index.yaml` — índice da pasta, lido pelo agente para descoberta rápida.
- `PADRAO.md` (dentro de cada pasta) — regras específicas daquela pasta.

## 3. Vendors suportados

`mikrotik`, `unifi`, `ubiquiti`, `cisco`, `huawei`, `proxmox`, `vmware`, `datacom`,
`linux`, `fiberhome`, `intelbras`, `zabbix` — e os que surgirem. `general` = boas práticas
cross-vendor (não pertence a um fabricante).

**Conteúdo seed completo:** `mikrotik` e `linux`. Os demais já têm a pasta e o
`_TEMPLATE` — preenche-se conforme o projeto vivo evolui.

## 4. Formato de cada pasta (resumo — detalhe no `PADRAO.md` de cada uma)

- **agents/** — `.agent.md` com 8 seções (Persona, Principles, Operational Framework,
  Voice Guidance, Output Examples, Anti-Patterns, Quality Criteria, Integration).
- **best-practices/** — Markdown com front-matter YAML; subpastas por vendor + `general/`;
  indexado por `_catalog.yaml`. Texto descritivo, comandos só como ilustração.
- **config-examples/** — arquivos na sintaxe nativa do fabricante (`.rsc`, `.ios`, `.conf`...);
  subpastas por vendor; indexado por `_index.yaml`. Cada exemplo tem cabeçalho comentado.
- **scripts/** — cada script tem um `SKILL.md` ao lado descrevendo uso. `lib/` é o núcleo
  reutilizável; `access/`, `diagnostics/`, `analysis/`, `docs/` são as famílias de script.
- **planning-examples/** — `.plan.md` mostrando objetivo, escopo, passos, riscos, rollback.
- **network/**: inventário real git-ignorado (`hosts.yaml`, `credentials.yaml`, `topology.yaml`,
  `topology.md`, `maps.yaml`); modelos `*.example.yaml` versionados. Layout é apresentação,
  nunca um segundo cadastro de hosts.
- **workflows/** — `.workflow.yaml` com `steps` (tipo `subagent`/`inline`/`checkpoint`).
- **memory/** — um arquivo só: `MEMORY.md` (seções: Preferências, Ambiente e convenções, Lições aprendidas).
  **Pessoal da instância, git-ignorada:** `memory/`, `reports/`, `runs/`, `backups/`, `network/hosts.yaml`/`credentials.yaml` e
  `core/config/project-config.yaml` nunca sobem para o repositório do produto (ele é distribuído a outras empresas); quem
  guarda esses dados é o backup da própria instância. Instalação nova começa com `memory/` vazia e config a partir de
  `core/config/project-config.example.yaml`. Código, docs e testes do produto não citam empresa, ISP, IP nem host reais: use
  exemplos genéricos (RFC 5737 `192.0.2.0/24`, `203.0.113.0/24`; RFC 3849 `2001:db8::/32`).

## 5. Como adicionar um fabricante novo

1. Criar `best-practices/<vendor>/` copiando `best-practices/_TEMPLATE.md`.
2. Criar `config-examples/<vendor>/` copiando `config-examples/_TEMPLATE/`.
3. Registrar o vendor em `best-practices/_catalog.yaml` e `config-examples/_index.yaml`.
4. Adicionar o mapeamento em `scripts/engine/lib/vendor_map.py` (`device_type` Netmiko / driver NAPALM / API).
5. Adicionar a seção do vendor neste arquivo (item 3).

## 6. Como adicionar um aprendizado (projeto vivo)

1. Durante a reflexão pós-execução, anexar um bullet datado (`AAAA-MM-DD — fato`) em "Lições
   aprendidas" de `memory/MEMORY.md` — fato declarativo, não ordem.
2. Se virar conhecimento permanente de um fabricante, promover para `best-practices/` ou
   `config-examples/`.

Ver `core/rules/memory-protocol.md` para o protocolo completo.
