// Workflows (*.workflow.yaml) e Agents (*.agent.md) — editores de texto cru + validação.
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError, t } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { WorkflowForm } from "../workflow-form.js";
import { FilterBar, DataTable, Field, Modal, CodeTextEditor, MarkdownEditor } from "../components.js";

// Página de um único tipo (workflows OU agentes), sem abas.
// URL: #workflows|#agents[/<arquivo>|/new][?q=]  (core/rules/urls-navegacao.md)
function CatalogSection({ kind, title }) {
  const r = useMenuRoute(kind);
  return html`<div>
    <div class="page-title"><h1>${title}</h1><span class="spacer"></span>
      <button class="primary needs-knowledge-edit" onClick=${() => r.open("new")}>${t("catalog.new_btn")}</button></div>
    <${Kind} kind=${kind} r=${r} />
  </div>`;
}

export function WorkflowsPage() {
  return html`<${CatalogSection} kind="workflows" title=${t("catalog.workflows")} />`;
}

export function AgentsPage() {
  return html`<${CatalogSection} kind="agents" title=${t("catalog.agents")} />`;
}

function Kind({ kind, r }) {
  const res = useResource(`/${kind}`, [kind]);
  const creating = r.segments[0] === "new";
  const open = r.segments[0] && !creating ? r.segments[0] : null;
  const setOpen = (f) => (f ? r.open(f) : r.close());
  const setCreating = (v) => (v ? r.open("new") : r.close());
  const q = r.params.q || "";
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("catalog.error", { message: res.error.message })}</div>`;
  const items = (res.data[kind] || []).filter((i) => matchText(q, i.name, i.file, i.id, i.function));
  const cols = kind === "workflows"
    ? [{ key: "name", label: t("common.name"), hideable: false, sort: (r) => r.name || r.file, render: (r) => html`<b>${r.name || r.file}</b><div class="help">${r.file}</div>` },
       { key: "id", label: "ID", sort: true, render: (r) => r.id || "—" },
       { key: "steps", label: t("catalog.col_steps"), sort: true, render: (r) => html`<${Badge}>${r.steps}<//>` }]
    : [{ key: "name", label: t("catalog.col_agent"), hideable: false, sort: (r) => r.name || r.file, render: (r) => html`${r.icon || ""} <b>${r.name || r.file}</b><div class="help">${r.file}</div>` },
       { key: "id", label: "ID", sort: true, render: (r) => r.id || "—" },
       { key: "function", label: t("catalog.col_function"), sort: true, render: (r) => r.function || "—" }];
  cols[0].render = ((orig) => (row) => html`<a href=${"#" + kind + "/" + encodeURIComponent(row.file)} onClick=${(e) => e.stopPropagation()}>${orig(row)}</a>`)(cols[0].render);
  if (open) return html`<${Detail} key=${open} kind=${kind} file=${open} onClose=${() => setOpen(null)} onSaved=${() => res.reload()} />`;
  return html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("common.search")} count=${items.length} total=${(res.data[kind] || []).length} />
    <${DataTable} tableId=${kind} urlSort columns=${cols} rows=${items.map((i) => ({ ...i, _key: i.file }))}
      onRowClick=${(r) => setOpen(r.file)} empty=${t("catalog.empty")} />
    ${creating && html`<${Creator} kind=${kind} onClose=${() => setCreating(false)} onSaved=${() => { setCreating(false); res.reload(); }} />`}
  </div>`;
}

// Detalhe inline (sem modal), como Memória e Skills: #workflows/<arquivo> | #agents/<arquivo>
function Detail({ kind, file, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [name, setName] = useState(file);
  const [err, setErr] = useState(null);
  useEffect(() => { api.get(`/${kind}/${file}`).then((d) => { setData(d); setText(d.text); }).catch(setErr); }, []);
  if (err) return html`<div class="card">${t("catalog.not_found", { file })} <a href=${"#" + kind}>${t("common.back")}</a></div>`;
  if (!data) return html`<${Spinner} />`;
  async function save() {
    try {
      let target = file, rev = data.rev;
      if (name !== file) {                          // renomeia o arquivo (conteúdo igual => rev não muda)
        await api.post(`/${kind}/${file}/rename`, { to: name });
        target = name;
      }
      const r = await api.put(`/${kind}/${target}`, { text }, rev);
      toast.ok(t("catalog.saved"));
      if (target !== file) { location.hash = `#${kind}/${encodeURIComponent(target)}`; onSaved(); return; }
      setData({ ...data, rev: r?.rev ?? rev, text }); onSaved();
    } catch (e) { handleError(e); }
  }
  const isMd = file.endsWith(".md");
  const dirty = text !== data.text || name !== file;
  return html`<div>
    <div class="help"><a href=${"#" + kind}>← ${kind === "workflows" ? t("catalog.workflows") : t("catalog.agents")}</a></div>
    <div class="page-title"><h1>${file}</h1></div>
    <${Field} label=${t("catalog.file_name_rename", { ext: kind === "workflows" ? ".workflow.yaml" : ".agent.md" })}>
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    ${isMd ? html`<${MarkdownEditor} value=${text} onChange=${setText} />`
      : html`<${YamlEditor} name=${file} value=${text} onChange=${setText} view=${kind === "workflows" ? WorkflowView : null} form=${kind === "workflows" ? WorkflowForm : null} />`}
    <div class="help">${t("catalog.server_validation", { rule: kind === "workflows" ? t("catalog.rule_workflow") : t("catalog.rule_agent") })}</div>
    <div style="margin-top:12px"><button class="primary needs-knowledge-edit" disabled=${!dirty} onClick=${save}>${t("common.save")}</button></div>
  </div>`;
}

// YAML estruturado: mesmos modos do Markdown — Ler (formatado) e Texto puro (validado).
function YamlEditor({ name, value, onChange, view, form }) {
  const [mode, setMode] = useState("read");
  return html`<div>
    <div class="md-toolbar"><div class="seg">
      ${[["read", t("components.md_mode_read")], ...(form ? [["visual", t("components.md_mode_visual")]] : []), ["raw", t("components.md_mode_raw")]].map(([k, l]) => html`<button type="button" class=${mode === k ? "on" : ""} onClick=${() => setMode(k)}>${l}</button>`)}
    </div></div>
    ${mode === "visual" ? html`<${form} value=${value} onChange=${onChange} />`
      : mode === "raw" ? html`<${CodeTextEditor} name=${name} value=${value} onChange=${onChange} />`
      : html`<div class="card md-readbox">${view ? html`<${view} text=${value} />` : html`<pre class="raw">${value}</pre>`}</div>`}
  </div>`;
}

const STEP_FIELDS = [["inputFiles", "catalog.step_inputs"], ["outputFiles", "catalog.step_outputs"], ["qualityCriteria", "catalog.step_quality"], ["vetoConditions", "catalog.step_veto"]];
function WorkflowView({ text }) {
  const [doc, setDoc] = useState(undefined);
  useEffect(() => {
    import("js-yaml").then((m) => { try { setDoc((m.load || m.default.load)(text)); } catch (e) { setDoc(e); } });
  }, [text]);
  if (doc === undefined) return html`<${Spinner} />`;
  if (doc instanceof Error) return html`<div class="yaml-bad">${t("catalog.yaml_invalid", { error: doc.message.split("\n")[0] })}</div>`;
  const w = doc?.workflow;
  if (!w) return html`<pre class="raw">${text}</pre>`;
  const list = (v) => (Array.isArray(v) ? v : [v]).map((x) => html`<code>${String(x)}</code> `);
  return html`<div class="md">
    <h2>${w.name || w.id}</h2>
    ${w.description && html`<p>${w.description}</p>`}
    ${w.triggers?.length ? html`<p><b>${t("catalog.triggers")}</b> ${list(w.triggers)}</p>` : ""}
    <h3>${t("catalog.steps_count", { n: (w.steps || []).length })}</h3>
    ${(w.steps || []).map((st) => html`<div class="card" key=${st.id} style="margin-bottom:10px">
      <div><b>${st.id} · ${st.name}</b> ${st.type && html`<${Badge}>${st.type}<//>`} ${st.agent && html`<${Badge}>${st.agent}<//>`}</div>
      ${st.instructions && html`<p>${st.instructions}</p>`}
      ${STEP_FIELDS.filter(([k]) => st[k] && (!Array.isArray(st[k]) || st[k].length)).map(([k, l]) => html`<div><b>${t(l)}:</b> ${list(st[k])}</div>`)}
    </div>`)}
  </div>`;
}

function Creator({ kind, onClose, onSaved }) {
  const ext = kind === "workflows" ? ".workflow.yaml" : ".agent.md";
  const tmpl = kind === "workflows"
    ? "workflow:\n  id: meu-workflow\n  name: Meu Workflow\n  description: \n  triggers: []\n  steps:\n    - id: \"01\"\n      name: Passo 1\n      type: inline\n      agent: coordinator\n      instructions: \n"
    : "---\nid: meu-agente\nname: Meu Agente\nicon: 🤖\nfunction: executar\nscope: \n---\n\n# Meu Agente\n\n## Persona\n";
  const [file, setFile] = useState("");
  const [text, setText] = useState(tmpl);
  async function save() {
    try { await api.post(`/${kind}`, { file, text }); toast.ok(t("catalog.created")); onSaved(); }
    catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${t("catalog.new_kind", { kind })} onClose=${onClose} wide=${true}>
    <${Field} label=${t("catalog.file_name_ext", { ext })}><input value=${file} placeholder=${t("catalog.example_file", { ext })} onInput=${(e) => setFile(e.target.value)} /><//>
    ${ext.endsWith(".md") ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`<${CodeTextEditor} name=${ext} value=${text} onChange=${setText} />`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button><button class="primary" onClick=${save}>${t("common.create")}</button></div>
  <//>`;
}
