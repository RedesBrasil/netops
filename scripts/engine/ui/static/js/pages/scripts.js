// Scripts operacionais (scripts/tools/) — tabela única ordenável/pesquisável + CRUD. Sem execução.
import { html, useState, useEffect, useMemo, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { FilterBar, Field, Modal, ConfirmDialog, CodeTextEditor, MarkdownPanel } from "../components.js";

const LANG_ICON = { python: "🐍", shell: "🐚" };

// URL: #scripts[/<pasta>/<arquivo>|/new][?q=&location=&lang=&sort=&dir=&doc=<doc.md>]  (core/rules/urls-navegacao.md)
export function ScriptsPage() {
  const res = useResource("/scripts");
  const r = useMenuRoute("scripts");
  const { q = "", location = "", lang = "", sort: sortKey = "name", dir: sortDir = "asc", doc = null } = r.params;
  const sort = { key: sortKey, dir: sortDir === "desc" ? -1 : 1 };
  const creating = r.segments[0] === "new";
  const open = r.segments.length && !creating ? r.segments.join("/") : null;
  const setOpen = (p) => (p ? r.open(p.split("/")) : r.close());
  const setDoc = (d) => r.setParams({ doc: d || "" });
  const setCreating = (v) => (v ? r.open("new") : r.close());
  const [confirm, setConfirm] = useState(null);

  const all = res.data?.scripts || [];
  const locations = res.data?.locations || [];
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = all.filter((s) => (!location || s.location === location) && (!lang || s.lang === lang) && (!needle ||
      [s.name, s.path, s.location, s.lang, s.desc].some((v) => (v || "").toLowerCase().includes(needle))));
    const k = sort.key;
    return [...filtered].sort((a, b) => String(a[k] || "").localeCompare(String(b[k] || ""), "pt", { numeric: true }) * sort.dir);
  }, [all, q, location, lang, sortKey, sortDir]);

  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;

  const th = (key, label) => html`<th class="clickable" onClick=${() => r.setParams(sort.key === key ? { sort: key, dir: sort.dir > 0 ? "desc" : "" } : { sort: key, dir: "" })}>
    ${label}${sort.key === key ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</th>`;

  return html`<div>
    <div class="page-title"><h1>Scripts</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => setCreating(true)}>+ Novo</button></div>
    <div class="help">Scripts operacionais em <span class="mono">scripts/tools/</span> (Python/Shell) — acesso, diagnóstico, análise. O motor do NetOps não aparece aqui. Execução: Terminal/Claude.</div>

    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Pesquisar nome, pasta, descrição…"
      selects=${[{ key: "location", label: "Pasta", value: location, options: locations.filter((l) => l !== "(raiz)") }, { key: "lang", label: "Tipo", value: lang, options: [...new Set(all.map((s) => s.lang).filter(Boolean))].sort() }]} />
    <div class="help" style="margin-bottom:8px">${rows.length}/${all.length}</div>
    ${open && res.data && !all.some((s) => s.path === open) && html`<div class="card">Script '${open}' não encontrado. <a href="#scripts">Voltar aos scripts</a></div>`}

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
          <td><a href=${"#scripts/" + s.path.split("/").map(encodeURIComponent).join("/")} onClick=${(e) => e.stopPropagation()}><b>${s.name}</b></a>${s.doc ? html` <span title="Ver documentação" class="doc-icon"
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

    ${open && all.some((s) => s.path === open) && html`<${Editor} key=${open} path=${open} onClose=${() => setOpen(null)} onSaved=${() => { setOpen(null); res.reload(); }} />`}
    ${doc && html`<${DocViewer} key=${doc} path=${doc} onClose=${() => setDoc(null)} />`}
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
