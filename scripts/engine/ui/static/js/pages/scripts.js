// Scripts operacionais (scripts/tools/) — tabela única ordenável/pesquisável + CRUD. Sem execução.
import { html, useState, useEffect, useMemo, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { Field, Modal, ConfirmDialog, CodeTextEditor, MarkdownPanel } from "../components.js";

const LANG_ICON = { python: "🐍", shell: "🐚" };

export function ScriptsPage() {
  const res = useResource("/scripts");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState({ key: "name", dir: 1 });
  const [open, setOpen] = useState(null);     // path em edição
  const [doc, setDoc] = useState(null);       // path de doc (.md) em visualização
  const [creating, setCreating] = useState(false);
  const [confirm, setConfirm] = useState(null);

  const all = res.data?.scripts || [];
  const locations = res.data?.locations || [];
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = !needle ? all : all.filter((s) =>
      [s.name, s.path, s.location, s.lang, s.desc].some((v) => (v || "").toLowerCase().includes(needle)));
    const k = sort.key;
    return [...filtered].sort((a, b) => String(a[k] || "").localeCompare(String(b[k] || ""), "pt", { numeric: true }) * sort.dir);
  }, [all, q, sort]);

  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;

  const th = (key, label) => html`<th class="clickable" onClick=${() => setSort((s) => ({ key, dir: s.key === key ? -s.dir : 1 }))}>
    ${label}${sort.key === key ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</th>`;

  return html`<div>
    <div class="page-title"><h1>Scripts</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => setCreating(true)}>+ Novo</button></div>
    <div class="help">Scripts operacionais em <span class="mono">scripts/tools/</span> (Python/Shell) — acesso, diagnóstico, análise. O motor do NetOps não aparece aqui. Execução: Terminal/Claude.</div>

    <div class="toolbar" style="margin:12px 0">
      <input type="search" placeholder="🔎 pesquisar nome, pasta, descrição…" value=${q}
        onInput=${(e) => setQ(e.target.value)} style="width:100%;max-width:420px" />
      <span class="help" style="margin-left:8px">${rows.length}/${all.length}</span>
    </div>

    ${rows.length === 0 ? html`<div class="card"><div class="empty">Nenhum script.</div></div>` : html`
    <table>
      <thead><tr>
        ${th("name", "Script")}
        ${th("location", "Pasta")}
        ${th("lang", "Tipo")}
        ${th("desc", "Descrição")}
        <th></th>
      </tr></thead>
      <tbody>
        ${rows.map((s) => html`<tr key=${s.path} class="clickable" onClick=${() => setOpen(s.path)}>
          <td><b>${s.name}</b>${s.doc ? html` <span title="Ver documentação" class="doc-icon"
              onClick=${(e) => { e.stopPropagation(); setDoc(s.doc); }} style="cursor:pointer">📄</span>` : ""}
            <div class="help mono">${s.path}</div></td>
          <td><${Badge}>${s.location}<//></td>
          <td>${LANG_ICON[s.lang] || ""} ${s.lang}</td>
          <td>${s.desc || "—"}</td>
          <td class="actions" onClick=${(e) => e.stopPropagation()}>
            <button class="sm danger" onClick=${() => setConfirm(s.path)}>Excluir</button></td>
        </tr>`)}
      </tbody>
    </table>`}

    ${open && html`<${Editor} path=${open} onClose=${() => setOpen(null)} onSaved=${() => { setOpen(null); res.reload(); }} />`}
    ${doc && html`<${DocViewer} path=${doc} onClose=${() => setDoc(null)} />`}
    ${creating && html`<${Creator} locations=${locations} onClose=${() => setCreating(false)} onSaved=${() => { setCreating(false); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir script" danger=${true}
      message=${`Remover '${confirm}'? Esta ação não pode ser desfeita.`}
      onClose=${() => setConfirm(null)}
      onConfirm=${async () => {
        try { await api.del(`/scripts/file?path=${encodeURIComponent(confirm)}`); toast.ok("Removido"); setConfirm(null); res.reload(); }
        catch (e) { handleError(e); }
      }} />`}
  </div>`;
}

function Editor({ path, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [name, setName] = useState(path);
  useEffect(() => {
    api.get(`/scripts/file?path=${encodeURIComponent(path)}`).then((d) => { setData(d); setText(d.text); }).catch(handleError);
  }, []);
  if (!data) return html`<${Modal} title="Carregando…" onClose=${onClose}><${Spinner} /><//>`;
  async function save() {
    try {
      let target = path;
      if (name !== path) {                          // renomeia/move primeiro (conteúdo igual => rev não muda)
        await api.post(`/scripts/rename`, { path, to: name });
        target = name;
      }
      await api.put(`/scripts/file`, { path: target, text }, data.rev);
      toast.ok("Salvo"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${path} onClose=${onClose} wide=${true}>
    <${Field} label="Caminho (alterar = renomear/mover dentro de tools/)">
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    <${CodeTextEditor} value=${text} onChange=${setText} />
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button><button class="primary" onClick=${save}>Salvar</button></div>
  <//>`;
}

function DocViewer({ path, onClose }) {
  const [text, setText] = useState(null);
  useEffect(() => { api.get(`/scripts/file?path=${encodeURIComponent(path)}`).then((d) => setText(d.text)).catch(handleError); }, []);
  return html`<${Modal} title=${`📄 ${path}`} onClose=${onClose} wide=${true}>
    ${text === null ? html`<${Spinner} />` : html`<${MarkdownPanel} text=${text} />`}
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button></div>
  <//>`;
}

function Creator({ locations, onClose, onSaved }) {
  const [path, setPath] = useState("");
  const [text, setText] = useState("");
  async function save() {
    try { await api.post(`/scripts`, { path, text }); toast.ok("Criado"); onSaved(); }
    catch (e) { handleError(e); }
  }
  return html`<${Modal} title="Novo script" onClose=${onClose} wide=${true}>
    <${Field} label="Caminho" hint="ex.: access/meu-script.py — relativo a tools/ (só .py/.sh)">
      <input value=${path} placeholder="pasta/arquivo.py" list="script-locations" onInput=${(e) => setPath(e.target.value)} />
      <datalist id="script-locations">${(locations || []).filter((l) => l !== "(raiz)").map((l) => html`<option key=${l} value=${l + "/"} />`)}</datalist>
    <//>
    <${CodeTextEditor} value=${text} onChange=${setText} />
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
  <//>`;
}
