// Componentes reutilizáveis: formulário, tabela, markdown, banner do cofre.
import { marked } from "marked";
import {
  html, useState, useEffect, api, Badge, CopyButton, Spinner, Modal,
  vaultStore, useStore, refreshVault, toast,
} from "./ui.js";
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
export function Field({ label, error, hint, tag, children }) {
  return html`<div class="field">
    ${label && html`<label>${label}${tag}</label>`}
    ${children}
    ${hint && html`<div class="help">${hint}</div>`}
    ${error && html`<div class="err">${error}</div>`}
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
export function RefSelect({ value, options, onChange, placeholder, allowEmpty = true, invalid }) {
  return html`<select class=${invalid ? "invalid" : ""} value=${value ?? ""}
      onChange=${(e) => onChange(e.target.value || null)}>
    ${allowEmpty && html`<option value="">${placeholder || "—"}</option>`}
    ${(options || []).map((o) => html`<option key=${o} value=${o} selected=${o === value}>${o}</option>`)}
  </select>`;
}

/* --------------------------- ResourceTable ------------------------------ */
export function ResourceTable({ columns, rows, onRowClick, actions, empty }) {
  if (!rows || rows.length === 0) return html`<div class="card"><div class="empty">${empty || "Nada aqui ainda."}</div></div>`;
  return html`<table>
    <thead><tr>
      ${columns.map((c) => html`<th key=${c.key}>${c.label}</th>`)}
      ${actions && html`<th></th>`}
    </tr></thead>
    <tbody>
      ${rows.map((r, i) => html`<tr key=${r._key ?? i} class=${onRowClick ? "clickable" : ""}
          onClick=${onRowClick ? () => onRowClick(r) : undefined}>
        ${columns.map((c) => html`<td key=${c.key}>${c.render ? c.render(r) : r[c.key]}</td>`)}
        ${actions && html`<td class="actions" onClick=${(e) => e.stopPropagation()}>${actions(r)}</td>`}
      </tr>`)}
    </tbody>
  </table>`;
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

export function MarkdownEditor({ value, onChange, tokenBudget }) {
  const tokens = Math.max(1, Math.round((value || "").length / 4));
  const pct = tokenBudget ? Math.min(100, Math.round((tokens / tokenBudget) * 100)) : 0;
  const meterKind = pct > 100 ? "danger" : pct > 85 ? "warn" : "";
  return html`<div>
    <div class="split">
      <textarea class="codearea" value=${value} onInput=${(e) => onChange(e.target.value)}></textarea>
      <div class="card" style="margin:0;overflow:auto;max-height:420px"><${MarkdownView} text=${value} /></div>
    </div>
    ${tokenBudget && html`<div>
      <div class="help">~${tokens} tokens / orçamento ~${tokenBudget}</div>
      <div class="meter ${meterKind}"><div style=${`width:${Math.min(100, pct)}%`}></div></div>
    </div>`}
  </div>`;
}

export function CodeTextEditor({ value, onChange }) {
  return html`<textarea class="codearea" value=${value} onInput=${(e) => onChange(e.target.value)}></textarea>`;
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

  const cmd = v.unlock_cmd || "cd /home/francisco/netops && .venv/bin/python3 scripts/vault/cli.py unlock";
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
    ${canUnlock && html`<span class="help">ou no terminal:</span>`}
    <code>${cmd}</code><${CopyButton} text=${cmd} />
    <button class="sm" onClick=${refreshVault}>Re-verificar</button>
    ${modal}
  </div>`;
}

export function vaultWritable() {
  const v = vaultStore.get();
  return v.state === "cache" || v.state === "env";
}
