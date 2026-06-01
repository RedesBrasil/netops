# PADRÃO — `best-practices/`

Boas práticas em **texto descritivo** — o "porquê" e o "o quê". Pouca ou nenhuma
configuração (config detalhada vive em `config-examples/`). O agente lê estes guias antes
de planejar ou auditar.

## Organização

- `general/` — boas práticas cross-vendor (valem para qualquer fabricante).
- `<vendor>/` — boas práticas específicas de um fabricante (`mikrotik/`, `linux/`, ...).
- `_catalog.yaml` — índice de todos os guias; o agente lê o catálogo primeiro e só abre
  o guia relevante.

## Formato de um guia (`<topico>.md`)

Front-matter YAML + corpo:

```markdown
---
id: identificador-unico
titulo: Título legível
vendor: general | mikrotik | linux | ...
tags: [security, ssh, ...]
severidade: alta | media | baixa
---

## Resumo
Para que serve este guia, em 1-2 parágrafos.

## Checklist
- [ ] Item verificável 1
- [ ] Item verificável 2

## Detalhamento
Explicação de cada ponto.

## Configuração relacionada
Aponta para os arquivos de `config-examples/<vendor>/` que implementam isto.

## Referências
Links e documentação oficial.
```

## Como adicionar um guia

Copie `_TEMPLATE.md`, escreva o conteúdo, e registre o guia em `_catalog.yaml`.
Conteúdo seed completo: `general/`, `mikrotik/`, `linux/`. Demais vendors: preencher
conforme o projeto vivo evolui (ver `PADRAO.md` raiz, §5).
