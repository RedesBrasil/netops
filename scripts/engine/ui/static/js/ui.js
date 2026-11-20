// Núcleo compartilhado da UI: re-exports, store mínimo, toasts, hooks e componentes base.
import { html } from "htm/preact";
import { useState, useEffect, useRef, useCallback, useMemo } from "preact/hooks";
import { api, ConflictError, ValidationError, VaultLockedError, ForbiddenError } from "./api.js";
import { t, lang, fmtDateTime, fmtDate, fmtTime, fmtNumber, errorText, onLocaleChange } from "./i18n.js";

export { html, useState, useEffect, useRef, useCallback, useMemo, api };
export { ConflictError, ValidationError, VaultLockedError, ForbiddenError };
export { t, lang, fmtDateTime, fmtDate, fmtTime, fmtNumber, errorText };

// Re-render on language change (Minha conta -> Idioma, first-access wizard).
export function useLocale() {
  const [l, setL] = useState(lang());
  useEffect(() => onLocaleChange(setL), []);
  return l;
}

/* ----------------------------- store mínimo ----------------------------- */
export function createStore(initial) {
  let value = initial; const subs = new Set();
  return {
    get: () => value,
    set: (v) => { value = typeof v === "function" ? v(value) : v; subs.forEach((f) => f(value)); },
    sub: (f) => { subs.add(f); return () => subs.delete(f); },
  };
}
export function useStore(store) {
  const [, force] = useState(0);
  useEffect(() => store.sub(() => force((n) => n + 1)), [store]);
  return store.get();
}

/* ------------------------------- toasts --------------------------------- */
const toastStore = createStore([]);
let _tid = 0;
export function toast(kind, message) {
  const id = ++_tid;
  toastStore.set((l) => [...l, { id, kind, message }]);
  setTimeout(() => toastStore.set((l) => l.filter((t) => t.id !== id)), 4200);
}
toast.ok = (m) => toast("ok", m);
toast.err = (m) => toast("err", m);
toast.info = (m) => toast("info", m);

export function ToastHost() {
  const list = useStore(toastStore);
  return html`<div class="toast-host">
    ${list.map((t) => html`<div key=${t.id} class="toast ${t.kind}"><span>${t.message}</span><button class="toast-x" title=${t("common.close")} aria-label=${t("common.close")} onClick=${() => toastStore.set((l) => l.filter((x) => x.id !== t.id))}>✕</button></div>`)}
  </div>`;
}

/* --------------------------- vault status store -------------------------- */
export const vaultStore = createStore({ state: "loading" });
export async function refreshVault() {
  try { vaultStore.set(await api.get("/vault/status")); }
  catch (e) { vaultStore.set({ state: "error", detail: String(e.message) }); }
}
let _poll = null;
export function startVaultPolling() {
  refreshVault();
  if (!_poll) {
    _poll = setInterval(refreshVault, 30000);
    // Voltou para a aba (standby/troca de aba): atualiza na hora, sem esperar o ciclo.
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshVault(); });
    window.addEventListener("focus", refreshVault);
  }
}

/* ------------------------- usuário logado (me) -------------------------- */
// /api/auth/me: quem sou + permissões efetivas. O front só ESCONDE o que não pode; quem bloqueia é o
// backend (services/authz.py). `can(perm)` = admin ou permissão no(s) grupo(s).
export const meStore = createStore(null);
export async function refreshMe() {
  try { meStore.set(await api.get("/auth/me")); }
  catch (e) { if (e.status === 401) meStore.set(null); }
  return meStore.get();
}
export function can(perm, me = meStore.get()) {
  if (!perm) return true;
  if (!me) return false;
  return !!me.is_admin || (me.permissions || []).includes(perm);
}
export function useMe() { return useStore(meStore); }
export function permLabel(perm, me = meStore.get()) {
  const p = (me?.catalog || []).find((x) => x.key === perm);
  return p ? p.label : t("common.admins_only");
}

/* ----------------------------- useResource ------------------------------ */
export function useResource(path, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try { setState({ data: await api.get(path), loading: false, error: null }); }
    catch (e) { setState({ data: null, loading: false, error: e }); }
  }, [path]);
  useEffect(() => { reload(); }, deps);
  useEffect(() => {
    const focus = () => { if (!document.querySelector(".modal-bg, .map-modal-bg")) reload(); };
    addEventListener("focus", focus);
    return () => removeEventListener("focus", focus);
  }, [reload]);
  return { ...state, reload, setData: (d) => setState((s) => ({ ...s, data: d })) };
}

/* --------------------------- handler de erros --------------------------- */
// Converte exceções de api em toast / dispara o resolvedor de conflito quando houver.
export function handleError(e, { onConflict } = {}) {
  if (e instanceof ValidationError) {
    const first = e.fieldErrors[0];
    toast.err(first ? `${first.loc}: ${first.msg}` : t("errors.validation_failed"));
    return e.fieldErrors;
  }
  if (e instanceof ConflictError) {
    if (onConflict) onConflict(e); else toast.err(errorText(e.payload, t("errors.version_conflict")));
    return [];
  }
  if (e instanceof VaultLockedError) { refreshVault(); toast.err(t("errors.vault_locked_toast")); return []; }
  if (e instanceof ForbiddenError) {
    toast.err(e.passwordChange ? t("errors.password_change_required") : (e.message || t("errors.forbidden_short")));
    return [];
  }
  toast.err(e.message || t("common.error"));
  return [];
}

/* ----------------------------- componentes ------------------------------ */
export const Spinner = () => html`<div class="spinner">${t("common.loading")}</div>`;

export function Badge({ kind, children }) {
  return html`<span class="badge ${kind || ""}">${children}</span>`;
}

export function CopyButton({ text, label }) {
  const [done, setDone] = useState(false);
  return html`<button class="sm" onClick=${async () => {
    try { await navigator.clipboard.writeText(text); } catch (e) {}
    setDone(true); setTimeout(() => setDone(false), 1500);
  }}>${done ? t("common.copied") : (label || t("common.copy"))}</button>`;
}

export function Modal({ title, children, onClose, wide, cls = "" }) {
  return html`<div class="modal-bg" onClick=${(e) => { if (e.target.classList.contains("modal-bg")) onClose?.(); }}>
    <div class="modal ${wide ? "wide" : ""} ${cls}">
      <h2>${title}</h2>
      ${children}
    </div>
  </div>`;
}

export function ConfirmDialog({ title, message, danger, onConfirm, onClose }) {
  return html`<${Modal} title=${title} onClose=${onClose}>
    <p>${message}</p>
    <div class="modal-actions">
      <button onClick=${onClose}>${t("common.cancel")}</button>
      <button class=${danger ? "danger" : "primary"} onClick=${() => { onConfirm(); onClose(); }}>${t("common.confirm")}</button>
    </div>
  <//>`;
}

export function ConflictDialog({ onReload, onClose }) {
  return html`<${Modal} title=${t("common.file_changed_title")} onClose=${onClose}>
    <p>${t("common.file_changed_body")}</p>
    <div class="modal-actions">
      <button class="primary" onClick=${() => { onReload(); onClose(); }}>${t("common.reload")}</button>
      <button onClick=${onClose}>${t("common.close")}</button>
    </div>
  <//>`;
}

export function Tabs({ tabs, active, onChange, actions }) {
  return html`<div class="tabs">
    ${tabs.map((tab) => html`<button key=${tab.key} class=${active === tab.key ? "active" : ""}
      onClick=${() => onChange(tab.key)}>${tab.label}</button>`)}
    ${actions && html`<div class="tabs-actions">${actions}</div>`}
  </div>`;
}
