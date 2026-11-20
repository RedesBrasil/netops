// Conhecimento: best-practices/ e config-examples/ (catálogo + editores de arquivo).
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError, t } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, Modal, MarkdownEditor, CodeTextEditor, MarkdownView, EnumSelect, useEnums } from "../components.js";

// Página de uma única seção (boas práticas OU exemplos de config), sem abas.
// URL: #<menu>[/<vendor>/<arquivo>|/new][?q=&vendor=]  (core/rules/urls-navegacao.md)
function KnowledgeSection({ kind, title, menu }) {
  const r = useMenuRoute(menu);
  return html`<div>
    <div class="page-title"><h1>${title}</h1><span class="spacer"></span>
      <button class="primary needs-knowledge-edit" onClick=${() => r.open("new")}>${t("knowledge.new_file_btn")}</button></div>
    <${KnowledgeKind} kind=${kind} r=${r} />
  </div>`;
}

export function BestPracticesPage() {
  return html`<${KnowledgeSection} kind="best-practices" title=${t("knowledge.best_practices")} menu="practices" />`;
}

export function ConfigsPage() {
  return html`<${KnowledgeSection} kind="config-examples" title=${t("knowledge.configs")} menu="configs" />`;
}

function KnowledgeKind({ kind, r }) {
  const res = useResource(`/knowledge/${kind}`, [kind]);
  const creating = r.segments[0] === "new";
  const open = r.segments.length >= 2 ? { vendor: r.segments[0], name: r.segments.slice(1).join("/") } : null;
  const setOpen = (it) => (it ? r.open([it.vendor, ...it.name.split("/")]) : r.close());
  const setCreating = (v) => (v ? r.open("new") : r.close());
  const { q = "", vendor = "" } = r.params;
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("knowledge.error", { message: res.error.message })}</div>`;
  const { index, files } = res.data;
  const all = index || [];
  const rows = all.filter((e) => (!vendor || e.vendor === vendor) && matchText(q, e.titulo, e.topico, e.file, e.quando_usar, e.descricao))
    .map((e) => ({ ...e, _key: e.file }));
  const cols = kind === "best-practices"
    ? [{ key: "titulo", hideable: false, sort: true, label: t("knowledge.col_title"), render: (r) => html`<b>${r.titulo}</b>` },
       { key: "vendor", sort: true, label: "Vendor", render: (r) => html`<${Badge}>${r.vendor}<//>` },
       { key: "file", sort: true, label: t("knowledge.col_file"), render: (r) => html`<span class="mono">${r.file}</span>` },
       { key: "quando_usar", sort: true, label: t("knowledge.col_when"), render: (r) => r.quando_usar }]
    : [{ key: "topico", hideable: false, sort: true, label: t("knowledge.col_topic"), render: (r) => html`<b>${r.topico}</b>` },
       { key: "vendor", sort: true, label: "Vendor", render: (r) => html`<${Badge}>${r.vendor}<//>` },
       { key: "file", sort: true, label: t("knowledge.col_file"), render: (r) => html`<span class="mono">${r.file}</span>` },
       { key: "descricao", sort: true, label: t("common.description"), render: (r) => r.descricao }];
  function split(rel) { const [vendor, ...rest] = rel.split("/"); return { vendor, name: rest.join("/") }; }
  const link = (r0, label) => html`<a href=${"#" + (kind === "best-practices" ? "practices" : "configs") + "/" + r0.file.split("/").map(encodeURIComponent).join("/")} onClick=${(e) => e.stopPropagation()}>${label}</a>`;
  cols[0].render = (r0) => link(r0, html`<b>${r0.titulo || r0.topico}</b>`);
  return html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("knowledge.search_file")} count=${rows.length} total=${all.length}
      selects=${[{ key: "vendor", sort: true, label: "Vendor", value: vendor, options: [...new Set(all.map((e) => e.vendor))].sort() }]} />
    <${DataTable} tableId=${kind} urlSort columns=${cols} rows=${rows} onRowClick=${(r) => setOpen(split(r.file))} empty=${t("knowledge.empty")} />
    ${files?.length ? html`<div class="help" style="margin-top:8px">${t("knowledge.files_on_disk", { files: files.join(", ") })}</div>` : ""}
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
  if (!data) return html`<${Modal} title=${t("common.loading")} onClose=${onClose}><${Spinner} /><//>`;
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
      toast.ok(t("knowledge.saved")); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${`${target.vendor}/${target.name}`} onClose=${onClose} wide=${true}>
    <${Field} label=${t("knowledge.file_name_rename")}>
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    ${isMd ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`<${CodeTextEditor} name=${target.name} value=${text} onChange=${setText} />`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.close")}</button><button class="primary needs-knowledge-edit" onClick=${save}>${t("common.save")}</button></div>
  <//>`;
}

function NewFile({ kind, onClose, onSaved }) {
  const enums = useEnums();
  const [f, setF] = useState({ vendor: "general", name: "", titulo: "", quando_usar: "", topico: "", descricao: "", text: "" });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  async function save() {
    try { await api.post(`/knowledge/${kind}`, f); toast.ok(t("knowledge.created")); onSaved(); }
    catch (e) { handleError(e); }
  }
  const vendors = enums?.vendors_knowledge || ["general"];
  return html`<${Modal} title=${t("knowledge.new_file_title", { kind })} onClose=${onClose} wide=${true}>
    <div class="row">
      <${Field} label="Vendor"><${EnumSelect} value=${f.vendor} options=${vendors} onChange=${(v) => set("vendor", v)} /><//>
      <${Field} label=${t("knowledge.file_name")} hint=${t("components.example", { value: kind === "best-practices" ? "firewall.md" : "vlan-trunk.rsc" })}>
        <input value=${f.name} onInput=${(e) => set("name", e.target.value)} /><//>
    </div>
    ${kind === "best-practices"
      ? html`<${Field} label=${t("knowledge.col_title")}><input value=${f.titulo} onInput=${(e) => set("titulo", e.target.value)} /><//>
             <${Field} label=${t("knowledge.col_when")}><input value=${f.quando_usar} onInput=${(e) => set("quando_usar", e.target.value)} /><//>`
      : html`<${Field} label=${t("knowledge.col_topic")}><input value=${f.topico} onInput=${(e) => set("topico", e.target.value)} /><//>
             <${Field} label=${t("common.description")}><input value=${f.descricao} onInput=${(e) => set("descricao", e.target.value)} /><//>`}
    <${Field} label=${t("knowledge.content")}>${f.name.endsWith(".md") || (kind === "best-practices" && !/\.\w+$/.test(f.name))
      ? html`<${MarkdownEditor} value=${f.text} onChange=${(v) => set("text", v)} />`
      : html`<${CodeTextEditor} name=${f.name} value=${f.text} onChange=${(v) => set("text", v)} />`}<//>
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button><button class="primary" onClick=${save}>${t("common.create")}</button></div>
  <//>`;
}
