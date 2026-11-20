// Scripts / Skills (scripts/tools/) — cada pasta é uma skill (SKILL.md + scripts). CRUD, sem execução.
import { html, useState, useEffect, useMemo, api, useResource, Spinner, Badge, toast, handleError, Tabs, t } from "../ui.js";
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
  const setTab = (tb) => r.openWith([], { tab: tb, q: "", location: "", lang: "", sort: "", dir: "" });
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
  if (res.error) return html`<div class="card">${t("scripts.error", { message: res.error.message })}</div>`;

  const NAME_SORT = { key: "name", dir: "asc" };
  const scriptCols = [
    { key: "name", label: "Script", hideable: false, sort: true, render: (s) => html`<a href=${"#scripts/" + enc(s.path) + (onScriptsTab ? "?tab=scripts" : "")} onClick=${(e) => e.stopPropagation()}><b>${s.name}</b></a>${s.doc && !s.doc.endsWith("/SKILL.md") ? html` <span title=${t("scripts.see_docs")} class="doc-icon"
        onClick=${(e) => { e.stopPropagation(); setDoc(s.doc); }} style="cursor:pointer">📄</span>` : ""}
      <div class="help mono">${s.path}</div>` },
    ...(skill ? [] : [{ key: "location", label: "Skill", sort: true, render: (s) => skills.some((k) => k.id === s.location)
      ? html`<a href=${"#scripts/" + encodeURIComponent(s.location)} onClick=${(e) => e.stopPropagation()}><${Badge}>${s.location}<//></a>`
      : html`<${Badge}>${s.location}<//>` }]),
    { key: "lang", label: t("scripts.col_type"), sort: true, render: (s) => `${LANG_ICON[s.lang] || ""} ${s.lang}` },
    { key: "desc", label: t("common.description"), sort: true, render: (s) => s.desc || "—" },
  ];
  const table = html`<${DataTable} tableId="scripts" urlSort defaultSort=${NAME_SORT} columns=${scriptCols} rows=${rows}
    onRowClick=${(s) => r.open(s.path.split("/"))}
    actions=${(s) => html`<button class="sm danger needs-scripts-edit" onClick=${() => setConfirm(s.path)}>${t("common.delete")}</button>`}
    empty=${skill ? t("scripts.no_scripts_skill") : t("scripts.no_scripts")} />`;

  const filters = html`<${FilterBar} q=${q} onChange=${r.setParams} placeholder=${skill ? t("scripts.search_skill_scripts") : t("scripts.search_scripts")}
      count=${rows.length} total=${skill ? all.filter((s) => s.location === skill.id).length : all.length}
      selects=${[...(skill ? [] : [{ key: "location", label: "Skill", value: location, options: locations.filter((l) => l !== "(raiz)") }]),
        { key: "lang", label: t("scripts.col_type"), value: lang, options: [...new Set(all.map((s) => s.lang).filter(Boolean))].sort() }]} />`;

  const skillsTable = html`<${DataTable} tableId="skills" urlSort defaultSort=${NAME_SORT} rows=${skillRows} empty=${t("scripts.no_skills")}
    onRowClick=${(k) => r.openWith(k.id, { q: "", sort: "", dir: "" })}
    columns=${[
      { key: "name", label: "Skill", hideable: false, sort: true, render: (k) => html`<a href=${"#scripts/" + encodeURIComponent(k.id)} onClick=${(e) => e.stopPropagation()}><b>${k.name}</b></a>
        <div class="help mono">${k.id}/</div>` },
      { key: "description", label: t("common.description"), sort: true, render: (k) => k.description || "—" },
      { key: "scripts", label: "Scripts", sort: true, render: (k) => html`<${Badge}>${k.scripts}<//>` },
      { key: "doc", label: "Doc", sort: (k) => (k.doc ? 1 : 0), render: (k) => k.doc ? "SKILL.md" : html`<span class="help">${t("scripts.no_skill_md")}</span>` },
    ]} />`;

  const overview = html`<div>
    <div class="page-title"><h1>${t("scripts.title")}</h1><span class="spacer"></span>
      <button class="primary needs-scripts-edit" onClick=${() => startCreate()}>${t("scripts.new_btn")}</button></div>
    <div class="help" style="margin-bottom:8px">${t("scripts.help_1")} <span class="mono">scripts/tools/</span> ${t("scripts.help_2")} <b>skill</b>${t("scripts.help_3")} <span class="mono">SKILL.md</span> ${t("scripts.help_4")}</div>
    <${Tabs} active=${onScriptsTab ? "scripts" : "skills"} onChange=${(tb) => setTab(tb === "scripts" ? "scripts" : "")} tabs=${[
      { key: "skills", label: t("scripts.tab_skills", { n: skills.length }) },
      { key: "scripts", label: t("scripts.tab_scripts", { n: all.length }) },
    ]} />
    ${onScriptsTab
      ? html`${filters}${table}`
      : html`<${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("scripts.search_skills")} count=${skillRows.length} total=${skills.length} />${skillsTable}`}
  </div>`;

  const skillView = skill && html`<div>
    <div class="help"><a href="#scripts">← Skills</a></div>
    <div class="page-title"><h1>${skill.name}</h1><span class="spacer"></span>
      <button class="primary needs-scripts-edit" onClick=${() => startCreate(skill.id + "/")}>${t("scripts.new_script_btn")}</button></div>
    ${skill.description && html`<div style="margin-bottom:4px">${skill.description}</div>`}
    <div class="help mono" style="margin-bottom:8px">scripts/tools/${skill.id}/</div>
    ${skill.doc ? html`<${SkillDoc} key=${skill.doc} path=${skill.doc} version=${res.data} onSaved=${res.reload} />`
      : html`<div class="card">${t("scripts.no_skill_md_1")} <span class="mono">SKILL.md</span> ${t("scripts.no_skill_md_2")}
          <div style="margin-top:8px"><button class="primary" onClick=${async () => {
            try { await api.post("/scripts", { path: `${skill.id}/SKILL.md`, text: SKILL_TMPL(skill.id) }); toast.ok(t("scripts.skill_md_created")); res.reload(); r.open([skill.id, "SKILL.md"]); }
            catch (e) { handleError(e); } }}>${t("scripts.create_skill_md")}</button></div></div>`}
    <h3 style="margin-top:16px">${t("scripts.skill_scripts")}</h3>
    ${filters}
    ${table}
  </div>`;

  const missing = joined && !creating && !skill && !editable(joined);

  return html`<div>
    ${missing ? html`<div class="card">${t("scripts.not_found", { path: joined })} <a href="#scripts">${t("scripts.back")}</a></div>` : ""}
    ${skill ? skillView : overview}

    ${open && editable(open) && html`<${Editor} key=${open} path=${open} onClose=${closeEditor} onSaved=${() => { closeEditor(); res.reload(); }} />`}
    ${doc && html`<${DocViewer} key=${doc} path=${doc} onClose=${() => setDoc(null)} />`}
    ${creating && html`<${Creator} locations=${locations} initial=${newPrefix} onClose=${() => r.close()} onSaved=${(p) => { res.reload(); r.open(p.split("/")[0]); }} />`}
    ${confirm && html`<${ConfirmDialog} title=${t("scripts.delete_title")} danger=${true}
      message=${t("scripts.delete_confirm", { path: confirm })}
      onClose=${() => setConfirm(null)}
      onConfirm=${async () => {
        try { await api.del(`/scripts/file?path=${encodeURIComponent(confirm)}`); toast.ok(t("scripts.removed")); setConfirm(null); res.reload(); }
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
      setData({ ...data, rev: r?.rev ?? data.rev, text }); toast.ok(t("scripts.saved")); onSaved && onSaved();
    } catch (e) { handleError(e); }
  }
  if (text === null) return html`<${Spinner} />`;
  return html`<div>
    <${MarkdownEditor} value=${text} onChange=${setText} />
    <div style="margin-top:12px"><button class="primary needs-scripts-edit" disabled=${text === data.text} onClick=${save}>${t("scripts.save_skill_md")}</button></div>
  </div>`;
}

function Editor({ path, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [name, setName] = useState(path);
  useEffect(() => {
    api.get(`/scripts/file?path=${encodeURIComponent(path)}`).then((d) => { setData(d); setText(d.text); }).catch(handleError);
  }, []);
  if (!data) return html`<${Modal} title=${t("common.loading")} onClose=${onClose}><${Spinner} /><//>`;
  async function save() {
    try {
      let target = path;
      if (name !== path) {                          // renomeia/move primeiro (conteúdo igual => rev não muda)
        await api.post(`/scripts/rename`, { path, to: name });
        target = name;
      }
      await api.put(`/scripts/file`, { path: target, text }, data.rev);
      toast.ok(t("scripts.saved")); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${path} onClose=${onClose} wide=${true}>
    ${path.endsWith(".md") ? html`<${MarkdownEditor} value=${text} onChange=${setText} />` : html`
    <${Field} label=${t("scripts.path_rename")}>
      <input value=${name} onInput=${(e) => setName(e.target.value)} /><//>
    <${CodeTextEditor} name=${path} value=${text} onChange=${setText} />`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.close")}</button><button class="primary needs-scripts-edit" onClick=${save}>${t("common.save")}</button></div>
  <//>`;
}

function DocViewer({ path, onClose }) {
  const [text, setText] = useState(null);
  useEffect(() => { api.get(`/scripts/file?path=${encodeURIComponent(path)}`).then((d) => setText(d.text)).catch(handleError); }, []);
  return html`<${Modal} title=${`📄 ${path}`} onClose=${onClose} wide=${true}>
    ${text === null ? html`<${Spinner} />` : html`<${MarkdownPanel} text=${text} />`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.close")}</button></div>
  <//>`;
}

function Creator({ locations, initial = "", onClose, onSaved }) {
  const [path, setPath] = useState(initial);
  const [text, setText] = useState("");
  async function save() {
    try { await api.post(`/scripts`, { path, text }); toast.ok(t("scripts.created")); onSaved(path); }
    catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${t("scripts.new_script")} onClose=${onClose} wide=${true}>
    <${Field} label=${t("scripts.path")} hint=${t("scripts.path_hint")}>
      <input value=${path} placeholder=${t("scripts.path_placeholder")} list="script-locations" onInput=${(e) => setPath(e.target.value)} />
      <datalist id="script-locations">${(locations || []).filter((l) => l !== "(raiz)").map((l) => html`<option key=${l} value=${l + "/"} />`)}</datalist>
    <//>
    <${CodeTextEditor} value=${text} onChange=${setText} />
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button><button class="primary" onClick=${save}>${t("common.create")}</button></div>
  <//>`;
}
