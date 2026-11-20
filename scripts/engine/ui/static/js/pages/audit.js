// Auditoria (menu Sistema; só admin): quem fez o quê no console. Banco de acesso (tabela audit).
// URL: #audit?user=&action=&q=&page=&sort=&dir=   (core/rules/urls-navegacao.md)
import { html, useResource, Spinner, Badge, t, fmtDateTime } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { FilterBar, DataTable } from "../components.js";

const PAGE = 200;
const fmtTs = (ts) => fmtDateTime(ts, { dateStyle: "short", timeStyle: "medium" });
// Audit action codes (stored data) -> catalog key "audit.action_<code>" for the display label.
const ACTIONS = new Set(["api", "login", "login_failed", "logout", "bootstrap_admin", "password_changed", "password_reset",
  "user_created", "user_updated", "user_deleted", "group_created", "group_updated", "group_deleted",
  "sessions_dropped", "server_terminal_open", "host_terminal_open", "reset_admin"]);

export function AuditPage() {
  const r = useMenuRoute("audit");
  const { user = "", action = "", q = "" } = r.params;
  const page = Math.max(0, parseInt(r.params.page || "0", 10) || 0);
  const qs = new URLSearchParams({ user, action, q, limit: String(PAGE), offset: String(page * PAGE) });
  const res = useResource("/audit?" + qs.toString(), [user, action, q, page]);
  const data = res.data;
  if (!data && res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("audit.error", { error: res.error.message })}</div>`;
  const label = (a) => (ACTIONS.has(a) ? t("audit.action_" + a) : a);
  const cols = [
    { key: "ts", label: t("audit.col_when"), hideable: false, sort: (i) => i.ts, render: (i) => fmtTs(i.ts) },
    { key: "username", label: t("audit.col_user"), sort: true, render: (i) => i.username
        ? html`<a href=${"#audit?user=" + encodeURIComponent(i.username)} onClick=${(e) => e.stopPropagation()}>${i.username}</a>` : "—" },
    { key: "action", label: t("audit.col_action"), sort: true, render: (i) => html`<${Badge} kind=${i.action === "login_failed" || i.status === 403 ? "danger" : ""}>${label(i.action)}<//>` },
    { key: "what", label: t("audit.col_what"), sort: (i) => i.path || i.target, render: (i) => i.action === "api"
        ? html`<code>${i.method} ${i.path}</code>` : (i.target || "—") },
    { key: "status", label: t("audit.col_result"), sort: (i) => i.status || 0, render: (i) => i.status == null ? "—"
        : html`<${Badge} kind=${i.status < 300 ? "ok" : i.status === 403 ? "danger" : "warn"}>${i.status}<//>` },
    { key: "ip", label: "IP", sort: true, render: (i) => i.ip || "—" },
    { key: "detail", label: t("audit.col_detail"), sort: true, hidden: true, render: (i) => i.detail || "—" },
  ];
  const pages = Math.max(1, Math.ceil(data.total / PAGE));
  return html`<div>
    <div class="page-title"><h1>${t("audit.title")}</h1></div>
    <p class="help">${t("audit.help_pre")} <code>ui.audit_keep_days</code> ${t("audit.help_post")}</p>
    <${FilterBar} q=${q} onChange=${(p) => r.setParams({ ...p, page: "" })} placeholder=${t("audit.search")}
      selects=${[{ key: "user", label: t("audit.col_user"), value: user, options: data.users },
                 { key: "action", label: t("audit.col_action"), value: action, options: data.actions }]}
      count=${data.items.length} total=${data.total} />
    <${DataTable} tableId="audit" urlSort columns=${cols} rows=${data.items.map((i) => ({ ...i, _key: String(i.id) }))}
      empty=${t("audit.empty")} />
    ${pages > 1 && html`<div class="toolbar" style="display:flex;gap:8px;align-items:center;margin-top:8px">
      <button class="sm" disabled=${page === 0} onClick=${() => r.pushParams({ page: page - 1 ? String(page - 1) : "" })}>${t("audit.newer")}</button>
      <span class="help">${t("audit.page_of", { page: page + 1, pages })}</span>
      <button class="sm" disabled=${page + 1 >= pages} onClick=${() => r.pushParams({ page: String(page + 1) })}>${t("audit.older")}</button>
    </div>`}
  </div>`;
}
