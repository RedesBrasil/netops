// Conhecimento: best-practices/ e config-examples/ (catálogo + editores de arquivo).
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, ResourceTable, Field, Modal, MarkdownEditor, CodeTextEditor, MarkdownView, EnumSelect, useEnums } from "../components.js";

// Página de uma única seção (boas práticas OU exemplos de config), sem abas.
// URL: #<menu>[/<vendor>/<arquivo>|/new][?q=&vendor=]  (core/rules/urls-navegacao.md)
function KnowledgeSection({ kind, title, menu }) {
  const r = useMenuRoute(menu);
  return html`<div>
    <div class="page-title"><h1>${title}</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => r.open("new")}>+ Novo arquivo</button></div>
    <${KnowledgeKind} kind=${kind} r=${r} />
  </div>`;
}

export function BestPracticesPage() {
  return html`<${KnowledgeSection} kind="best-practices" title="Boas práticas" menu="practices" />`;
}

export function ConfigsPage() {
  return html`<${KnowledgeSection} kind="config-examples" title="Configurações" menu="configs" />`;
}

function KnowledgeKind({ kind, r }) {
  const res = useResource(`/knowledge/${kind}`, [kind]);
  const creating = r.segments[0] === "new";
  const open = r.segments.length >= 2 ? { vendor: r.segments[0], name: r.segments.slice(1).join("/") } : null;
  const setOpen = (t) => (t ? r.open([t.vendor, ...t.name.split("/")]) : r.close());
  const setCreating = (v) => (v ? r.open("new") : r.close());
  const { q = "", vendor = "" } = r.params;
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { index, files } = res.data;
  const all = index || [];
  const rows = all.filter((e) => (!vendor || e.vendor === vendor) && matchText(q, e.titulo, e.topico, e.file, e.quando_usar, e.descricao))
    .map((e) => ({ ...e, _key: e.file }));
  const cols = kind === "best-practices"
    ? [{ key: "titulo", label: "Título", render: (r) => html`<b>${r.titulo}</b>` },
       { key: "vendor", label: "Vendor", render: (r) => html`<${Badge}>${r.vendor}<//>` },
       { key: "file", label: "Arquivo", render: (r) => html`<span class="mono">${r.file}</span>` },
       { key: "quando_usar", label: "Quando usar", render: (r) => r.quando_usar }]
    : [{ key: "topico", label: "Tópico", render: (r) => html`<b>${r.topico}</b>` },
       { key: "vendor", label: "Vendor", render: (r) => html`<${Badge}>${r.vendor}<//>` },
       { key: "file", label: "Arquivo", render: (r) => html`<span class="mono">${r.file}</span>` },
       { key: "descricao", label: "Descrição", render: (r) => r.descricao }];
  function split(rel) { const [vendor, ...rest] = rel.split("/"); return { vendor, name: rest.join("/") }; }
  const link = (r0, label) => html`<a href=${"#" + (kind === "best-practices" ? "practices" : "configs") + "/" + r0.file.split("/").map(encodeURIComponent).join("/")} onClick=${(e) => e.stopPropagation()}>${label}</a>`;
  cols[0].render = (r0) => link(r0, html`<b>${r0.titulo || r0.topico}</b>`);
  return html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar arquivo" count=${rows.length} total=${all.length}
      selects=${[{ key: "vendor", label: "Vendor", value: vendor, options: [...new Set(all.map((e) => e.vendor))].sort() }]} />
    <${ResourceTable} columns=${cols} rows=${rows} onRowClick=${(r) => setOpen(split(r.file))} empty="Catálogo vazio." />
    ${files?.length ? html`<div class="help" style="margin-top:8px">Arquivos em disco: ${files.join(", ")}</div>` : ""}
    ${open && html`<${FileEditor} key=${open.vendor + "/" + open.name} kind=${kind} target=${open} onClose=${() => setOpen(null)} onSaved=${() => { setOpen(null); res.reload(); }} />`}
    ${creating && html`<${NewFile} kind=${kind} onClose=${() => setCreating(false)} onSaved=${() => { setCreating(false); res.reload(); }} />`}
  </div>`;
}

function FileEditor({ kind, target, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [name, setName] = useState(target.name);
  useEffect(() => {
    api.get(`/knowledge/${kind}/file?vendor=${encodeURIComponent(target.vendor)}&name=${encodeURIComponent(target.name)}`)
      .then((d) => { setData(d); setText(d.text); }).catch(handleError);
  }, []);
  if (!data) return html`<${Modal} title="Carregando…" onClose=${onClose}><${Spinner} /><//>`;
  const isMd = target.name.endsWith(".md");
  async function save() {
    try {
      let path = { vendor: target.vendor, name: target.name }, rev = data.rev;
      if (name !== target.name) {                           // renomeia o arquivo + atualiza o índice
        rev = (await api.post(`/knowledge/${kind}/rename`,
          { vendor: target.vendor, name: target.name, to_name: name })).rev;
        path = { vendor: target.vendor, name };
      }
      await api.put(`/knowledge/${kind}/file`, { ...path, text }, rev);
      toast.ok("Salvo"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${`${target.vendor}/${target.name}`} onClose=${onClose} wide=${true}>
    <${Field} label="Nome do arquivo (alterar = renomear, atualiza o índice)">
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    ${isMd ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`<${CodeTextEditor} name=${target.name} value=${text} onChange=${setText} />`}
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
    <${Field} label="Conteúdo">${f.name.endsWith(".md") || (kind === "best-practices" && !/\.\w+$/.test(f.name))
      ? html`<${MarkdownEditor} value=${f.text} onChange=${(v) => set("text", v)} />`
      : html`<${CodeTextEditor} name=${f.name} value=${f.text} onChange=${(v) => set("text", v)} />`}<//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
  <//>`;
}
