// Componentes reutilizáveis: formulário, tabela, markdown, banner do cofre.
import { marked } from "marked";
import {
  html, useState, useEffect, useRef, api, Badge, CopyButton, Spinner, Modal,
  vaultStore, useStore, refreshVault, toast, handleError,
} from "./ui.js";
import { setAuthToken } from "./api.js";
// Re-export dos diálogos base p/ as páginas poderem importar tudo de components.js.
export { Modal, ConfirmDialog, ConflictDialog, Tabs } from "./ui.js";

/* ------------------------------- enums ---------------------------------- */
let _enums = null;
export async function loadEnums() { if (!_enums) _enums = await api.get("/meta/enums"); return _enums; }
export function useEnums() {
  const [e, setE] = useState(_enums);
  useEffect(() => { loadEnums().then(setE); }, []);
  return e;
}

/* ------------------------------- Field ---------------------------------- */
export function Field({ label, error, hint, tag, children, htmlFor, errorId }) {
  return html`<div class="field">
    ${label && html`<label for=${htmlFor}>${label}${tag}</label>`}
    ${children}
    ${hint && html`<div class="help">${hint}</div>`}
    ${error && html`<div class="err" id=${errorId}>${error}</div>`}
  </div>`;
}

/* enum <select> com opção opcional de "herdar do grupo" */
export function EnumSelect({ value, options, onChange, allowInherit, inheritLabel, invalid }) {
  return html`<select class=${invalid ? "invalid" : ""} value=${value ?? ""}
      onChange=${(e) => onChange(e.target.value || null)}>
    ${allowInherit && html`<option value="">${inheritLabel || "(herdar)"}</option>`}
    ${!allowInherit && (value == null) && html`<option value="">—</option>`}
    ${(options || []).map((o) => html`<option key=${o} value=${o} selected=${o === value}>${o}</option>`)}
  </select>`;
}

/* select de referência (credenciais, grupos, hosts) */
export function RefSelect({ value, options, onChange, placeholder, allowEmpty = true, invalid, id, required, describedBy }) {
  return html`<select id=${id} required=${required} aria-invalid=${invalid || undefined} aria-describedby=${describedBy} class=${invalid ? "invalid" : ""} value=${value ?? ""}
      onChange=${(e) => onChange(e.target.value || null)}>
    ${allowEmpty && html`<option value="">${placeholder || "—"}</option>`}
    ${(options || []).map((o) => html`<option key=${o} value=${o} selected=${o === value}>${o}</option>`)}
  </select>`;
}

/* ------------------------------ LinkForm -------------------------------- */
export function LinkForm({ link, hosts, rev, onClose, onSaved }) {
  const isNew = !!link.__new;
  const [f, setF] = useState({
    ah: link.a?.host || "", ap: link.a?.port || "", bh: link.b?.host || "", bp: link.b?.port || "",
    media: link.media ?? null, speed: link.speed || "", desc: link.desc || "",
  });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const form = useRef(null);
  const fields = { ah: "Host A", bh: "Host B" };
  const set = (k, v) => {
    setF(x => ({ ...x, [k]: v }));
    setErrors(x => { const next = { ...x }; delete next[k]; return next; });
  };
  async function save(event) {
    event.preventDefault();
    if (saving) return;
    const required = Object.fromEntries(Object.entries(fields).filter(([k]) => !f[k]?.trim())
      .map(([k, label]) => [k, `Informe ${label.toLowerCase()}.`]));
    setErrors(required);
    if (Object.keys(required).length) {
      toast.err("Selecione os hosts A e B para salvar o enlace.");
      form.current?.querySelector(`#link-${Object.keys(required)[0]}`)?.focus();
      return;
    }
    const body = { a: { host: f.ah.trim() }, b: { host: f.bh.trim() } };
    if (f.ap.trim()) body.a.port = f.ap.trim();
    if (f.bp.trim()) body.b.port = f.bp.trim();
    if (f.media) body.media = f.media;
    if (f.speed.trim()) body.speed = f.speed.trim();
    if (f.desc.trim()) body.desc = f.desc.trim();
    setSaving(true);
    try {
      if (isNew) await api.post("/topology/links", body, rev);
      else await api.put(link.id ? `/topology/link/${encodeURIComponent(link.id)}` : `/topology/links/${link.index}`, body, rev);
      toast.ok("Enlace salvo"); onSaved();
    } catch (e) {
      const keys = { "a/host": "ah", "a/port": "ap", "b/host": "bh", "b/port": "bp" };
      const next = {};
      for (const error of handleError(e)) next[keys[error.loc] || error.loc] = error.msg;
      setErrors(next);
    } finally { setSaving(false); }
  }
  return html`<${Modal} title=${isNew ? "Novo enlace" : "Editar enlace"} onClose=${saving ? undefined : onClose}>
    <form ref=${form} onSubmit=${save} noValidate>
      <p class="help">Selecione os dois hosts. As interfaces são opcionais e podem ser preenchidas depois, por exemplo ether2, sfp1 ou Gi0/1.</p>
      ${Object.keys(errors).length > 0 && html`<p role="alert">Revise os campos indicados antes de salvar o enlace.</p>`}
      <div class="row">
        <${Field} label="Host A *" htmlFor="link-ah" error=${errors.ah} errorId="link-ah-error">
          <${RefSelect} id="link-ah" required=true invalid=${!!errors.ah} describedBy=${errors.ah ? "link-ah-error" : undefined}
            value=${f.ah} options=${hosts} onChange=${v => set("ah", v)} /><//>
        <${Field} label="Porta A (opcional)" htmlFor="link-ap" error=${errors.ap} errorId="link-ap-error">
          <input id="link-ap" value=${f.ap} aria-invalid=${!!errors.ap || undefined} aria-describedby=${errors.ap ? "link-ap-error" : undefined}
            class=${errors.ap ? "invalid" : ""} placeholder="ex.: ether2" onInput=${e => set("ap", e.target.value)} /><//>
      </div>
      <div class="row">
        <${Field} label="Host B *" htmlFor="link-bh" error=${errors.bh} errorId="link-bh-error">
          <${RefSelect} id="link-bh" required=true invalid=${!!errors.bh} describedBy=${errors.bh ? "link-bh-error" : undefined}
            value=${f.bh} options=${hosts} onChange=${v => set("bh", v)} /><//>
        <${Field} label="Porta B (opcional)" htmlFor="link-bp" error=${errors.bp} errorId="link-bp-error">
          <input id="link-bp" value=${f.bp} aria-invalid=${!!errors.bp || undefined} aria-describedby=${errors.bp ? "link-bp-error" : undefined}
            class=${errors.bp ? "invalid" : ""} placeholder="ex.: ether1" onInput=${e => set("bp", e.target.value)} /><//>
      </div>
      <div class="row">
        <${Field} label="Meio"><${EnumSelect} value=${f.media} options=${["fiber", "copper"]} onChange=${v => set("media", v)} /><//>
        <${Field} label="Velocidade" htmlFor="link-speed"><input id="link-speed" value=${f.speed} placeholder="ex.: 10G" onInput=${e => set("speed", e.target.value)} /><//>
      </div>
      <${Field} label="Descrição" htmlFor="link-desc"><input id="link-desc" value=${f.desc} onInput=${e => set("desc", e.target.value)} /><//>
      <div class="modal-actions"><button type="button" disabled=${saving} onClick=${onClose}>Cancelar</button>
        <button type="submit" class="primary" disabled=${saving}>${saving ? "Salvando…" : "Salvar"}</button></div>
    </form>
  <//>`;
}


export function IconPicker({ value, onChange, error, title = "Ícone do host", defaultLabel = "Padrão", defaultHint = "Padrão: mantém o símbolo atual do dispositivo." }) {
  const [icons, setIcons] = useState([]);
  const [loadError, setLoadError] = useState(false);
  useEffect(() => { api.get("/meta/icons").then(data => setIcons(data.icons)).catch(() => setLoadError(true)); }, []);
  const chosen = icons.find(icon => icon.id === value);
  return html`<fieldset class="host-icon-picker">
    <legend>${title}</legend>
    <p class="help">${chosen ? `Selecionado: ${chosen.name}` : value ? `Selecionado: ${value}` : defaultHint}</p>
    <div class="host-icon-options" role="group" aria-label=${`Escolher ${title.toLowerCase()}`}>
      <button type="button" class=${"host-icon-option" + (!value ? " selected" : "")} aria-pressed=${!value} onClick=${() => onChange("")}>
        <span class="host-icon-default" aria-hidden="true">▤</span><span>${defaultLabel}</span></button>
      ${icons.map(icon => html`<button key=${icon.id} type="button" class=${"host-icon-option" + (value === icon.id ? " selected" : "")}
        aria-label=${`Ícone ${icon.name}`} aria-pressed=${value === icon.id} onClick=${() => onChange(icon.id)}>
        <img src=${icon.url} alt="" width="48" height="48" loading="lazy" decoding="async" draggable=false /><span>${icon.name}</span>
      </button>`)}
    </div>
    ${loadError && html`<p class="help" role="status">Não foi possível carregar a biblioteca de ícones. A seleção atual será mantida.</p>`}
    ${error && html`<p class="err" role="alert">${error}</p>`}
  </fieldset>`;
}


/* --------------------------- ResourceTable ------------------------------ */
export function ResourceTable({ columns, rows, onRowClick, actions, empty }) {
  // Ordenação opt-in: colunas que definem `sort: (row) => valor` ficam clicáveis.
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  if (!rows || rows.length === 0) return html`<div class="card"><div class="empty">${empty || "Nada aqui ainda."}</div></div>`;

  const activeCol = sort.key && columns.find((c) => c.key === sort.key && c.sort);
  let view = rows;
  if (activeCol) {
    const val = activeCol.sort;
    view = [...rows].sort((a, b) => {
      const va = val(a), vb = val(b);
      let cmp;
      if (typeof va === "number" && typeof vb === "number") cmp = va - vb;
      else cmp = String(va ?? "").localeCompare(String(vb ?? ""), "pt", { numeric: true, sensitivity: "base" });
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }
  const onHead = (c) => { if (c.sort) setSort((s) => s.key === c.key ? { key: c.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: "asc" }); };
  const ind = (c) => sort.key === c.key ? (sort.dir === "asc" ? "▲" : "▼") : (c.sort ? "⇅" : "");

  return html`<table>
    <thead><tr>
      ${columns.map((c) => html`<th key=${c.key} class=${c.sort ? "sortable" : ""}
          onClick=${c.sort ? () => onHead(c) : undefined}>${c.label}${c.sort || sort.key === c.key ? html` <span class="sort-ind">${ind(c)}</span>` : ""}</th>`)}
      ${actions && html`<th></th>`}
    </tr></thead>
    <tbody>
      ${view.map((r, i) => html`<tr key=${r._key ?? i} class=${onRowClick ? "clickable" : ""}
          onClick=${onRowClick ? () => onRowClick(r) : undefined}>
        ${columns.map((c) => html`<td key=${c.key}>${c.render ? c.render(r) : r[c.key]}</td>`)}
        ${actions && html`<td class="actions" onClick=${(e) => e.stopPropagation()}>${actions(r)}</td>`}
      </tr>`)}
    </tbody>
  </table>`;
}

/* ------------------------------- Toggle --------------------------------- */
// Interruptor liga/desliga controlado.
export function Toggle({ checked, onChange, label }) {
  return html`<label class="toggle">
    <input type="checkbox" checked=${checked} onChange=${(e) => onChange(e.target.checked)} />
    <span class="track"><span class="thumb"></span></span>
    ${label && html`<span class="toggle-label">${label}</span>`}
  </label>`;
}

/* ------------------------------ Markdown -------------------------------- */
function sanitize(htmlStr) {
  // Minimalista (ferramenta localhost): remove <script>/<style> e atributos on*.
  return htmlStr
    .replace(/<\/?(script|style)[^>]*>/gi, "")
    .replace(/\son\w+="[^"]*"/gi, "")
    .replace(/\son\w+='[^']*'/gi, "")
    .replace(/javascript:/gi, "");
}
export function MarkdownView({ text }) {
  const out = sanitize(marked.parse(text || "", { breaks: true }));
  return html`<div class="md" dangerouslySetInnerHTML=${{ __html: out }}></div>`;
}

// Visualização read-only de markdown: formatado por padrão; toggle revela o código-fonte.
export function MarkdownPanel({ text }) {
  const [source, setSource] = useState(false);
  return html`<div>
    <div class="md-toolbar"><${Toggle} checked=${source} onChange=${setSource} label="Código-fonte" /></div>
    ${source ? html`<pre class="raw">${text}</pre>` : html`<${MarkdownView} text=${text} />`}
  </div>`;
}

// Por padrão mostra só o Markdown FORMATADO (leitura). Ligar "Editar" revela o texto puro.
export function MarkdownEditor({ value, onChange, tokenBudget }) {
  const [editing, setEditing] = useState(false);
  const tokens = Math.max(1, Math.round((value || "").length / 4));
  const pct = tokenBudget ? Math.min(100, Math.round((tokens / tokenBudget) * 100)) : 0;
  const meterKind = pct > 100 ? "danger" : pct > 85 ? "warn" : "";
  return html`<div>
    <div class="md-toolbar"><${Toggle} checked=${editing} onChange=${setEditing} label="Editar (texto puro)" /></div>
    ${editing
      ? html`<textarea class="codearea" value=${value} onInput=${(e) => onChange(e.target.value)}></textarea>`
      : html`<div class="card md-readbox"><${MarkdownView} text=${value} /></div>`}
    ${tokenBudget && editing && html`<div>
      <div class="help">~${tokens} tokens / orçamento ~${tokenBudget}</div>
      <div class="meter ${meterKind}"><div style=${`width:${Math.min(100, pct)}%`}></div></div>
    </div>`}
  </div>`;
}

export function CodeTextEditor({ value, onChange }) {
  return html`<textarea class="codearea" value=${value} onInput=${(e) => onChange(e.target.value)}></textarea>`;
}

/* ---------------------------- LoginScreen ------------------------------- */
// Gate de acesso ao console: a senha-mestra do cofre autentica a sessão de login (e
// destranca o cofre na mesma ação). Mesmo caminho de verificação do UnlockModal.
export function LoginScreen({ onAuthed }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!pw || busy) return;
    setBusy(true); setErr("");
    try {
      const r = await api.post("/auth/login", { master_password: pw });
      setPw("");
      setAuthToken(r.auth_token);
      await refreshVault();
      onAuthed && onAuthed();
    } catch (e2) {
      if (e2.status === 401) setErr("Senha mestra incorreta.");
      else setErr(e2.payload?.detail || e2.message || "Falha ao entrar.");
    } finally { setBusy(false); }
  }

  return html`<div class="login-screen">
    <form class="login-card" onSubmit=${submit}>
      <div class="login-brand">🔒 NetOps Console</div>
      <p class="help">Acesso protegido. Entre com a senha-mestra do cofre.</p>
      <div class="field">
        <label>Senha mestra</label>
        <input type="password" autocomplete="current-password" autofocus value=${pw}
          onInput=${(e) => setPw(e.target.value)} disabled=${busy} />
        ${err && html`<div class="err">${err}</div>`}
      </div>
      <button type="submit" class="primary" disabled=${busy || !pw}>${busy ? "Entrando…" : "Entrar"}</button>
    </form>
  </div>`;
}

/* ---------------------------- UnlockModal ------------------------------- */
// Destranca o cofre digitando a senha-mestra. A senha vai só nesta request (POST
// /vault/unlock), deriva a chave no servidor e é descartada — nunca volta ao browser.
export function UnlockModal({ onClose }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!pw || busy) return;
    setBusy(true); setErr("");
    try {
      await api.post("/vault/unlock", { master_password: pw });
      setPw("");
      await refreshVault();
      toast.ok("Cofre destrancado");
      onClose && onClose();
    } catch (e2) {
      if (e2.status === 401) setErr("Senha mestra incorreta.");
      else if (e2.status === 409) setErr(e2.payload?.detail || "Cofre não inicializado — rode 'init' no terminal.");
      else if (e2.status === 403) setErr(e2.payload?.detail || "Destrancar pela web está desabilitado.");
      else setErr(e2.message || "Falha ao destrancar.");
    } finally { setBusy(false); }
  }

  return html`<${Modal} title="Destrancar o cofre" onClose=${onClose}>
    <form onSubmit=${submit}>
      <p class="help">A senha-mestra é usada só para derivar a chave nesta sessão; não é gravada,
        registrada nem devolvida. A sessão vale também para a CLI e os agentes.</p>
      <div class="field">
        <label>Senha mestra</label>
        <input type="password" autocomplete="off" autofocus value=${pw}
          onInput=${(e) => setPw(e.target.value)} disabled=${busy} />
        ${err && html`<div class="err">${err}</div>`}
      </div>
      <div class="modal-actions">
        <button type="button" onClick=${onClose} disabled=${busy}>Cancelar</button>
        <button type="submit" class="primary" disabled=${busy || !pw}>${busy ? "Destrancando…" : "Destrancar"}</button>
      </div>
    </form>
  <//>`;
}

/* ----------------------------- VaultBanner ------------------------------ */
export function VaultBanner() {
  const v = useStore(vaultStore);
  const [tick, setTick] = useState(0);
  const [showUnlock, setShowUnlock] = useState(false);
  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), 1000); return () => clearInterval(t); }, []);

  const canUnlock = v.allow_unlock !== false;
  async function doLock() {
    try { await api.post("/vault/lock"); await refreshVault(); toast.info("Cofre trancado"); }
    catch (e) { toast.err(e.message || "Falha ao trancar"); }
  }
  const unlockBtn = canUnlock && html`<button class="sm primary" onClick=${() => setShowUnlock(true)}>Destrancar aqui</button>`;
  const modal = showUnlock && html`<${UnlockModal} onClose=${() => setShowUnlock(false)} />`;

  if (v.state === "loading" || v.state === "cache" || v.state === "env") {
    if (v.state === "cache") {
      const left = Math.max(0, (v.expires_in || 0) - tick);
      const mm = String(Math.floor(left / 60)).padStart(2, "0"), ss = String(left % 60).padStart(2, "0");
      return html`<div class="vault-banner ok">🔓 Cofre destrancado (sessão) — expira em ${mm}:${ss}
        <span class="spacer"></span>
        <button class="sm" onClick=${refreshVault}>Re-verificar</button>
        <button class="sm" onClick=${doLock}>Trancar</button></div>`;
    }
    if (v.state === "env") return html`<div class="vault-banner ok">🔓 Cofre destrancado (variável de ambiente)</div>`;
    return null;
  }

  const cmd = v.unlock_cmd || "cd /opt/netops && .venv/bin/python3 scripts/engine/vault/cli.py unlock";
  if (v.state === "insecure")
    return html`<div class="vault-banner insecure">⚠ Permissões inseguras no cache do cofre — ${v.detail}
      ${unlockBtn}
      <span class="spacer"></span><button class="sm" onClick=${refreshVault}>Re-verificar</button>
      ${modal}</div>`;
  // locked / error
  return html`<div class="vault-banner locked">
    🔒 Cofre <b>TRANCADO</b> — edições de senha desabilitadas.
    ${unlockBtn}
    <span class="spacer"></span>
    ${canUnlock && html`<span class="help">ou rode no shell abaixo:</span>`}
    <code>${cmd}</code><${CopyButton} text=${cmd} />
    <button class="sm" onClick=${refreshVault}>Re-verificar</button>
    ${modal}
  </div>`;
}

export function vaultWritable() {
  const v = vaultStore.get();
  return v.state === "cache" || v.state === "env";
}

/* -------------------------- RenameCascadeHint --------------------------- */
// Dentro do formulário de edição: quando o ID/nome muda, mostra quantas
// referências serão atualizadas em cascade ao salvar. `refsPath` é o endpoint
// GET .../references; `changed` liga o aviso só quando o campo difere do original.
export function RenameCascadeHint({ refsPath, changed }) {
  const [refs, setRefs] = useState(null);
  useEffect(() => { api.get(refsPath).then((d) => setRefs(d.references || [])).catch(() => setRefs([])); }, [refsPath]);
  if (!changed || !refs || !refs.length) return null;
  return html`<div class="card rename-refs">⚠ Ao salvar, <b>${refs.length} referência(s)</b> serão atualizadas:
    <ul>${refs.map((r, i) => html`<li key=${i}>${r.label || r.id}</li>`)}</ul></div>`;
}
