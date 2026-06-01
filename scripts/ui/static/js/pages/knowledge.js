// Conhecimento: best-practices/ e config-examples/ (catálogo + editores de arquivo).
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError, Tabs } from "../ui.js";
import { ResourceTable, Field, Modal, MarkdownEditor, CodeTextEditor, MarkdownView, EnumSelect, useEnums } from "../components.js";

export function KnowledgePage() {
  const [tab, setTab] = useState("best-practices");
  const [creating, setCreating] = useState(false);
  return html`<div>
    <div class="page-title"><h1>Conhecimento</h1></div>
    <${Tabs} tabs=${[{ key: "best-practices", label: "Boas práticas" }, { key: "config-examples", label: "Exemplos de config" }]}
      active=${tab} onChange=${(k) => { setCreating(false); setTab(k); }}
      actions=${html`<button class="primary sm" onClick=${() => setCreating(true)}>+ Novo arquivo</button>`} />
    <${KnowledgeKind} kind=${tab} key=${tab} creating=${creating} setCreating=${setCreating} />
  </div>`;
}

function KnowledgeKind({ kind, creating, setCreating }) {
  const res = useResource(`/knowledge/${kind}`, [kind]);
  const [open, setOpen] = useState(null);   // {vendor, name}
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { index, files } = res.data;
  const rows = (index || []).map((e) => ({ ...e, _key: e.file }));
  const cols = kind === "best-practices"
    ? [{ key: "titulo", label: "Título", render: (r) => html`<b>${r.titulo}</b>` },
       { key: "vendor", label: "Vendor", render: (r) => html`<${Badge}>${r.vendor}<//>` },
       { key: "file", label: "Arquivo", render: (r) => html`<span class="mono">${r.file}</span>` },
       { key: "quando_usar", label: "Quando usar", render: (r) => r.quando_usar }]
    : [{ key: "topico", label: "Tópico", render: (r) => html`<b>${r.topico}</b>` },
       { key: "vendor", label: "Vendor", render: (r) => html`<${Badge}>${r.vendor}<//>` },
       { key: "file", label: "Arquivo", render: (r) => html`<span class="mono">${r.file}</span>` },
       { key: "descricao", label: "Descrição", render: (r) => r.descricao }];
  function openFile(rel) { const [vendor, ...rest] = rel.split("/"); setOpen({ vendor, name: rest.join("/") }); }
  return html`<div>
    <${ResourceTable} columns=${cols} rows=${rows} onRowClick=${(r) => openFile(r.file)} empty="Catálogo vazio." />
    ${files?.length ? html`<div class="help" style="margin-top:8px">Arquivos em disco: ${files.join(", ")}</div>` : ""}
    ${open && html`<${FileEditor} kind=${kind} target=${open} onClose=${() => setOpen(null)} onSaved=${() => res.reload()} />`}
    ${creating && html`<${NewFile} kind=${kind} onClose=${() => setCreating(false)} onSaved=${() => { setCreating(false); res.reload(); }} />`}
  </div>`;
}

function FileEditor({ kind, target, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  useEffect(() => {
    api.get(`/knowledge/${kind}/file?vendor=${encodeURIComponent(target.vendor)}&name=${encodeURIComponent(target.name)}`)
      .then((d) => { setData(d); setText(d.text); }).catch(handleError);
  }, []);
  if (!data) return html`<${Modal} title="Carregando…" onClose=${onClose}><${Spinner} /><//>`;
  const isMd = target.name.endsWith(".md");
  async function save() {
    try { await api.put(`/knowledge/${kind}/file`, { vendor: target.vendor, name: target.name, text }, data.rev); toast.ok("Salvo"); onSaved(); }
    catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${`${target.vendor}/${target.name}`} onClose=${onClose} wide=${true}>
    ${isMd ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`<${CodeTextEditor} value=${text} onChange=${setText} />`}
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button><button class="primary" onClick=${save}>Salvar</button></div>
  <//>`;
}

function NewFile({ kind, onClose, onSaved }) {
  const enums = useEnums();
  const [f, setF] = useState({ vendor: "general", name: "", titulo: "", quando_usar: "", topico: "", descricao: "", text: "" });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  async function save() {
    try { await api.post(`/knowledge/${kind}`, f); toast.ok("Arquivo criado"); onSaved(); }
    catch (e) { handleError(e); }
  }
  const vendors = enums?.vendors_knowledge || ["general"];
  return html`<${Modal} title=${`Novo arquivo (${kind})`} onClose=${onClose} wide=${true}>
    <div class="row">
      <${Field} label="Vendor"><${EnumSelect} value=${f.vendor} options=${vendors} onChange=${(v) => set("vendor", v)} /><//>
      <${Field} label="Nome do arquivo" hint=${kind === "best-practices" ? "ex.: firewall.md" : "ex.: vlan-trunk.rsc"}>
        <input value=${f.name} onInput=${(e) => set("name", e.target.value)} /><//>
    </div>
    ${kind === "best-practices"
      ? html`<${Field} label="Título"><input value=${f.titulo} onInput=${(e) => set("titulo", e.target.value)} /><//>
             <${Field} label="Quando usar"><input value=${f.quando_usar} onInput=${(e) => set("quando_usar", e.target.value)} /><//>`
      : html`<${Field} label="Tópico"><input value=${f.topico} onInput=${(e) => set("topico", e.target.value)} /><//>
             <${Field} label="Descrição"><input value=${f.descricao} onInput=${(e) => set("descricao", e.target.value)} /><//>`}
    <${Field} label="Conteúdo"><textarea class="codearea" value=${f.text} onInput=${(e) => set("text", e.target.value)}></textarea><//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
  <//>`;
}
