// Workflows (*.workflow.yaml) e Agents (*.agent.md) — editores de texto cru + validação.
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError, Tabs } from "../ui.js";
import { ResourceTable, Field, Modal, CodeTextEditor, MarkdownEditor } from "../components.js";

export function CatalogPage() {
  const [tab, setTab] = useState("workflows");
  const [creating, setCreating] = useState(false);
  return html`<div>
    <div class="page-title"><h1>Workflows & Agentes</h1></div>
    <${Tabs} tabs=${[{ key: "workflows", label: "Workflows" }, { key: "agents", label: "Agentes" }]} active=${tab}
      onChange=${(k) => { setCreating(false); setTab(k); }}
      actions=${html`<button class="primary sm" onClick=${() => setCreating(true)}>+ Novo</button>`} />
    <${Kind} kind=${tab} key=${tab} creating=${creating} setCreating=${setCreating} />
  </div>`;
}

function Kind({ kind, creating, setCreating }) {
  const res = useResource(`/${kind}`, [kind]);
  const [open, setOpen] = useState(null);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const items = res.data[kind] || [];
  const cols = kind === "workflows"
    ? [{ key: "name", label: "Nome", render: (r) => html`<b>${r.name || r.file}</b><div class="help">${r.file}</div>` },
       { key: "id", label: "ID", render: (r) => r.id || "—" },
       { key: "steps", label: "Passos", render: (r) => html`<${Badge}>${r.steps}<//>` }]
    : [{ key: "name", label: "Agente", render: (r) => html`${r.icon || ""} <b>${r.name || r.file}</b><div class="help">${r.file}</div>` },
       { key: "id", label: "ID", render: (r) => r.id || "—" },
       { key: "function", label: "Função", render: (r) => r.function || "—" }];
  return html`<div>
    <${ResourceTable} columns=${cols} rows=${items.map((i) => ({ ...i, _key: i.file }))}
      onRowClick=${(r) => setOpen(r.file)} empty="Nada aqui." />
    ${open && html`<${Editor} kind=${kind} file=${open} onClose=${() => setOpen(null)} onSaved=${() => { setOpen(null); res.reload(); }} />`}
    ${creating && html`<${Creator} kind=${kind} onClose=${() => setCreating(false)} onSaved=${() => { setCreating(false); res.reload(); }} />`}
  </div>`;
}

function Editor({ kind, file, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [name, setName] = useState(file);
  useEffect(() => { api.get(`/${kind}/${file}`).then((d) => { setData(d); setText(d.text); }).catch(handleError); }, []);
  if (!data) return html`<${Modal} title="Carregando…" onClose=${onClose}><${Spinner} /><//>`;
  async function save() {
    try {
      let target = file;
      if (name !== file) {                          // renomeia o arquivo (conteúdo igual => rev não muda)
        await api.post(`/${kind}/${file}/rename`, { to: name });
        target = name;
      }
      await api.put(`/${kind}/${target}`, { text }, data.rev);
      toast.ok("Salvo"); onSaved();
    } catch (e) { handleError(e); }
  }
  const isMd = file.endsWith(".md");
  return html`<${Modal} title=${file} onClose=${onClose} wide=${true}>
    <${Field} label=${`Nome do arquivo (alterar = renomear — termina em ${kind === "workflows" ? ".workflow.yaml" : ".agent.md"})`}>
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    ${isMd ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`<${CodeTextEditor} value=${text} onChange=${setText} />`}
    <div class="help">Validação no servidor: ${kind === "workflows" ? "exige workflow.steps" : "frontmatter com id/name/function"}.</div>
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button><button class="primary" onClick=${save}>Salvar</button></div>
  <//>`;
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
    <${CodeTextEditor} value=${text} onChange=${setText} />
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
  <//>`;
}
