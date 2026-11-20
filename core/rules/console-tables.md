# Permanent rule: every console table uses DataTable

Read before creating or changing any listing in `scripts/engine/ui/static/js/`.

## Rule

1. **Never write `<table>` by hand in a screen.** Use `DataTable` from `static/js/table.js` (also
   exported by `components.js`). The only exceptions are tables that are not data, such as the template
   inserted by the Markdown editor (`wysiwyg.js`).
   **Exception: the file explorer** (`static/js/file-browser.js`, **Files** menu and SFTP panel of the
   host terminal) is a list of folders and files with icons, in the style of MobaXterm and the system
   explorer. It is not a data table and does not use `DataTable` (user decision, 13/11/2026). The list is
   made of `div`s in a grid, without `<table>`. Sorting, filter and folder go in the URL (`#files?path=&q=&sort=`).
2. **Every `DataTable` has a stable and unique `tableId`** (e.g.: `"hosts"`, `"backup-host-files"`). It is the
   key of the preference saved in the browser. Changing the id erases the layout the user built.
3. **Every data column gets `sort`**: `sort: true` sorts by `row[key]`, or pass a function `(row) => value`.
4. The **main table of the screen uses `urlSort`**, which puts the sorting in the URL (`core/rules/navigation-urls.md`).
   In modals and with several tables in the same URL, use `urlSort="prefix"` or keep the sorting local.
5. **The identity column** (host name, group name etc.) gets `hideable: false`. Secondary fields come in
   with `hidden: true`: they are available in the ⚙ Columns menu without cluttering the default.
6. **Per-row buttons go in `actions`**, which is the fixed column on the right next to ⚙ Columns. A selection
   checkbox is a `pinned: true` column (fixed on the left, it does not move or resize).

The user gets, with no extra code: live resizing (double click fits the content), dragging a
column, show/hide, restore default, sticky header and the actions column always visible.

## Example

Visible texts go through `t()` (see `core/rules/i18n.md`).

```js
import { DataTable } from "../components.js";
<${DataTable} tableId="groups" urlSort rows=${rows.map((g) => ({ ...g, _key: g.name }))}
  onRowClick=${open} empty=${t("groups.empty")}
  actions=${(g) => html`<button class="sm danger" onClick=${() => del(g)}>${t("common.delete")}</button>`}
  columns=${[
    { key: "name", label: t("groups.col_group"), hideable: false, sort: true, render: (g) => html`<a href=${"#groups/" + g.name}>${g.name}</a>` },
    { key: "vendor", label: t("groups.col_vendor"), sort: true },
    { key: "notes", label: t("groups.col_notes"), sort: true, hidden: true },
  ]} />
```

The props and column options are documented in the header of `static/js/table.js`. The pure logic lives in
`static/js/table-core.js`.

## Automatic check

`node --test scripts/engine/ui/tests/table-core.test.mjs` rejects raw `<table>` in a screen, `DataTable` without
`tableId` and a repeated `tableId`. Also run `tests/tables-all.browser.mjs` (smoke test on all screens) and
`tests/table-columns.browser.mjs` (interactions, on desktop and on mobile).
