// Memória: índice memory/MEMORY.md, AGENTS.md (instruções do projeto, lido primeiro por toda IA)
// e as notas memory/*.md que o índice aponta.
// URL: #memory[/<arquivo>][?q=]  — #memory = MEMORY.md  (core/rules/urls-navegacao.md)
import { html, useState, useEffect, api, useResource, Spinner, toast, handleError, Tabs, t } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { MarkdownEditor, FilterBar, DataTable } from "../components.js";

const HELP = { "MEMORY.md": "memory.help_memory", "AGENTS.md": "memory.help_agents" };
const helpFor = (name) => (HELP[name] ? html`<b>${name}</b> ${t(HELP[name])}` : null);

export function MemoryPage() {
  const r = useMenuRoute("memory");
  const files = useResource("/memory/files");
  const q = r.params.q || "";
  const current = r.segments[0] || "MEMORY.md";
  const tab = current === "MEMORY.md" || current === "AGENTS.md" ? current : "notes";
  const notes = (files.data?.files || []).filter((f) => f.kind === "note");
  const shown = notes.filter((n) => matchText(q, n.name, n.title));
  const known = !files.data || (files.data.files || []).some((f) => f.name === current && f.exists);

  // Abas: MEMORY.md = #memory, AGENTS.md = #memory/AGENTS.md, Notas = #memory/notas (lista)
  const listing = current === "notas";
  const onTab = (k) => (k === "MEMORY.md" ? r.close() : r.open(k === "notes" ? "notas" : k));

  return html`<div>
    <div class="page-title"><h1>${t("memory.title")}</h1></div>
    <${Tabs} active=${listing ? "notes" : tab} onChange=${onTab} tabs=${[
      { key: "MEMORY.md", label: "MEMORY.md" },
      { key: "AGENTS.md", label: "AGENTS.md" },
      { key: "notes", label: `${t("memory.tab_notes")}${files.data ? ` (${notes.length})` : ""}` },
    ]} />
    ${listing ? html`<div>
        <div class="help" style="margin-bottom:8px">${t("memory.notes_help_1")} <span class="mono">memory/</span> ${t("memory.notes_help_2")}</div>
        <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("memory.search_note")} count=${shown.length} total=${notes.length} />
        ${files.loading ? html`<${Spinner} />` : shown.length === 0 ? html`<div class="card"><div class="empty">${t("memory.no_notes")}</div></div>` : html`
        <${DataTable} tableId="memory-notes" urlSort rows=${shown.map((n) => ({ ...n, _key: n.name }))} onRowClick=${(n) => r.open(n.name)}
          columns=${[
            { key: "name", label: t("memory.col_note"), hideable: false, sort: true, render: (n) => html`<a class="mono" href=${"#memory/" + encodeURIComponent(n.name)} onClick=${(e) => e.stopPropagation()}>${n.name}</a>` },
            { key: "title", label: t("memory.col_title"), sort: true, render: (n) => n.title || "—" },
          ]} />`}
      </div>`
    : !known ? html`<div class="card">${t("memory.not_found", { name: current })} <a href="#memory">${t("memory.back")}</a></div>`
    : html`<div>
        <div class="help" style="margin-bottom:8px">
          ${helpFor(current) || html`${t("memory.note")} <span class="mono">memory/${current}</span> · <a href="#memory/notas">${t("memory.all_notes")}</a>`}
        </div>
        <${FileEditor} key=${current} name=${current} />
      </div>`}
  </div>`;
}

function FileEditor({ name }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    api.get(`/memory/file?name=${encodeURIComponent(name)}`)
      .then((d) => { setData(d); setText(d.text); }).catch((e) => setErr(e));
  }, [name]);
  async function save() {
    try {
      const r = await api.put("/memory/file", { name, text }, data.rev);
      setData({ ...data, rev: r.rev, text }); toast.ok(t("memory.saved"));
    } catch (e) { handleError(e); }
  }
  if (err) return html`<div class="card">${t("memory.load_error", { name, message: err.message })}</div>`;
  if (text === null) return html`<${Spinner} />`;
  return html`<div>
    <${MarkdownEditor} value=${text} onChange=${setText} />
    <div style="margin-top:12px"><button class="primary needs-knowledge-edit" disabled=${text === data.text} onClick=${save}>${t("common.save")}</button></div>
  </div>`;
}
