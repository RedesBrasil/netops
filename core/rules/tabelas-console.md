# Regra permanente: toda tabela do console usa o DataTable

Leia antes de criar ou alterar qualquer listagem em `scripts/engine/ui/static/js/`.

## Regra

1. **Nunca escreva `<table>` à mão numa tela.** Use `DataTable` de `static/js/table.js` (também
   exportado por `components.js`). Só ficam de fora as tabelas que não são de dados, como o modelo
   inserido pelo editor de Markdown (`wysiwyg.js`).
2. **Todo `DataTable` tem um `tableId` estável e único** (ex.: `"hosts"`, `"backup-host-files"`). Ele é a
   chave da preferência salva no navegador. Trocar o id apaga o layout que o usuário montou.
3. **Toda coluna de dados ganha `sort`**: `sort: true` ordena por `row[key]`, ou passe uma função `(row) => valor`.
4. A **tabela principal da tela usa `urlSort`**, o que põe a ordenação na URL (`core/rules/urls-navegacao.md`).
   Em modais e com várias tabelas na mesma URL, use `urlSort="prefixo"` ou deixe a ordenação local.
5. **A coluna de identidade** (nome do host, do grupo etc.) leva `hideable: false`. Campos secundários entram
   com `hidden: true`: ficam disponíveis no menu ⚙ Colunas sem poluir o padrão.
6. **Botões por linha vão em `actions`**, que é a coluna fixa à direita junto do ⚙ Colunas. Uma checkbox de
   seleção é coluna `pinned: true` (fixa à esquerda, não move nem redimensiona).

O usuário ganha, sem código extra: redimensionar ao vivo (duplo clique ajusta ao conteúdo), arrastar
coluna, mostrar/ocultar, restaurar padrão, cabeçalho fixo e a coluna de ações sempre visível.

## Exemplo

```js
import { DataTable } from "../components.js";
<${DataTable} tableId="groups" urlSort rows=${rows.map((g) => ({ ...g, _key: g.name }))}
  onRowClick=${open} empty="Nenhum grupo."
  actions=${(g) => html`<button class="sm danger" onClick=${() => del(g)}>Excluir</button>`}
  columns=${[
    { key: "name", label: "Grupo", hideable: false, sort: true, render: (g) => html`<a href=${"#groups/" + g.name}>${g.name}</a>` },
    { key: "vendor", label: "Vendor", sort: true },
    { key: "notes", label: "Notas", sort: true, hidden: true },
  ]} />
```

As props e as opções de coluna estão documentadas no cabeçalho de `static/js/table.js`. A lógica pura fica em
`static/js/table-core.js`.

## Verificação automática

`node --test scripts/engine/ui/tests/table-core.test.mjs` reprova `<table>` cru numa tela, `DataTable` sem
`tableId` e `tableId` repetido. Rode também `tests/tables-all.browser.mjs` (smoke em todas as telas) e
`tests/table-columns.browser.mjs` (interações, no desktop e no celular).
