// Scripts / Skills (scripts/tools/) — cada pasta é uma skill (SKILL.md + scripts). CRUD, sem execução.
import { html, useState, useEffect, useMemo, api, useResource, Spinner, Badge, toast, handleError, Tabs } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { FilterBar, DataTable, Field, Modal, ConfirmDialog, CodeTextEditor, MarkdownPanel, MarkdownEditor } from "../components.js";

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
  const { q = "", location = "", lang = "", doc = null, tab = "" } = r.params;
  const onScriptsTab = tab === "scripts";
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
  // O SKILL.md da skill é editado direto na página dela (sem modal); só scripts abrem em janela.
  const open = joined && (r.segments.length > 1 || !skillOfSeg) && !(skill && joined === skill.doc) ? joined : null;
  const setDoc = (d) => r.setParams({ doc: d || "" });
  const closeEditor = () => (skill ? r.open(skill.id) : r.close());
  const setTab = (t) => r.openWith([], { tab: t, q: "", location: "", lang: "", sort: "", dir: "" });
  const startCreate = (prefix = "") => { setNewPrefix(prefix); r.open("new"); };

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const loc = skill ? skill.id : location;
    return all.filter((s) => (!loc || s.location === loc) && (!lang || s.lang === lang) && (!needle ||
      [s.name, s.path, s.location, s.lang, s.desc].some((v) => (v || "").toLowerCase().includes(needle))))
      .map((s) => ({ ...s, _key: s.path }));
  }, [all, q, location, lang, skill?.id]);

  const skillRows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return skills.filter((k) => !needle || [k.name, k.id, k.description].some((v) => (v || "").toLowerCase().includes(needle)))
      .map((k) => ({ ...k, _key: k.id }));
  }, [skills, q]);

  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;

  const NAME_SORT = { key: "name", dir: "asc" };
  const scriptCols = [
    { key: "name", label: "Script", hideable: false, sort: true, render: (s) => html`<a href=${"#scripts/" + enc(s.path) + (onScriptsTab ? "?tab=scripts" : "")} onClick=${(e) => e.stopPropagation()}><b>${s.name}</b></a>${s.doc && !s.doc.endsWith("/SKILL.md") ? html` <span title="Ver documentação" class="doc-icon"
        onClick=${(e) => { e.stopPropagation(); setDoc(s.doc); }} style="cursor:pointer">📄</span>` : ""}
      <div class="help mono">${s.path}</div>` },
    ...(skill ? [] : [{ key: "location", label: "Skill", sort: true, render: (s) => skills.some((k) => k.id === s.location)
      ? html`<a href=${"#scripts/" + encodeURIComponent(s.location)} onClick=${(e) => e.stopPropagation()}><${Badge}>${s.location}<//></a>`
      : html`<${Badge}>${s.location}<//>` }]),
    { key: "lang", label: "Tipo", sort: true, render: (s) => `${LANG_ICON[s.lang] || ""} ${s.lang}` },
    { key: "desc", label: "Descrição", sort: true, render: (s) => s.desc || "—" },
  ];
  const table = html`<${DataTable} tableId="scripts" urlSort defaultSort=${NAME_SORT} columns=${scriptCols} rows=${rows}
    onRowClick=${(s) => r.open(s.path.split("/"))}
    actions=${(s) => html`<button class="sm danger needs-scripts-edit" onClick=${() => setConfirm(s.path)}>Excluir</button>`}
    empty=${"Nenhum script" + (skill ? " nesta skill — ela é só documentação" : "") + "."} />`;

  const filters = html`<${FilterBar} q=${q} onChange=${r.setParams} placeholder=${skill ? "Pesquisar scripts da skill…" : "Pesquisar nome, skill, descrição…"}
      count=${rows.length} total=${skill ? all.filter((s) => s.location === skill.id).length : all.length}
      selects=${[...(skill ? [] : [{ key: "location", label: "Skill", value: location, options: locations.filter((l) => l !== "(raiz)") }]),
        { key: "lang", label: "Tipo", value: lang, options: [...new Set(all.map((s) => s.lang).filter(Boolean))].sort() }]} />`;

  const skillsTable = html`<${DataTable} tableId="skills" urlSort defaultSort=${NAME_SORT} rows=${skillRows} empty="Nenhuma skill."
    onRowClick=${(k) => r.openWith(k.id, { q: "", sort: "", dir: "" })}
    columns=${[
      { key: "name", label: "Skill", hideable: false, sort: true, render: (k) => html`<a href=${"#scripts/" + encodeURIComponent(k.id)} onClick=${(e) => e.stopPropagation()}><b>${k.name}</b></a>
        <div class="help mono">${k.id}/</div>` },
      { key: "description", label: "Descrição", sort: true, render: (k) => k.description || "—" },
      { key: "scripts", label: "Scripts", sort: true, render: (k) => html`<${Badge}>${k.scripts}<//>` },
      { key: "doc", label: "Doc", sort: (k) => (k.doc ? 1 : 0), render: (k) => k.doc ? "SKILL.md" : html`<span class="help">⚠ sem SKILL.md</span>` },
    ]} />`;

  const overview = html`<div>
    <div class="page-title"><h1>Scripts / Skills</h1><span class="spacer"></span>
      <button class="primary needs-scripts-edit" onClick=${() => startCreate()}>+ Novo</button></div>
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
      <button class="primary needs-scripts-edit" onClick=${() => startCreate(skill.id + "/")}>+ Novo script</button></div>
    ${skill.description && html`<div style="margin-bottom:4px">${skill.description}</div>`}
    <div class="help mono" style="margin-bottom:8px">scripts/tools/${skill.id}/</div>
    ${skill.doc ? html`<${SkillDoc} key=${skill.doc} path=${skill.doc} version=${res.data} onSaved=${res.reload} />`
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

// SKILL.md editável direto na página da skill (Ler / Editar visual / Texto puro), como na Memória.
function SkillDoc({ path, version, onSaved }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState(null);
  useEffect(() => {
    api.get(`/scripts/file?path=${encodeURIComponent(path)}`).then((d) => { setData(d); setText(d.text); }).catch(handleError);
  }, [path, version]);
  async function save() {
    try {
      const r = await api.put(`/scripts/file`, { path, text }, data.rev);
      setData({ ...data, rev: r?.rev ?? data.rev, text }); toast.ok("Salvo"); onSaved && onSaved();
    } catch (e) { handleError(e); }
  }
  if (text === null) return html`<${Spinner} />`;
  return html`<div>
    <${MarkdownEditor} value=${text} onChange=${setText} />
    <div style="margin-top:12px"><button class="primary needs-scripts-edit" disabled=${text === data.text} onClick=${save}>Salvar SKILL.md</button></div>
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
    ${path.endsWith(".md") ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`
    <${Field} label="Caminho (alterar = renomear/mover dentro de tools/)">
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    <${CodeTextEditor} name=${path} value=${text} onChange=${setText} />`}
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button><button class="primary needs-scripts-edit" onClick=${save}>Salvar</button></div>
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
