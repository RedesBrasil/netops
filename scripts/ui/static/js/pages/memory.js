// Memória: USER.md, MEMORY.md, learned-patterns.yaml e lições (append-only).
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError, Tabs } from "../ui.js";
import { ResourceTable, Field, MarkdownEditor, Modal, EnumSelect } from "../components.js";

export function MemoryPage() {
  const [tab, setTab] = useState("user");
  const [creatingPattern, setCreatingPattern] = useState(false);
  const [creatingLesson, setCreatingLesson] = useState(false);
  const tabs = [
    { key: "user", label: "USER.md" }, { key: "notes", label: "MEMORY.md" },
    { key: "patterns", label: "Padrões" }, { key: "lessons", label: "Lições" },
  ];
  const actions = tab === "patterns"
    ? html`<button class="primary sm" onClick=${() => setCreatingPattern(true)}>+ Padrão</button>`
    : tab === "lessons"
    ? html`<button class="primary sm" onClick=${() => setCreatingLesson(true)}>+ Nova lição</button>`
    : null;
  function changeTab(k) { setCreatingPattern(false); setCreatingLesson(false); setTab(k); }
  return html`<div>
    <div class="page-title"><h1>Memória</h1></div>
    <${Tabs} tabs=${tabs} active=${tab} onChange=${changeTab} actions=${actions} />
    ${tab === "user" && html`<${MdFile} which="user" />`}
    ${tab === "notes" && html`<${MdFile} which="notes" />`}
    ${tab === "patterns" && html`<${Patterns} creating=${creatingPattern} onCreateClose=${() => setCreatingPattern(false)} />`}
    ${tab === "lessons" && html`<${Lessons} creating=${creatingLesson} onCreateClose=${() => setCreatingLesson(false)} />`}
  </div>`;
}

function MdFile({ which }) {
  const res = useResource(`/memory/${which}`, [which]);
  const [text, setText] = useState(null);
  const [rev, setRev] = useState(null);
  useEffect(() => { if (res.data) { setText(res.data.text); setRev(res.data.rev); } }, [res.data]);
  if (res.loading || text === null) return html`<${Spinner} />`;
  async function save() {
    try { const r = await api.put(`/memory/${which}`, { text }, rev); setRev(r.rev); toast.ok("Salvo"); }
    catch (e) { handleError(e); }
  }
  return html`<div>
    <${MarkdownEditor} value=${text} onChange=${setText} tokenBudget=${800} />
    <div style="margin-top:12px"><button class="primary" onClick=${save}>Salvar</button></div>
  </div>`;
}

function Patterns({ creating, onCreateClose }) {
  const res = useResource("/memory/patterns");
  const [editing, setEditing] = useState(null);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { patterns, rev } = res.data;
  const cols = [
    { key: "id", label: "ID", render: (r) => html`<b>${r.id}</b>` },
    { key: "vendor", label: "Vendor", render: (r) => html`<${Badge}>${r.vendor || "—"}<//>` },
    { key: "tipo", label: "Tipo", render: (r) => r.tipo || "—" },
    { key: "padrao", label: "Padrão", render: (r) => r.padrao },
  ];
  return html`<div>
    <${ResourceTable} columns=${cols} rows=${patterns.map((p) => ({ ...p, _key: p.id }))}
      onRowClick=${(r) => setEditing(r)}
      actions=${(r) => html`<button class="sm danger" onClick=${async () => { try { await api.del(`/memory/patterns/${r.id}`, rev); toast.ok("Removido"); res.reload(); } catch (e) { handleError(e); } }}>Excluir</button>`}
      empty="Nenhum padrão consolidado." />
    ${editing && html`<${PatternForm} pattern=${editing} rev=${rev}
        onClose=${() => setEditing(null)} onSaved=${() => { setEditing(null); res.reload(); }} />`}
    ${creating && html`<${PatternForm} pattern=${{ __new: true }} rev=${rev}
        onClose=${onCreateClose} onSaved=${() => { onCreateClose(); res.reload(); }} />`}
  </div>`;
}

function PatternForm({ pattern, rev, onClose, onSaved }) {
  const isNew = !!pattern.__new;
  const [f, setF] = useState({ id: pattern.id || "", vendor: pattern.vendor || "general",
    tipo: pattern.tipo || "operational", padrao: pattern.padrao || "", aplicar: pattern.aplicar || "" });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  async function save() {
    try {
      if (isNew) {
        await api.post("/memory/patterns", f, rev);
      } else {
        let curRev = rev;
        if (f.id !== pattern.id) {                          // renomeia o id primeiro
          curRev = (await api.post(`/memory/patterns/${pattern.id}/rename`, { to: f.id }, curRev)).rev;
        }
        await api.put(`/memory/patterns/${f.id}`, f, curRev);
      }
      toast.ok("Padrão salvo"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? "Novo padrão" : `Editar ${pattern.id}`} onClose=${onClose}>
    <${Field} label=${isNew ? "ID (kebab-case)" : "ID (alterar = renomear)"}>
      <input value=${f.id} onInput=${(e) => set("id", e.target.value)} /><//>
    <div class="row">
      <${Field} label="Vendor"><input value=${f.vendor} onInput=${(e) => set("vendor", e.target.value)} /><//>
      <${Field} label="Tipo"><${EnumSelect} value=${f.tipo} options=${["connection-quirk", "vendor-quirk", "operational", "error"]} onChange=${(v) => set("tipo", v)} /><//>
    </div>
    <${Field} label="Padrão (o fato)"><textarea value=${f.padrao} onInput=${(e) => set("padrao", e.target.value)}></textarea><//>
    <${Field} label="Aplicar (como agir)"><textarea value=${f.aplicar} onInput=${(e) => set("aplicar", e.target.value)}></textarea><//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Salvar</button></div>
  <//>`;
}

function Lessons({ creating, onCreateClose }) {
  const res = useResource("/memory/lessons");
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const estadoBadge = (e) => e === "ativo" ? html`<${Badge} kind="ok">ativo<//>`
    : e === "archived" ? html`<${Badge}>arquivado<//>` : html`<${Badge} kind="warn">stale<//>`;
  async function transition(file, estado) {
    try {
      const cur = await api.get(`/memory/lessons/${file}`);
      await api.patch(`/memory/lessons/${file}/estado`, { estado }, cur.rev);
      toast.ok(`Estado → ${estado}`); res.reload();
    } catch (e) { handleError(e); }
  }
  const cols = [
    { key: "id", label: "Lição", render: (r) => html`<b>${r.id || r.file}</b><div class="help">${r.file}</div>` },
    { key: "vendor", label: "Vendor", render: (r) => r.vendor || "—" },
    { key: "licao", label: "Lição", render: (r) => html`<div>${r.licao}</div>` },
    { key: "estado", label: "Estado", render: (r) => estadoBadge(r.estado) },
  ];
  return html`<div>
    <div class="help" style="margin-bottom:8px">Lições são <b>append-only</b> (constituição §II): nunca apagadas, só mudam de estado.</div>
    <${ResourceTable} columns=${cols} rows=${res.data.lessons.map((l) => ({ ...l, _key: l.file }))}
      actions=${(r) => html`
        <button class="sm" onClick=${() => transition(r.file, "ativo")}>ativo</button>
        <button class="sm" onClick=${() => transition(r.file, "stale")}>stale</button>
        <button class="sm" onClick=${() => transition(r.file, "archived")}>arquivar</button>`}
      empty="Nenhuma lição registrada." />
    ${creating && html`<${LessonForm} onClose=${onCreateClose} onSaved=${() => { onCreateClose(); res.reload(); }} />`}
  </div>`;
}

function LessonForm({ onClose, onSaved }) {
  const [f, setF] = useState({ slug: "", tipo: "operational", vendor: "general", gatilho: "", licao: "", correcao: "" });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  async function save() {
    try { const r = await api.post("/memory/lessons", f); toast.ok(`Lição criada: ${r.file}`); onSaved(); }
    catch (e) { handleError(e); }
  }
  return html`<${Modal} title="Nova lição" onClose=${onClose}>
    <div class="row">
      <${Field} label="Slug (kebab-case)"><input value=${f.slug} onInput=${(e) => set("slug", e.target.value)} /><//>
      <${Field} label="Vendor"><input value=${f.vendor} onInput=${(e) => set("vendor", e.target.value)} /><//>
    </div>
    <${Field} label="Tipo"><${EnumSelect} value=${f.tipo} options=${["connection-quirk", "vendor-quirk", "operational", "error"]} onChange=${(v) => set("tipo", v)} /><//>
    <${Field} label="Gatilho"><textarea value=${f.gatilho} onInput=${(e) => set("gatilho", e.target.value)}></textarea><//>
    <${Field} label="Lição"><textarea value=${f.licao} onInput=${(e) => set("licao", e.target.value)}></textarea><//>
    <${Field} label="Correção"><textarea value=${f.correcao} onInput=${(e) => set("correcao", e.target.value)}></textarea><//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
  <//>`;
}
