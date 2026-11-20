// Componentes reutilizáveis: formulário, tabela, markdown, banner do cofre.
import { marked } from "marked";
import { openTermHref } from "./term-link.js";
import {
  html, useState, useEffect, useRef, api, Badge, CopyButton, Spinner, Modal,
  vaultStore, useStore, refreshVault, toast, handleError, t, useLocale,
} from "./ui.js";
import { loadIndex, loadLocale, languages } from "./i18n.js";
import { authToken, setAuthToken } from "./api.js";
import { WysiwygEditor } from "./wysiwyg.js";
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
    ${allowInherit && html`<option value="">${inheritLabel || t("components.inherit")}</option>`}
    ${!allowInherit && (value == null) && html`<option value="">—</option>`}
    ${(options || []).map((o) => html`<option key=${o} value=${o} selected=${o === value}>${o}</option>`)}
  </select>`;
}

/* select de referência (credenciais, grupos, hosts) */
export function RefSelect({ value, options, onChange, placeholder, allowEmpty = true, invalid, id, required, describedBy }) {
  return html`<select id=${id} required=${required} aria-invalid=${invalid || undefined} aria-describedby=${describedBy} class=${invalid ? "invalid" : ""} value=${value ?? ""}
      onChange=${(e) => onChange(e.target.value || null)}>
    ${allowEmpty && html`<option value="">${placeholder || "—"}</option>`}
    ${(options || []).map((o) => {
      const id = typeof o === "object" ? o.id : o;
      const label = typeof o === "object" ? o.label || o.hostname || o.id : o;
      return html`<option key=${id} value=${id} selected=${String(id) === String(value)}>${label}</option>`;
    })}
  </select>`;
}

/* ------------------------------ LinkForm -------------------------------- */
export function LinkForm({ link, hosts, rev, onClose, onSaved }) {
  const isNew = !!link.__new;
  const [f, setF] = useState({
    ah: String(link.a?.host ?? ""), ap: link.a?.port || "", bh: String(link.b?.host ?? ""), bp: link.b?.port || "",
    media: link.media ?? null, speed: link.speed || "", desc: link.desc || "",
  });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const form = useRef(null);
  const fields = { ah: "components.link_ah_required", bh: "components.link_bh_required" };
  const set = (k, v) => {
    setF(x => ({ ...x, [k]: v }));
    setErrors(x => { const next = { ...x }; delete next[k]; return next; });
  };
  async function save(event) {
    event.preventDefault();
    if (saving) return;
    const required = Object.fromEntries(Object.entries(fields).filter(([k]) => !f[k] || !/^[1-9]\d*$/.test(f[k]) || !Number.isSafeInteger(Number(f[k])))
      .map(([k, key]) => [k, t(key)]));
    setErrors(required);
    if (Object.keys(required).length) {
      toast.err(t("components.link_select_hosts"));
      form.current?.querySelector(`#link-${Object.keys(required)[0]}`)?.focus();
      return;
    }
    const body = { a: { host: Number(f.ah) }, b: { host: Number(f.bh) } };
    if (f.ap.trim()) body.a.port = f.ap.trim();
    if (f.bp.trim()) body.b.port = f.bp.trim();
    if (f.media) body.media = f.media;
    if (f.speed.trim()) body.speed = f.speed.trim();
    if (f.desc.trim()) body.desc = f.desc.trim();
    setSaving(true);
    try {
      if (isNew) await api.post("/topology/links", body, rev);
      else await api.put(link.id ? `/topology/link/${encodeURIComponent(link.id)}` : `/topology/links/${link.index}`, body, rev);
      toast.ok(t("components.link_saved")); onSaved();
    } catch (e) {
      const keys = { "a/host": "ah", "a/port": "ap", "b/host": "bh", "b/port": "bp" };
      const next = {};
      for (const error of handleError(e)) next[keys[error.loc] || error.loc] = error.msg;
      setErrors(next);
    } finally { setSaving(false); }
  }
  return html`<${Modal} title=${isNew ? t("components.link_new") : t("components.link_edit")} onClose=${saving ? undefined : onClose}>
    <form ref=${form} onSubmit=${save} noValidate>
      <p class="help">${t("components.link_help")}</p>
      ${Object.keys(errors).length > 0 && html`<p role="alert">${t("components.link_review")}</p>`}
      <div class="row">
        <${Field} label=${t("components.link_host_a")} htmlFor="link-ah" error=${errors.ah} errorId="link-ah-error">
          <${RefSelect} id="link-ah" required=true invalid=${!!errors.ah} describedBy=${errors.ah ? "link-ah-error" : undefined}
            value=${f.ah} options=${hosts} onChange=${v => set("ah", v || "")} /><//>
        <${Field} label=${t("components.link_port_a")} htmlFor="link-ap" error=${errors.ap} errorId="link-ap-error">
          <input id="link-ap" value=${f.ap} aria-invalid=${!!errors.ap || undefined} aria-describedby=${errors.ap ? "link-ap-error" : undefined}
            class=${errors.ap ? "invalid" : ""} placeholder=${t("components.example", { value: "ether2" })} onInput=${e => set("ap", e.target.value)} /><//>
      </div>
      <div class="row">
        <${Field} label=${t("components.link_host_b")} htmlFor="link-bh" error=${errors.bh} errorId="link-bh-error">
          <${RefSelect} id="link-bh" required=true invalid=${!!errors.bh} describedBy=${errors.bh ? "link-bh-error" : undefined}
            value=${f.bh} options=${hosts} onChange=${v => set("bh", v || "")} /><//>
        <${Field} label=${t("components.link_port_b")} htmlFor="link-bp" error=${errors.bp} errorId="link-bp-error">
          <input id="link-bp" value=${f.bp} aria-invalid=${!!errors.bp || undefined} aria-describedby=${errors.bp ? "link-bp-error" : undefined}
            class=${errors.bp ? "invalid" : ""} placeholder=${t("components.example", { value: "ether1" })} onInput=${e => set("bp", e.target.value)} /><//>
      </div>
      <div class="row">
        <${Field} label=${t("components.link_media")}><${EnumSelect} value=${f.media} options=${["fiber", "copper"]} onChange=${v => set("media", v)} /><//>
        <${Field} label=${t("components.link_speed")} htmlFor="link-speed"><input id="link-speed" value=${f.speed} placeholder=${t("components.example", { value: "10G" })} onInput=${e => set("speed", e.target.value)} /><//>
      </div>
      <${Field} label=${t("common.description")} htmlFor="link-desc"><input id="link-desc" value=${f.desc} onInput=${e => set("desc", e.target.value)} /><//>
      <div class="modal-actions"><button type="button" disabled=${saving} onClick=${onClose}>${t("common.cancel")}</button>
        <button type="submit" class="primary" disabled=${saving}>${saving ? t("common.saving") : t("common.save")}</button></div>
    </form>
  <//>`;
}


export function IconPicker({ value, onChange, error, title = t("components.icon_title"), defaultLabel = t("components.icon_default"), defaultHint = t("components.icon_default_hint") }) {
  const [icons, setIcons] = useState([]);
  const [loadError, setLoadError] = useState(false);
  useEffect(() => { api.get("/meta/icons").then(data => setIcons(data.icons)).catch(() => setLoadError(true)); }, []);
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    const away = e => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    const esc = e => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const chosen = icons.find(icon => icon.id === value);
  const pick = id => { onChange(id); setOpen(false); };
  const label = chosen ? chosen.name : value ? value : defaultLabel;
  return html`<fieldset class="host-icon-picker">
    <legend>${title}</legend>
    <div class="icon-dd" ref=${rootRef}>
      <button type="button" class="icon-dd-btn" aria-haspopup="listbox" aria-expanded=${open} onClick=${() => setOpen(!open)}>
        ${chosen ? html`<img src=${chosen.url} alt="" width="28" height="28" />` : html`<span class="host-icon-default" aria-hidden="true">▤</span>`}
        <span class="icon-dd-label">${label}</span><span aria-hidden="true">▾</span>
      </button>
      ${open && html`<div class="icon-dd-menu" role="listbox" aria-label=${t("components.icon_choose", { title: title.toLowerCase() })}>
        <button type="button" role="option" aria-selected=${!value} class=${"icon-dd-item" + (!value ? " selected" : "")} onClick=${() => pick("")}>
          <span class="host-icon-default" aria-hidden="true">▤</span><span>${defaultLabel}</span></button>
        ${icons.map(icon => html`<button key=${icon.id} type="button" role="option" aria-selected=${value === icon.id}
          class=${"icon-dd-item" + (value === icon.id ? " selected" : "")} onClick=${() => pick(icon.id)}>
          <img src=${icon.url} alt="" width="28" height="28" loading="lazy" decoding="async" draggable=false /><span>${icon.name}</span>
        </button>`)}
      </div>`}
    </div>
    <p class="help">${value ? "" : defaultHint}</p>
    ${loadError && html`<p class="help" role="status">${t("components.icon_load_error")}</p>`}
    ${error && html`<p class="err" role="alert">${error}</p>`}
  </fieldset>`;
}


/* ---------------------------- FilterBar --------------------------------- */
// Filtros que vivem na URL: o chamador passa valores e `onChange(patch)` (useMenuRoute().setParams).
export function FilterBar({ q = "", selects = [], onChange, placeholder = t("common.search"), pretty = true, count = null, total = null }) {
  // options: strings, or { value, label } when the value (URL) differs from the text shown
  const opt = (o) => (o && typeof o === "object"
    ? html`<option key=${o.value} value=${o.value}>${o.label}</option>` : html`<option key=${o} value=${o}>${o}</option>`);
  const active = q || selects.some((s) => s.value);
  const clear = () => onChange({ q: "", ...Object.fromEntries(selects.map((s) => [s.key, ""])) });
  if (pretty) return html`<div class="fb" role="search">
    <label class="fb-search">
      <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M13 13l4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
      <input type="search" aria-label=${placeholder} placeholder=${placeholder} value=${q} onInput=${(e) => onChange({ q: e.target.value })} />
    </label>
    ${selects.map((s) => html`<label key=${s.key} class=${"fb-select" + (s.value ? " on" : "")}>
      <span class="fb-label">${s.label}</span>
      <select aria-label=${s.label} value=${s.value || ""} onChange=${(e) => onChange({ [s.key]: e.target.value })}>
        <option value="">${t("components.filter_all")}</option>${s.options.map(opt)}</select>
    </label>`)}
    ${active && html`<button type="button" class="fb-clear" onClick=${clear}>${t("components.filter_clear_x")}</button>`}
    ${count != null && html`<span class="fb-count">${total != null ? t("components.filter_count", { shown: count, total }) : count}</span>`}
  </div>`;
  return html`<div class="toolbar filter-bar" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
    <input type="search" aria-label=${placeholder} placeholder=${placeholder} value=${q} onInput=${(e) => onChange({ q: e.target.value })} />
    ${selects.map((s) => html`<select key=${s.key} aria-label=${s.label} value=${s.value || ""} onChange=${(e) => onChange({ [s.key]: e.target.value })}>
      <option value="">${t("components.filter_select_all", { label: s.label })}</option>${s.options.map(opt)}</select>`)}
    ${active && html`<button class="sm" onClick=${clear}>${t("components.filter_clear")}</button>`}
  </div>`;
}

/* ---------------------- Tabelas → js/table.js ------------------------- */
// Toda tabela de dados usa DataTable (core/rules/console-tables.md). Re-export p/ compatibilidade.
export { DataTable, ResourceTable } from "./table.js";

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
// Blocos de código ganham cabeçalho com a linguagem e botão "Copiar" (delegação de clique em .md).
function wrapCodeBlocks(h) {
  return h.replace(/<pre>(<code(?: class="language-([\w+-]+)")?[^>]*>)([\s\S]*?)<\/code><\/pre>/g,
    (_, open, lang, body) => `<div class="md-codeblock"><div class="md-codehead"><span>${lang || t("components.md_code")}</span>` +
      `<button type="button" class="md-copy sm">${t("components.md_copy")}</button></div><pre>${open}${body}</code></pre></div>`);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (_) {}
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (_) {}
  ta.remove(); return ok;
}
// Caminho de relatório citado pelo agente (`reports/x.md`, /opt/netops/reports/x.pdf, link markdown) -> clicável.
const REPORT_RE = /^(?:\/opt\/netops\/|\.\/)?reports\/([^\/\s]+\.(?:md|txt|log|pdf))$/i;
function reportOf(s) { const m = REPORT_RE.exec((s || "").trim()); return m ? m[1] : null; }
function linkReports(root) {
  root.querySelectorAll("code, a").forEach((el) => {
    if (el.closest("pre") || el.dataset.report) return;
    const f = el.tagName === "A" ? reportOf(decodeURIComponent(el.getAttribute("href") || "")) : reportOf(el.textContent);
    if (!f) return;
    el.dataset.report = f; el.classList.add("md-reportlink"); el.title = t("components.md_open_report", { file: f });
  });
}
function onMdClick(e) {
  const rep = e.target.closest && e.target.closest("[data-report]");
  if (rep) { e.preventDefault(); window.dispatchEvent(new CustomEvent("netops:open-report", { detail: rep.dataset.report })); return; }
  // Link para o terminal de host (#hostterm/...): abre em janela nova, não troca a página atual.
  const term = e.target.closest && e.target.closest('a[href^="#hostterm/"]');
  if (term) { e.preventDefault(); openTermHref(term.getAttribute("href"), { fallbackHere: true }); return; }
  const btn = e.target.closest && e.target.closest(".md-copy");
  if (!btn) return;
  const code = btn.closest(".md-codeblock")?.querySelector("pre");
  copyText(code ? code.innerText.replace(/\n$/, "") : "").then((ok) => {
    btn.textContent = ok ? t("components.md_copied") : t("components.md_copy_failed");
    setTimeout(() => { btn.textContent = t("components.md_copy"); }, 1500);
  });
}
export function MarkdownView({ text }) {
  const out = wrapCodeBlocks(sanitize(marked.parse(text || "", { breaks: true })));
  const ref = useRef(null);
  useEffect(() => { if (ref.current) linkReports(ref.current); }, [out]);
  return html`<div class="md" ref=${ref} onClick=${onMdClick} dangerouslySetInnerHTML=${{ __html: out }}></div>`;
}

// Visualização read-only de markdown: formatado por padrão; toggle revela o código-fonte.
export function MarkdownPanel({ text }) {
  const [source, setSource] = useState(false);
  return html`<div>
    <div class="md-toolbar"><${Toggle} checked=${source} onChange=${setSource} label=${t("components.md_source")} /></div>
    ${source ? html`<pre class="raw">${text}</pre>` : html`<${MarkdownView} text=${text} />`}
  </div>`;
}

// Três modos: Ler (formatado), Editor visual (WYSIWYG, botões de formatação) e Texto puro (Markdown cru).
export function MarkdownEditor({ value, onChange, tokenBudget }) {
  const [mode, setMode] = useState("read");
  const tokens = Math.max(1, Math.round((value || "").length / 4));
  const pct = tokenBudget ? Math.min(100, Math.round((tokens / tokenBudget) * 100)) : 0;
  const meterKind = pct > 100 ? "danger" : pct > 85 ? "warn" : "";
  const modes = [["read", t("components.md_mode_read")], ["visual", t("components.md_mode_visual")], ["raw", t("components.md_mode_raw")]];
  // Frontmatter YAML (--- … ---) não é Markdown: fica fora do editor visual e é reanexado intacto.
  const fm = (value || "").match(/^---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/);
  const front = fm ? fm[0] : "";
  const body = (value || "").slice(front.length);
  return html`<div>
    <div class="md-toolbar"><div class="seg">
      ${modes.map(([k, l]) => html`<button type="button" class=${mode === k ? "on" : ""} onClick=${() => setMode(k)}>${l}</button>`)}
    </div></div>
    ${mode === "visual" ? html`<div>
        ${front && html`<details class="md-front"><summary>${t("components.md_frontmatter_edit")}</summary><pre class="raw">${front}</pre></details>`}
        <${WysiwygEditor} value=${body.replace(/^\n+/, "")} onChange=${(md) => onChange(front + (front ? "\n" : "") + md)} />
      </div>`
      : mode === "raw" ? html`<textarea class="codearea" value=${value} onInput=${(e) => onChange(e.target.value)}></textarea>`
      : html`<div class="card md-readbox">
          ${front && html`<details class="md-front"><summary>${t("components.md_frontmatter")}</summary><pre class="raw">${front}</pre></details>`}
          <${MarkdownView} text=${body} /></div>`}
    ${tokenBudget && mode !== "read" && html`<div>
      <div class="help">${t("components.md_tokens", { tokens, budget: tokenBudget })}</div>
      <div class="meter ${meterKind}"><div style=${`width:${Math.min(100, pct)}%`}></div></div>
    </div>`}
  </div>`;
}

// Editor de código/YAML em texto puro: Tab indenta (não sai do campo) e .yaml/.yml é validado ao digitar.
export function CodeTextEditor({ value, onChange, name = "" }) {
  const isYaml = /\.ya?ml$/i.test(name) || /^\s*(workflow|version|project):/m.test(value || "") && !name;
  const [yerr, setYerr] = useState("");
  useEffect(() => {
    if (!isYaml) return setYerr("");
    const tm = setTimeout(async () => {
      try { const y = await import("js-yaml"); (y.load || y.default.load)(value || ""); setYerr(""); }
      catch (e) { setYerr(e.message.split("\n")[0]); }
    }, 300);
    return () => clearTimeout(tm);
  }, [value, isYaml]);
  const onKey = (e) => {
    if (e.key !== "Tab" || e.ctrlKey || e.altKey || e.metaKey) return;
    e.preventDefault();
    const ta = e.target, i = ta.selectionStart, j = ta.selectionEnd;
    ta.setRangeText("  ", i, j, "end");
    onChange(ta.value);
  };
  return html`<div>
    <textarea class="codearea" spellcheck="false" value=${value} onKeyDown=${onKey} onInput=${(e) => onChange(e.target.value)}></textarea>
    ${isYaml && html`<div class=${yerr ? "help yaml-bad" : "help yaml-ok"}>${yerr ? t("components.yaml_invalid", { error: yerr }) : t("components.yaml_valid")}</div>`}
  </div>`;
}

/* ---------------------------- LoginScreen ------------------------------- */
// Gate de acesso ao console: E-MAIL + senha (banco de acesso). Sem usuários cadastrados, e-mail do
// admin + senha-mestra do cofre (o 1º login cria o admin). O keyslot do usuário destranca o cofre.
/* --------------------------- PasswordInput ------------------------------ */
// Campo de senha com "olhinho" para mostrar/ocultar o que está sendo digitado.
export function PasswordInput({ value, onInput, ...rest }) {
  const [show, setShow] = useState(false);
  return html`<span class="pw-wrap">
    <input ...${rest} type=${show ? "text" : "password"} value=${value} onInput=${onInput} />
    <button type="button" class="pw-eye" tabindex="-1" title=${show ? t("components.pw_hide") : t("components.pw_show")}
      aria-label=${show ? t("components.pw_hide") : t("components.pw_show")} onMouseDown=${(e) => e.preventDefault()}
      onClick=${() => setShow(!show)}>${show ? "🙈" : "👁"}</button>
  </span>`;
}

// Language switch on the login screen: before login the user may need another language (remembered in this browser).
function LoginLanguages() {
  const cur = useLocale();
  const [list, setList] = useState(languages());
  useEffect(() => { loadIndex().then((idx) => setList(idx.languages || [])); }, []);
  if (list.length < 2) return null;
  return html`<div class="login-langs" role="group" aria-label=${t("common.language")}
      style="display:flex;gap:6px;justify-content:center;flex-wrap:wrap;margin-top:14px">
    ${list.map((l) => html`<button type="button" key=${l.code} class="sm ghost" aria-pressed=${l.code === cur}
      style=${l.code === cur ? "font-weight:700;text-decoration:underline" : ""}
      onClick=${() => loadLocale(l.code)}>${l.name}</button>`)}
  </div>`;
}

export function LoginScreen({ onAuthed, multiuser = false }) {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());

  async function submit(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!pw || busy || !emailOk) return;
    setBusy(true); setErr("");
    try {
      const login = email.trim().toLowerCase();
      // Sem usuários (modo senha-mestra): o e-mail informado vira o login do admin criado agora.
      const body = multiuser ? { email: login, password: pw } : { email: login, master_password: pw };
      const r = await api.post("/auth/login", body);
      setPw("");
      setAuthToken(r.auth_token);
      await refreshVault();
      if (authToken() !== r.auth_token) return;
      if (r.bootstrap) toast.ok(t("components.login_admin_created", { login }));
      onAuthed && onAuthed();
    } catch (e2) {
      if (e2.status === 401) setErr(multiuser ? t("components.login_bad_credentials") : t("components.master_password_wrong"));
      else setErr(e2.payload?.detail || e2.message || t("components.login_failed"));
    } finally { setBusy(false); }
  }

  return html`<div class="login-screen">
    <form class="login-card" onSubmit=${submit}>
      <div class="login-brand">🔒 NetOps Console</div>
      <p class="help">${multiuser ? t("components.login_help_multiuser") : t("components.login_help_first")}</p>
      <div class="field">
        <label>${multiuser ? t("common.email") : t("components.login_admin_email")}</label>
        <input type="email" autocomplete="username" autocapitalize="none" spellcheck="false" autofocus value=${email}
          onInput=${(e) => setEmail(e.target.value)} disabled=${busy} />
      </div>
      <div class="field">
        <label>${multiuser ? t("common.password") : t("components.master_password")}</label>
        <${PasswordInput} autocomplete="current-password" value=${pw}
          onInput=${(e) => setPw(e.target.value)} disabled=${busy} />
        ${err && html`<div class="err">${err}</div>`}
      </div>
      <button type="submit" class="primary" disabled=${busy || !pw || !emailOk}>${busy ? t("components.login_busy") : t("components.login_submit")}</button>
      <${LoginLanguages} />
    </form>
  </div>`;
}

/* ---------------------------- UnlockModal ------------------------------- */
// Destranca o cofre digitando a senha-mestra. A senha vai só nesta request (POST
// /vault/unlock), deriva a chave no servidor e é descartada — nunca volta ao browser.
export function UnlockModal({ onClose, reason }) {
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
      toast.ok(t("components.vault_unlocked_toast"));
      onClose && onClose();
    } catch (e2) {
      if (e2.status === 401) setErr(t("components.master_password_wrong"));
      else if (e2.status === 409) setErr(e2.payload?.detail || t("components.vault_not_initialized"));
      else if (e2.status === 403) setErr(e2.payload?.detail || t("components.vault_web_unlock_disabled"));
      else setErr(e2.message || t("components.vault_unlock_failed"));
    } finally { setBusy(false); }
  }

  return html`<${Modal} title=${t("components.vault_unlock_title")} onClose=${onClose}>
    <form onSubmit=${submit}>
      ${reason && html`<p class="vault-reason">🔒 ${reason}</p>`}
      <p class="help">${t("components.vault_unlock_help")}</p>
      <div class="field">
        <label>${t("components.master_password")}</label>
        <${PasswordInput} autocomplete="off" autofocus value=${pw}
          onInput=${(e) => setPw(e.target.value)} disabled=${busy} />
        ${err && html`<div class="err">${err}</div>`}
      </div>
      <div class="modal-actions">
        <button type="button" onClick=${onClose} disabled=${busy}>${t("common.cancel")}</button>
        <button type="submit" class="primary" disabled=${busy || !pw}>${busy ? t("components.vault_unlocking") : t("components.vault_unlock")}</button>
      </div>
    </form>
  <//>`;
}

/* ----------------------------- VaultBanner ------------------------------ */
export function VaultBanner({ compact = false } = {}) {
  const v = useStore(vaultStore);
  const [tick, setTick] = useState(0);
  const [showUnlock, setShowUnlock] = useState(false);
  useEffect(() => { const iv = setInterval(() => setTick((n) => n + 1), 1000); return () => clearInterval(iv); }, []);

  const canUnlock = v.allow_unlock !== false;
  async function doLock() {
    try { await api.post("/vault/lock"); await refreshVault(); toast.info(t("components.vault_locked_toast")); }
    catch (e) { toast.err(e.message || t("components.vault_lock_failed")); }
  }
  const unlockBtn = canUnlock && html`<button class="sm primary" onClick=${() => setShowUnlock(true)}>${t("components.vault_unlock_here")}</button>`;
  const modal = showUnlock && html`<${UnlockModal} onClose=${() => setShowUnlock(false)} />`;

  if (v.state === "loading" || v.state === "cache" || v.state === "env") {
    if (v.state === "cache") {
      const left = Math.max(0, (v.expires_in || 0) - tick);
      const mm = String(Math.floor(left / 60)).padStart(2, "0"), ss = String(left % 60).padStart(2, "0");
      if (compact) return html`<button type="button" class="sm icon-btn vault-icon ok" onClick=${doLock}
        title=${t("components.vault_cache_title", { time: `${mm}:${ss}` })} aria-label=${t("components.vault_cache_aria")}>🔓<span class="mob-label">${t("components.vault_lock_mob")}</span></button>`;
      return html`<div class="vault-banner ok">${t("components.vault_cache_banner", { time: `${mm}:${ss}` })}
        <span class="spacer"></span>
        <button class="sm" onClick=${doLock}>${t("components.vault_lock")}</button></div>`;
    }
    if (v.state === "env") return compact
      ? html`<span class="sm icon-btn vault-icon ok" title=${t("components.vault_env_title")}>🔓</span>`
      : html`<div class="vault-banner ok">${t("components.vault_env_banner")}</div>`;
    return null;
  }

  const cmd = v.unlock_cmd || "cd /opt/netops && .venv/bin/python3 scripts/engine/vault/cli.py unlock";
  if (compact) return html`<button type="button" class=${"sm icon-btn vault-icon " + (v.state === "insecure" ? "insecure" : "locked")}
    onClick=${() => canUnlock ? setShowUnlock(true) : toast.info(t("components.vault_web_disabled_run", { cmd }))}
    title=${(v.state === "insecure" ? t("components.vault_insecure_title", { detail: v.detail }) : t("components.vault_locked_title"))
      + (canUnlock ? t("components.vault_click_unlock") : "")} aria-label=${t("components.vault_locked_aria")}>${v.state === "insecure" ? "⚠" : "🔒"}<span class="mob-label">${t("components.vault_unlock_title")}</span></button>${modal}`;
  if (v.state === "insecure")
    return html`<div class="vault-banner insecure">⚠ ${t("components.vault_insecure_title", { detail: v.detail })}
      ${unlockBtn}
      <span class="spacer"></span>
      ${modal}</div>`;
  // locked / error
  return html`<div class="vault-banner locked">
    🔒 ${t("components.vault_locked_pre")} <b>${t("components.vault_locked_word")}</b> ${t("components.vault_locked_post")}
    ${unlockBtn}
    <span class="spacer"></span>
    ${canUnlock && html`<span class="help">${t("components.vault_or_run_shell")}</span>`}
    <code>${cmd}</code><${CopyButton} text=${cmd} />
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
  return html`<div class="card rename-refs">${t("components.rename_refs_pre")} <b>${t("components.rename_refs_count", { count: refs.length })}</b> ${t("components.rename_refs_post")}
    <ul>${refs.map((r, i) => html`<li key=${i}>${r.label || r.id}</li>`)}</ul></div>`;
}
