// Biblioteca de tabelas do console — TODA tabela de dados usa <DataTable> (regra: core/rules/console-tables.md).
//
// O que o usuário ganha em qualquer tabela, sem código extra na página:
//   • redimensionar coluna (arrastar a borda do cabeçalho; duplo clique = ajustar ao conteúdo)
//   • mover coluna (arrastar o cabeçalho, ou ↑↓ no menu ⚙ Colunas)
//   • mostrar/ocultar colunas (menu ⚙ Colunas, "Restaurar padrão")
//   • ordenar (clique no cabeçalho; na URL com `urlSort`, regra core/rules/navigation-urls.md)
// Layout = preferência do navegador em localStorage `netops.table.<tableId>` ({order, vis, widths}).
//
// Uso mínimo:
//   <${DataTable} tableId="groups" columns=${cols} rows=${rows} urlSort onRowClick=${open}
//       actions=${(r) => html`<button …>Excluir</button>`} empty="Nenhum grupo." />
//
// Coluna: { key, label, render?(row), sort?: (row)=>valor | true (= row[key]), hidden?: true (oculta por padrão),
//           hideable?: false (sempre visível), width?/minWidth? (px), menuLabel?, tdClass?,
//           pinned?: true (fixa à esquerda, sem mover/redimensionar/ocultar — ex.: checkbox de seleção) }
// Props:   tableId (estável e único; sem ele vira "auto:<menu>:<chaves>"), columns, rows, rowKey?(row) (padrão row._key),
//          onRowClick?, rowClass?(row), actions?(row), empty?, urlSort? (true = params sort/dir; "x" = x_sort/x_dir),
//          sortState?/onSortChange? (ordenação controlada), defaultSort? {key, dir}, wrapClass?, plain? (tabela crua, sem layout)
import { html } from "htm/preact";
import { useState, useEffect, useRef, useLayoutEffect } from "preact/hooks";
import { useRoute, navigate } from "./route.js";
import { t } from "./i18n.js";

import { TL_MIN, ACT, loadTableLayout, saveTableLayout, resolveColumns, moveColumn, sortRows } from "./table-core.js";
export { loadTableLayout, saveTableLayout, resolveColumns, moveColumn, sortRows } from "./table-core.js";

/* ------------------------------ ordenação ------------------------------- */
// urlSort: ordenação na URL (replaceState, sem poluir o histórico); senão estado local.
function useSort({ urlSort, sortState, onSortChange, defaultSort }) {
  const route = useRoute();
  const [local, setLocal] = useState(defaultSort || { key: null, dir: "asc" });
  if (sortState) return [sortState, onSortChange || (() => {})];
  if (urlSort) {
    const p = urlSort === true ? "" : urlSort + "_";
    const key = route.params[p + "sort"] || (defaultSort && defaultSort.key) || null;
    const dir = route.params[p + "dir"] || (route.params[p + "sort"] ? "asc" : (defaultSort && defaultSort.dir) || "asc");
    const set = (n) => navigate({ ...route, params: { ...route.params, [p + "sort"]: n.key || "", [p + "dir"]: n.dir === "desc" ? "desc" : "" } }, { replace: true });
    return [{ key, dir }, set];
  }
  return [local, setLocal];
}

/* ------------------------------ menu ⚙ ---------------------------------- */
function ColumnMenu({ anchor, ordered, isVisible, visibleCount, onToggle, onMove, onReset, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const down = (e) => { if (ref.current && !ref.current.contains(e.target) && !anchor.contains(e.target)) onClose(); };
    const key = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", down); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("pointerdown", down); document.removeEventListener("keydown", key); };
  }, []);
  const r = anchor.getBoundingClientRect();
  const top = Math.min(r.bottom + 4, innerHeight - 80);
  const right = Math.max(8, innerWidth - r.right);
  const name = (c) => c.menuLabel || (typeof c.label === "string" ? c.label : c.key);
  return html`<div class="rt-menu" ref=${ref} role="dialog" aria-label=${t("table.columns_visible")}
      style=${`top:${top}px;right:${right}px;max-height:${Math.max(160, innerHeight - top - 12)}px`}>
    <div class="rt-menu-title">${t("table.columns")}</div>
    ${ordered.map((c, i) => {
      const on = isVisible(c), locked = c.hideable === false || (on && visibleCount <= 1);
      return html`<div class="rt-menu-row" key=${c.key}>
        <label><input type="checkbox" checked=${on} disabled=${locked} onChange=${() => onToggle(c.key, !on)} />
          <span>${name(c)}</span></label>
        <span class="rt-menu-move">
          <button type="button" class="sm" title=${t("table.move_left")} aria-label=${t("table.move_col_left", { name: name(c) })}
            disabled=${i === 0} onClick=${() => onMove(i, -1)}>↑</button>
          <button type="button" class="sm" title=${t("table.move_right")} aria-label=${t("table.move_col_right", { name: name(c) })}
            disabled=${i === ordered.length - 1} onClick=${() => onMove(i, 1)}>↓</button>
        </span>
      </div>`;
    })}
    <div class="rt-menu-foot"><button type="button" class="sm" onClick=${onReset}>${t("table.reset")}</button></div>
  </div>`;
}

/* ------------------------------ DataTable ------------------------------- */
export function DataTable(props) {
  const { columns, rows, onRowClick, rowClass, actions, empty, wrapClass = "", plain } = props;
  const rowKey = props.rowKey || ((r, i) => r._key ?? i);
  const route = useRoute();
  const tableId = props.tableId || `auto:${route.menu}:${columns.map((c) => c.key).join(",")}`;
  const [sort, setSort] = useSort(props);
  const [layout, setLayout] = useState(() => (plain ? {} : loadTableLayout(tableId)));
  const [measured, setMeasured] = useState({});      // larguras naturais medidas (não persistidas)
  const [menuOpen, setMenuOpen] = useState(false);
  const [drop, setDrop] = useState(null);             // { key, side } durante o arraste de coluna
  const tableRef = useRef(null), menuBtn = useRef(null), busy = useRef(false), dragKey = useRef(null);
  const { ordered, visible, isVisible } = resolveColumns(columns, plain ? {} : layout);
  const shown = plain ? columns : visible;
  const widthOf = (k) => (layout.widths || {})[k] || measured[k];
  const colW = (c) => widthOf(c.key) || c.width;
  const pending = !plain && rows && rows.length > 0 && (shown.some((c) => !colW(c)) || !widthOf(ACT));
  // Mede (layout automático) as colunas sem largura e então trava em layout fixo — antes do paint.
  useLayoutEffect(() => {
    if (!pending || !tableRef.current) return;
    const got = {};
    tableRef.current.querySelectorAll("thead th[data-col]").forEach((th) => {
      const k = th.dataset.col; if (!widthOf(k)) got[k] = Math.max(k === ACT ? 0 : TL_MIN, Math.round(th.getBoundingClientRect().width));
    });
    setMeasured((m) => ({ ...m, ...got }));
  });
  const update = (f, persist = true) => setLayout((l) => { const n = f(l); if (persist) saveTableLayout(tableId, n); return n; });

  if (!rows || rows.length === 0) return html`<div class="card"><div class="empty">${empty || t("table.empty")}</div></div>`;

  const view = sortRows(rows, columns, sort);
  const onHead = (c) => { if (busy.current || !c.sort) return; setSort(sort.key === c.key ? { key: c.key, dir: sort.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: "asc" }); };
  const ind = (c) => sort.key === c.key ? (sort.dir === "asc" ? "▲" : "▼") : (c.sort ? "⇅" : "");
  const ariaSort = (c) => sort.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined;
  const label = (c) => html`${c.label}${c.sort || sort.key === c.key ? html` <span class="sort-ind">${ind(c)}</span>` : ""}`;
  const cell = (r, c) => (c.render ? c.render(r) : r[c.key]);
  const trProps = (r) => ({ class: [onRowClick ? "clickable" : "", rowClass ? rowClass(r) : ""].filter(Boolean).join(" ") || undefined,
                            onClick: onRowClick ? () => onRowClick(r) : undefined });

  if (plain) return html`<table>
    <thead><tr>
      ${columns.map((c) => html`<th key=${c.key} class=${c.sort ? "sortable" : ""} aria-sort=${ariaSort(c)} onClick=${() => onHead(c)}>${label(c)}</th>`)}
      ${actions && html`<th></th>`}
    </tr></thead>
    <tbody>
      ${view.map((r, i) => html`<tr key=${rowKey(r, i)} ...${trProps(r)}>
        ${columns.map((c) => html`<td key=${c.key} class=${c.tdClass}>${cell(r, c)}</td>`)}
        ${actions && html`<td class="actions" onClick=${(e) => e.stopPropagation()}>${actions(r)}</td>`}
      </tr>`)}
    </tbody>
  </table>`;

  /* ---- interação ---- */
  const minOf = (k) => Math.max(TL_MIN, columns.find((c) => c.key === k)?.minWidth || 0);
  const startResize = (e, key) => {
    if (e.button > 0) return;
    e.preventDefault(); e.stopPropagation();
    const th = e.currentTarget.parentElement, x0 = e.clientX, w0 = th.getBoundingClientRect().width, min = minOf(key);
    busy.current = true;
    const move = (ev) => update((l) => ({ ...l, widths: { ...(l.widths || {}), [key]: Math.max(min, Math.round(w0 + ev.clientX - x0)) } }), false);
    const end = () => {
      removeEventListener("pointermove", move); removeEventListener("pointerup", end); removeEventListener("pointercancel", end);
      update((l) => l, true); setTimeout(() => { busy.current = false; }, 0);
    };
    addEventListener("pointermove", move); addEventListener("pointerup", end); addEventListener("pointercancel", end);
  };
  // Duplo clique na borda: ajusta à maior largura de conteúdo da coluna (cabeçalho incluso).
  const autoFit = (e, key) => {
    e.preventDefault(); e.stopPropagation();
    const range = document.createRange(); let w = 0;
    tableRef.current.querySelectorAll(`[data-col="${CSS.escape(key)}"]`).forEach((td) => {
      range.selectNodeContents(td.querySelector(".rt-th-label") || td);
      w = Math.max(w, Math.ceil(range.getBoundingClientRect().width) + (td.tagName === "TH" ? 44 : 26));
    });
    update((l) => ({ ...l, widths: { ...(l.widths || {}), [key]: Math.max(minOf(key), Math.min(w, 900)) } }));
  };
  const fullOrder = ordered.map((c) => c.key);
  const onDragStart = (e, key) => {
    if (busy.current) { e.preventDefault(); return; }
    dragKey.current = key;
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", key); } catch { /* ignore */ }
  };
  const onDragOver = (e, key) => {
    if (!dragKey.current) return;
    e.preventDefault(); e.dataTransfer.dropEffect = "move";
    const r = e.currentTarget.getBoundingClientRect();
    const side = e.clientX < r.left + r.width / 2 ? "before" : "after";
    if (!drop || drop.key !== key || drop.side !== side) setDrop({ key, side });
  };
  const onDrop = (e, key) => {
    e.preventDefault();
    const from = dragKey.current; dragKey.current = null;
    const side = drop && drop.key === key ? drop.side : "before";
    setDrop(null);
    if (from && from !== key) update((l) => ({ ...l, order: moveColumn(fullOrder, from, key, side) }));
  };
  const onDragEnd = () => { dragKey.current = null; setDrop(null); };
  const toggle = (key, on) => update((l) => ({ ...l, vis: { ...(l.vis || {}), [key]: on } }));
  const moveBy = (i, d) => {
    const j = i + d; if (j < 0 || j >= fullOrder.length) return;
    update((l) => ({ ...l, order: moveColumn(fullOrder, fullOrder[i], fullOrder[j], d > 0 ? "after" : "before") }));
  };
  const reset = () => { update(() => ({})); setMeasured({}); };
  const fixed = !pending;
  const totalW = shown.reduce((s, c) => s + (colW(c) || 0), 0) + (widthOf(ACT) || 0);

  return html`<div class=${"rt-wrap " + wrapClass}>
    <table ref=${tableRef} class=${"rt" + (fixed ? " rt-fixed" : "")} style=${fixed ? `min-width:${totalW}px` : ""} data-table=${tableId}>
      ${fixed && html`<colgroup>
        ${shown.map((c) => html`<col key=${c.key} style=${`width:${colW(c)}px`} />`)}
        <col class="rt-fill-col" />
        <col style=${`width:${widthOf(ACT)}px`} />
      </colgroup>`}
      <thead><tr>
        ${shown.map((c) => {
          if (c.pinned) return html`<th key=${c.key} data-col=${c.key} class="rt-th rt-pinned">${c.label}</th>`;
          const cls = ["rt-th", c.sort ? "sortable" : "", drop && drop.key === c.key ? "rt-drop-" + drop.side : ""].filter(Boolean).join(" ");
          return html`<th key=${c.key} data-col=${c.key} class=${cls} aria-sort=${ariaSort(c)} draggable="true"
              title=${(c.sort ? t("table.click_to_sort") : "") + t("table.drag_to_move")}
              onClick=${() => onHead(c)}
              onDragStart=${(e) => onDragStart(e, c.key)} onDragOver=${(e) => onDragOver(e, c.key)}
              onDragLeave=${(e) => { if (!e.currentTarget.contains(e.relatedTarget) && drop && drop.key === c.key) setDrop(null); }}
              onDrop=${(e) => onDrop(e, c.key)} onDragEnd=${onDragEnd}>
            <span class="rt-th-label">${label(c)}</span>
            <span class="rt-resize" role="separator" aria-orientation="vertical" aria-label=${t("table.resize_col", { name: c.menuLabel || c.label })}
              title=${t("table.resize_hint")} draggable="false"
              onPointerDown=${(e) => startResize(e, c.key)} onClick=${(e) => e.stopPropagation()}
              onDblClick=${(e) => autoFit(e, c.key)} onDragStart=${(e) => { e.preventDefault(); e.stopPropagation(); }}></span>
          </th>`;
        })}
        <th class="rt-fill"></th>
        <th class="rt-act-th" data-col=${ACT}>
          <button type="button" class="sm rt-cols-btn" ref=${menuBtn} aria-haspopup="dialog" aria-expanded=${menuOpen}
            title=${t("table.columns_title")} onClick=${(e) => { e.stopPropagation(); setMenuOpen((o) => !o); }}>${t("table.columns_btn")}</button>
        </th>
      </tr></thead>
      <tbody>
        ${view.map((r, i) => html`<tr key=${rowKey(r, i)} ...${trProps(r)}>
          ${shown.map((c) => html`<td key=${c.key} data-col=${c.key} class=${c.tdClass}>${cell(r, c)}</td>`)}
          <td class="rt-fill"></td>
          <td class="actions" onClick=${(e) => e.stopPropagation()}>${actions ? actions(r) : ""}</td>
        </tr>`)}
      </tbody>
    </table>
    ${menuOpen && menuBtn.current && html`<${ColumnMenu} anchor=${menuBtn.current} ordered=${ordered} isVisible=${isVisible}
        visibleCount=${visible.filter((c) => !c.pinned).length} onToggle=${toggle} onMove=${moveBy} onReset=${reset} onClose=${() => setMenuOpen(false)} />`}
  </div>`;
}

// Nome antigo (compatibilidade): ResourceTable === DataTable.
export const ResourceTable = DataTable;
