// Explorador de arquivos (estilo painel SFTP do MobaXterm): barra de ícones, caminho, lista de pastas/arquivos.
// Usado em dois lugares com a MESMA API (/api/files/*, routers/files.py):
//   - menu Arquivos (#files?path=/etc)          src="local"  — este servidor;
//   - painel ao lado do terminal de host         src=<token>  — SFTP sobre a conexão SSH do terminal.
// Lista própria (não é DataTable): exceção registrada em core/rules/tabelas-console.md.
// Estado de navegação (path, q, sort, hidden, open) é CONTROLADO por quem usa (URL no menu Arquivos).
import { html, useState, useEffect, useRef, useMemo, api, toast, Modal } from "./ui.js";
import { CodeTextEditor } from "./components.js";
import { authToken } from "./api.js";
import {
  normPath, joinPath, parentPath, baseName, crumbs, formatSize, formatDate, sortEntries, filterEntries,
  nextSelection, modeToOctal, octalToBits, bitsToOctal, fileKind, topNames, validName,
} from "./files-core.js";

const CHUNK = 8 * 1024 * 1024;
const enc = encodeURIComponent;

// Área de transferência compartilhada entre os exploradores abertos na mesma aba.
let CLIP = null;   // { src, op: "copy"|"move", paths: [] }
const clipSubs = new Set();
function setClip(v) { CLIP = v; clipSubs.forEach((f) => f(v)); }
function useClip() {
  const [c, setC] = useState(CLIP);
  useEffect(() => { clipSubs.add(setC); return () => clipSubs.delete(setC); }, []);
  return c;
}

/* ------------- pasta de destino dos downloads (lembrada no navegador) ------------- */
// O navegador não deixa gravar na raiz de Downloads; o usuário escolhe UMA vez uma pasta (ex.: Downloads\NetOps)
// e o "handle" fica no IndexedDB: os próximos downloads de pasta vão direto para lá (como o MobaXterm).
function idb(mode, fn) {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open("netops-files", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("kv");
    r.onerror = () => reject(r.error);
    r.onsuccess = () => {
      let tx, req;
      try { tx = r.result.transaction("kv", mode); req = fn(tx.objectStore("kv")); }
      catch (e) { r.result.close(); return reject(e); }    // ex.: objeto não clonável
      tx.oncomplete = () => { resolve(req && req.result); r.result.close(); };
      tx.onerror = () => reject(tx.error);
    };
  });
}
export const downloadDir = {
  get: () => idb("readonly", (st) => st.get("download-dir")).catch(() => null),
  set: (h) => idb("readwrite", (st) => st.put(h, "download-dir")).catch(() => {}),
  clear: () => idb("readwrite", (st) => st.delete("download-dir")).catch(() => {}),
};

/* ------------------------------- ícones -------------------------------- */
const ICON_COLORS = {
  dir: "#e8b130", code: "#4aa3e0", conf: "#8e7cc3", text: "#93a1b1", archive: "#c0763a",
  image: "#3ec07f", disk: "#c0392b", key: "#d4a017", exec: "#1f9d57", file: "#93a1b1",
};
export function FileIcon({ entry, size = 18 }) {
  const kind = fileKind(entry);
  const c = ICON_COLORS[kind] || ICON_COLORS.file;
  const link = entry.type === "link";
  const body = kind === "dir"
    ? html`<path d="M2 5.5A1.5 1.5 0 0 1 3.5 4h4.2l1.6 1.8h7.2A1.5 1.5 0 0 1 18 7.3v8.2a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 2 15.5z" fill=${c} />
           <path d="M2 8h16v7.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 2 15.5z" fill=${c} opacity="0.75" />`
    : html`<path d="M5 2h7l4 4v11.5a.5.5 0 0 1-.5.5h-10.5a.5.5 0 0 1-.5-.5V2.5A.5.5 0 0 1 5 2z" fill="none" stroke=${c} stroke-width="1.4" />
           <path d="M12 2v4h4" fill="none" stroke=${c} stroke-width="1.4" />
           ${kind !== "file" && html`<rect x="6.5" y="10" width="7" height="5" rx="1" fill=${c} opacity="0.85" />`}`;
  return html`<svg class="fm-ico" width=${size} height=${size} viewBox="0 0 20 20" aria-hidden="true">${body}
    ${link && html`<path d="M3 19l5-5m-3 0h3v3" stroke="#4aa3e0" stroke-width="1.8" fill="none" />`}</svg>`;
}

// Ícones da barra (traço, estilo Feather) — não dependem de fonte de emoji.
const TOOL_PATHS = {
  up: "M12 19V5M5 12l7-7 7 7",
  refresh: "M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6",
  home: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  mkdir: "M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 10v6M9 13h6",
  touch: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M12 12v6M9 15h6",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  updir: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 17v-6M9 14l3-3 3 3",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  cut: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12",
  paste: "M9 4h6v3H9zM9 5H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-3",
  rename: "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
  chmod: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  del: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  files: "M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
};
export function ToolIcon({ name, size = 16 }) {
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${TOOL_PATHS[name]} /></svg>`;
}

/* -------------------------- upload (em partes) -------------------------- */
function putChunk(url, blob, onProgress, xhrRef) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    xhrRef.current = x;
    x.open("PUT", url);
    const a = authToken(); if (a) x.setRequestHeader("X-Netops-Session", a);
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.upload.onprogress = (e) => onProgress(e.loaded);
    x.onload = () => {
      let body = null; try { body = JSON.parse(x.responseText); } catch (e) {}
      if (x.status >= 200 && x.status < 300) resolve(body);
      else reject(Object.assign(new Error(body?.detail || body?.error || `HTTP ${x.status}`), { status: x.status, body }));
    };
    x.onerror = () => reject(new Error("falha de rede no upload"));
    x.onabort = () => reject(Object.assign(new Error("cancelado"), { aborted: true }));
    x.send(blob);
  });
}

function uid() {
  const a = new Uint8Array(12); crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

// Lê o que foi arrastado do computador: arquivos e PASTAS (recursivo), com o caminho relativo.
async function readDrop(dt) {
  const files = [], dirs = [];
  const items = [...(dt.items || [])].map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null));
  if (!items.some(Boolean)) {
    for (const f of dt.files || []) files.push({ file: f, rel: f.name });
    return { files, dirs };
  }
  const readAll = (reader) => new Promise((res, rej) => {
    const out = [];
    const step = () => reader.readEntries((batch) => { if (!batch.length) res(out); else { out.push(...batch); step(); } }, rej);
    step();
  });
  async function walk(entry, prefix) {
    const rel = prefix ? prefix + "/" + entry.name : entry.name;
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      files.push({ file, rel });
    } else if (entry.isDirectory) {
      dirs.push(rel);
      for (const child of await readAll(entry.createReader())) await walk(child, rel);
    }
  }
  for (const e of items) if (e) await walk(e, "");
  return { files, dirs };
}

/* ------------------------------ diálogos ------------------------------- */
function NameDialog({ title, label, initial = "", ok = "OK", onOk, onClose }) {
  const [v, setV] = useState(initial);
  const [err, setErr] = useState("");
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    el.focus();
    const dot = initial.lastIndexOf(".");
    el.setSelectionRange(0, dot > 0 ? dot : initial.length);
  }, []);
  async function submit(e) {
    e && e.preventDefault();
    const m = validName(v); if (m) return setErr(m);
    try { await onOk(v.trim()); onClose(); } catch (ex) { setErr(ex.message || String(ex)); }
  }
  return html`<${Modal} title=${title} onClose=${onClose}>
    <form onSubmit=${submit}>
      <label class="fm-label">${label}<input ref=${ref} value=${v} onInput=${(e) => { setV(e.target.value); setErr(""); }} /></label>
      ${err && html`<div class="err">${err}</div>`}
      <div class="modal-actions"><button type="button" onClick=${onClose}>Cancelar</button><button class="primary" type="submit">${ok}</button></div>
    </form>
  <//>`;
}

// Copia texto: API moderna (HTTPS/localhost) ou, em HTTP puro, o textarea + execCommand de reserva.
export async function copyText(text) {
  try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; } } catch (e) {}
  try {
    const t = document.createElement("textarea");
    t.value = text; t.setAttribute("readonly", ""); t.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(t); t.select();
    const ok = document.execCommand("copy"); t.remove(); return ok;
  } catch (e) { return false; }
}

function DeleteDialog({ paths, entries, onOk, onClose }) {
  const single = paths.length === 1;
  const expected = single ? baseName(paths[0]) : String(paths.length);
  const [v, setV] = useState("");
  const [busy, setBusy] = useState(false);
  const dirs = entries.filter((e) => e.is_dir && e.type !== "link").length;
  const [copied, setCopied] = useState(false);
  const inputRef = useRef(null);
  async function copyExpected() {
    const ok = await copyText(expected);
    setCopied(ok);
    if (!ok) toast.err("Não consegui copiar; digite o nome.");
    inputRef.current?.focus();
  }
  async function go(e) {
    e && e.preventDefault();
    if (v.trim() !== expected) return;
    setBusy(true);
    try { await onOk(); onClose(); } finally { setBusy(false); }
  }
  return html`<${Modal} title=${single ? "Apagar de vez?" : `Apagar ${paths.length} itens de vez?`} onClose=${onClose}>
    <form onSubmit=${go}>
      <p>Exclusão <b>definitiva</b> (sem lixeira)${dirs ? html`, incluindo <b>todo o conteúdo</b> de ${dirs} pasta(s)` : ""}.</p>
      <ul class="fm-del-list">${paths.slice(0, 12).map((p) => html`<li class="mono" key=${p}>${p}</li>`)}
        ${paths.length > 12 && html`<li>… e mais ${paths.length - 12}</li>`}</ul>
      <div class="fm-label">Para confirmar, digite ${single ? "o nome" : "a quantidade"}
        <button type="button" class="fm-copy" title="Clique para copiar e depois cole no campo abaixo" onClick=${copyExpected}>
          <span class="mono">${expected}</span> <${ToolIcon} name="copy" size=${14} /> <span class="fm-copy-txt">${copied ? "copiado!" : "copiar"}</span></button></div>
      <label class="fm-label">
        <input ref=${inputRef} autoFocus value=${v} onInput=${(e) => setV(e.target.value)} /></label>
      <div class="modal-actions"><button type="button" onClick=${onClose}>Cancelar</button>
        <button class="danger" type="submit" disabled=${busy || v.trim() !== expected}>${busy ? "Apagando…" : "Apagar de vez"}</button></div>
    </form>
  <//>`;
}

function ChmodDialog({ entry, path, onOk, onClose }) {
  const [oct, setOct] = useState(modeToOctal(entry.mode));
  const [err, setErr] = useState("");
  const bits = octalToBits(oct);
  const flip = (i) => { const b = [...bits]; b[i] = !b[i]; setOct(bitsToOctal(b, oct)); };
  const who = ["Dono", "Grupo", "Outros"], what = ["ler", "gravar", "executar"];
  async function go(e) {
    e && e.preventDefault();
    if (!/^[0-7]{3,4}$/.test(oct)) return setErr("Use 3 ou 4 dígitos octais (ex.: 644, 0755).");
    try { await onOk(oct); onClose(); } catch (ex) { setErr(ex.message || String(ex)); }
  }
  return html`<${Modal} title="Permissões" onClose=${onClose}>
    <form onSubmit=${go}>
      <p class="mono">${path}</p>
      <p class="help">Dono: <b>${entry.owner || "?"}</b> · Grupo: <b>${entry.group || "?"}</b> · atual: <span class="mono">${entry.perms}</span></p>
      <div class="fm-perm-grid">
        <span></span>${what.map((w) => html`<b key=${w}>${w}</b>`)}
        ${who.map((w, r) => html`<b key=${w}>${w}</b>${[0, 1, 2].map((c) => html`<input type="checkbox" key=${w + c}
            checked=${bits[r * 3 + c]} onChange=${() => flip(r * 3 + c)} />`)}`)}
      </div>
      <label class="fm-label">Octal<input class="mono" value=${oct} onInput=${(e) => { setOct(e.target.value.trim()); setErr(""); }} /></label>
      ${err && html`<div class="err">${err}</div>`}
      <div class="modal-actions"><button type="button" onClick=${onClose}>Cancelar</button><button class="primary" type="submit">Aplicar</button></div>
    </form>
  <//>`;
}

function ConflictDialog({ names, onChoice, onClose }) {
  return html`<${Modal} title="Já existe na pasta" onClose=${() => { onChoice("cancel"); onClose(); }}>
    <p>${names.length === 1 ? html`<b class="mono">${names[0]}</b> já existe.` : html`${names.length} itens já existem:`}</p>
    ${names.length > 1 && html`<ul class="fm-del-list">${names.slice(0, 10).map((n) => html`<li class="mono" key=${n}>${n}</li>`)}
      ${names.length > 10 && html`<li>… e mais ${names.length - 10}</li>`}</ul>`}
    <div class="modal-actions">
      <button onClick=${() => { onChoice("cancel"); onClose(); }}>Cancelar</button>
      <button onClick=${() => { onChoice("skip"); onClose(); }}>Pular existentes</button>
      <button class="danger" onClick=${() => { onChoice("overwrite"); onClose(); }}>Substituir</button>
    </div>
  <//>`;
}

/* ------------------------------- editor -------------------------------- */
export function FileEditor({ src, path, onClose, onSaved, onDownload }) {
  const [doc, setDoc] = useState(null);       // {content, mtime, size, binary, encoding}
  const [text, setTextState] = useState("");
  const textRef = useRef("");          // Ctrl+S logo após digitar: salva o texto ATUAL, não o do último render
  const setText = (v) => { textRef.current = v; setTextState(v); };
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const dirty = doc && !doc.binary && text !== doc.content;

  async function load() {
    setErr(""); setDoc(null); setConflict(false);
    try {
      const d = await api.get(`/files/read?src=${enc(src)}&path=${enc(path)}`);
      setDoc(d); setText(d.content || "");
    } catch (e) { setErr(e.message || String(e)); }
  }
  useEffect(() => { load(); }, [src, path]);

  async function save(force = false) {
    if (!doc || busy) return;
    setBusy(true);
    try {
      const content = textRef.current;
      const body = { src, path, content };
      if (!force) Object.assign(body, { mtime: doc.mtime, size: doc.size });
      const r = await api.put("/files/write", body);
      setDoc({ ...doc, content, mtime: r.mtime, size: r.size });
      setConflict(false);
      toast.ok(`Salvo: ${baseName(path)}`);
      onSaved && onSaved();
    } catch (e) {
      if (e.status === 409 && e.payload?.error === "changed") setConflict(true);
      else toast.err(e.message || String(e));
    } finally { setBusy(false); }
  }
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const k = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveRef.current(); } };
    addEventListener("keydown", k); return () => removeEventListener("keydown", k);
  }, []);
  const close = () => { if (!dirty || confirm("Descartar as alterações não salvas?")) onClose(); };

  return html`<${Modal} title=${html`<span class="mono">${path}</span>`} onClose=${close} wide cls="fm-editor-modal">
    ${err && html`<div class="err">${err}</div>`}
    ${!doc && !err && html`<p class="help">Carregando…</p>`}
    ${doc && doc.binary && html`<p>Arquivo binário (${formatSize(doc.size)}) — não abre no editor.</p>`}
    ${doc && !doc.binary && html`
      <p class="help">${formatSize(doc.size)} · ${doc.encoding}${doc.encoding !== "utf-8" ? " (salvar converte para UTF-8)" : ""} · Ctrl+S salva</p>
      <${CodeTextEditor} value=${text} onChange=${setText} name=${baseName(path)} />`}
    ${conflict && html`<div class="err">O arquivo mudou no disco desde que foi aberto.
      <button class="sm" onClick=${load}>Recarregar (perde a edição)</button>
      <button class="sm danger" onClick=${() => save(true)}>Sobrescrever mesmo assim</button></div>`}
    <div class="modal-actions">
      <button onClick=${() => onDownload([path])}>Baixar</button>
      <span class="spacer"></span>
      <button onClick=${close}>Fechar</button>
      ${doc && !doc.binary && html`<button class="primary" disabled=${!dirty || busy} onClick=${() => save()}>${busy ? "Salvando…" : "Salvar"}</button>`}
    </div>
  <//>`;
}

/* ------------------------------ explorador ----------------------------- */
const SORTS = [["name", "Nome"], ["size", "Tamanho"], ["mtime", "Modificado"]];

// state: {path, q, sort, hidden(bool), open(caminho do arquivo aberto no editor)}; setState(patch, {push})
export function FileBrowser({ src = "local", state, setState, compact = false, home = "/", title = "" }) {
  const path = normPath(state.path || home);
  const sort = state.sort || "name";
  const showHidden = state.hidden !== false;
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState([]);
  const [anchor, setAnchor] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [menu, setMenu] = useState(null);         // {x, y}
  const [dropOn, setDropOn] = useState(null);     // "" = pasta atual; nome = pasta da lista
  const [up, setUp] = useState(null);             // progresso do upload
  const [editPath, setEditPath] = useState(false);
  const [pathInput, setPathInput] = useState(path);
  const xhrRef = useRef(null);
  const cancelRef = useRef(false);
  const listRef = useRef(null);
  const fileInput = useRef(null);
  const dirInput = useRef(null);
  const clip = useClip();
  const coarse = useMemo(() => typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches, []);

  async function load(p = path, { keepSel = false } = {}) {
    setLoading(true);
    try {
      const d = await api.get(`/files/list?src=${enc(src)}&path=${enc(p)}`);
      setData(d); setErr(null);
      if (!keepSel) { setSel([]); setAnchor(null); }
      else setSel((s) => s.filter((n) => d.entries.some((e) => e.name === n)));
    } catch (e) { setErr(e); setData(null); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(path); setPathInput(path); }, [src, path]);

  const entries = useMemo(() => sortEntries(filterEntries(data?.entries || [], { q: state.q, hidden: showHidden }), sort),
    [data, state.q, showHidden, sort]);
  const names = entries.map((e) => e.name);
  const byName = useMemo(() => Object.fromEntries((data?.entries || []).map((e) => [e.name, e])), [data]);
  const selEntries = sel.map((n) => byName[n]).filter(Boolean);
  const selPaths = selEntries.map((e) => joinPath(path, e.name));

  const go = (p) => setState({ path: normPath(p), q: "" }, { push: true });
  const goUp = () => { const pp = parentPath(path); if (pp) go(pp); };

  function open(entry) {
    const full = joinPath(path, entry.name);
    if (entry.is_dir) return go(full);
    if (entry.type === "other") return toast.info("Não é um arquivo comum (socket, dispositivo ou fifo).");
    if ((entry.type === "link" ? entry.target_size : entry.size) > 5 * 1024 * 1024) {
      if (confirm(`${entry.name} tem ${formatSize(entry.size)} — grande demais para o editor. Baixar?`)) download([full]);
      return;
    }
    setState({ open: full }, { push: true });
  }

  // Download SEM zip: arquivos saem um a um; pastas são recriadas numa pasta do PC escolhida pelo usuário
  // (File System Access API: Chrome/Edge em HTTPS ou localhost). Sem essa API, oferece .zip ou arquivos soltos.
  const [dl, setDl] = useState(null);   // progresso do download de pasta
  const dlCancel = useRef(false);
  const canPickDir = typeof window !== "undefined" && window.isSecureContext && "showDirectoryPicker" in window;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function linkFor(p) { return api.get(`/files/download-link?src=${enc(src)}&path=${enc(p)}`); }
  function clickLink(url, name) {
    const a = document.createElement("a");
    a.href = url; a.download = name; a.rel = "noopener";
    document.body.appendChild(a); a.click(); a.remove();
  }

  async function downloadZip(paths = selPaths) {
    if (!paths.length) return toast.info("Selecione o que baixar.");
    try {
      const qs = paths.map((p) => "path=" + enc(p)).join("&");
      const r = await api.get(`/files/download-link?src=${enc(src)}&${qs}`);
      clickLink(r.url, r.name);
      if (r.zip) toast.info(`Compactando e baixando ${r.name}…`);
    } catch (e) { toast.err(e.message || String(e)); }
  }

  async function downloadLoose(paths) {
    // Arquivos soltos (um download por arquivo). O navegador pode pedir 1 vez "permitir vários downloads".
    let n = 0;
    for (const p of paths) {
      try { const r = await linkFor(p); clickLink(r.url, baseName(p)); n++; }
      catch (e) { toast.err(`${baseName(p)}: ${e.message || e}`); }
      await sleep(350);
    }
    if (paths.length > 1) toast.info(`${n} download(s) iniciado(s). Se só veio 1, permita "vários downloads" no navegador.`);
  }

  async function downloadIntoDir(paths, dirHandle) {
    let plan;
    try { plan = await api.get(`/files/download-plan?src=${enc(src)}&${paths.map((p) => "path=" + enc(p)).join("&")}`); }
    catch (e) { return toast.err(e.message || String(e)); }
    const files = plan.items.filter((i) => !i.is_dir);
    const total = plan.bytes || 1;
    dlCancel.current = false;
    let done = 0, ok = 0, fail = 0;
    // Já existe "html" no destino? Salva como "html (2)" (não mistura com o download anterior).
    const rename = new Map();
    for (const top of [...new Set(plan.items.map((i) => i.rel.split("/")[0]))]) {
      let name = top, n = 1;
      for (;;) {
        let exists = false;
        try { await dirHandle.getDirectoryHandle(name); exists = true; } catch (e) {
          try { await dirHandle.getFileHandle(name); exists = true; } catch (e2) { /* livre */ }
        }
        if (!exists) break;
        n++; const dot = top.lastIndexOf(".");
        name = dot > 0 && !plan.items.find((i) => i.rel === top)?.is_dir ? `${top.slice(0, dot)} (${n})${top.slice(dot)}` : `${top} (${n})`;
      }
      rename.set(top, name);
    }
    for (const it of plan.items) { const [t, ...rest] = it.rel.split("/"); it.rel = [rename.get(t), ...rest].join("/"); }
    const tops = [...rename.values()];
    const dirCache = new Map([["", dirHandle]]);
    async function dirOf(rel) {
      if (dirCache.has(rel)) return dirCache.get(rel);
      const i = rel.lastIndexOf("/");
      const parent = await dirOf(i < 0 ? "" : rel.slice(0, i));
      const h = await parent.getDirectoryHandle(rel.slice(i + 1), { create: true });
      dirCache.set(rel, h); return h;
    }
    try {
      for (const d of plan.items.filter((i) => i.is_dir)) await dirOf(d.rel);
      for (let k = 0; k < files.length; k++) {
        if (dlCancel.current) break;
        const f = files[k];
        setDl({ name: f.rel, n: k + 1, of: files.length, pct: Math.round((done / total) * 100) });
        try {
          const i = f.rel.lastIndexOf("/");
          const dir = await dirOf(i < 0 ? "" : f.rel.slice(0, i));
          const fh = await dir.getFileHandle(f.rel.slice(i + 1), { create: true });
          const r = await linkFor(f.path);
          const res = await fetch(r.url);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const w = await fh.createWritable();
          const reader = res.body.getReader();
          for (;;) {
            const { value, done: end } = await reader.read();
            if (end) break;
            await w.write(value);
            done += value.length;
            if (dlCancel.current) { await reader.cancel(); break; }
          }
          await w.close(); ok++;
          setDl((x) => x && ({ ...x, pct: Math.min(100, Math.round((done / total) * 100)) }));
        } catch (e) { fail++; toast.err(`${f.rel}: ${e.message || e}`); }
      }
    } finally { setDl(null); }
    if (dlCancel.current) toast.info(`Download cancelado (${ok} arquivo(s) salvos).`);
    else if (!fail) toast.ok(`Baixado: ${dirHandle.name}/${tops.join(", ")} (${ok} arquivo(s)).`);
  }

  async function download(paths = selPaths) {
    if (!paths.length) return toast.info("Selecione o que baixar.");
    const info = paths.map((p) => byName[baseName(p)] && parentPath(p) === path ? byName[baseName(p)] : null);
    const hasDir = info.some((e) => e && e.is_dir);
    if (!hasDir) return downloadLoose(paths);
    if (!canPickDir) return setDialog({ kind: "nodir", paths });
    return pickDirAndDownload(paths);          // o clique em Baixar é o gesto que abre o seletor
  }

  // Sempre pergunta onde salvar (o usuário quer escolher a cada vez). A janela é do navegador/SO: não dá para
  // esconder Downloads nem trocar o texto do botão; ela só ABRE na última pasta usada (handle no IndexedDB).
  // O Chrome recusa a raiz de Downloads/Área de Trabalho/Documentos ("contém arquivos de sistema").
  async function pickDirAndDownload(paths) {
    const last = await downloadDir.get();
    toast.info("Crie ou selecione uma pasta para salvar os arquivos (a raiz de Downloads, Área de Trabalho e Documentos não é aceita pelo navegador).");
    let handle;
    try { handle = await window.showDirectoryPicker({ id: "netops-download", mode: "readwrite", startIn: last || "downloads" }); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      if (last) {   // a última pasta sumiu/foi movida: abre em Downloads
        try { handle = await window.showDirectoryPicker({ id: "netops-download", mode: "readwrite", startIn: "downloads" }); }
        catch (e2) { if (e2 && e2.name !== "AbortError") toast.err(`Não deu para usar essa pasta: ${e2.message || e2}`); return; }
      } else { toast.err(`Não deu para usar essa pasta: ${e.message || e}`); return; }
    }
    await downloadDir.set(handle);
    return downloadIntoDir(paths, handle);
  }

  // Sem seletor de pasta: arquivos soltos com o caminho no nome (pasta_sub_arquivo.txt).
  async function downloadFlat(paths) {
    let plan;
    try { plan = await api.get(`/files/download-plan?src=${enc(src)}&${paths.map((p) => "path=" + enc(p)).join("&")}`); }
    catch (e) { return toast.err(e.message || String(e)); }
    const files = plan.items.filter((i) => !i.is_dir);
    if (files.length > 50 && !confirm(`Isso inicia ${files.length} downloads separados. Continuar?`)) return;
    let n = 0;
    for (const f of files) {
      try { const r = await linkFor(f.path); clickLink(r.url, f.rel.split("/").join("_")); n++; }
      catch (e) { toast.err(`${f.rel}: ${e.message || e}`); }
      await sleep(350);
    }
    toast.info(`${n} download(s) iniciado(s).`);
  }

  function report(res, verb) {
    const bad = (res.results || []).filter((r) => !r.ok);
    if (!bad.length) return toast.ok(verb);
    toast.err(`${bad.length} falha(s): ${bad[0].error}${bad.length > 1 ? " …" : ""}`);
  }

  async function doDelete() {
    const res = await api.post("/files/delete", { src, paths: selPaths });
    report(res, `Apagado: ${selPaths.length} item(ns)`);
    load(path);
  }

  async function paste(dest = path) {
    if (!clip) return;
    if (clip.src !== src) return toast.info("A área de transferência é de outra origem (servidor × host). Baixe e envie o arquivo.");
    try {
      const res = await api.post("/files/paste", { src, op: clip.op, paths: clip.paths, dest });
      report(res, clip.op === "move" ? "Movido" : "Copiado");
      if (clip.op === "move") setClip(null);
      load(path, { keepSel: true });
    } catch (e) { toast.err(e.message || String(e)); }
  }

  async function moveInto(paths, destDir) {
    const real = paths.filter((p) => p !== destDir && parentPath(p) !== destDir);
    if (!real.length) return;
    try {
      const res = await api.post("/files/paste", { src, op: "move", paths: real, dest: destDir });
      report(res, `Movido para ${baseName(destDir)}`);
      load(path);
    } catch (e) { toast.err(e.message || String(e)); }
  }

  /* --------------------------- upload --------------------------- */
  async function startUpload(files, dirs = [], dest = path) {
    if (!files.length && !dirs.length) return;
    let existing = new Set();
    try { existing = new Set((await api.get(`/files/list?src=${enc(src)}&path=${enc(dest)}`)).entries.map((e) => e.name)); }
    catch (e) { return toast.err(e.message || String(e)); }
    const tops = topNames([...files, ...dirs.map((d) => ({ rel: d }))]);
    const clash = tops.filter((n) => existing.has(n));
    let mode = "overwrite";
    if (clash.length) {
      mode = await new Promise((res) => setDialog({ kind: "conflict", names: clash, onChoice: res }));
      if (mode === "cancel") return;
    }
    const skip = (rel) => mode === "skip" && clash.includes(rel.split("/")[0]);
    const todo = files.filter((f) => !skip(f.rel));
    const total = todo.reduce((s, f) => s + f.file.size, 0) || 1;
    cancelRef.current = false;
    let doneBytes = 0, ok = 0, fail = 0;
    setUp({ name: "", pct: 0, n: 0, of: todo.length });
    try {
      for (const d of dirs.filter((d) => !skip(d))) {
        try { await api.post("/files/mkdir", { src, path: joinPath(dest, d) }); } catch (e) { /* já existe: ok */ }
      }
      for (let i = 0; i < todo.length; i++) {
        if (cancelRef.current) break;
        const { file, rel } = todo[i];
        const target = joinPath(dest, rel);
        const id = uid();
        setUp({ name: rel, pct: Math.round((doneBytes / total) * 100), n: i + 1, of: todo.length });
        try {
          let off = 0;
          do {
            const blob = file.slice(off, off + CHUNK);
            const final = off + blob.size >= file.size;
            const url = `/api/files/upload?src=${enc(src)}&path=${enc(target)}&uid=${id}&offset=${off}`
              + `${final ? "&final=1" : ""}${mode === "overwrite" ? "&overwrite=1" : ""}`;
            await putChunk(url, blob, (loaded) => setUp((u) => u && ({ ...u, pct: Math.min(100, Math.round(((doneBytes + off + loaded) / total) * 100)) })), xhrRef);
            off += blob.size;
          } while (off < file.size);
          doneBytes += file.size; ok++;
        } catch (e) {
          if (e.aborted) { fetch(`/api/files/upload?src=${enc(src)}&path=${enc(target)}&uid=${id}`, { method: "DELETE", headers: { "X-Netops-Session": authToken() } }).catch(() => {}); break; }
          fail++; toast.err(`${rel}: ${e.message}`);
        }
      }
    } finally {
      setUp(null); xhrRef.current = null;
      load(path, { keepSel: true });
    }
    if (cancelRef.current) toast.info(`Upload cancelado (${ok} enviado(s)).`);
    else if (!fail) toast.ok(`Enviado: ${ok} arquivo(s)${dirs.length ? ` e ${dirs.length} pasta(s)` : ""}.`);
  }
  function cancelUpload() { cancelRef.current = true; try { xhrRef.current && xhrRef.current.abort(); } catch (e) {} }

  function pickFiles(e, isDir) {
    const list = [...e.target.files].map((f) => ({ file: f, rel: isDir ? (f.webkitRelativePath || f.name) : f.name }));
    e.target.value = "";
    startUpload(list);
  }

  /* ---------------------- arrastar e soltar ---------------------- */
  const INTERNAL = "application/x-netops-files";
  // Arrastar PARA FORA (para o Explorer/Área de Trabalho) = download. Chrome/Edge: "DownloadURL" leva 1 arquivo
  // por arraste; vários itens/pastas vão como .zip. O link (ticket de uso único) precisa existir JÁ no dragstart
  // (não dá para esperar a API), então é preparado ao selecionar ou passar o mouse sobre o item.
  const dragLinks = useRef(new Map());     // chave (caminhos) -> {url, name, zip, exp}
  const dragKey = (paths) => [...paths].sort().join("\n");
  async function prepareDrag(paths) {
    if (!paths.length) return;
    const k = dragKey(paths), hit = dragLinks.current.get(k);
    if (hit && (hit.pending || hit.exp > Date.now())) return;
    dragLinks.current.set(k, { pending: true });
    try {
      const r = await api.get(`/files/download-link?src=${enc(src)}&${paths.map((p) => "path=" + enc(p)).join("&")}`);
      dragLinks.current.set(k, { ...r, exp: Date.now() + 100000 });
    } catch (e) { dragLinks.current.delete(k); }
  }
  useEffect(() => { dragLinks.current.clear(); }, [src, path]);
  useEffect(() => {
    if (!sel.length) return;
    const t = setTimeout(() => prepareDrag(selPaths), 120);
    return () => clearTimeout(t);
  }, [sel.join("\n"), path, src]);
  const hoverTimer = useRef(null);
  function hoverRow(entry) {
    clearTimeout(hoverTimer.current);
    if (sel.includes(entry.name) || entry.type === "other") return;
    hoverTimer.current = setTimeout(() => prepareDrag([joinPath(path, entry.name)]), 200);
  }

  function onDragStartRow(e, entry) {
    const names2 = sel.includes(entry.name) ? sel : [entry.name];
    if (!sel.includes(entry.name)) { setSel([entry.name]); setAnchor(entry.name); }
    const paths = names2.map((n) => joinPath(path, n));
    e.dataTransfer.setData(INTERNAL, JSON.stringify({ src, paths }));
    const k = dragKey(paths), link = dragLinks.current.get(k);
    if (link && link.url && link.exp > Date.now()) {
      const name = String(link.name).replace(/:/g, "_");
      e.dataTransfer.setData("DownloadURL", `${link.zip ? "application/zip" : "application/octet-stream"}:${name}:${location.origin}${link.url}`);
      dragLinks.current.delete(k);           // ticket é de uso único: prepara outro para o próximo arraste
      setTimeout(() => prepareDrag(paths), 400);
    } else {
      prepareDrag(paths);
      toast.info("Preparando o download… arraste de novo para soltar no computador.");
    }
    e.dataTransfer.effectAllowed = "copyMove";
  }
  function onDragOver(e, target = "") {
    const t = e.dataTransfer.types || [];
    if (![...t].includes("Files") && ![...t].includes(INTERNAL)) return;
    e.preventDefault(); e.stopPropagation();
    if (dropOn !== target) setDropOn(target);
  }
  async function onDrop(e, target = "") {
    e.preventDefault(); e.stopPropagation(); setDropOn(null);
    const dest = target ? joinPath(path, target) : path;
    const internal = e.dataTransfer.getData(INTERNAL);
    if (internal) {
      try { const d = JSON.parse(internal); if (d.src === src && target) moveInto(d.paths, dest); } catch (err2) {}
      return;
    }
    if (up) return toast.info("Aguarde o upload em andamento terminar.");
    const { files, dirs } = await readDrop(e.dataTransfer);
    startUpload(files, dirs, dest);
  }

  /* --------------------------- seleção --------------------------- */
  function clickRow(e, entry) {
    setMenu(null);
    if (coarse && !e.ctrlKey && !e.shiftKey && !e.target.closest(".fm-check")) return open(entry);
    const r = nextSelection(names, sel, anchor, entry.name, { ctrl: e.ctrlKey || e.metaKey || !!e.target.closest(".fm-check"), shift: e.shiftKey });
    setSel(r.selected); setAnchor(r.anchor);
  }
  function contextRow(e, entry) {
    e.preventDefault(); e.stopPropagation();
    if (entry && !sel.includes(entry.name)) { setSel([entry.name]); setAnchor(entry.name); }
    if (!entry) { setSel([]); }
    const box = listRef.current?.closest(".fm")?.getBoundingClientRect() || { left: 0, top: 0 };
    setMenu({ x: e.clientX - box.left, y: e.clientY - box.top, empty: !entry });
  }

  const one = selEntries.length === 1 ? selEntries[0] : null;
  const actions = {
    open: () => one && open(one),
    download: () => download(),
    rename: () => one && setDialog({ kind: "rename", entry: one }),
    copy: () => selPaths.length && (setClip({ src, op: "copy", paths: selPaths }), toast.info(`${selPaths.length} item(ns) copiado(s) — cole em outra pasta (Ctrl+V).`)),
    cut: () => selPaths.length && (setClip({ src, op: "move", paths: selPaths }), toast.info(`${selPaths.length} item(ns) recortado(s) — cole em outra pasta (Ctrl+V).`)),
    paste: () => paste(),
    chmod: () => one && setDialog({ kind: "chmod", entry: one }),
    del: () => selPaths.length && setDialog({ kind: "delete" }),
    mkdir: () => setDialog({ kind: "mkdir" }),
    touch: () => setDialog({ kind: "touch" }),
    copyPath: () => { const t = one ? joinPath(path, one.name) : path; navigator.clipboard?.writeText(t).then(() => toast.ok("Caminho copiado.")).catch(() => prompt("Caminho:", t)); },
    refresh: () => load(path, { keepSel: true }),
  };

  function onKey(e) {
    if (e.target.closest("input, textarea")) return;
    const k = e.key, mod = e.ctrlKey || e.metaKey;
    if (k === "Enter" && one) { e.preventDefault(); actions.open(); }
    else if (k === "Backspace" || (k === "ArrowUp" && e.altKey)) { e.preventDefault(); goUp(); }
    else if (k === "Delete") { e.preventDefault(); actions.del(); }
    else if (k === "F2") { e.preventDefault(); actions.rename(); }
    else if (k === "F5") { e.preventDefault(); actions.refresh(); }
    else if (mod && k.toLowerCase() === "a") { e.preventDefault(); setSel(names); }
    else if (mod && k.toLowerCase() === "c") { e.preventDefault(); actions.copy(); }
    else if (mod && k.toLowerCase() === "x") { e.preventDefault(); actions.cut(); }
    else if (mod && k.toLowerCase() === "v") { e.preventDefault(); actions.paste(); }
    else if (k === "ArrowDown" || k === "ArrowUp") {
      e.preventDefault();
      const i = names.indexOf(anchor);
      const j = Math.max(0, Math.min(names.length - 1, i < 0 ? 0 : i + (k === "ArrowDown" ? 1 : -1)));
      if (names[j]) {
        const r = nextSelection(names, sel, anchor, names[j], { shift: e.shiftKey });
        setSel(r.selected); setAnchor(e.shiftKey ? anchor : names[j]);
        listRef.current?.querySelector(`[data-i="${j}"]`)?.scrollIntoView({ block: "nearest" });
      }
    }
  }
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    addEventListener("click", close); addEventListener("scroll", close, true);
    return () => { removeEventListener("click", close); removeEventListener("scroll", close, true); };
  }, [menu]);

  const canPaste = clip && clip.src === src;
  const btn = (label, icon, fn, dis = false, cls = "") => html`<button class=${"fm-btn " + cls} title=${label} aria-label=${label}
    disabled=${dis} onClick=${fn}><${ToolIcon} name=${icon} />${!compact && html`<span>${label}</span>`}</button>`;
  const sortBy = (k) => setState({ sort: sort === k ? "-" + k : k });
  const sortMark = (k) => (sort === k ? " ▲" : sort === "-" + k ? " ▼" : "");

  return html`<div class=${"fm" + (compact ? " fm-compact" : "")}>
    <div class="fm-toolbar">
      ${btn("Subir", "up", goUp, !parentPath(path))}
      ${btn("Atualizar", "refresh", actions.refresh)}
      ${btn("Início", "home", () => go(home))}
      <span class="fm-sep"></span>
      ${btn("Nova pasta", "mkdir", actions.mkdir)}
      ${btn("Novo arquivo", "touch", actions.touch)}
      ${btn("Enviar arquivos", "upload", () => fileInput.current?.click(), !!up)}
      ${btn("Enviar pasta", "updir", () => dirInput.current?.click(), !!up)}
      ${btn("Baixar", "download", () => download(), !sel.length)}
      <span class="fm-sep"></span>
      ${btn("Copiar", "copy", actions.copy, !sel.length)}
      ${btn("Recortar", "cut", actions.cut, !sel.length)}
      ${btn("Colar", "paste", actions.paste, !canPaste)}
      ${btn("Renomear", "rename", actions.rename, !one)}
      ${btn("Permissões", "chmod", actions.chmod, !one)}
      ${btn("Apagar", "del", actions.del, !sel.length, "fm-danger")}
      <input ref=${fileInput} type="file" multiple hidden onChange=${(e) => pickFiles(e, false)} />
      <input ref=${dirInput} type="file" multiple hidden webkitdirectory=${true} directory=${true} onChange=${(e) => pickFiles(e, true)} />
    </div>
    <div class="fm-pathbar">
      ${editPath
        ? html`<form class="fm-pathform" onSubmit=${(e) => { e.preventDefault(); setEditPath(false); go(pathInput.trim() || "/"); }}>
            <input class="mono" autoFocus value=${pathInput} onInput=${(e) => setPathInput(e.target.value)}
              onBlur=${() => { setEditPath(false); setPathInput(path); }} onKeyDown=${(e) => { if (e.key === "Escape") { setEditPath(false); setPathInput(path); } }} /></form>`
        : html`<div class="fm-crumbs" title="Clique no espaço vazio para digitar o caminho" onClick=${(e) => { if (!e.target.closest("a")) setEditPath(true); }}>
            ${crumbs(path).map((c, i) => html`<span key=${c.path}>${i > 1 ? html`<span class="fm-crumb-sep">/</span>` : ""}<a
              href="#" onClick=${(e) => { e.preventDefault(); go(c.path); }}>${c.name}</a></span>`)}
          </div>`}
      <input class="fm-filter" type="search" placeholder="Filtrar" value=${state.q || ""}
        onInput=${(e) => setState({ q: e.target.value })} />
      <label class="fm-hidden-tg" title="Mostrar arquivos ocultos (que começam com ponto)">
        <input type="checkbox" checked=${showHidden} onChange=${(e) => setState({ hidden: e.target.checked })} />${compact ? ".*" : "ocultos"}</label>
    </div>
    <div class="fm-head">
      <span class="fm-c-name" onClick=${() => sortBy("name")}>Nome${sortMark("name")}</span>
      <span class="fm-c-size" onClick=${() => sortBy("size")}>Tamanho${sortMark("size")}</span>
      <span class="fm-c-date" onClick=${() => sortBy("mtime")}>Modificado${sortMark("mtime")}</span>
      ${!compact && html`<span class="fm-c-perm">Permissões</span><span class="fm-c-own">Dono</span>`}
    </div>
    <div ref=${listRef} class=${"fm-list" + (dropOn === "" ? " fm-drop" : "")} tabIndex="0" onKeyDown=${onKey}
      onDragOver=${(e) => onDragOver(e, "")} onDragLeave=${(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDropOn(null); }}
      onDrop=${(e) => onDrop(e, "")} onContextMenu=${(e) => contextRow(e, null)}
      onClick=${(e) => { if (e.target === e.currentTarget) { setSel([]); setMenu(null); } }}>
      ${err && html`<div class="fm-msg err">${err.message || String(err)}${err.status === 404 && parentPath(path)
        ? html` <button class="sm" onClick=${goUp}>Voltar para ${parentPath(path)}</button>` : ""}</div>`}
      ${!err && !data && html`<div class="fm-msg help">Carregando…</div>`}
      ${data && parentPath(path) && html`<div class="fm-row fm-up" onDblClick=${goUp} onClick=${coarse ? goUp : undefined}
          onDragOver=${(e) => onDragOver(e, "..")} onDrop=${(e) => { e.preventDefault(); setDropOn(null);
            const d = e.dataTransfer.getData(INTERNAL); if (d) try { moveInto(JSON.parse(d).paths, parentPath(path)); } catch (x) {} }}>
        <span class="fm-c-name"><${FileIcon} entry=${{ name: "..", is_dir: true }} /> ..</span></div>`}
      ${data && !entries.length && html`<div class="fm-msg help">${state.q ? "Nada com esse filtro." : "Pasta vazia — arraste arquivos ou pastas para cá."}</div>`}
      ${entries.map((e, i) => html`<div key=${e.name} data-i=${i} draggable="true"
          class=${"fm-row" + (sel.includes(e.name) ? " sel" : "") + (dropOn === e.name ? " fm-drop" : "") + (e.name.startsWith(".") ? " fm-dot" : "")
            + (clip && clip.op === "move" && clip.src === src && clip.paths.includes(joinPath(path, e.name)) ? " fm-cut" : "")}
          title=${e.type === "link" ? `${e.name} → ${e.target || "?"}${e.broken ? " (quebrado)" : ""}` : e.name}
          onClick=${(ev) => clickRow(ev, e)} onDblClick=${() => open(e)} onContextMenu=${(ev) => contextRow(ev, e)}
          onDragStart=${(ev) => onDragStartRow(ev, e)} onMouseEnter=${() => hoverRow(e)}
          onDragOver=${e.is_dir ? (ev) => onDragOver(ev, e.name) : undefined}
          onDrop=${e.is_dir ? (ev) => onDrop(ev, e.name) : undefined}>
        <span class="fm-c-name">${coarse && html`<input type="checkbox" class="fm-check" checked=${sel.includes(e.name)} />`}<${FileIcon} entry=${e} />
          <span class="fm-name">${e.name}</span>${e.type === "link" && html`<span class="fm-link">→ ${e.target || ""}</span>`}</span>
        <span class="fm-c-size">${e.is_dir ? "" : formatSize(e.type === "link" ? e.target_size : e.size)}</span>
        <span class="fm-c-date">${formatDate(e.mtime)}</span>
        ${!compact && html`<span class="fm-c-perm mono">${e.perms}</span><span class="fm-c-own">${e.owner}${e.group && e.group !== e.owner ? ":" + e.group : ""}</span>`}
      </div>`)}
    </div>
    <div class="fm-status">
      ${dl && !up
        ? html`<span class="fm-progress"><span style=${`width:${dl.pct}%`}></span></span>
            <span class="fm-up-txt">Baixando ${dl.n}/${dl.of} · ${dl.pct}% · <span class="mono">${dl.name}</span></span>
            <button class="sm" onClick=${() => { dlCancel.current = true; }}>Cancelar</button>`
        : up
        ? html`<span class="fm-progress"><span style=${`width:${up.pct}%`}></span></span>
            <span class="fm-up-txt">Enviando ${up.n}/${up.of} · ${up.pct}% · <span class="mono">${up.name}</span></span>
            <button class="sm" onClick=${cancelUpload}>Cancelar</button>`
        : html`<span>${loading ? "Atualizando…" : `${entries.length} item(ns)`}${sel.length ? ` · ${sel.length} selecionado(s)` : ""}${
            clip && clip.src === src ? ` · ${clip.paths.length} na área de transferência (${clip.op === "move" ? "recortar" : "copiar"})` : ""}</span>
          ${title && html`<span class="spacer"></span><span class="help">${title}</span>`}`}
    </div>

    ${menu && html`<div class="fm-menu" style=${`left:${menu.x}px;top:${menu.y}px`} onClick=${(e) => e.stopPropagation()}>
      ${!menu.empty && one && html`<button onClick=${() => { setMenu(null); actions.open(); }}>${one.is_dir ? "Abrir" : "Abrir / editar"}</button>`}
      ${!menu.empty && html`<button onClick=${() => { setMenu(null); download(); }}>Baixar</button>
        <button onClick=${() => { setMenu(null); downloadZip(); }}>Baixar como .zip</button>`}
      ${!menu.empty && html`<hr /><button onClick=${() => { setMenu(null); actions.copy(); }}>Copiar</button>
        <button onClick=${() => { setMenu(null); actions.cut(); }}>Recortar</button>`}
      <button disabled=${!canPaste} onClick=${() => { setMenu(null); paste(one && one.is_dir && !menu.empty ? joinPath(path, one.name) : path); }}>
        Colar${one && one.is_dir && !menu.empty ? " dentro" : " aqui"}</button>
      ${!menu.empty && one && html`<hr /><button onClick=${() => { setMenu(null); actions.rename(); }}>Renomear</button>
        <button onClick=${() => { setMenu(null); actions.chmod(); }}>Permissões…</button>`}
      <button onClick=${() => { setMenu(null); actions.copyPath(); }}>Copiar caminho</button>
      <hr /><button onClick=${() => { setMenu(null); actions.mkdir(); }}>Nova pasta</button>
      <button onClick=${() => { setMenu(null); actions.touch(); }}>Novo arquivo</button>
      <button onClick=${() => { setMenu(null); fileInput.current?.click(); }}>Enviar arquivos…</button>
      ${!menu.empty && html`<hr /><button class="fm-danger" onClick=${() => { setMenu(null); actions.del(); }}>Apagar…</button>`}
    </div>`}

    ${dialog?.kind === "mkdir" && html`<${NameDialog} title="Nova pasta" label="Nome" ok="Criar" onClose=${() => setDialog(null)}
      onOk=${async (n) => { await api.post("/files/mkdir", { src, path: joinPath(path, n) }); await load(path); setSel([n]); setAnchor(n); }} />`}
    ${dialog?.kind === "touch" && html`<${NameDialog} title="Novo arquivo" label="Nome" ok="Criar e editar" onClose=${() => setDialog(null)}
      onOk=${async (n) => { await api.post("/files/touch", { src, path: joinPath(path, n) }); await load(path); setState({ open: joinPath(path, n) }, { push: true }); }} />`}
    ${dialog?.kind === "rename" && html`<${NameDialog} title="Renomear" label="Novo nome" initial=${dialog.entry.name} ok="Renomear"
      onClose=${() => setDialog(null)} onOk=${async (n) => { if (n === dialog.entry.name) return;
        await api.post("/files/rename", { src, path: joinPath(path, dialog.entry.name), name: n }); await load(path); setSel([n]); setAnchor(n); }} />`}
    ${dialog?.kind === "chmod" && html`<${ChmodDialog} entry=${dialog.entry} path=${joinPath(path, dialog.entry.name)} onClose=${() => setDialog(null)}
      onOk=${async (mode) => { await api.post("/files/chmod", { src, path: joinPath(path, dialog.entry.name), mode }); await load(path, { keepSel: true }); }} />`}
    ${dialog?.kind === "delete" && html`<${DeleteDialog} paths=${selPaths} entries=${selEntries} onOk=${doDelete} onClose=${() => setDialog(null)} />`}
    ${dialog?.kind === "nodir" && html`<${Modal} title="Baixar pasta" onClose=${() => setDialog(null)}>
      <p>Este navegador não deixa o site gravar uma <b>pasta</b> no seu computador. Isso exige Chrome ou Edge com o console
        em <b>HTTPS</b> (ou localhost); o endereço atual é ${location.protocol === "https:" ? "HTTPS, mas o navegador não oferece o recurso" : "HTTP"}.</p>
      <p>Escolha como baixar:</p>
      <div class="modal-actions">
        <button onClick=${() => setDialog(null)}>Cancelar</button>
        <button onClick=${() => { const p = dialog.paths; setDialog(null); downloadFlat(p); }}>Arquivos soltos (pasta_arquivo)</button>
        <button class="primary" onClick=${() => { const p = dialog.paths; setDialog(null); downloadZip(p); }}>Baixar .zip</button>
      </div>
    <//>`}
    ${dialog?.kind === "conflict" && html`<${ConflictDialog} names=${dialog.names} onChoice=${dialog.onChoice} onClose=${() => setDialog(null)} />`}
    ${state.open && html`<${FileEditor} src=${src} path=${state.open} onDownload=${download}
      onClose=${() => setState({ open: "" }, { back: true })} onSaved=${() => load(path, { keepSel: true })} />`}
  </div>`;
}
