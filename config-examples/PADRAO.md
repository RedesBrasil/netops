# PADRÃO — `config-examples/`

Exemplos de configuração **reais e aplicáveis**, na sintaxe nativa de cada fabricante. Onde
`best-practices/` explica o "porquê", aqui está o "como" — config pronta para o `planner`
adaptar (REUSE > ADAPT > CREATE).

## Organização

- `<vendor>/` — uma pasta por fabricante (`mikrotik/`, `linux/`, `cisco/`, ...).
- `_index.yaml` — índice de todos os exemplos, por vendor e tópico.
- `_TEMPLATE/` — modelo a copiar ao adicionar um vendor/exemplo novo.

## Formato de um exemplo

Arquivo na extensão nativa do fabricante, com **cabeçalho comentado** explicando:
o que configura, em que versão foi testado, e o que ajustar antes de aplicar.

| Fabricante | Extensão | Sintaxe |
|------------|----------|---------|
| MikroTik | `.rsc` | Script RouterOS (`/comando ...`) |
| Cisco | `.ios` | IOS CLI |
| Linux | `.conf`, `.sh`, `.yml` | Config do serviço / shell / compose |
| Huawei | `.cfg` | VRP CLI |

Exemplo de cabeçalho (MikroTik):

```
# ============================================================
# Exemplo: <o que configura>
# Testado em: RouterOS 7.x
# Ajuste antes de aplicar: <interfaces, IPs, sub-redes>
# Boa prática relacionada: best-practices/mikrotik/<guia>.md
# ============================================================
```

## Regras

- Exemplo é ponto de partida — **sempre** ajustar interfaces/IPs/sub-redes ao host real.
- Toda mudança aplicada a partir daqui exige baseline + rollback (ver `core/rules/connection-safety.md`).
- Registrar o exemplo em `_index.yaml`.

## Como adicionar

Copie `_TEMPLATE/`, crie o exemplo na sintaxe do fabricante, registre em `_index.yaml`.
Conteúdo seed: `mikrotik/` e `linux/`. Demais vendors: preencher conforme o projeto evolui.
