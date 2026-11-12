// Workflows (*.workflow.yaml) e Agents (*.agent.md) — editores de texto cru + validação.
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, ResourceTable, Field, Modal, CodeTextEditor, MarkdownEditor } from "../components.js";

// Página de um único tipo (workflows OU agentes), sem abas.
// URL: #workflows|#agents[/<arquivo>|/new][?q=]  (core/rules/urls-navegacao.md)
function CatalogSection({ kind, title }) {
  const r = useMenuRoute(kind);
  return html`<div>
    <div class="page-title"><h1>${title}</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => r.open("new")}>+ Novo</button></div>
    <${Kind} kind=${kind} r=${r} />
  </div>`;
}

export function WorkflowsPage() {
  return html`<${CatalogSection} kind="workflows" title="Workflows" />`;
}

export function AgentsPage() {
  return html`<${CatalogSection} kind="agents" title="Agentes" />`;
}

function Kind({ kind, r }) {
  const res = useResource(`/${kind}`, [kind]);
  const creating = r.segments[0] === "new";
  const open = r.segments[0] && !creating ? r.segments[0] : null;
  const setOpen = (f) => (f ? r.open(f) : r.close());
  const setCreating = (v) => (v ? r.open("new") : r.close());
  const q = r.params.q || "";
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const items = (res.data[kind] || []).filter((i) => matchText(q, i.name, i.file, i.id, i.function));
  const cols = kind === "workflows"
    ? [{ key: "name", label: "Nome", render: (r) => html`<b>${r.name || r.file}</b><div class="help">${r.file}</div>` },
       { key: "id", label: "ID", render: (r) => r.id || "—" },
       { key: "steps", label: "Passos", render: (r) => html`<${Badge}>${r.steps}<//>` }]
    : [{ key: "name", label: "Agente", render: (r) => html`${r.icon || ""} <b>${r.name || r.file}</b><div class="help">${r.file}</div>` },
       { key: "id", label: "ID", render: (r) => r.id || "—" },
       { key: "function", label: "Função", render: (r) => r.function || "—" }];
  cols[0].render = ((orig) => (row) => html`<a href=${"#" + kind + "/" + encodeURIComponent(row.file)} onClick=${(e) => e.stopPropagation()}>${orig(row)}</a>`)(cols[0].render);
  if (open) return html`<${Detail} key=${open} kind=${kind} file=${open} onClose=${() => setOpen(null)} onSaved=${() => res.reload()} />`;
  return html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar" count=${items.length} total=${(res.data[kind] || []).length} />
    <${ResourceTable} columns=${cols} rows=${items.map((i) => ({ ...i, _key: i.file }))}
      onRowClick=${(r) => setOpen(r.file)} empty="Nada aqui." />
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
  if (err) return html`<div class="card">'${file}' não encontrado. <a href=${"#" + kind}>Voltar</a></div>`;
  if (!data) return html`<${Spinner} />`;
  async function save() {
    try {
      let target = file, rev = data.rev;
      if (name !== file) {                          // renomeia o arquivo (conteúdo igual => rev não muda)
        await api.post(`/${kind}/${file}/rename`, { to: name });
        target = name;
      }
      const r = await api.put(`/${kind}/${target}`, { text }, rev);
      toast.ok("Salvo");
      if (target !== file) { location.hash = `#${kind}/${encodeURIComponent(target)}`; onSaved(); return; }
      setData({ ...data, rev: r?.rev ?? rev, text }); onSaved();
    } catch (e) { handleError(e); }
  }
  const isMd = file.endsWith(".md");
  const dirty = text !== data.text || name !== file;
  return html`<div>
    <div class="help"><a href=${"#" + kind}>← ${kind === "workflows" ? "Workflows" : "Agentes"}</a></div>
    <div class="page-title"><h1>${file}</h1></div>
    <${Field} label=${`Nome do arquivo (alterar = renomear — termina em ${kind === "workflows" ? ".workflow.yaml" : ".agent.md"})`}>
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    ${isMd ? html`<${MarkdownEditor} value=${text} onChange=${setText} />`
      : html`<${YamlEditor} name=${file} value=${text} onChange=${setText} view=${kind === "workflows" ? WorkflowView : null} />`}
    <div class="help">Validação no servidor: ${kind === "workflows" ? "exige workflow.steps" : "frontmatter com id/name/function"}.</div>
    <div style="margin-top:12px"><button class="primary" disabled=${!dirty} onClick=${save}>Salvar</button></div>
  </div>`;
}

// YAML estruturado: mesmos modos do Markdown — Ler (formatado) e Texto puro (validado).
function YamlEditor({ name, value, onChange, view }) {
  const [mode, setMode] = useState("read");
  return html`<div>
    <div class="md-toolbar"><div class="seg">
      ${[["read", "Ler"], ["raw", "Texto puro"]].map(([k, l]) => html`<button type="button" class=${mode === k ? "on" : ""} onClick=${() => setMode(k)}>${l}</button>`)}
    </div></div>
    ${mode === "raw" ? html`<${CodeTextEditor} name=${name} value=${value} onChange=${onChange} />`
      : html`<div class="card md-readbox">${view ? html`<${view} text=${value} />` : html`<pre class="raw">${value}</pre>`}</div>`}
  </div>`;
}

const STEP_FIELDS = [["inputFiles", "Entradas"], ["outputFiles", "Saídas"], ["qualityCriteria", "Critérios de qualidade"], ["vetoConditions", "Condições de veto"]];
function WorkflowView({ text }) {
  const [doc, setDoc] = useState(undefined);
  useEffect(() => {
    import("js-yaml").then((m) => { try { setDoc((m.load || m.default.load)(text)); } catch (e) { setDoc(e); } });
  }, [text]);
  if (doc === undefined) return html`<${Spinner} />`;
  if (doc instanceof Error) return html`<div class="yaml-bad">⚠ YAML inválido: ${doc.message.split("\n")[0]}. Corrija em “Texto puro”.</div>`;
  const w = doc?.workflow;
  if (!w) return html`<pre class="raw">${text}</pre>`;
  const list = (v) => (Array.isArray(v) ? v : [v]).map((x) => html`<code>${String(x)}</code> `);
  return html`<div class="md">
    <h2>${w.name || w.id}</h2>
    ${w.description && html`<p>${w.description}</p>`}
    ${w.triggers?.length ? html`<p><b>Gatilhos:</b> ${list(w.triggers)}</p>` : ""}
    <h3>Passos (${(w.steps || []).length})</h3>
    ${(w.steps || []).map((st) => html`<div class="card" key=${st.id} style="margin-bottom:10px">
      <div><b>${st.id} · ${st.name}</b> ${st.type && html`<${Badge}>${st.type}<//>`} ${st.agent && html`<${Badge}>${st.agent}<//>`}</div>
      ${st.instructions && html`<p>${st.instructions}</p>`}
      ${STEP_FIELDS.filter(([k]) => st[k] && (!Array.isArray(st[k]) || st[k].length)).map(([k, l]) => html`<div><b>${l}:</b> ${list(st[k])}</div>`)}
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
    try { await api.post(`/${kind}`, { file, text }); toast.ok("Criado"); onSaved(); }
    catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${`Novo ${kind}`} onClose=${onClose} wide=${true}>
    <${Field} label=${`Nome do arquivo (termina em ${ext})`}><input value=${file} placeholder=${`exemplo${ext}`} onInput=${(e) => setFile(e.target.value)} /><//>
    ${ext.endsWith(".md") ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`<${CodeTextEditor} name=${ext} value=${text} onChange=${setText} />`}
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
  <//>`;
}
