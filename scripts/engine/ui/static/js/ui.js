// Núcleo compartilhado da UI: re-exports, store mínimo, toasts, hooks e componentes base.
import { html } from "htm/preact";
import { useState, useEffect, useRef, useCallback, useMemo } from "preact/hooks";
import { api, ConflictError, ValidationError, VaultLockedError } from "./api.js";

export { html, useState, useEffect, useRef, useCallback, useMemo, api };
export { ConflictError, ValidationError, VaultLockedError };

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
    ${list.map((t) => html`<div key=${t.id} class="toast ${t.kind}">${t.message}</div>`)}
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
    toast.err(first ? `${first.loc}: ${first.msg}` : "Validação falhou");
    return e.fieldErrors;
  }
  if (e instanceof ConflictError) {
    if (onConflict) onConflict(e); else toast.err(e.payload?.detail || "Conflito de versão — recarregue");
    return [];
  }
  if (e instanceof VaultLockedError) { refreshVault(); toast.err("Cofre trancado — destranque no terminal"); return []; }
  toast.err(e.message || "Erro");
  return [];
}

/* ----------------------------- componentes ------------------------------ */
export const Spinner = () => html`<div class="spinner">Carregando…</div>`;

export function Badge({ kind, children }) {
  return html`<span class="badge ${kind || ""}">${children}</span>`;
}

export function CopyButton({ text, label = "Copiar" }) {
  const [done, setDone] = useState(false);
  return html`<button class="sm" onClick=${async () => {
    try { await navigator.clipboard.writeText(text); } catch (e) {}
    setDone(true); setTimeout(() => setDone(false), 1500);
  }}>${done ? "copiado ✓" : label}</button>`;
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
      <button onClick=${onClose}>Cancelar</button>
      <button class=${danger ? "danger" : "primary"} onClick=${() => { onConfirm(); onClose(); }}>Confirmar</button>
    </div>
  <//>`;
}

export function ConflictDialog({ onReload, onClose }) {
  return html`<${Modal} title="Arquivo mudou no disco" onClose=${onClose}>
    <p>Este arquivo foi modificado por fora (outro operador ou um agente de IA) desde que você abriu o editor.</p>
    <div class="modal-actions">
      <button class="primary" onClick=${() => { onReload(); onClose(); }}>Recarregar</button>
      <button onClick=${onClose}>Fechar</button>
    </div>
  <//>`;
}

export function Tabs({ tabs, active, onChange, actions }) {
  return html`<div class="tabs">
    ${tabs.map((t) => html`<button key=${t.key} class=${active === t.key ? "active" : ""}
      onClick=${() => onChange(t.key)}>${t.label}</button>`)}
    ${actions && html`<div class="tabs-actions">${actions}</div>`}
  </div>`;
}
