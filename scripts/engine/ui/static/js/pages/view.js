// Reports (read-only), Runs (read-only) e Settings (project-config.yaml).
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError, t, fmtDateTime } from "../ui.js";
import { authToken } from "../api.js";
import { UpdatesControl } from "./updates.js";
import { InstanceLanguageCard } from "../language.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, Modal, MarkdownPanel, CodeTextEditor } from "../components.js";

// URL: #reports[/<arquivo>][?q=]  (core/rules/navigation-urls.md)
export function ReportsPage() {
  const res = useResource("/reports");
  const r = useMenuRoute("reports");
  const q = r.params.q || "";
  const open = r.segments[0] || null;
  const setOpen = (f) => (f ? r.open(f) : r.close());
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("view.error", { message: res.error.message })}</div>`;
  const cols = [
    { key: "file", label: t("view.col_report"), hideable: false, sort: true, render: (x) => html`<a href=${"#reports/" + encodeURIComponent(x.file)} onClick=${(e) => e.stopPropagation()}><b>${x.file}</b></a>` },
    { key: "size", label: t("view.col_size"), sort: true, render: (r) => `${r.size} B` },
  ];
  return html`<div>
    <div class="page-title"><h1>${t("view.reports_title")}</h1></div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("view.search_report")} count=${res.data.reports.filter((x) => matchText(q, x.file)).length} total=${res.data.reports.length} />
    <${DataTable} tableId="reports" urlSort columns=${cols} rows=${res.data.reports.filter((x) => matchText(q, x.file)).map((x) => ({ ...x, _key: x.file }))}
      onRowClick=${(r) => setOpen(r.file)} empty=${t("view.no_reports")} />
    ${open && html`<${ReportView} key=${open} file=${open} onClose=${() => setOpen(null)} />`}
  </div>`;
}
// Visualizador de relatório (md/txt/log/pdf) + Baixar. Usado na página Relatórios e nos links da aba Claude.
export function ReportView({ file, onClose, fullLink }) {
  const ext = (file.split(".").pop() || "").toLowerCase();
  const [content, setContent] = useState(null);   // texto (md/txt) ou URL de blob (pdf)
  const fetchRaw = async (dl) => {
    const h = {}; const tok = authToken(); if (tok) h["X-Netops-Session"] = tok;
    const res = await fetch(`/api/reports/${encodeURIComponent(file)}/raw${dl ? "?download=1" : ""}`, { headers: h });
    if (!res.ok) throw new Error(res.status === 404 ? t("view.file_not_found") : t("view.http_error", { status: res.status }));
    return res.blob();
  };
  useEffect(() => {
    let url = null, dead = false;
    fetchRaw(false).then(async (b) => {
      if (dead) return;
      if (ext === "pdf") { url = URL.createObjectURL(b); setContent(url); } else setContent(await b.text());
    }).catch((e) => { if (!dead) { setContent(false); handleError(e); } });
    return () => { dead = true; if (url) URL.revokeObjectURL(url); };
  }, [file]);
  const download = async () => {
    try {
      const u = URL.createObjectURL(await fetchRaw(true));
      const a = document.createElement("a"); a.href = u; a.download = file; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(u), 10000);
    } catch (e) { handleError(e); }
  };
  const body = content === null ? html`<${Spinner} />`
    : content === false ? html`<div class="card">${t("view.open_failed")}</div>`
    : ext === "pdf" ? html`<iframe src=${content} title=${file} style="width:100%;height:70vh;border:0"></iframe>`
    : ext === "md" ? html`<${MarkdownPanel} text=${content} />`
    : html`<pre class="raw">${content}</pre>`;
  return html`<${Modal} title=${file} onClose=${onClose} wide=${true}>
    ${body}
    <div class="modal-actions">
      ${fullLink && html`<a class="btn" href=${"#reports/" + encodeURIComponent(file)} onClick=${onClose}>${t("view.open_full")}</a>`}
      <button class="primary" onClick=${download}>${t("view.download")}</button>
      <button onClick=${onClose}>${t("common.close")}</button>
    </div>
  <//>`;
}

// URL: #runs[/<id>][?q=&status=]  (core/rules/navigation-urls.md)
export function RunsPage() {
  const res = useResource("/runs");
  const r = useMenuRoute("runs");
  const { q = "", status = "" } = r.params;
  const open = r.segments[0] || null;
  const setOpen = (id) => (id ? r.open(id) : r.close());
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("view.error", { message: res.error.message })}</div>`;
  const dot = (s) => ({ completed: "var(--ok)", failed: "var(--danger)", in_progress: "var(--warn)" }[s] || "var(--muted)");
  const cols = [
    { key: "id", label: t("view.col_run"), hideable: false, sort: true, render: (x) => html`<a href=${"#runs/" + encodeURIComponent(x.id)} onClick=${(e) => e.stopPropagation()}><b>${x.id}</b></a>` },
    { key: "status", label: t("common.status"), sort: true, render: (x) => html`<span class="statedot" style=${`background:${dot(x.status)}`}></span>${x.status || "—"}` },
  ];
  return html`<div>
    <div class="page-title"><h1>${t("view.runs_title")}</h1></div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("view.search_run")} count=${res.data.runs.filter((x) => (!status || x.status === status) && matchText(q, x.id)).length} total=${res.data.runs.length}
      selects=${[{ key: "status", label: t("common.status"), value: status, options: [...new Set(res.data.runs.map((x) => x.status).filter(Boolean))].sort() }]} />
    <${DataTable} tableId="runs" urlSort columns=${cols} rows=${res.data.runs.filter((x) => (!status || x.status === status) && matchText(q, x.id)).map((x) => ({ ...x, _key: x.id }))}
      onRowClick=${(r) => setOpen(r.id)} empty=${t("view.no_runs")} />
    ${open && html`<${RunView} key=${open} id=${open} onClose=${() => setOpen(null)} />`}
  </div>`;
}
function RunView({ id, onClose }) {
  const [data, setData] = useState(null);
  const [artifact, setArtifact] = useState(null);
  useEffect(() => { api.get(`/runs/${id}`).then(setData).catch(handleError); }, []);
  return html`<${Modal} title=${t("view.run_title", { id })} onClose=${onClose} wide=${true}>
    ${!data ? html`<${Spinner} />` : html`<div>
      <h3>state.json</h3>
      <pre class="md">${JSON.stringify(data.state, null, 2)}</pre>
      <h3>${t("view.artifacts")}</h3>
      ${data.artifacts.length ? html`<ul>${data.artifacts.map((a) => html`<li key=${a}>
        <button class="ghost" onClick=${async () => { try { setArtifact(await api.get(`/runs/${id}/artifact?path=${encodeURIComponent(a)}`)); } catch (e) { handleError(e); } }}>${a}</button></li>`)}</ul>`
        : html`<div class="help">${t("view.no_artifacts")}</div>`}
      ${artifact && html`<div class="card"><b>${artifact.path}</b><pre class="md">${artifact.text}</pre></div>`}
    </div>`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.close")}</button></div>
  <//>`;
}

// Firewall de acesso web: só IP/redes da lista acessam o console (services/web_access_svc.py).
const toLines = (s) => s.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
function WebAccessCard({ rev, setRev }) {
  const st = useResource("/web-access");
  const [form, setForm] = useState(null);
  useEffect(() => {
    if (st.data && !form) setForm({ enabled: st.data.enabled, nets: st.data.allowed_networks.join("\n"), proxies: st.data.trusted_proxies.join("\n") });
  }, [st.data]);
  if (st.loading && !form) return html`<div class="card"><${Spinner} /></div>`;
  if (st.error || !form) return html`<div class="card">${t("settings.error", { message: st.error?.message || t("settings.no_data") })}</div>`;
  const d = st.data;
  async function save() {
    try {
      const r = await api.put("/config", { web_access: { enabled: form.enabled, allowed_networks: toLines(form.nets), trusted_proxies: toLines(form.proxies) } }, rev);
      setRev(r.rev); toast.ok(t("settings.web_saved"));
      st.reload();
    } catch (e) { handleError(e); }
  }
  const cols = [
    { key: "ip", label: t("settings.col_blocked_ip"), hideable: false, sort: true, render: (x) => x.ip },
    { key: "count", label: t("settings.col_attempts"), sort: true, render: (x) => x.count },
    { key: "path", label: t("settings.col_last_path"), sort: true, render: (x) => x.path },
    { key: "last", label: t("settings.col_last_time"), sort: true, render: (x) => fmtDateTime(x.last * 1000) },
  ];
  return html`<div class="card">
    <h3>${t("settings.web_title")}</h3>
    <div class="help">${t("settings.your_ip")} <b>${d.client_ip || "?"}</b> ${d.client_allowed ? html`<${Badge} kind="ok">${t("settings.ip_allowed")}<//>` : html`<${Badge} kind="err">${t("settings.ip_outside")}<//>`}</div>
    <${Field} label="">
      <label><input type="checkbox" checked=${form.enabled} onChange=${(e) => setForm({ ...form, enabled: e.target.checked })} /> ${t("settings.web_restrict")}</label><//>
    <${Field} label=${t("settings.web_networks")} hint=${t("settings.web_networks_hint")}>
      <textarea rows="6" value=${form.nets} onInput=${(e) => setForm({ ...form, nets: e.target.value })}></textarea><//>
    <${Field} label=${t("settings.web_proxies")} hint=${t("settings.web_proxies_hint")}>
      <textarea rows="2" value=${form.proxies} onInput=${(e) => setForm({ ...form, proxies: e.target.value })}></textarea><//>
    <div class="row">
      <button class="primary" onClick=${save}>${t("settings.web_save")}</button>
      <button onClick=${() => setForm({ ...form, nets: d.defaults.join("\n") })}>${t("settings.web_restore")}</button>
    </div>
    ${d.denied.length ? html`<h4>${t("settings.web_recent_blocks")}</h4>
      <${DataTable} tableId="web-access-denied" columns=${cols} rows=${d.denied.map((x) => ({ ...x, _key: x.ip }))} empty=${t("settings.web_no_blocks")} />` : null}
  </div>`;
}

export function SettingsPage() {
  const res = useResource("/config");
  const [data, setData] = useState(null);
  const [rev, setRev] = useState(null);
  useEffect(() => { if (res.data) { setData(res.data.data); setRev(res.data.rev); } }, [res.data]);
  if (res.loading || !data) return html`<${Spinner} />`;
  const proj = data.project || {}, ops = data.operations || {}, vault = data.vault || {}, access = data.access || {};
  const upd = (sec, k, v) => setData((d) => ({ ...d, [sec]: { ...(d[sec] || {}), [k]: v } }));
  async function save() {
    try {
      const body = {
        project: { network_name: proj.network_name, description: proj.description },
        operations: { maintenance_window: ops.maintenance_window, escalation_contact: ops.escalation_contact },
        vault: { session_ttl_seconds: vault.session_ttl_seconds ? Number(vault.session_ttl_seconds) : undefined },
        access: { session_idle_minutes: access.session_idle_minutes ? Number(access.session_idle_minutes) : undefined },
      };
      const r = await api.put("/config", body, rev); setRev(r.rev); toast.ok(t("settings.saved"));
    } catch (e) { handleError(e); }
  }
  return html`<div>
    <div class="page-title"><h1>${t("settings.title")}</h1></div>
    <div class="card">
      <${Field} label=${t("settings.network_name")}><input value=${proj.network_name || ""} onInput=${(e) => upd("project", "network_name", e.target.value)} /><//>
      <${Field} label=${t("common.description")}><input value=${proj.description || ""} onInput=${(e) => upd("project", "description", e.target.value)} /><//>
      <div class="row">
        <${Field} label=${t("settings.maintenance_window")}><input value=${ops.maintenance_window || ""} onInput=${(e) => upd("operations", "maintenance_window", e.target.value)} /><//>
        <${Field} label=${t("settings.escalation_contact")}><input value=${ops.escalation_contact || ""} onInput=${(e) => upd("operations", "escalation_contact", e.target.value)} /><//>
      </div>
      <${Field} label=${t("settings.vault_ttl")} hint=${t("settings.vault_ttl_hint")}>
        <input type="number" value=${vault.session_ttl_seconds || ""} onInput=${(e) => upd("vault", "session_ttl_seconds", e.target.value)} /><//>
      <${Field} label=${t("settings.access_idle")} hint=${t("settings.access_idle_hint")}>
        <input type="number" min="1" step="1" placeholder="5" value=${access.session_idle_minutes || ""} onInput=${(e) => upd("access", "session_idle_minutes", e.target.value)} /><//>
      <button class="primary" onClick=${save}>${t("common.save")}</button>
    </div>
    <${InstanceLanguageCard} />
    <${WebAccessCard} rev=${rev} setRev=${setRev} />
    <div class="card">
      <h3>${t("settings.updates")}</h3>
      <${UpdatesControl} />
    </div>
  </div>`;
}
