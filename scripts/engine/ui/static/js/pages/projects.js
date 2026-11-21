// Projetos: nome + pasta do servidor. Cada projeto tem as próprias sessões do Claude Code (as conversas
// daquela pasta). URLs: #projects[?arquivados=1], #projects/new, #projects/<id>[?q=], #projects/<id>/new,
// #projects/<id>/<uuid>, #projects/<id>/files[?path=&open=&q=&sort=&hidden=] (arquivos da pasta do projeto).
// O chat em si é a ClaudeCodePage; quem liga o agente à pasta é o ClaudeProvider (?project= no WebSocket).
import { html, useState, useEffect, useRef, toast, api, t, can, fmtDateTime, useMe } from "../ui.js";
import { Modal, Field, ConfirmDialog, DataTable, FilterBar } from "../components.js";
import { useMenuRoute, navigate } from "../route.js";
import { ClaudeCodePage, SessionsList } from "./claude.js";
import { FileBrowser } from "../file-browser.js";
import { validProjectId, claudeSessionHash } from "../claude-sessions.js";

// 404 sem `error` = rota que o servidor não conhece (as nossas respostas sempre trazem `error`): o console
// está rodando uma versão anterior ao menu Projetos e precisa ser reiniciado.
const errText = (e, fallback) => (e && e.status === 404 && e.payload && !e.payload.error)
  ? t("projects.server_outdated")
  : (e && e.payload && (e.payload.detail || e.payload.error)) || (e && e.message) || fallback;
const changed = () => window.dispatchEvent(new Event("netops:projects"));   // a sidebar recarrega a lista

// Lista de projetos para a sidebar (recarrega quando algo muda ou a janela volta ao foco).
let accountWarning = false;   // conta do agente só nos settings do NetOps (ver claude_models.account_only_in_netops)
let defaultBase = "";         // base de "criar pasta nova" vinda do servidor (~/projects da conta do console)
export function useProjects(enabled) {
  const [list, setList] = useState([]);
  useEffect(() => {
    if (!enabled) { setList([]); return; }
    let alive = true;
    const load = () => api.get("/projects").then((d) => {
      accountWarning = !!d.account_warning;
      if (d.default_base) defaultBase = d.default_base;
      if (alive) setList(d.projects || []);
    }).catch(() => {});
    load();
    addEventListener("netops:projects", load); addEventListener("focus", load);
    return () => { alive = false; removeEventListener("netops:projects", load); removeEventListener("focus", load); };
  }, [enabled]);
  return list;
}

// Seletor de pasta do servidor: só lista subpastas; dá para navegar ou digitar o caminho.
// `requireAllowed`: só deixa usar pasta que pode ser projeto (o servidor devolve allowed/reason).
function FolderPicker({ start, onPick, onClose, requireAllowed = true, title = t("projects.pick_title") }) {
  const [data, setData] = useState(null);
  const [typed, setTyped] = useState(start || "");
  const [hidden, setHidden] = useState(false);
  const [err, setErr] = useState("");
  async function go(path, showHidden = hidden) {
    setErr("");
    try {
      const d = await api.get(`/projects/browse?path=${encodeURIComponent(path || "")}${showHidden ? "&hidden=1" : ""}`);
      setData(d); setTyped(d.path);
    } catch (e) { setErr(errText(e, t("projects.open_folder_failed"))); }
  }
  useEffect(() => { go(start || ""); }, []);
  return html`<${Modal} title=${title} onClose=${onClose} wide=${true}>
    <div class="pj-pick-path">
      <input class="mono" value=${typed} aria-label=${t("projects.folder_path")} placeholder=${t("projects.folder_placeholder")}
        onInput=${(e) => setTyped(e.target.value)}
        onKeyDown=${(e) => { if (e.key === "Enter") go(typed); }} />
      <button type="button" onClick=${() => go(typed)}>${t("projects.go")}</button>
    </div>
    <label class="help pj-hidden"><input type="checkbox" checked=${hidden}
      onChange=${(e) => { setHidden(e.target.checked); go(typed, e.target.checked); }} /> ${t("projects.show_hidden")}</label>
    ${err && html`<div class="err">${err}</div>`}
    ${data && html`<div class="pj-folders">
      ${data.parent != null && html`<button class="pj-folder" type="button" onClick=${() => go(data.parent)}>⬆ ..</button>`}
      ${data.dirs.length === 0 && html`<div class="help">${t("projects.no_subfolders")}</div>`}
      ${data.dirs.map((d) => html`<button key=${d.path} type="button" class="pj-folder" onClick=${() => go(d.path)}>📁 ${d.name}</button>`)}
    </div>`}
    ${data && requireAllowed && !data.allowed && html`<div class="help pj-deny">⛔ ${data.reason}</div>`}
    <div class="modal-actions">
      <button type="button" onClick=${onClose}>${t("common.cancel")}</button>
      <button type="button" class="primary" disabled=${!data || (requireAllowed && !data.allowed)}
        onClick=${() => { onPick(data.path); onClose(); }}>${t("projects.use_folder")}</button>
    </div>
  <//>`;
}

// O que a pasta traz para o agente. `exec` = config que executa algo ao abrir (hooks, MCP, env/proxy):
// só entra com a pasta marcada como confiável (modelo "Workspace Trust" do VS Code).
function ConfigList({ config }) {
  const ex = (config && config.exec) || [], info = (config && config.info) || [];
  if (!ex.length && !info.length) return html`<div class="help">${t("projects.no_config")}</div>`;
  return html`<div class="help pj-config">
    ${ex.length > 0 && html`<div>${t("projects.runs_on_open")} ${ex.map((n) => html`<code key=${n}>${n}</code> `)}</div>`}
    ${info.length > 0 && html`<div>${t("projects.instructions")} ${info.map((n) => html`<code key=${n}>${n}</code> `)}</div>`}
  </div>`;
}

// Base padrão: o servidor manda em GET /projects (default_base). Abrir #projects/new direto (sem a lista
// carregada) busca de novo; enquanto isso o campo fica vazio e o botão Criar desabilitado.
function useDefaultBase() {
  const [base, setBase] = useState(defaultBase);
  useEffect(() => {
    if (base) return;
    api.get("/projects").then((d) => { if (d.default_base) { defaultBase = d.default_base; setBase(d.default_base); } }).catch(() => {});
  }, []);
  return base;
}

function NewProject() {
  // projects.create without projects.manage: only a new folder right inside the default base (no folder picker).
  const restricted = !can("projects.manage");
  const [name, setName] = useState("");
  const [mode, setMode] = useState("new");          // "new" = criar pasta nova (como o VS Code) | "existing"
  const [path, setPath] = useState("");
  const base = useDefaultBase();
  const [parent, setParent] = useState(defaultBase);
  useEffect(() => { if (base && !parent) setParent(base); }, [base]);
  const [folder, setFolder] = useState("");
  const [info, setInfo] = useState(null);           // browse da pasta existente: allowed/reason/config
  const [trust, setTrust] = useState(false);
  const [pick, setPick] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // Sugere o nome da pasta a partir do nome do projeto (o usuário pode trocar).
  const [folderTouched, setFolderTouched] = useState(false);
  useEffect(() => {
    if (!folderTouched) setFolder(name.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
      .replace(/[^a-z0-9._-]+/g, "-").replace(/^[-.]+|-+$/g, "").slice(0, 64));
  }, [name]);
  // Pasta existente: pergunta ao servidor se pode e o que ela traz (para pedir confiança).
  useEffect(() => {
    setInfo(null); setTrust(false);
    if (mode !== "existing" || !path.trim().startsWith("/")) return;
    const tm = setTimeout(() => api.get(`/projects/browse?path=${encodeURIComponent(path.trim())}`)
      .then(setInfo).catch(() => setInfo(null)), 300);
    return () => clearTimeout(tm);
  }, [path, mode]);
  const needsTrust = mode === "existing" && info && info.config && info.config.exec.length > 0;
  const ready = name.trim() && (mode === "new" ? folder.trim() && parent.trim() : path.trim() && (!info || info.allowed));
  async function save(e) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const body = mode === "new" ? { name, path: restricted ? base : parent, new_folder: folder } : { name, path, trust };
      const p = await api.post("/projects", body);
      changed(); toast.ok(p.trusted ? t("projects.created") : t("projects.created_restricted"));
      navigate("#projects/" + p.id);
    } catch (x) { setErr(errText(x, t("projects.create_failed"))); }
    finally { setBusy(false); }
  }
  // O seletor fica FORA do <form>: dentro dele, Enter e os botões do modal (type=submit por padrão)
  // submeteriam o formulário e criariam o projeto sem o usuário pedir.
  return html`<div>
  <form class="card pj-form" onSubmit=${save}>
    <h2>${t("projects.new_title")}</h2>
    <p class="help">${t("projects.new_help")}</p>
    <${Field} label=${t("common.name")} htmlFor="pj-name">
      <input id="pj-name" value=${name} maxlength="80" autoFocus placeholder=${t("projects.name_placeholder")} onInput=${(e) => setName(e.target.value)} />
    <//>
    <p class="help">🔒 ${t("projects.new_private_help")}</p>
    <div class="pj-mode" role="radiogroup" aria-label=${t("projects.project_folder")} hidden=${restricted}>
      <label><input type="radio" name="pj-mode" checked=${mode === "new"} onChange=${() => setMode("new")} /> ${t("projects.mode_new")}</label>
      <label><input type="radio" name="pj-mode" checked=${mode === "existing"} onChange=${() => setMode("existing")} /> ${t("projects.mode_existing")}</label>
    </div>
    ${mode === "new" ? html`
      <${Field} label=${t("projects.create_inside")} htmlFor="pj-parent" hint=${t("projects.create_inside_hint", { path: base || "~/projects" })}>
        <div class="pj-pick-path">
          <input id="pj-parent" class="mono" value=${restricted ? base : parent} readOnly=${restricted}
            onInput=${(e) => setParent(e.target.value)} />
          ${!restricted && html`<button type="button" onClick=${() => setPick(true)}>${t("projects.choose")}</button>`}
        </div>
      <//>
      <${Field} label=${t("projects.folder_name")} htmlFor="pj-folder" hint=${t("projects.folder_name_hint")}>
        <input id="pj-folder" class="mono" value=${folder} maxlength="64"
          onInput=${(e) => { setFolderTouched(true); setFolder(e.target.value); }} />
      <//>
      <div class="help mono">📁 ${(parent || "").replace(/\/+$/, "")}/${folder}</div>`
    : html`
      <${Field} label=${t("projects.server_folder")} htmlFor="pj-path" hint=${t("projects.server_folder_hint")}>
        <div class="pj-pick-path">
          <input id="pj-path" class="mono" value=${path} placeholder=${t("projects.folder_placeholder")} onInput=${(e) => setPath(e.target.value)} />
          <button type="button" onClick=${() => setPick(true)}>${t("projects.choose_folder")}</button>
        </div>
      <//>
      ${info && !info.allowed && html`<div class="err">${info.reason}</div>`}
      ${info && info.allowed && html`<${ConfigList} config=${info.config} />`}
      ${needsTrust && html`<label class="pj-trust">
        <input type="checkbox" checked=${trust} onChange=${(e) => setTrust(e.target.checked)} />
        <span><b>${t("projects.trust_strong")}</b> ${t("projects.trust_text")} <b>${t("projects.restricted_mode_lower")}</b>${t("projects.trust_text_end")}</span>
      </label>`}`}
    ${err && html`<div class="err">${err}</div>`}
    <div class="modal-actions">
      <a class="btn" href="#projects">${t("common.cancel")}</a>
      <button class="primary" type="submit" disabled=${busy || !ready}>${t("projects.create_project")}</button>
    </div>
  </form>
  ${pick && (mode === "new"
    ? html`<${FolderPicker} start=${parent} title=${t("projects.where_create")} requireAllowed=${false} onPick=${setParent} onClose=${() => setPick(false)} />`
    : html`<${FolderPicker} start=${path} onPick=${setPath} onClose=${() => setPick(false)} />`)}
  </div>`;
}

function TrustBadge({ p }) {
  return p.trusted
    ? html`<span class="badge ok" title=${t("projects.trusted_title")}>${t("projects.trusted")}</span>`
    : html`<span class="badge warn" title=${t("projects.restricted_title")}>${t("projects.restricted_mode_lower")}</span>`;
}

// Sharing levels (server: services/project_acl.py). view < participate < manage < owner.
const LEVELS = ["view", "participate", "manage", "owner"];
export const atLeast = (p, lvl) => !!p && LEVELS.indexOf(p.my_level) >= LEVELS.indexOf(lvl);
const levelLabel = (l) => ({ view: t("projects.level_view"), participate: t("projects.level_participate"),
  manage: t("projects.level_manage"), owner: t("projects.level_owner") })[l] || l || "—";

// 🔒 private / 👥 shared / "from X · level" / admin outside the project.
function ShareBadge({ p }) {
  if (p.admin_view) return html`<span class="badge danger" title=${t("projects.admin_view_title")}>${t("projects.not_shared_with_you")}</span>`;
  const n = ((p.shared && p.shared.users) || 0) + ((p.shared && p.shared.groups) || 0);
  if (p.my_level && p.my_level !== "owner")
    return html`<span class="badge" title=${t("projects.shared_with_you_title")}>👥 ${p.owner_name
      ? t("projects.from_owner", { name: p.owner_name, level: levelLabel(p.my_level) }) : levelLabel(p.my_level)}</span>`;
  if (p.ownerless) return html`<span class="badge warn">${t("projects.ownerless")}</span>`;
  return n
    ? html`<span class="badge" title=${t("projects.shared_title")}>👥 ${t("projects.shared_count", { count: n })}</span>`
    : html`<span class="badge" title=${t("projects.private_title")}>🔒 ${t("projects.private")}</span>`;
}

// Arrastar e soltar p/ reordenar (lista e barra lateral). `ids` = ordem atual; devolve handlers por item.
// A ordem é do usuário (PUT /projects/order); arquivados ficam no fim, na ordem em que estavam.
export function useProjectDrag(list) {
  const [dragId, setDragId] = useState("");
  const [overId, setOverId] = useState("");
  async function drop(targetId) {
    const from = dragId; setDragId(""); setOverId("");
    if (!from || from === targetId) return;
    const ids = list.map((p) => p.id).filter((x) => x !== from);
    const at = ids.indexOf(targetId);
    ids.splice(at < 0 ? ids.length : at, 0, from);
    try { await api.put("/projects/order", { ids }); changed(); }
    catch (e) { toast.err(errText(e, t("projects.order_failed"))); }
  }
  const props = (id) => ({
    draggable: true,
    onDragStart: (e) => { setDragId(id); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", id); } catch (_) {} },
    onDragOver: (e) => { if (dragId) { e.preventDefault(); if (overId !== id) setOverId(id); } },
    onDragLeave: () => { if (overId === id) setOverId(""); },
    onDrop: (e) => { e.preventDefault(); drop(id); },
    onDragEnd: () => { setDragId(""); setOverId(""); },
  });
  const cls = (id) => (dragId === id ? " pj-dragging" : "") + (overId === id && dragId && dragId !== id ? " pj-dropover" : "");
  return { props, cls };
}

async function setArchived(p, v) {
  try { await api.put(`/projects/${encodeURIComponent(p.id)}/archived`, { archived: v }); changed();
    toast.ok(v ? t("projects.archived_toast", { name: p.name }) : t("projects.unarchived_toast", { name: p.name })); }
  catch (e) { toast.err(errText(e, t("projects.archive_failed"))); }
}
async function renameProject(p, name) {
  const v = (name || "").trim();
  if (!v || v === p.name) return null;
  try { const out = await api.patch(`/projects/${encodeURIComponent(p.id)}`, { name: v }); changed(); toast.ok(t("projects.renamed")); return out; }
  catch (e) { toast.err(errText(e, t("projects.rename_failed"))); return null; }
}
async function removeProject(p) {
  try { await api.del(`/projects/${encodeURIComponent(p.id)}`); changed(); toast.ok(t("projects.removed")); return true; }
  catch (e) { toast.err(errText(e, t("projects.remove_failed"))); return false; }
}

function ProjectRow({ p, drag, onRename, onDelete }) {
  const [editing, setEditing] = useState(null);
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  async function commit() { const v = editing; setEditing(null); await renameProject(p, v); }
  return html`<div class=${"card pj-item pj-row" + (drag ? drag.cls(p.id) : "")} ...${drag ? drag.props(p.id) : {}}>
    ${drag && html`<span class="pj-grip" title=${t("projects.drag_title")} aria-hidden="true">⠿</span>`}
    <a class="pj-row-main" href=${"#projects/" + p.id} draggable="false">
      ${editing != null
        ? html`<input class="pj-rename" value=${editing} autoFocus maxlength="80" aria-label=${t("projects.rename_project")}
            onClick=${stop} onInput=${(e) => setEditing(e.target.value)} onBlur=${commit}
            onKeyDown=${(e) => { if (e.key === "Enter") { stop(e); e.target.blur(); } else if (e.key === "Escape") setEditing(null); }} />`
        : html`<b>${p.name} <${TrustBadge} p=${p} /> <${ShareBadge} p=${p} /></b>`}
      <span class="mono help">${p.path}</span>
      ${!p.exists && html`<span class="badge warn">${t("projects.folder_not_found")}</span>`}
    </a>
    <span class="pj-row-actions">
      ${atLeast(p, "manage") && html`<button class="sm" title=${t("common.rename")} aria-label=${t("projects.rename_name", { name: p.name })}
        onClick=${(e) => { stop(e); setEditing(p.name); }}>✏</button>`}
      <button class="sm" title=${p.archived ? t("projects.unarchive_title") : t("projects.archive_title")}
        aria-label=${p.archived ? t("projects.unarchive_name", { name: p.name }) : t("projects.archive_name", { name: p.name })}
        onClick=${(e) => { stop(e); setArchived(p, !p.archived); }}>${p.archived ? "↩" : "🗄"}</button>
      ${(p.my_level === "owner" || can("server.admin")) && html`<button class="sm danger" title=${t("projects.remove_project")}
        aria-label=${t("projects.remove_name", { name: p.name })} onClick=${(e) => { stop(e); onDelete(p); }}>🗑</button>`}
    </span>
  </div>`;
}

// Admin: every project of the console (audited on the server). URL #projects?all=1
function useAllProjects(on) {
  const [list, setList] = useState(null);
  useEffect(() => {
    if (!on) { setList(null); return; }
    let alive = true;
    const load = () => api.get("/projects?all=1").then((d) => { if (alive) setList(d.projects || []); }).catch(() => {});
    load();
    addEventListener("netops:projects", load);
    return () => { alive = false; removeEventListener("netops:projects", load); };
  }, [on]);
  return list;
}

function ProjectList({ r }) {
  const mine = useProjects(true);
  const showAll = r.params.all === "1" && can("server.admin");
  const allList = useAllProjects(showAll);
  const all = showAll ? (allList || []) : mine;
  const showArch = r.params.arquivados === "1";
  const filter = r.params.filter || "";   // "" | mine | shared
  const byFilter = (p) => filter === "mine" ? p.my_level === "owner" && !p.admin_view
    : filter === "shared" ? p.my_level !== "owner" && !p.admin_view : true;
  const active = all.filter((p) => !p.archived && byFilter(p)), archived = all.filter((p) => p.archived && byFilter(p));
  const list = showArch ? archived : active;
  const drag = useProjectDrag(active);
  const [del, setDel] = useState(null);
  return html`<div>
    <div class="pj-head"><h2>${showArch ? t("projects.archived_projects") : t("projects.projects")}</h2><span class="spacer"></span>
      ${showArch
        ? html`<a class="btn" href="#projects">${t("projects.back_to_projects", { n: active.length })}</a>`
        : html`<a class="btn" href="#projects?arquivados=1" title=${t("projects.archived_link_title")}>${t("projects.archived_link", { n: archived.length })}</a>`}
      <a class="btn primary needs-projects-create" href="#projects/new">${t("projects.new_button")}</a></div>
    <div class="pj-filters" role="group" aria-label=${t("projects.filter_label")}>
      ${[["", t("projects.filter_all")], ["mine", t("projects.filter_mine")], ["shared", t("projects.filter_shared")]].map(([k, lbl]) =>
        html`<button key=${k} class=${"sm" + (filter === k ? " primary" : "")} aria-pressed=${filter === k}
          onClick=${() => r.setParams({ filter: k })}>${lbl}</button>`)}
      ${can("server.admin") && html`<button class=${"sm" + (showAll ? " danger" : "")} aria-pressed=${showAll}
        title=${t("projects.all_admin_title")} onClick=${() => r.pushParams({ all: showAll ? "" : "1" })}>🛡 ${t("projects.all_admin")}</button>`}
    </div>
    ${showAll && html`<div class="card pj-warn">${t("projects.all_admin_help")}</div>`}
    ${accountWarning && html`<div class="card pj-warn">${t("projects.account_warning_1")}<code>.claude/settings*.json</code>${t("projects.account_warning_2")} <code>env</code>${t("projects.account_warning_3")} <code>env</code> ${t("projects.account_warning_4")} <code>~/.claude/settings.json</code> ${t("projects.account_warning_5")}</div>`}
    ${!showArch && active.length > 1 && html`<div class="help pj-hint">${t("projects.drag_hint")}</div>`}
    ${list.length === 0
      ? html`<div class="card empty">${showArch ? t("projects.none_archived") : all.length
          ? t("projects.all_archived") : t("projects.none_yet")}</div>`
      : list.map((p) => html`<${ProjectRow} key=${p.id} p=${p} drag=${showArch || showAll || filter ? null : drag} onDelete=${setDel} />`)}
    ${del && html`<${ConfirmDialog} title=${t("projects.remove_project")} danger=${true}
      message=${t("projects.remove_confirm", { name: del.name })}
      onConfirm=${() => removeProject(del)} onClose=${() => setDel(null)} />`}
  </div>`;
}

// Arquivos da pasta do projeto (mesmo gerenciador do menu Arquivos, preso à pasta).
// URL: #projects/<id>/files?path=<pasta>&open=<arquivo>&q=&sort=&hidden=0
function ProjectFilesPage({ id, r }) {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { setInfo(null); setErr("");
    api.get(`/files/info?src=${encodeURIComponent("project:" + id)}`).then(setInfo).catch((e) => setErr(errText(e, t("projects.files_failed")))); }, [id]);
  const p = r.params;
  const state = { path: p.path || (info && info.root) || "", q: p.q || "", sort: p.sort || "", hidden: p.hidden !== "0", open: p.open || "" };
  function setState(patch, { push = false } = {}) {
    const out = {};
    for (const [k, v] of Object.entries(patch)) {
      if (k === "hidden") out.hidden = v ? "" : "0";
      else if (k === "sort") out.sort = v === "name" ? "" : v;
      else out[k] = v || "";
    }
    if ("path" in patch && !("open" in patch)) out.open = "";
    push ? r.pushParams(out) : r.setParams(out);
  }
  return html`<div class="files-page">
    <div class="pj-head"><a class="btn" href=${"#projects/" + id}>${t("projects.back_project")}</a><h2>${t("projects.project_files")}</h2>
      ${info && html`<span class="mono help">${info.root}</span>`}</div>
    ${err ? html`<div class="err">${err}</div>` : !info ? html`<div class="help">${t("projects.opening")}</div>`
      : html`<${FileBrowser} src=${"project:" + id} home=${info.root} state=${state} setState=${setState} />`}
  </div>`;
}

function ProjectHome({ id, r }) {
  const [proj, setProj] = useState(undefined);   // undefined = carregando, null = não existe
  const [renaming, setRenaming] = useState(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const [confirmTrust, setConfirmTrust] = useState(false);
  const load = () => api.get(`/projects/${encodeURIComponent(id)}`)
    .then(setProj).catch((e) => setProj(e.status === 404 ? null : undefined));
  useEffect(() => { setProj(undefined); load(); }, [id]);
  async function enterAsAdmin() {
    try { await api.post(`/projects/${encodeURIComponent(id)}/admin-access`, {}); load(); }
    catch (e) { toast.err(errText(e, t("projects.admin_access_failed"))); }
  }
  if (proj === null) return html`<div class="card">${t("projects.not_found", { id })} <a href="#projects">${t("projects.back_list")}</a>
    ${can("server.admin") && html`<p class="help">${t("projects.admin_enter_help")}</p>
      <button class="danger" onClick=${enterAsAdmin}>🛡 ${t("projects.admin_enter")}</button>`}</div>`;
  if (!proj) return html`<div class="help">${t("common.loading")}</div>`;
  const isOwner = proj.my_level === "owner";

  async function commitRename() {
    const v = (renaming || "").trim(); setRenaming(null);
    if (!v || v === proj.name) return;
    try { setProj(await api.patch(`/projects/${encodeURIComponent(id)}`, { name: v })); changed(); toast.ok(t("projects.renamed")); }
    catch (e) { toast.err(errText(e, t("projects.rename_failed"))); }
  }
  async function setTrusted(v) {
    try { setProj(await api.patch(`/projects/${encodeURIComponent(id)}`, { trusted: v })); changed();
      toast.ok(v ? t("projects.trusted_toast") : t("projects.restricted_toast")); }
    catch (e) { toast.err(errText(e, t("projects.trust_failed"))); }
  }
  async function remove() {
    try { await api.del(`/projects/${encodeURIComponent(id)}`); changed(); toast.ok(t("projects.removed")); navigate("#projects"); }
    catch (e) { toast.err(errText(e, t("projects.remove_failed"))); }
  }
  return html`<div>
    <div class="pj-head">
      ${renaming != null
        ? html`<input class="pj-rename" value=${renaming} autoFocus maxlength="80" aria-label=${t("projects.rename_project")}
            onInput=${(e) => setRenaming(e.target.value)} onBlur=${commitRename}
            onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); else if (e.key === "Escape") setRenaming(null); }} />`
        : html`<h2 title=${atLeast(proj, "manage") ? t("projects.dblclick_rename") : ""}
            onDblClick=${() => atLeast(proj, "manage") && setRenaming(proj.name)}>${proj.name}</h2>`}
      <span class="spacer"></span>
      ${proj.exists && atLeast(proj, "participate")
        ? html`<a class="btn primary" href=${"#projects/" + id + "/new"}>${t("projects.new_session")}</a>`
        : html`<button class="primary" disabled=${true} title=${atLeast(proj, "participate") ? "" : t("projects.view_only_title")}>${t("projects.new_session")}</button>`}
      ${atLeast(proj, "manage") && html`<a class="btn" href=${"#projects/" + id + "/share"} title=${t("projects.share_title")}>👥 ${t("projects.share")}</a>`}
      <a class="btn needs-projects-files" href=${"#projects/" + id + "/files"} title=${t("projects.files_title")}>${t("projects.files")}</a>
      <button onClick=${async () => { await setArchived(proj, !proj.archived); load(); }}
        title=${proj.archived ? t("projects.unarchive_home_title") : t("projects.archive_home_title")}>${proj.archived ? t("projects.unarchive") : t("projects.archive")}</button>
      ${proj.trusted
        ? html`<button class="needs-projects-manage" onClick=${() => setTrusted(false)}>${t("projects.restricted_mode")}</button>`
        : html`<button class="needs-projects-manage" onClick=${() => setConfirmTrust(true)}>${t("projects.trust_folder")}</button>`}
      ${atLeast(proj, "manage") && html`<button onClick=${() => setRenaming(proj.name)}>${t("common.rename")}</button>`}
      ${(isOwner || can("server.admin")) && html`<button class="danger" onClick=${() => setConfirmDel(true)}>${t("common.remove")}</button>`}
    </div>
    ${proj.admin_view && html`<div class="card pj-admin-banner" role="alert">🛡 ${t("projects.admin_banner", {
      name: proj.owner_name || proj.owner || "—", time: proj.override_until ? fmtDateTime(proj.override_until * 1000) : "—" })}</div>`}
    <div class="pj-share-line">
      <${ShareBadge} p=${proj} />
      <span class="help">${isOwner ? t("projects.you_are_owner") : t("projects.your_level", { level: levelLabel(proj.my_level) })}
        ${proj.owner_name && !isOwner ? " · " + t("projects.owner_is", { name: proj.owner_name }) : ""}</span>
      ${atLeast(proj, "manage") && html`<a href=${"#projects/" + id + "/share"}>${t("projects.manage_access")}</a>`}
    </div>
    <div class="mono help pj-path" title=${t("projects.path_title")}>📁 ${proj.path} <${TrustBadge} p=${proj} /></div>
    ${!proj.trusted && html`<div class="help">${t("projects.restricted_help")}</div>`}
    ${proj.exists && html`<${ConfigList} config=${proj.config} />`}
    ${!proj.exists && html`<div class="card">${t("projects.folder_gone")}</div>`}
    <div class="pj-sess">
      <${SessionsList} project=${id} q=${r.params.q || ""} onQ=${(v) => r.setParams({ q: v })}
        onResume=${(sid) => navigate(claudeSessionHash(sid, id))} />
    </div>
    ${confirmTrust && html`<${ConfirmDialog} title=${t("projects.trust_confirm_title")} danger=${true}
      message=${t("projects.trust_confirm", { path: proj.path, items: [...(proj.config.exec || []), ...(proj.config.info || [])].join(", ") || t("projects.none_for_now") })}
      onConfirm=${() => setTrusted(true)} onClose=${() => setConfirmTrust(false)} />`}
    ${confirmDel && html`<${ConfirmDialog} title=${t("projects.remove_project")} danger=${true}
      message=${t("projects.remove_confirm", { name: proj.name })}
      onConfirm=${remove} onClose=${() => setConfirmDel(false)} />`}
  </div>`;
}

// --------------------------------------------------------------------- sharing
// #projects/<id>/share[?tab=effective&q=] — owner/manage pick users and access groups and the level of each.
// Edits are a draft: one PUT (with rev) on "Save"; a stale rev (someone else saved) = 409, the page reloads.
function ProjectSharePage({ id, r }) {
  const me = useMe();
  const [proj, setProj] = useState(undefined);
  const [data, setData] = useState(null);        // server state (GET /shares)
  const [draft, setDraft] = useState(null);      // {users: [...], groups: [...]}
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [leave, setLeave] = useState(false);
  const [transfer, setTransfer] = useState(false);
  const tab = r.params.tab === "effective" ? "effective" : "members";
  const q = r.params.q || "";
  const load = () => Promise.all([api.get(`/projects/${encodeURIComponent(id)}`), api.get(`/projects/${encodeURIComponent(id)}/shares`)])
    .then(([p, d]) => { setProj(p); setData(d); setDraft({ users: d.users, groups: d.groups }); setErr(""); })
    .catch((e) => { setProj(e.status === 404 ? null : undefined); setErr(errText(e, t("projects.share_load_failed"))); });
  useEffect(() => { setProj(undefined); setData(null); load(); }, [id]);
  if (proj === null) return html`<div class="card">${t("projects.not_found", { id })} <a href="#projects">${t("projects.back_list")}</a></div>`;
  if (err && !data) return html`<div class="card"><div class="err">${err}</div><a href=${"#projects/" + id}>${t("projects.back_project")}</a></div>`;
  if (!proj || !data || !draft) return html`<div class="help">${t("common.loading")}</div>`;

  const canOwner = proj.my_level === "owner" || can("server.admin");
  const key = (x) => (x.username ? "u:" + x.username : "g:" + x.name);
  const sig = (d) => JSON.stringify([d.users.map((x) => [x.username, x.level]).sort(), d.groups.map((x) => [x.name, x.level]).sort()]);
  const dirty = sig(draft) !== sig(data);
  const total = draft.users.length + draft.groups.length;
  function add(items, level) {
    setDraft((d) => {
      const users = [...d.users], groups = [...d.groups];
      for (const it of items) {
        if (it.kind === "user" && !users.some((x) => x.username === it.username)) users.push({ ...it, level });
        if (it.kind === "group" && !groups.some((x) => x.name === it.name)) groups.push({ ...it, level });
      }
      return { users, groups };
    });
  }
  const setLevel = (row, level) => setDraft((d) => row.username
    ? { ...d, users: d.users.map((x) => (x.username === row.username ? { ...x, level } : x)) }
    : { ...d, groups: d.groups.map((x) => (x.name === row.name ? { ...x, level } : x)) });
  const removeRow = (row) => setDraft((d) => row.username
    ? { ...d, users: d.users.filter((x) => x.username !== row.username) }
    : { ...d, groups: d.groups.filter((x) => x.name !== row.name) });
  async function save() {
    setBusy(true);
    try {
      const out = await api.put(`/projects/${encodeURIComponent(id)}/shares`, { rev: data.rev,
        users: draft.users.map((x) => ({ username: x.username, level: x.level })),
        groups: draft.groups.map((x) => ({ name: x.name, level: x.level })) });
      setData(out); setDraft({ users: out.users, groups: out.groups }); changed(); toast.ok(t("projects.share_saved"));
      if (!out.my_level) navigate("#projects");
    } catch (e) {
      if (e.status === 409) { toast.err(t("projects.share_conflict")); load(); }
      else toast.err(errText(e, t("projects.share_save_failed")));
    } finally { setBusy(false); }
  }
  const levels = canOwner ? ["view", "participate", "manage"] : ["view", "participate", "manage"];
  const rows = [...draft.users.map((x) => ({ ...x, kind: "user" })), ...draft.groups.map((x) => ({ ...x, kind: "group" }))]
    .filter((x) => !q || [x.username, x.name, x.display_name, x.description].some((v) => (v || "").toLowerCase().includes(q.toLowerCase())))
    .map((x) => ({ ...x, _key: key(x) }));
  const cols = [
    { key: "kind", label: t("projects.col_type"), sort: true, width: 70,
      render: (x) => html`<span title=${x.kind === "user" ? t("projects.kind_user") : t("projects.kind_group")}>${x.kind === "user" ? "👤" : "👥"}</span>` },
    { key: "name", label: t("common.name"), hideable: false, sort: (x) => (x.display_name || x.name || "").toLowerCase(),
      render: (x) => html`<b>${x.kind === "user" ? x.display_name || x.username : x.name}</b>
        ${me && x.username === me.username ? html` <span class="badge">${t("projects.you")}</span>` : ""}` },
    { key: "detail", label: t("projects.col_detail"), sort: (x) => x.username || x.description || "",
      render: (x) => x.kind === "user" ? html`<code>${x.username}</code>`
        : html`<span class="help">${x.description || ""} · ${t("projects.members_count", { count: x.members || 0 })}</span>` },
    { key: "level", label: t("projects.col_level"), hideable: false, sort: (x) => LEVELS.indexOf(x.level),
      render: (x) => html`<select aria-label=${t("projects.level_of", { name: x.display_name || x.name || x.username })}
          value=${x.level} onClick=${(e) => e.stopPropagation()} onChange=${(e) => setLevel(x, e.target.value)}>
        ${levels.map((l) => html`<option value=${l}>${levelLabel(l)}</option>`)}</select>` },
    { key: "warn", label: t("projects.col_notes"), sort: (x) => (x.has_claude === false ? 1 : 0) + (x.disabled ? 2 : 0),
      render: (x) => html`${x.has_claude === false ? html`<span class="badge warn" title=${t("projects.no_claude_title")}>${t("projects.no_claude")}</span> ` : ""}
        ${x.disabled ? html`<span class="badge danger">${t("projects.user_disabled")}</span> ` : ""}
        ${x.kind === "group" && x.name === "admin" ? html`<span class="badge">${t("projects.admin_group_note")}</span>` : ""}` },
    { key: "granted_by", label: t("projects.col_granted_by"), sort: (x) => x.granted_by_name || "", hidden: false,
      render: (x) => x.granted_by_name || (x.granted_at ? "—" : html`<span class="help">${t("projects.not_saved")}</span>`) },
    { key: "granted_at", label: t("projects.col_when"), sort: (x) => x.granted_at || 0,
      render: (x) => (x.granted_at ? fmtDateTime(x.granted_at * 1000) : "—") },
  ];
  const ecols = [
    { key: "name", label: t("common.name"), hideable: false, sort: (x) => (x.display_name || "").toLowerCase(),
      render: (x) => html`<b>${x.display_name}</b> <code class="help">${x.username}</code>` },
    { key: "level", label: t("projects.col_level"), sort: (x) => LEVELS.indexOf(x.level), render: (x) => levelLabel(x.level) },
    { key: "via", label: t("projects.col_via"), sort: (x) => x.via.join(","),
      render: (x) => x.via.map((v) => html`<span class="badge">${v === "owner" ? t("projects.via_owner") : v === "direct"
        ? t("projects.via_direct") : t("projects.via_group", { name: v.slice(6) })}</span> `) },
    { key: "warn", label: t("projects.col_notes"), sort: (x) => (x.has_claude ? 0 : 1),
      render: (x) => html`${!x.has_claude ? html`<span class="badge warn" title=${t("projects.no_claude_title")}>${t("projects.no_claude")}</span>` : ""}
        ${x.disabled ? html`<span class="badge danger">${t("projects.user_disabled")}</span>` : ""}` },
  ];
  const eff = (data.effective || []).filter((x) => !q || [x.username, x.display_name].some((v) => (v || "").toLowerCase().includes(q.toLowerCase())))
    .map((x) => ({ ...x, _key: x.username }));
  const back = () => (dirty ? setLeave(true) : navigate("#projects/" + id));
  return html`<div class="pj-share">
    <div class="pj-head">
      <button type="button" onClick=${back}>${t("projects.back_project")}</button>
      <h2>${t("projects.share_heading", { name: proj.name })}</h2><span class="spacer"></span>
      ${dirty && html`<span class="badge warn">${t("projects.unsaved")}</span>`}
    </div>
    <div class="card pj-share-state">
      <div>${total ? html`👥 ${t("projects.state_shared", { users: draft.users.length, groups: draft.groups.length })}` : html`🔒 ${t("projects.state_private")}`}</div>
      <div class="help">${t("projects.owner_label")}: <b>${data.owner ? data.owner.display_name : t("projects.ownerless")}</b>
        ${data.owner && html` <code>${data.owner.username}</code>`}
        ${canOwner && html` <button class="sm" onClick=${() => setTransfer(true)}>${t("projects.transfer")}</button>`}</div>
      <div class="help">${t("projects.share_os_note")}</div>
    </div>
    <${SharePicker} id=${id} exclude=${new Set([...draft.users.map((x) => "u:" + x.username), ...draft.groups.map((x) => "g:" + x.name),
      ...(data.owner ? ["u:" + data.owner.username] : [])])} levels=${levels} onAdd=${add} />
    <div class="pj-share-tabs" role="tablist">
      <button role="tab" aria-selected=${tab === "members"} class=${"sm" + (tab === "members" ? " primary" : "")}
        onClick=${() => r.setParams({ tab: "" })}>${t("projects.tab_members", { count: total })}</button>
      <button role="tab" aria-selected=${tab === "effective"} class=${"sm" + (tab === "effective" ? " primary" : "")}
        onClick=${() => r.setParams({ tab: "effective" })}>${t("projects.tab_effective", { count: (data.effective || []).length })}</button>
    </div>
    <${FilterBar} q=${q} onChange=${(p) => r.setParams(p)} placeholder=${t("projects.filter_members")} />
    ${tab === "members"
      ? html`<${DataTable} tableId="project-shares" urlSort="m" columns=${cols} rows=${rows}
          actions=${(x) => html`<button class="sm danger" aria-label=${t("projects.remove_access", { name: x.display_name || x.name || x.username })}
            onClick=${(e) => { e.stopPropagation(); removeRow(x); }}>🗑</button>`}
          empty=${t("projects.no_members")} />`
      : html`<p class="help">${t("projects.effective_help")}</p>
        ${dirty && html`<p class="help pj-warn">${t("projects.effective_after_save")}</p>`}
        <${DataTable} tableId="project-access-effective" urlSort="e" columns=${ecols} rows=${eff} empty=${t("projects.no_members")} />`}
    <div class="modal-actions">
      <button type="button" disabled=${!dirty || busy} onClick=${() => setDraft({ users: data.users, groups: data.groups })}>${t("projects.discard")}</button>
      <button type="button" class="primary" disabled=${!dirty || busy} onClick=${save}>${t("projects.save_changes")}</button>
    </div>
    ${leave && html`<${ConfirmDialog} title=${t("projects.unsaved")} danger=${true} message=${t("projects.leave_confirm")}
      onConfirm=${() => navigate("#projects/" + id)} onClose=${() => setLeave(false)} />`}
    ${transfer && html`<${TransferOwner} id=${id} proj=${proj} owner=${data.owner} onClose=${() => setTransfer(false)}
      onDone=${(out) => { setTransfer(false); changed(); if (!out.my_level) navigate("#projects"); else load(); }} />`}
  </div>`;
}

// Search users and groups together (one field), multi-select into chips, one level for the batch.
function SharePicker({ id, exclude, levels, onAdd }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState({ users: [], groups: [] });
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState([]);
  const [level, setLevel] = useState("participate");
  const box = useRef(null);
  useEffect(() => {
    if (!open) return;
    const tm = setTimeout(() => api.get(`/projects/${encodeURIComponent(id)}/shares/candidates?q=${encodeURIComponent(q)}`)
      .then(setRes).catch(() => {}), 200);
    return () => clearTimeout(tm);
  }, [q, open, id]);
  useEffect(() => {
    const down = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", down);
    return () => document.removeEventListener("pointerdown", down);
  }, []);
  const k = (x) => (x.kind === "user" ? "u:" + x.username : "g:" + x.name);
  const taken = new Set([...exclude, ...picked.map(k)]);
  const options = [...res.users.map((u) => ({ ...u, kind: "user" })), ...res.groups.map((g) => ({ ...g, kind: "group" }))]
    .filter((x) => !taken.has(k(x)));
  const pick = (x) => { setPicked((p) => [...p, x]); setQ(""); };
  function addNow() { if (!picked.length) return; onAdd(picked, level); setPicked([]); setOpen(false); }
  return html`<div class="card pj-share-add" ref=${box}>
    <b>${t("projects.add_people")}</b>
    <div class="pj-share-add-row">
      <div class="pj-share-search">
        <div class="pj-chips">
          ${picked.map((x) => html`<span class="pj-chip" key=${k(x)}>${x.kind === "user" ? "👤 " + (x.display_name || x.username) : "👥 " + x.name}
            <button type="button" class="sm" aria-label=${t("projects.unpick", { name: x.display_name || x.name })}
              onClick=${() => setPicked((p) => p.filter((y) => k(y) !== k(x)))}>✕</button></span>`)}
          <input value=${q} placeholder=${t("projects.search_people")} aria-label=${t("projects.search_people")}
            onFocus=${() => setOpen(true)} onInput=${(e) => { setQ(e.target.value); setOpen(true); }}
            onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); if (options[0] && q) pick(options[0]); else addNow(); }
              else if (e.key === "Escape") setOpen(false);
              else if (e.key === "Backspace" && !q && picked.length) setPicked((p) => p.slice(0, -1)); }} />
        </div>
        ${open && html`<div class="pj-share-menu" role="listbox">
          ${options.length === 0 && html`<div class="help">${t("projects.no_candidates")}</div>`}
          ${options.map((x) => html`<button type="button" role="option" key=${k(x)} class="pj-share-opt" onClick=${() => pick(x)}>
            <span>${x.kind === "user" ? "👤" : "👥"}</span>
            <b>${x.kind === "user" ? x.display_name || x.username : x.name}</b>
            <small>${x.kind === "user" ? x.username + (x.groups && x.groups.length ? " · " + x.groups.join(", ") : "")
              : (x.description || "") + " · " + t("projects.members_count", { count: x.members || 0 })}</small>
            ${!x.has_claude && html`<span class="badge warn">${t("projects.no_claude")}</span>`}
          </button>`)}
        </div>`}
      </div>
      <select value=${level} aria-label=${t("projects.col_level")} onChange=${(e) => setLevel(e.target.value)}>
        ${levels.map((l) => html`<option value=${l}>${levelLabel(l)}</option>`)}</select>
      <button type="button" class="primary" disabled=${!picked.length} onClick=${addNow}>${t("projects.add")}</button>
    </div>
    <div class="help">${t("projects.levels_help")}</div>
  </div>`;
}

function TransferOwner({ id, proj, owner, onClose, onDone }) {
  const [users, setUsers] = useState([]);
  const [to, setTo] = useState("");
  const [keep, setKeep] = useState("manage");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get(`/projects/${encodeURIComponent(id)}/shares/candidates?q=`).then((d) => setUsers(d.users || [])).catch(() => {}); }, [id]);
  async function go() {
    setBusy(true);
    try { onDone(await api.put(`/projects/${encodeURIComponent(id)}/owner`, { username: to, keep })); toast.ok(t("projects.transferred")); }
    catch (e) { toast.err(errText(e, t("projects.transfer_failed"))); }
    finally { setBusy(false); }
  }
  return html`<${Modal} title=${t("projects.transfer_title", { name: proj.name })} onClose=${onClose}>
    <${Field} label=${t("projects.new_owner")} htmlFor="pj-new-owner">
      <select id="pj-new-owner" value=${to} onChange=${(e) => setTo(e.target.value)}>
        <option value="">—</option>
        ${users.filter((u) => !owner || u.username !== owner.username).map((u) => html`<option value=${u.username}>${u.display_name} (${u.username})</option>`)}
      </select>
    <//>
    ${owner && html`<${Field} label=${t("projects.previous_owner_keeps", { name: owner.display_name })} htmlFor="pj-keep">
      <select id="pj-keep" value=${keep} onChange=${(e) => setKeep(e.target.value)}>
        ${["manage", "participate", "view"].map((l) => html`<option value=${l}>${levelLabel(l)}</option>`)}
        <option value="none">${t("projects.leave_project")}</option>
      </select>
    <//>`}
    <${Field} label=${t("projects.type_name_to_confirm", { name: proj.name })} htmlFor="pj-confirm">
      <input id="pj-confirm" value=${confirm} onInput=${(e) => setConfirm(e.target.value)} />
    <//>
    <div class="modal-actions">
      <button type="button" onClick=${onClose}>${t("common.cancel")}</button>
      <button type="button" class="danger" disabled=${!to || confirm.trim() !== proj.name || busy} onClick=${go}>${t("projects.transfer")}</button>
    </div>
  <//>`;
}

export function ProjectsPage() {
  const r = useMenuRoute("projects");
  const [a, b] = r.segments;
  if (!a) return html`<${ProjectList} r=${r} />`;
  if (a === "new") return html`<${NewProject} />`;
  if (!validProjectId(a)) return html`<div class="card">${t("projects.not_found", { id: a })} <a href="#projects">${t("projects.back_list")}</a></div>`;
  // #projects/<id>/<uuid|new>: a conversa (o provider liga o agente à pasta do projeto).
  // (id de conversa inválido também cai aqui: o provider mostra o erro e o link de volta)
  if (b === "files") return html`<${ProjectFilesPage} id=${a} r=${r} />`;
  if (b === "share") return html`<${ProjectSharePage} id=${a} r=${r} />`;
  if (b !== undefined) return html`<${ClaudeCodePage} />`;
  return html`<${ProjectHome} id=${a} r=${r} />`;
}
