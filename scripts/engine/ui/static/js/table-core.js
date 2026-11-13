// Núcleo puro das tabelas (sem DOM/Preact) — usado por table.js e testado em tests/table-core.test.mjs.
export const TL_PREFIX = "netops.table.";
export const TL_MIN = 48;
export const ACT = "__actions";

/* --------------------------- funções puras ------------------------------ */
export function loadTableLayout(id) {
  try { const v = JSON.parse(localStorage.getItem(TL_PREFIX + id)); return v && typeof v === "object" ? v : {}; } catch { return {}; }
}
export function saveTableLayout(id, l) {
  try {
    const empty = !(l.order && l.order.length) && !Object.keys(l.vis || {}).length && !Object.keys(l.widths || {}).length;
    if (empty) localStorage.removeItem(TL_PREFIX + id); else localStorage.setItem(TL_PREFIX + id, JSON.stringify(l));
  } catch { /* storage cheio/bloqueado: segue só em memória */ }
}
// Ordem efetiva (pinned primeiro), visibilidade e lista do menu.
export function resolveColumns(columns, layout = {}) {
  const pinned = columns.filter((c) => c.pinned);
  const free = columns.filter((c) => !c.pinned);
  const keys = free.map((c) => c.key);
  const saved = (layout.order || []).filter((k) => keys.includes(k));
  const order = [...saved, ...keys.filter((k) => !saved.includes(k))];
  const byKey = Object.fromEntries(free.map((c) => [c.key, c]));
  const vis = layout.vis || {};
  const isVisible = (c) => c.pinned || c.hideable === false || (c.key in vis ? !!vis[c.key] : !c.hidden);
  const ordered = order.map((k) => byKey[k]);
  return { ordered, visible: [...pinned, ...ordered.filter(isVisible)], isVisible };
}
export function moveColumn(order, key, target, side) {
  if (key === target) return order;
  const out = order.filter((k) => k !== key);
  const i = out.indexOf(target);
  if (i < 0) return order;
  out.splice(side === "after" ? i + 1 : i, 0, key);
  return out;
}
export const sortFn = (c) => (typeof c.sort === "function" ? c.sort : c.sort ? (r) => r[c.key] : null);
export function sortRows(rows, columns, sort) {
  const col = sort && sort.key && columns.find((c) => c.key === sort.key && c.sort);
  if (!col) return rows;
  const val = sortFn(col);
  return [...rows].sort((a, b) => {
    const va = val(a), vb = val(b);
    const cmp = typeof va === "number" && typeof vb === "number" ? va - vb
      : String(va ?? "").localeCompare(String(vb ?? ""), "pt", { numeric: true, sensitivity: "base" });
    return sort.dir === "desc" ? -cmp : cmp;
  });
}
