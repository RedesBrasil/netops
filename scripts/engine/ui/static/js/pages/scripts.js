// Scripts / Skills (scripts/tools/) — cada pasta é uma skill (SKILL.md + scripts). CRUD, sem execução.
import { html, useState, useEffect, useMemo, api, useResource, Spinner, Badge, toast, handleError, Tabs } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { FilterBar, Field, Modal, ConfirmDialog, CodeTextEditor, MarkdownPanel, MarkdownEditor } from "../components.js";

const LANG_ICON = { python: "🐍", shell: "🐚" };

const SKILL_TMPL = (id) => `---\nid: ${id}\nname: ${id}\ntype: script\nruntime: python\ndescription: Uma linha — o que esta skill faz e quando usar.\nenv: []\n---\n\n## O que faz\n\n## Quando usar\n\n## Scripts\n\n| Script | Função |\n|--------|--------|\n\n## Uso\n\n\`\`\`bash\npython scripts/tools/${id}/<script>.py --help\n\`\`\`\n`;

const enc = (p) => p.split("/").map(encodeURIComponent).join("/");

// Cada pasta de scripts/tools/ é uma SKILL (padrão Agent Skills): SKILL.md + scripts relacionados.
// URL: #scripts                      → aba Skills (tabela de skills)
//      #scripts?tab=scripts          → aba Scripts (tabela de todos os scripts)
//      #scripts/<skill>              → página da skill (SKILL.md formatado + scripts dela)
//      #scripts/<skill>/<arquivo>    → editor do script (ou do SKILL.md) sobre a skill / a aba Scripts
//      #scripts/new                  → novo script
//      ?q=&location=&lang=&sort=&dir=&doc=<doc.md>   (core/rules/urls-navegacao.md)
export function ScriptsPage() {
  const res = useResource("/scripts");
  const r = useMenuRoute("scripts");
  const { q = "", location = "", lang = "", sort: sortKey = "name", dir: sortDir = "asc", doc = null, tab = "" } = r.params;
  const onScriptsTab = tab === "scripts";
  const sort = { key: sortKey, dir: sortDir === "desc" ? -1 : 1 };
  const creating = r.segments[0] === "new";
  const [confirm, setConfirm] = useState(null);
  const [newPrefix, setNewPrefix] = useState("");

  const all = res.data?.scripts || [];
  const skills = res.data?.skills || [];
  const locations = res.data?.locations || [];
  const joined = r.segments.length && !creating ? r.segments.join("/") : null;
  const skillOfSeg = !creating && r.segments[0] ? skills.find((k) => k.id === r.segments[0]) || null : null;
  // Script aberto a partir da aba Scripts fica sobre a aba Scripts; senão, sobre a página da skill
  const skill = skillOfSeg && !(onScriptsTab && r.segments.length > 1) ? skillOfSeg : null;
  // Arquivo aberto: script (.py/.sh) ou a doc da skill (SKILL.md)
  const editable = (p) => all.some((s) => s.path === p) || skills.some((k) => k.doc === p);
  const open = joined && (r.segments.length > 1 || !skillOfSeg) ? joined : null;
  const setDoc = (d) => r.setParams({ doc: d || "" });
  const closeEditor = () => (skill ? r.open(skill.id) : r.close());
  const setTab = (t) => r.openWith([], { tab: t, q: "", location: "", lang: "", sort: "", dir: "" });
  const startCreate = (prefix = "") => { setNewPrefix(prefix); r.open("new"); };

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const loc = skill ? skill.id : location;
    const filtered = all.filter((s) => (!loc || s.location === loc) && (!lang || s.lang === lang) && (!needle ||
      [s.name, s.path, s.location, s.lang, s.desc].some((v) => (v || "").toLowerCase().includes(needle))));
    const k = sort.key;
    return [...filtered].sort((a, b) => String(a[k] || "").localeCompare(String(b[k] || ""), "pt", { numeric: true }) * sort.dir);
  }, [all, q, location, lang, sortKey, sortDir, skill?.id]);

  const skillRows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = skills.filter((k) => !needle || [k.name, k.id, k.description].some((v) => (v || "").toLowerCase().includes(needle)));
    const k = ["name", "id", "scripts", "description"].includes(sortKey) ? sortKey : "name";
    return [...filtered].sort((a, b) => String(a[k] ?? "").localeCompare(String(b[k] ?? ""), "pt", { numeric: true }) * sort.dir);
  }, [skills, q, sortKey, sortDir]);

  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;

  const th = (key, label) => html`<th class="clickable" onClick=${() => r.setParams(sort.key === key ? { sort: key, dir: sort.dir > 0 ? "desc" : "" } : { sort: key, dir: "" })}>
    ${label}${sort.key === key ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</th>`;

  const table = html`${rows.length === 0 ? html`<div class="card"><div class="empty">Nenhum script${skill ? " nesta skill — ela é só documentação" : ""}.</div></div>` : html`
    <table>
      <thead><tr>
        ${th("name", "Script")}
        ${!skill && th("location", "Skill")}
        ${th("lang", "Tipo")}
        ${th("desc", "Descrição")}
        <th></th>
      </tr></thead>
      <tbody>
        ${rows.map((s) => html`<tr key=${s.path} class="clickable" onClick=${() => r.open(s.path.split("/"))}>
          <td><a href=${"#scripts/" + enc(s.path) + (onScriptsTab ? "?tab=scripts" : "")} onClick=${(e) => e.stopPropagation()}><b>${s.name}</b></a>${s.doc && !s.doc.endsWith("/SKILL.md") ? html` <span title="Ver documentação" class="doc-icon"
              onClick=${(e) => { e.stopPropagation(); setDoc(s.doc); }} style="cursor:pointer">📄</span>` : ""}
            <div class="help mono">${s.path}</div></td>
          ${!skill && html`<td>${skills.some((k) => k.id === s.location)
            ? html`<a href=${"#scripts/" + encodeURIComponent(s.location)} onClick=${(e) => e.stopPropagation()}><${Badge}>${s.location}<//></a>`
            : html`<${Badge}>${s.location}<//>`}</td>`}
          <td>${LANG_ICON[s.lang] || ""} ${s.lang}</td>
          <td>${s.desc || "—"}</td>
          <td class="actions" onClick=${(e) => e.stopPropagation()}>
            <button class="sm danger" onClick=${() => setConfirm(s.path)}>Excluir</button></td>
        </tr>`)}
      </tbody>
    </table>`}`;

  const filters = html`<${FilterBar} q=${q} onChange=${r.setParams} placeholder=${skill ? "Pesquisar scripts da skill…" : "Pesquisar nome, skill, descrição…"}
      count=${rows.length} total=${skill ? all.filter((s) => s.location === skill.id).length : all.length}
      selects=${[...(skill ? [] : [{ key: "location", label: "Skill", value: location, options: locations.filter((l) => l !== "(raiz)") }]),
        { key: "lang", label: "Tipo", value: lang, options: [...new Set(all.map((s) => s.lang).filter(Boolean))].sort() }]} />`;

  const skillsTable = skillRows.length === 0 ? html`<div class="card"><div class="empty">Nenhuma skill.</div></div>` : html`
    <table>
      <thead><tr>${th("name", "Skill")}${th("description", "Descrição")}${th("scripts", "Scripts")}<th>Doc</th></tr></thead>
      <tbody>
        ${skillRows.map((k) => html`<tr key=${k.id} class="clickable" onClick=${() => r.openWith(k.id, { q: "", sort: "", dir: "" })}>
          <td><a href=${"#scripts/" + encodeURIComponent(k.id)} onClick=${(e) => e.stopPropagation()}><b>${k.name}</b></a>
            <div class="help mono">${k.id}/</div></td>
          <td>${k.description || "—"}</td>
          <td><${Badge}>${k.scripts}<//></td>
          <td>${k.doc ? "SKILL.md" : html`<span class="help">⚠ sem SKILL.md</span>`}</td>
        </tr>`)}
      </tbody>
    </table>`;

  const overview = html`<div>
    <div class="page-title"><h1>Scripts / Skills</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => startCreate()}>+ Novo</button></div>
    <div class="help" style="margin-bottom:8px">Cada pasta de <span class="mono">scripts/tools/</span> é uma <b>skill</b>: o <span class="mono">SKILL.md</span> diz o que ela faz e quando usar,
      e os scripts (Python/Shell) são as ferramentas dela. O motor do NetOps não aparece aqui. Execução: Terminal/Claude.</div>
    <${Tabs} active=${onScriptsTab ? "scripts" : "skills"} onChange=${(t) => setTab(t === "scripts" ? "scripts" : "")} tabs=${[
      { key: "skills", label: `Skills (${skills.length})` },
      { key: "scripts", label: `Scripts (${all.length})` },
    ]} />
    ${onScriptsTab
      ? html`${filters}${table}`
      : html`<${FilterBar} q=${q} onChange=${r.setParams} placeholder="Pesquisar skill, pasta, descrição…" count=${skillRows.length} total=${skills.length} />${skillsTable}`}
  </div>`;

  const skillView = skill && html`<div>
    <div class="help"><a href="#scripts">← Skills</a></div>
    <div class="page-title"><h1>${skill.name}</h1><span class="spacer"></span>
      ${skill.doc && html`<button onClick=${() => r.open(skill.doc.split("/"))}>Editar SKILL.md</button>`}
      <button class="primary" onClick=${() => startCreate(skill.id + "/")}>+ Novo script</button></div>
    ${skill.description && html`<div style="margin-bottom:4px">${skill.description}</div>`}
    <div class="help mono" style="margin-bottom:8px">scripts/tools/${skill.id}/</div>
    ${skill.doc ? html`<${SkillDoc} key=${skill.doc} path=${skill.doc} version=${res.data} />`
      : html`<div class="card">Esta skill ainda não tem <span class="mono">SKILL.md</span> — sem ele a IA não sabe quando nem como usar estes scripts.
          <div style="margin-top:8px"><button class="primary" onClick=${async () => {
            try { await api.post("/scripts", { path: `${skill.id}/SKILL.md`, text: SKILL_TMPL(skill.id) }); toast.ok("SKILL.md criado"); res.reload(); r.open([skill.id, "SKILL.md"]); }
            catch (e) { handleError(e); } }}>Criar SKILL.md</button></div></div>`}
    <h3 style="margin-top:16px">Scripts desta skill</h3>
    ${filters}
    ${table}
  </div>`;

  const missing = joined && !creating && !skill && !editable(joined);

  return html`<div>
    ${missing ? html`<div class="card">'${joined}' não encontrado. <a href="#scripts">Voltar aos scripts / skills</a></div>` : ""}
    ${skill ? skillView : overview}

    ${open && editable(open) && html`<${Editor} key=${open} path=${open} onClose=${closeEditor} onSaved=${() => { closeEditor(); res.reload(); }} />`}
    ${doc && html`<${DocViewer} key=${doc} path=${doc} onClose=${() => setDoc(null)} />`}
    ${creating && html`<${Creator} locations=${locations} initial=${newPrefix} onClose=${() => r.close()} onSaved=${(p) => { res.reload(); r.open(p.split("/")[0]); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir script" danger=${true}
      message=${`Remover '${confirm}'? Esta ação não pode ser desfeita.`}
      onClose=${() => setConfirm(null)}
      onConfirm=${async () => {
        try { await api.del(`/scripts/file?path=${encodeURIComponent(confirm)}`); toast.ok("Removido"); setConfirm(null); res.reload(); }
        catch (e) { handleError(e); }
      }} />`}
  </div>`;
}

function SkillDoc({ path, version }) {
  const [text, setText] = useState(null);
  useEffect(() => { api.get(`/scripts/file?path=${encodeURIComponent(path)}`).then((d) => setText(d.text)).catch(handleError); }, [path, version]);
  // frontmatter (id/name/description) já aparece no cabeçalho — renderizado viraria um título gigante
  const body = text === null ? null : text.replace(/^---\n[\s\S]*?\n---\n?/, "").trimStart();
  return text === null ? html`<${Spinner} />` : html`<div class="card md-readbox"><${MarkdownPanel} text=${body} /></div>`;
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
    ${path.endsWith(".md") ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`
    <${Field} label="Caminho (alterar = renomear/mover dentro de tools/)">
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    <${CodeTextEditor} name=${path} value=${text} onChange=${setText} />`}
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

function Creator({ locations, initial = "", onClose, onSaved }) {
  const [path, setPath] = useState(initial);
  const [text, setText] = useState("");
  async function save() {
    try { await api.post(`/scripts`, { path, text }); toast.ok("Criado"); onSaved(path); }
    catch (e) { handleError(e); }
  }
  return html`<${Modal} title="Novo script" onClose=${onClose} wide=${true}>
    <${Field} label="Caminho" hint="<skill>/<arquivo> — ex.: access/meu-script.py (só .py/.sh). Pasta nova = skill nova.">
      <input value=${path} placeholder="pasta/arquivo.py" list="script-locations" onInput=${(e) => setPath(e.target.value)} />
      <datalist id="script-locations">${(locations || []).filter((l) => l !== "(raiz)").map((l) => html`<option key=${l} value=${l + "/"} />`)}</datalist>
    <//>
    <${CodeTextEditor} value=${text} onChange=${setText} />
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
  <//>`;
}
