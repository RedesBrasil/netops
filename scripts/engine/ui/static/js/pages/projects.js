// Projetos: nome + pasta do servidor. Cada projeto tem as próprias sessões do Claude Code (as conversas
// daquela pasta). URLs: #projects[?arquivados=1], #projects/new, #projects/<id>[?q=], #projects/<id>/new,
// #projects/<id>/<uuid>, #projects/<id>/files[?path=&open=&q=&sort=&hidden=] (arquivos da pasta do projeto).
// O chat em si é a ClaudeCodePage; quem liga o agente à pasta é o ClaudeProvider (?project= no WebSocket).
import { html, useState, useEffect, toast, api } from "../ui.js";
import { Modal, Field, ConfirmDialog } from "../components.js";
import { useMenuRoute, navigate } from "../route.js";
import { ClaudeCodePage, SessionsList } from "./claude.js";
import { FileBrowser } from "../file-browser.js";
import { validProjectId, claudeSessionHash } from "../claude-sessions.js";

// 404 sem `error` = rota que o servidor não conhece (as nossas respostas sempre trazem `error`): o console
// está rodando uma versão anterior ao menu Projetos e precisa ser reiniciado.
const errText = (e, fallback) => (e && e.status === 404 && e.payload && !e.payload.error)
  ? "O servidor ainda está na versão antiga (sem Projetos). Reinicie o console com scripts/engine/ui/start.sh."
  : (e && e.payload && (e.payload.detail || e.payload.error)) || (e && e.message) || fallback;
const changed = () => window.dispatchEvent(new Event("netops:projects"));   // a sidebar recarrega a lista

// Lista de projetos para a sidebar (recarrega quando algo muda ou a janela volta ao foco).
let accountWarning = false;   // conta do agente só nos settings do NetOps (ver claude_models.account_only_in_netops)
export function useProjects(enabled) {
  const [list, setList] = useState([]);
  useEffect(() => {
    if (!enabled) { setList([]); return; }
    let alive = true;
    const load = () => api.get("/projects").then((d) => {
      accountWarning = !!d.account_warning;
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
function FolderPicker({ start, onPick, onClose, requireAllowed = true, title = "Escolher pasta do projeto" }) {
  const [data, setData] = useState(null);
  const [typed, setTyped] = useState(start || "");
  const [hidden, setHidden] = useState(false);
  const [err, setErr] = useState("");
  async function go(path, showHidden = hidden) {
    setErr("");
    try {
      const d = await api.get(`/projects/browse?path=${encodeURIComponent(path || "")}${showHidden ? "&hidden=1" : ""}`);
      setData(d); setTyped(d.path);
    } catch (e) { setErr(errText(e, "Não foi possível abrir a pasta.")); }
  }
  useEffect(() => { go(start || ""); }, []);
  return html`<${Modal} title=${title} onClose=${onClose} wide=${true}>
    <div class="pj-pick-path">
      <input class="mono" value=${typed} aria-label="Caminho da pasta" placeholder="/caminho/da/pasta"
        onInput=${(e) => setTyped(e.target.value)}
        onKeyDown=${(e) => { if (e.key === "Enter") go(typed); }} />
      <button type="button" onClick=${() => go(typed)}>Ir</button>
    </div>
    <label class="help pj-hidden"><input type="checkbox" checked=${hidden}
      onChange=${(e) => { setHidden(e.target.checked); go(typed, e.target.checked); }} /> Mostrar pastas ocultas</label>
    ${err && html`<div class="err">${err}</div>`}
    ${data && html`<div class="pj-folders">
      ${data.parent != null && html`<button class="pj-folder" type="button" onClick=${() => go(data.parent)}>⬆ ..</button>`}
      ${data.dirs.length === 0 && html`<div class="help">Nenhuma subpasta aqui.</div>`}
      ${data.dirs.map((d) => html`<button key=${d.path} type="button" class="pj-folder" onClick=${() => go(d.path)}>📁 ${d.name}</button>`)}
    </div>`}
    ${data && requireAllowed && !data.allowed && html`<div class="help pj-deny">⛔ ${data.reason}</div>`}
    <div class="modal-actions">
      <button type="button" onClick=${onClose}>Cancelar</button>
      <button type="button" class="primary" disabled=${!data || (requireAllowed && !data.allowed)}
        onClick=${() => { onPick(data.path); onClose(); }}>Usar esta pasta</button>
    </div>
  <//>`;
}

// O que a pasta traz para o agente. `exec` = config que executa algo ao abrir (hooks, MCP, env/proxy):
// só entra com a pasta marcada como confiável (modelo "Workspace Trust" do VS Code).
function ConfigList({ config }) {
  const ex = (config && config.exec) || [], info = (config && config.info) || [];
  if (!ex.length && !info.length) return html`<div class="help">A pasta não traz configuração do Claude Code.</div>`;
  return html`<div class="help pj-config">
    ${ex.length > 0 && html`<div>⚠ Executa ao abrir: ${ex.map((n) => html`<code key=${n}>${n}</code> `)}</div>`}
    ${info.length > 0 && html`<div>Instruções: ${info.map((n) => html`<code key=${n}>${n}</code> `)}</div>`}
  </div>`;
}

const DEFAULT_BASE = "/opt/projetos";

function NewProject() {
  const [name, setName] = useState("");
  const [mode, setMode] = useState("new");          // "new" = criar pasta nova (como o VS Code) | "existing"
  const [path, setPath] = useState("");
  const [parent, setParent] = useState(DEFAULT_BASE);
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
    const t = setTimeout(() => api.get(`/projects/browse?path=${encodeURIComponent(path.trim())}`)
      .then(setInfo).catch(() => setInfo(null)), 300);
    return () => clearTimeout(t);
  }, [path, mode]);
  const needsTrust = mode === "existing" && info && info.config && info.config.exec.length > 0;
  const ready = name.trim() && (mode === "new" ? folder.trim() && parent.trim() : path.trim() && (!info || info.allowed));
  async function save(e) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const body = mode === "new" ? { name, path: parent, new_folder: folder } : { name, path, trust };
      const p = await api.post("/projects", body);
      changed(); toast.ok(p.trusted ? "Projeto criado" : "Projeto criado em modo restrito");
      navigate("#projects/" + p.id);
    } catch (x) { setErr(errText(x, "Não foi possível criar o projeto.")); }
    finally { setBusy(false); }
  }
  // O seletor fica FORA do <form>: dentro dele, Enter e os botões do modal (type=submit por padrão)
  // submeteriam o formulário e criariam o projeto sem o usuário pedir.
  return html`<div>
  <form class="card pj-form" onSubmit=${save}>
    <h2>Novo projeto</h2>
    <p class="help">Um projeto é uma pasta do servidor, como abrir uma pasta no VS Code. As sessões do Claude Code abertas nele rodam nessa pasta, com a conta do agente do servidor, e ficam guardadas no projeto.</p>
    <${Field} label="Nome" htmlFor="pj-name">
      <input id="pj-name" value=${name} maxlength="80" autoFocus placeholder="Ex.: Meu site" onInput=${(e) => setName(e.target.value)} />
    <//>
    <div class="pj-mode" role="radiogroup" aria-label="Pasta do projeto">
      <label><input type="radio" name="pj-mode" checked=${mode === "new"} onChange=${() => setMode("new")} /> Criar pasta nova</label>
      <label><input type="radio" name="pj-mode" checked=${mode === "existing"} onChange=${() => setMode("existing")} /> Abrir pasta existente</label>
    </div>
    ${mode === "new" ? html`
      <${Field} label="Criar dentro de" htmlFor="pj-parent" hint=${"Padrão: " + DEFAULT_BASE + " (criada se não existir)."}>
        <div class="pj-pick-path">
          <input id="pj-parent" class="mono" value=${parent} onInput=${(e) => setParent(e.target.value)} />
          <button type="button" onClick=${() => setPick(true)}>Escolher…</button>
        </div>
      <//>
      <${Field} label="Nome da pasta" htmlFor="pj-folder" hint="Letras, números, ponto, hífen ou _. A pasta nasce vazia e confiável.">
        <input id="pj-folder" class="mono" value=${folder} maxlength="64"
          onInput=${(e) => { setFolderTouched(true); setFolder(e.target.value); }} />
      <//>
      <div class="help mono">📁 ${(parent || "").replace(/\/+$/, "")}/${folder}</div>`
    : html`
      <${Field} label="Pasta do servidor" htmlFor="pj-path" hint="Caminho absoluto. Use “Escolher pasta…” para navegar.">
        <div class="pj-pick-path">
          <input id="pj-path" class="mono" value=${path} placeholder="/caminho/da/pasta" onInput=${(e) => setPath(e.target.value)} />
          <button type="button" onClick=${() => setPick(true)}>Escolher pasta…</button>
        </div>
      <//>
      ${info && !info.allowed && html`<div class="err">${info.reason}</div>`}
      ${info && info.allowed && html`<${ConfigList} config=${info.config} />`}
      ${needsTrust && html`<label class="pj-trust">
        <input type="checkbox" checked=${trust} onChange=${(e) => setTrust(e.target.checked)} />
        <span><b>Confio nos autores desta pasta.</b> Carregar a configuração dela (hooks, servidores MCP, variáveis de ambiente), que roda como o usuário do servidor. Sem marcar, o projeto abre em <b>modo restrito</b>: o agente ignora essa configuração.</span>
      </label>`}`}
    ${err && html`<div class="err">${err}</div>`}
    <div class="modal-actions">
      <a class="btn" href="#projects">Cancelar</a>
      <button class="primary" type="submit" disabled=${busy || !ready}>Criar projeto</button>
    </div>
  </form>
  ${pick && (mode === "new"
    ? html`<${FolderPicker} start=${parent} title="Onde criar a pasta" requireAllowed=${false} onPick=${setParent} onClose=${() => setPick(false)} />`
    : html`<${FolderPicker} start=${path} onPick=${setPath} onClose=${() => setPick(false)} />`)}
  </div>`;
}

function TrustBadge({ p }) {
  return p.trusted
    ? html`<span class="badge ok" title="A configuração da pasta (hooks, MCP, env) é carregada">confiável</span>`
    : html`<span class="badge warn" title="O agente ignora a configuração da pasta (hooks, MCP, env, CLAUDE.md)">modo restrito</span>`;
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
    catch (e) { toast.err(errText(e, "Falha ao salvar a ordem")); }
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
    toast.ok(v ? `“${p.name}” arquivado (só para você)` : `“${p.name}” de volta aos projetos`); }
  catch (e) { toast.err(errText(e, "Falha ao arquivar")); }
}
async function renameProject(p, name) {
  const v = (name || "").trim();
  if (!v || v === p.name) return null;
  try { const out = await api.patch(`/projects/${encodeURIComponent(p.id)}`, { name: v }); changed(); toast.ok("Projeto renomeado"); return out; }
  catch (e) { toast.err(errText(e, "Falha ao renomear")); return null; }
}
async function removeProject(p) {
  try { await api.del(`/projects/${encodeURIComponent(p.id)}`); changed(); toast.ok("Projeto removido"); return true; }
  catch (e) { toast.err(errText(e, "Falha ao remover")); return false; }
}

function ProjectRow({ p, drag, onRename, onDelete }) {
  const [editing, setEditing] = useState(null);
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  async function commit() { const v = editing; setEditing(null); await renameProject(p, v); }
  return html`<div class=${"card pj-item pj-row" + (drag ? drag.cls(p.id) : "")} ...${drag ? drag.props(p.id) : {}}>
    ${drag && html`<span class="pj-grip" title="Segure e arraste para mudar a ordem" aria-hidden="true">⠿</span>`}
    <a class="pj-row-main" href=${"#projects/" + p.id} draggable="false">
      ${editing != null
        ? html`<input class="pj-rename" value=${editing} autoFocus maxlength="80" aria-label="Renomear projeto"
            onClick=${stop} onInput=${(e) => setEditing(e.target.value)} onBlur=${commit}
            onKeyDown=${(e) => { if (e.key === "Enter") { stop(e); e.target.blur(); } else if (e.key === "Escape") setEditing(null); }} />`
        : html`<b>${p.name} <${TrustBadge} p=${p} /></b>`}
      <span class="mono help">${p.path}</span>
      ${!p.exists && html`<span class="badge warn">pasta não encontrada</span>`}
    </a>
    <span class="pj-row-actions">
      <button class="sm needs-projects-manage" title="Renomear" aria-label=${"Renomear " + p.name}
        onClick=${(e) => { stop(e); setEditing(p.name); }}>✏</button>
      <button class="sm" title=${p.archived ? "Desarquivar (volta para a lista e a barra lateral)" : "Arquivar (esconde só para você)"}
        aria-label=${(p.archived ? "Desarquivar " : "Arquivar ") + p.name}
        onClick=${(e) => { stop(e); setArchived(p, !p.archived); }}>${p.archived ? "↩" : "🗄"}</button>
      <button class="sm danger needs-projects-manage" title="Remover projeto" aria-label=${"Remover " + p.name}
        onClick=${(e) => { stop(e); onDelete(p); }}>🗑</button>
    </span>
  </div>`;
}

function ProjectList({ r }) {
  const all = useProjects(true);
  const showArch = r.params.arquivados === "1";
  const active = all.filter((p) => !p.archived), archived = all.filter((p) => p.archived);
  const list = showArch ? archived : active;
  const drag = useProjectDrag(active);
  const [del, setDel] = useState(null);
  return html`<div>
    <div class="pj-head"><h2>${showArch ? "Projetos arquivados" : "Projetos"}</h2><span class="spacer"></span>
      ${showArch
        ? html`<a class="btn" href="#projects">← Projetos (${active.length})</a>`
        : html`<a class="btn" href="#projects?arquivados=1" title="Projetos que você escondeu">🗄 Arquivados (${archived.length})</a>`}
      <a class="btn primary needs-projects-manage" href="#projects/new">＋ Novo projeto</a></div>
    ${accountWarning && html`<div class="card pj-warn">⚠ A conta do agente está só nos settings do NetOps (<code>.claude/settings*.json</code>, bloco <code>env</code>). Sessões de projeto rodam em outra pasta e não a enxergam. Mova esse bloco <code>env</code> para <code>~/.claude/settings.json</code> do servidor (nível do usuário, como no VS Code). O console não copia o token para os projetos.</div>`}
    ${!showArch && active.length > 1 && html`<div class="help pj-hint">Segure e arraste ⠿ para mudar a ordem (vale também na barra lateral).</div>`}
    ${list.length === 0
      ? html`<div class="card empty">${showArch ? "Nenhum projeto arquivado." : all.length
          ? "Todos os projetos estão arquivados." : "Nenhum projeto ainda. Crie um para abrir sessões do Claude Code numa pasta do servidor."}</div>`
      : list.map((p) => html`<${ProjectRow} key=${p.id} p=${p} drag=${showArch ? null : drag} onDelete=${setDel} />`)}
    ${del && html`<${ConfirmDialog} title="Remover projeto" danger=${true}
      message=${`Remover “${del.name}” da lista? A pasta e as conversas NÃO são apagadas.`}
      onConfirm=${() => removeProject(del)} onClose=${() => setDel(null)} />`}
  </div>`;
}

// Arquivos da pasta do projeto (mesmo gerenciador do menu Arquivos, preso à pasta).
// URL: #projects/<id>/files?path=<pasta>&open=<arquivo>&q=&sort=&hidden=0
function ProjectFilesPage({ id, r }) {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { setInfo(null); setErr("");
    api.get(`/files/info?src=${encodeURIComponent("project:" + id)}`).then(setInfo).catch((e) => setErr(errText(e, "Falha ao abrir os arquivos"))); }, [id]);
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
    <div class="pj-head"><a class="btn" href=${"#projects/" + id}>← Projeto</a><h2>Arquivos do projeto</h2>
      ${info && html`<span class="mono help">${info.root}</span>`}</div>
    ${err ? html`<div class="err">${err}</div>` : !info ? html`<div class="help">Abrindo…</div>`
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
  if (proj === null) return html`<div class="card">Projeto '${id}' não encontrado. <a href="#projects">Voltar aos projetos</a></div>`;
  if (!proj) return html`<div class="help">Carregando…</div>`;

  async function commitRename() {
    const v = (renaming || "").trim(); setRenaming(null);
    if (!v || v === proj.name) return;
    try { setProj(await api.patch(`/projects/${encodeURIComponent(id)}`, { name: v })); changed(); toast.ok("Projeto renomeado"); }
    catch (e) { toast.err(errText(e, "Falha ao renomear")); }
  }
  async function setTrusted(v) {
    try { setProj(await api.patch(`/projects/${encodeURIComponent(id)}`, { trusted: v })); changed();
      toast.ok(v ? "Pasta marcada como confiável (vale nas próximas sessões)" : "Projeto em modo restrito (vale nas próximas sessões)"); }
    catch (e) { toast.err(errText(e, "Falha ao alterar a confiança")); }
  }
  async function remove() {
    try { await api.del(`/projects/${encodeURIComponent(id)}`); changed(); toast.ok("Projeto removido"); navigate("#projects"); }
    catch (e) { toast.err(errText(e, "Falha ao remover")); }
  }
  return html`<div>
    <div class="pj-head">
      ${renaming != null
        ? html`<input class="pj-rename" value=${renaming} autoFocus maxlength="80" aria-label="Renomear projeto"
            onInput=${(e) => setRenaming(e.target.value)} onBlur=${commitRename}
            onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); else if (e.key === "Escape") setRenaming(null); }} />`
        : html`<h2 title="Duplo clique para renomear" onDblClick=${() => setRenaming(proj.name)}>${proj.name}</h2>`}
      <span class="spacer"></span>
      ${proj.exists
        ? html`<a class="btn primary" href=${"#projects/" + id + "/new"}>＋ Nova sessão</a>`
        : html`<button class="primary" disabled=${true}>＋ Nova sessão</button>`}
      <a class="btn needs-projects-files" href=${"#projects/" + id + "/files"} title="Arquivos da pasta do projeto">📁 Arquivos</a>
      <button onClick=${async () => { await setArchived(proj, !proj.archived); load(); }}
        title=${proj.archived ? "Volta para a lista e a barra lateral" : "Esconde da lista e da barra lateral (só para você)"}>${proj.archived ? "↩ Desarquivar" : "🗄 Arquivar"}</button>
      ${proj.trusted
        ? html`<button class="needs-projects-manage" onClick=${() => setTrusted(false)}>Modo restrito</button>`
        : html`<button class="needs-projects-manage" onClick=${() => setConfirmTrust(true)}>Confiar na pasta…</button>`}
      <button class="needs-projects-manage" onClick=${() => setRenaming(proj.name)}>Renomear</button>
      <button class="danger needs-projects-manage" onClick=${() => setConfirmDel(true)}>Remover</button>
    </div>
    <div class="mono help pj-path" title="Pasta do servidor onde o agente roda">📁 ${proj.path} <${TrustBadge} p=${proj} /></div>
    ${!proj.trusted && html`<div class="help">Modo restrito: o agente ignora a configuração desta pasta (hooks, MCP, env, CLAUDE.md/AGENTS.md).</div>`}
    ${proj.exists && html`<${ConfigList} config=${proj.config} />`}
    ${!proj.exists && html`<div class="card">A pasta deste projeto não existe mais no servidor. Recrie a pasta ou remova o projeto (as conversas continuam guardadas).</div>`}
    <div class="pj-sess">
      <${SessionsList} project=${id} q=${r.params.q || ""} onQ=${(v) => r.setParams({ q: v })}
        onResume=${(sid) => navigate(claudeSessionHash(sid, id))} />
    </div>
    ${confirmTrust && html`<${ConfirmDialog} title="Confiar nesta pasta?" danger=${true}
      message=${`A configuração de ${proj.path} (${[...(proj.config.exec || []), ...(proj.config.info || [])].join(", ") || "nenhuma por enquanto"}) passa a ser carregada pelo agente e pode executar comandos como o usuário do servidor. Confie só em pastas cujo conteúdo você conhece.`}
      onConfirm=${() => setTrusted(true)} onClose=${() => setConfirmTrust(false)} />`}
    ${confirmDel && html`<${ConfirmDialog} title="Remover projeto" danger=${true}
      message=${`Remover “${proj.name}” da lista? A pasta e as conversas NÃO são apagadas.`}
      onConfirm=${remove} onClose=${() => setConfirmDel(false)} />`}
  </div>`;
}

export function ProjectsPage() {
  const r = useMenuRoute("projects");
  const [a, b] = r.segments;
  if (!a) return html`<${ProjectList} r=${r} />`;
  if (a === "new") return html`<${NewProject} />`;
  if (!validProjectId(a)) return html`<div class="card">Projeto '${a}' não encontrado. <a href="#projects">Voltar aos projetos</a></div>`;
  // #projects/<id>/<uuid|new>: a conversa (o provider liga o agente à pasta do projeto).
  // (id de conversa inválido também cai aqui: o provider mostra o erro e o link de volta)
  if (b === "files") return html`<${ProjectFilesPage} id=${a} r=${r} />`;
  if (b !== undefined) return html`<${ClaudeCodePage} />`;
  return html`<${ProjectHome} id=${a} r=${r} />`;
}
