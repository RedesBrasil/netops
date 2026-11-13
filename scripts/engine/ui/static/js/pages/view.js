// Reports (read-only), Runs (read-only) e Settings (project-config.yaml).
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { UpdatesControl } from "./updates.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, Modal, MarkdownPanel, CodeTextEditor } from "../components.js";

// URL: #reports[/<arquivo>][?q=]  (core/rules/urls-navegacao.md)
export function ReportsPage() {
  const res = useResource("/reports");
  const r = useMenuRoute("reports");
  const q = r.params.q || "";
  const open = r.segments[0] || null;
  const setOpen = (f) => (f ? r.open(f) : r.close());
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const cols = [
    { key: "file", label: "Relatório", hideable: false, sort: true, render: (x) => html`<a href=${"#reports/" + encodeURIComponent(x.file)} onClick=${(e) => e.stopPropagation()}><b>${x.file}</b></a>` },
    { key: "size", label: "Tamanho", sort: true, render: (r) => `${r.size} B` },
  ];
  return html`<div>
    <div class="page-title"><h1>Relatórios</h1></div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar relatório" count=${res.data.reports.filter((x) => matchText(q, x.file)).length} total=${res.data.reports.length} />
    <${DataTable} tableId="reports" urlSort columns=${cols} rows=${res.data.reports.filter((x) => matchText(q, x.file)).map((x) => ({ ...x, _key: x.file }))}
      onRowClick=${(r) => setOpen(r.file)} empty="Nenhum relatório em reports/." />
    ${open && html`<${ReportView} key=${open} file=${open} onClose=${() => setOpen(null)} />`}
  </div>`;
}
function ReportView({ file, onClose }) {
  const [md, setMd] = useState(null);
  useEffect(() => { api.get(`/reports/${file}`).then((d) => setMd(d.markdown)).catch(handleError); }, []);
  return html`<${Modal} title=${file} onClose=${onClose} wide=${true}>
    ${md === null ? html`<${Spinner} />` : html`<${MarkdownPanel} text=${md} />`}
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button></div>
  <//>`;
}

// URL: #runs[/<id>][?q=&status=]  (core/rules/urls-navegacao.md)
export function RunsPage() {
  const res = useResource("/runs");
  const r = useMenuRoute("runs");
  const { q = "", status = "" } = r.params;
  const open = r.segments[0] || null;
  const setOpen = (id) => (id ? r.open(id) : r.close());
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const dot = (s) => ({ completed: "var(--ok)", failed: "var(--danger)", in_progress: "var(--warn)" }[s] || "var(--muted)");
  const cols = [
    { key: "id", label: "Execução", hideable: false, sort: true, render: (x) => html`<a href=${"#runs/" + encodeURIComponent(x.id)} onClick=${(e) => e.stopPropagation()}><b>${x.id}</b></a>` },
    { key: "status", label: "Status", sort: true, render: (x) => html`<span class="statedot" style=${`background:${dot(x.status)}`}></span>${x.status || "—"}` },
  ];
  return html`<div>
    <div class="page-title"><h1>Execuções</h1></div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar execução" count=${res.data.runs.filter((x) => (!status || x.status === status) && matchText(q, x.id)).length} total=${res.data.runs.length}
      selects=${[{ key: "status", label: "Status", value: status, options: [...new Set(res.data.runs.map((x) => x.status).filter(Boolean))].sort() }]} />
    <${DataTable} tableId="runs" urlSort columns=${cols} rows=${res.data.runs.filter((x) => (!status || x.status === status) && matchText(q, x.id)).map((x) => ({ ...x, _key: x.id }))}
      onRowClick=${(r) => setOpen(r.id)} empty="Nenhuma execução em runs/ (criadas durante workflows)." />
    ${open && html`<${RunView} key=${open} id=${open} onClose=${() => setOpen(null)} />`}
  </div>`;
}
function RunView({ id, onClose }) {
  const [data, setData] = useState(null);
  const [artifact, setArtifact] = useState(null);
  useEffect(() => { api.get(`/runs/${id}`).then(setData).catch(handleError); }, []);
  return html`<${Modal} title=${`Execução ${id}`} onClose=${onClose} wide=${true}>
    ${!data ? html`<${Spinner} />` : html`<div>
      <h3>state.json</h3>
      <pre class="md">${JSON.stringify(data.state, null, 2)}</pre>
      <h3>Artefatos</h3>
      ${data.artifacts.length ? html`<ul>${data.artifacts.map((a) => html`<li key=${a}>
        <button class="ghost" onClick=${async () => { try { setArtifact(await api.get(`/runs/${id}/artifact?path=${encodeURIComponent(a)}`)); } catch (e) { handleError(e); } }}>${a}</button></li>`)}</ul>`
        : html`<div class="help">sem artefatos</div>`}
      ${artifact && html`<div class="card"><b>${artifact.path}</b><pre class="md">${artifact.text}</pre></div>`}
    </div>`}
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button></div>
  <//>`;
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
      const r = await api.put("/config", body, rev); setRev(r.rev); toast.ok("Configuração salva");
    } catch (e) { handleError(e); }
  }
  return html`<div>
    <div class="page-title"><h1>Configuração do projeto</h1></div>
    <div class="card">
      <${Field} label="Nome da rede"><input value=${proj.network_name || ""} onInput=${(e) => upd("project", "network_name", e.target.value)} /><//>
      <${Field} label="Descrição"><input value=${proj.description || ""} onInput=${(e) => upd("project", "description", e.target.value)} /><//>
      <div class="row">
        <${Field} label="Janela de manutenção"><input value=${ops.maintenance_window || ""} onInput=${(e) => upd("operations", "maintenance_window", e.target.value)} /><//>
        <${Field} label="Contato de escalação"><input value=${ops.escalation_contact || ""} onInput=${(e) => upd("operations", "escalation_contact", e.target.value)} /><//>
      </div>
      <${Field} label="TTL da sessão do cofre (segundos)" hint="Tempo de inatividade até re-trancar (default 900)">
        <input type="number" value=${vault.session_ttl_seconds || ""} onInput=${(e) => upd("vault", "session_ttl_seconds", e.target.value)} /><//>
      <${Field} label="Sessão de acesso aos equipamentos (minutos sem comando)" hint="Sessão aberta pelo session.py (1 login por host, vários comandos) fecha após N min sem comando. Padrão 5. Vale na hora, inclusive para sessões já abertas.">
        <input type="number" min="1" step="1" placeholder="5" value=${access.session_idle_minutes || ""} onInput=${(e) => upd("access", "session_idle_minutes", e.target.value)} /><//>
      <button class="primary" onClick=${save}>Salvar</button>
    </div>
    <div class="card">
      <h3>Atualizações</h3>
      <${UpdatesControl} />
    </div>
  </div>`;
}
