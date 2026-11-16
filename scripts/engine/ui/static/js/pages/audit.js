// Auditoria (menu Sistema; só admin): quem fez o quê no console. Banco de acesso (tabela audit).
// URL: #audit?user=&action=&q=&page=&sort=&dir=   (core/rules/urls-navegacao.md)
import { html, useResource, Spinner, Badge } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { FilterBar, DataTable } from "../components.js";

const PAGE = 200;
const fmtTs = (t) => new Date(t * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" });
const ACTIONS = {
  api: "escrita na API", login: "login", login_failed: "falha de login", logout: "logout",
  bootstrap_admin: "admin criado (1º login)", password_changed: "trocou a senha", password_reset: "senha redefinida",
  user_created: "usuário criado", user_updated: "usuário alterado", user_deleted: "usuário apagado",
  group_created: "grupo criado", group_updated: "grupo alterado", group_deleted: "grupo apagado",
  sessions_dropped: "sessões encerradas", server_terminal_open: "terminal do servidor",
  host_terminal_open: "terminal de host", reset_admin: "reset-admin (CLI)",
};

export function AuditPage() {
  const r = useMenuRoute("audit");
  const { user = "", action = "", q = "" } = r.params;
  const page = Math.max(0, parseInt(r.params.page || "0", 10) || 0);
  const qs = new URLSearchParams({ user, action, q, limit: String(PAGE), offset: String(page * PAGE) });
  const res = useResource("/audit?" + qs.toString(), [user, action, q, page]);
  const data = res.data;
  if (!data && res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const label = (a) => ACTIONS[a] || a;
  const cols = [
    { key: "ts", label: "Quando", hideable: false, sort: (i) => i.ts, render: (i) => fmtTs(i.ts) },
    { key: "username", label: "Usuário", sort: true, render: (i) => i.username
        ? html`<a href=${"#audit?user=" + encodeURIComponent(i.username)} onClick=${(e) => e.stopPropagation()}>${i.username}</a>` : "—" },
    { key: "action", label: "Ação", sort: true, render: (i) => html`<${Badge} kind=${i.action === "login_failed" || i.status === 403 ? "danger" : ""}>${label(i.action)}<//>` },
    { key: "what", label: "O quê", sort: (i) => i.path || i.target, render: (i) => i.action === "api"
        ? html`<code>${i.method} ${i.path}</code>` : (i.target || "—") },
    { key: "status", label: "Resultado", sort: (i) => i.status || 0, render: (i) => i.status == null ? "—"
        : html`<${Badge} kind=${i.status < 300 ? "ok" : i.status === 403 ? "danger" : "warn"}>${i.status}<//>` },
    { key: "ip", label: "IP", sort: true, render: (i) => i.ip || "—" },
    { key: "detail", label: "Detalhe", sort: true, hidden: true, render: (i) => i.detail || "—" },
  ];
  const pages = Math.max(1, Math.ceil(data.total / PAGE));
  return html`<div>
    <div class="page-title"><h1>Auditoria</h1></div>
    <p class="help">Logins, falhas de login, toda escrita na API (incluindo as negadas), terminais abertos e mudanças de usuários/grupos.
      Corpo das requisições nunca é gravado. Retenção: <code>ui.audit_keep_days</code> (padrão 365 dias).</p>
    <${FilterBar} q=${q} onChange=${(p) => r.setParams({ ...p, page: "" })} placeholder="Buscar caminho, alvo, IP"
      selects=${[{ key: "user", label: "Usuário", value: user, options: data.users },
                 { key: "action", label: "Ação", value: action, options: data.actions }]}
      count=${data.items.length} total=${data.total} />
    <${DataTable} tableId="audit" urlSort columns=${cols} rows=${data.items.map((i) => ({ ...i, _key: String(i.id) }))}
      empty="Nada registrado com estes filtros." />
    ${pages > 1 && html`<div class="toolbar" style="display:flex;gap:8px;align-items:center;margin-top:8px">
      <button class="sm" disabled=${page === 0} onClick=${() => r.pushParams({ page: page - 1 ? String(page - 1) : "" })}>‹ Mais recentes</button>
      <span class="help">página ${page + 1} de ${pages}</span>
      <button class="sm" disabled=${page + 1 >= pages} onClick=${() => r.pushParams({ page: String(page + 1) })}>Mais antigos ›</button>
    </div>`}
  </div>`;
}
