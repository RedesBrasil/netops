// Projetos: nome + pasta do servidor. Cada projeto tem as próprias sessões do Claude Code (as conversas
// daquela pasta). URLs: #projects/new, #projects/<id>[?q=], #projects/<id>/new, #projects/<id>/<uuid>.
// O chat em si é a ClaudeCodePage; quem liga o agente à pasta é o ClaudeProvider (?project= no WebSocket).
import { html, useState, useEffect, toast, api } from "../ui.js";
import { Modal, Field, ConfirmDialog } from "../components.js";
import { useMenuRoute, navigate } from "../route.js";
import { ClaudeCodePage, SessionsList } from "./claude.js";
import { validProjectId, claudeSessionHash } from "../claude-sessions.js";

// 404 sem `error` = rota que o servidor não conhece (as nossas respostas sempre trazem `error`): o console
// está rodando uma versão anterior ao menu Projetos e precisa ser reiniciado.
const errText = (e, fallback) => (e && e.status === 404 && e.payload && !e.payload.error)
  ? "O servidor ainda está na versão antiga (sem Projetos). Reinicie o console com scripts/engine/ui/start.sh."
  : (e && e.payload && (e.payload.detail || e.payload.error)) || (e && e.message) || fallback;
const changed = () => window.dispatchEvent(new Event("netops:projects"));   // a sidebar recarrega a lista

// Lista de projetos para a sidebar (recarrega quando algo muda ou a janela volta ao foco).
export function useProjects(enabled) {
  const [list, setList] = useState([]);
  useEffect(() => {
    if (!enabled) { setList([]); return; }
    let alive = true;
    const load = () => api.get("/projects").then((d) => alive && setList(d.projects || [])).catch(() => {});
    load();
    addEventListener("netops:projects", load); addEventListener("focus", load);
    return () => { alive = false; removeEventListener("netops:projects", load); removeEventListener("focus", load); };
  }, [enabled]);
  return list;
}

// Seletor de pasta do servidor: só lista subpastas; dá para navegar ou digitar o caminho.
function FolderPicker({ start, onPick, onClose }) {
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
  return html`<${Modal} title="Escolher pasta do projeto" onClose=${onClose} wide=${true}>
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
    <div class="modal-actions">
      <button type="button" onClick=${onClose}>Cancelar</button>
      <button type="button" class="primary" disabled=${!data} onClick=${() => { onPick(data.path); onClose(); }}>Usar esta pasta</button>
    </div>
  <//>`;
}

function NewProject() {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [pick, setPick] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function save(e) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const p = await api.post("/projects", { name, path });
      changed(); toast.ok("Projeto criado");
      navigate("#projects/" + p.id);
    } catch (x) { setErr(errText(x, "Não foi possível criar o projeto.")); }
    finally { setBusy(false); }
  }
  // O seletor fica FORA do <form>: dentro dele, Enter e os botões do modal (type=submit por padrão)
  // submeteriam o formulário e criariam o projeto sem o usuário pedir.
  return html`<div>
  <form class="card pj-form" onSubmit=${save}>
    <h2>Novo projeto</h2>
    <p class="help">Um projeto é uma pasta do servidor. As sessões do Claude Code abertas nele rodam nessa pasta e ficam guardadas no projeto.</p>
    <${Field} label="Nome" htmlFor="pj-name">
      <input id="pj-name" value=${name} maxlength="80" autoFocus placeholder="Ex.: Meu site" onInput=${(e) => setName(e.target.value)} />
    <//>
    <${Field} label="Pasta do servidor" htmlFor="pj-path" hint="Caminho absoluto. Use “Escolher pasta…” para navegar.">
      <div class="pj-pick-path">
        <input id="pj-path" class="mono" value=${path} placeholder="/caminho/da/pasta" onInput=${(e) => setPath(e.target.value)} />
        <button type="button" onClick=${() => setPick(true)}>Escolher pasta…</button>
      </div>
    <//>
    ${err && html`<div class="err">${err}</div>`}
    <div class="modal-actions">
      <a class="btn" href="#projects">Cancelar</a>
      <button class="primary" type="submit" disabled=${busy || !name.trim() || !path.trim()}>Criar projeto</button>
    </div>
  </form>
  ${pick && html`<${FolderPicker} start=${path} onPick=${setPath} onClose=${() => setPick(false)} />`}
  </div>`;
}

function ProjectList() {
  const list = useProjects(true);
  return html`<div>
    <div class="pj-head"><h2>Projetos</h2><a class="btn primary" href="#projects/new">＋ Novo projeto</a></div>
    ${list.length === 0
      ? html`<div class="card empty">Nenhum projeto ainda. Crie um para abrir sessões do Claude Code numa pasta do servidor.</div>`
      : list.map((p) => html`<a key=${p.id} class="card pj-item" href=${"#projects/" + p.id}>
          <b>${p.name}</b><span class="mono help">${p.path}</span>
          ${!p.exists && html`<span class="badge warn">pasta não encontrada</span>`}
        </a>`)}
  </div>`;
}

function ProjectHome({ id, r }) {
  const [proj, setProj] = useState(undefined);   // undefined = carregando, null = não existe
  const [renaming, setRenaming] = useState(null);
  const [confirmDel, setConfirmDel] = useState(false);
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
      <button onClick=${() => setRenaming(proj.name)}>Renomear</button>
      <button class="danger" onClick=${() => setConfirmDel(true)}>Remover</button>
    </div>
    <div class="mono help pj-path" title="Pasta do servidor onde o agente roda">📁 ${proj.path}</div>
    ${!proj.exists && html`<div class="card">A pasta deste projeto não existe mais no servidor. Recrie a pasta ou remova o projeto (as conversas continuam guardadas).</div>`}
    <div class="pj-sess">
      <${SessionsList} project=${id} q=${r.params.q || ""} onQ=${(v) => r.setParams({ q: v })}
        onResume=${(sid) => navigate(claudeSessionHash(sid, id))} />
    </div>
    ${confirmDel && html`<${ConfirmDialog} title="Remover projeto" danger=${true}
      message=${`Remover “${proj.name}” da lista? A pasta e as conversas NÃO são apagadas.`}
      onConfirm=${remove} onClose=${() => setConfirmDel(false)} />`}
  </div>`;
}

export function ProjectsPage() {
  const r = useMenuRoute("projects");
  const [a, b] = r.segments;
  if (!a) return html`<${ProjectList} />`;
  if (a === "new") return html`<${NewProject} />`;
  if (!validProjectId(a)) return html`<div class="card">Projeto '${a}' não encontrado. <a href="#projects">Voltar aos projetos</a></div>`;
  // #projects/<id>/<uuid|new>: a conversa (o provider liga o agente à pasta do projeto).
  // (id de conversa inválido também cai aqui: o provider mostra o erro e o link de volta)
  if (b !== undefined) return html`<${ClaudeCodePage} />`;
  return html`<${ProjectHome} id=${a} r=${r} />`;
}
