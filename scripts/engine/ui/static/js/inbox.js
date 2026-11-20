// Central de Avisos — estado compartilhado (contador), sino do topo e ações reutilizadas pela página #inbox.
// As mensagens nascem fora do console (tarefas agendadas, scripts e agentes: scripts/engine/inbox/cli.py).
import { html, useState, useEffect, useRef, api, toast, handleError, createStore, useStore, can, useMe, t, fmtDateTime } from "./ui.js";
import { navigate } from "./route.js";
import { validSessionId } from "./claude-sessions.js";

// Labels are catalog keys (translated at render time with t()); use the *Text helpers below.
export const KIND = {
  info: { icon: "ℹ️", label: "inbox.kind_info", cls: "ib-k-info" },
  alert: { icon: "⚠️", label: "inbox.kind_alert", cls: "ib-k-alert" },
  approval: { icon: "✋", label: "inbox.kind_approval", cls: "ib-k-approval" },
};
export const SEVERITY = { info: ["inbox.sev_info", ""], warning: ["inbox.sev_warning", "warn"], critical: ["inbox.sev_critical", "danger"] };
export const STATUS = { pending: ["inbox.status_pending", "warn"], approved: ["inbox.status_approved", "ok"], rejected: ["inbox.status_rejected", "danger"], expired: ["inbox.status_expired", ""] };
export const SOURCE = { schedule: "inbox.source_schedule", script: "inbox.source_script", agent: "inbox.source_agent", chat: "inbox.source_chat", system: "inbox.source_system" };
export const sourceText = (src) => (SOURCE[src] ? t(SOURCE[src]) : src);
export const statusText = (st) => (STATUS[st] ? t(STATUS[st][0]) : st);

export function relTime(s) {
  if (!s) return "";
  const a = Math.max(0, Math.round(Date.now() / 1000 - s));
  if (a < 60) return t("inbox.rel_now");
  if (a < 3600) return t("inbox.rel_ago", { v: Math.round(a / 60) + " min" });
  if (a < 86400) return t("inbox.rel_ago", { v: Math.round(a / 3600) + " h" });
  return t("inbox.rel_ago", { v: Math.round(a / 86400) + " d" });
}
export const fmtTs = (s) => s ? fmtDateTime(s, { dateStyle: "short", timeStyle: "short" }) : "—";

// ---- contador (sino + menu + título da aba) -------------------------------- //
export const inboxStore = createStore({ unread: 0, pending: 0, badge: 0, critical: 0 });
export function refreshInbox() {
  return api.get("/inbox/summary").then((d) => inboxStore.set(d)).catch(() => {});
}
// Avisa sino/menu/página que algo mudou (ler, decidir, arquivar).
export function inboxChanged() { refreshInbox(); dispatchEvent(new Event("netops:inbox")); }

// Um único polling (30 s + foco da janela) compartilhado por sino, menu e título, com contagem de usuários.
let users = 0, timer = null;
const onFocus = () => refreshInbox();
function startPolling() {
  if (users++ > 0) return;
  refreshInbox();
  timer = setInterval(refreshInbox, 30000);
  addEventListener("focus", onFocus);
}
function stopPolling() {
  if (--users > 0) return;
  clearInterval(timer); timer = null;
  removeEventListener("focus", onFocus);
}
export function useInboxSummary(enabled) {
  const s = useStore(inboxStore);
  useEffect(() => {
    if (!enabled) return undefined;
    startPolling();
    return stopPolling;
  }, [enabled]);
  return enabled ? s : { unread: 0, pending: 0, badge: 0, critical: 0 };
}

// ---- ações ----------------------------------------------------------------- //
export async function decideMsg(msg, decision, note = "") {
  try {
    const r = await api.post(`/inbox/${msg.id}/decision`, { decision, note });
    toast.ok((decision === "approve" ? t("inbox.approved_toast") : t("inbox.rejected_toast")) + (r.actionable ? " " + t("inbox.action_in_progress_suffix") : ""));
    inboxChanged();
    return r;
  } catch (e) {
    if (e.status === 409) { toast.err(t("inbox.already_decided")); inboxChanged(); return null; }
    handleError(e); return null;
  }
}
export async function markRead(ids) {
  try { await api.post("/inbox/read", ids ? { ids } : {}); inboxChanged(); } catch (e) { handleError(e); }
}

// "Abrir no Claude": leva o aviso para o prompt da aba Claude, com o contexto já escrito no campo.
// Aviso vindo de um agente (session_id) continua A MESMA conversa dele; senão abre conversa nova.
export function openInClaude(msg, extra = "") {
  const k = KIND[msg.kind] || KIND.info;
  const body = String(msg.body || msg.body_excerpt || "").trim();
  const sid = validSessionId(msg.session_id || "") ? msg.session_id : "";
  const head = t("inbox.claude_head", { kind: t(k.label).toLowerCase(), id: msg.id, title: msg.title })
    + (msg.source_label ? " " + t("inbox.claude_head_source", { source: msg.source_label }) : "")
    + (msg.status ? " " + t("inbox.claude_head_status", { status: statusText(msg.status) }) : "") + ".";
  const text = sid
    ? `${head}\n\n${extra || ""}`
    : `${head}\n\n${body.length > 4000 ? body.slice(0, 4000) + "\n…" : body}\n\n(${t("inbox.claude_details")} python3 scripts/engine/inbox/cli.py get ${msg.id})\n\n${extra || ""}`;
  try { localStorage.setItem("cc-fork-prefill", JSON.stringify({ id: sid || "new", text, t: Date.now() })); } catch (_) {}
  navigate(sid ? "#claude/" + sid : "#claude/new");
  // Conversa-alvo já aberta (não reativa): o provider aplica o prefill por evento.
  setTimeout(() => dispatchEvent(new Event("netops:claude-prefill")), 400);
}

export function KindBadge({ msg }) {
  const k = KIND[msg.kind] || KIND.info;
  const sev = msg.kind !== "info" && SEVERITY[msg.severity];
  return html`<span class=${"ib-kind " + k.cls}>${k.icon} ${t(k.label)}</span>${sev && sev[1]
    ? html` <span class=${"badge " + sev[1]}>${t(sev[0])}</span>` : ""}`;
}
export function StatusBadge({ msg }) {
  if (msg.result && msg.result.state && msg.result.state !== "done") return html`<span class="badge accent">${t("inbox.action_running")}</span>`;
  if (msg.result && msg.result.state === "done" && msg.result.status !== "ok")
    return html`<span class="badge danger" title=${msg.result.error || ""}>${STATUS[msg.status] ? t(STATUS[msg.status][0]) : ""} · ${t("inbox.action_failed_short")}</span>`;
  if (!msg.status) return msg.unread ? html`<span class="badge accent">${t("inbox.new_badge")}</span>` : html`<span class="help">${t("inbox.read_label")}</span>`;
  const [label, cls] = STATUS[msg.status] ? [t(STATUS[msg.status][0]), STATUS[msg.status][1]] : [msg.status, ""];
  return html`<span class=${"badge " + cls}>${label}</span>`;
}

// ---- sino do topo ----------------------------------------------------------- //
function BellIcon() {
  return html`<svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round" d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>`;
}

export function InboxBell() {
  const me = useMe();
  const enabled = can("inbox.view", me);
  const s = useInboxSummary(enabled);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null);
  const ref = useRef(null);
  const load = () => api.get("/inbox?view=open&limit=12").then((d) => { setItems(d.items); inboxStore.set(d.summary); }).catch(() => setItems([]));
  useEffect(() => { if (open) load(); }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const out = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    const on = () => load();
    document.addEventListener("pointerdown", out); addEventListener("keydown", esc); addEventListener("netops:inbox", on);
    return () => { document.removeEventListener("pointerdown", out); removeEventListener("keydown", esc); removeEventListener("netops:inbox", on); };
  }, [open]);
  if (!enabled) return null;
  const n = s.badge || 0;
  const go = (hash) => { setOpen(false); navigate(hash); };
  const quick = async (e, m, d) => { e.stopPropagation(); await decideMsg(m, d); load(); };
  const title = n ? t("inbox.bell_title_counts", { unread: s.unread, pending: s.pending }) : t("inbox.title");
  return html`<div class="ib-bell-wrap" ref=${ref}>
    <button type="button" class=${"ib-bell" + (n ? " has" : "") + (s.critical ? " crit" : "")} aria-label=${title} title=${title}
      aria-expanded=${open} onClick=${() => setOpen(!open)}>
      <${BellIcon} />${n > 0 && html`<span class="ib-count">${n > 99 ? "99+" : n}</span>`}
    </button>
    ${open && html`<div class="ib-pop" role="dialog" aria-label=${t("inbox.title")}>
      <div class="ib-pop-head">
        <b>${t("inbox.title")}</b>
        <span class="help">${s.pending ? t("inbox.pop_pending", { n: s.pending }) : s.unread ? t("inbox.pop_unread", { count: s.unread }) : t("inbox.pop_all_clear")}</span>
        <span style="flex:1"></span>
        ${s.unread > 0 && html`<button class="sm link-btn" onClick=${() => markRead(null).then(load)}>${t("inbox.mark_read_short")}</button>`}
      </div>
      <div class="ib-pop-list">
        ${items === null ? html`<div class="help ib-pop-empty">${t("common.loading")}</div>`
          : items.length === 0 ? html`<div class="help ib-pop-empty">${t("inbox.pop_empty")}</div>`
          : items.map((m) => html`<a key=${m.id} href=${"#inbox/" + m.id} class=${"ib-pop-item" + (m.unread ? " unread" : "") + (m.status === "pending" ? " pending" : "")}
              onClick=${(e) => { e.preventDefault(); go("#inbox/" + m.id); }}>
              <span class="ib-pop-icon">${(KIND[m.kind] || KIND.info).icon}</span>
              <span class="ib-pop-main">
                <span class="ib-pop-title">${m.title}${m.occurrences > 1 ? html` <span class="help">×${m.occurrences}</span>` : ""}</span>
                <span class="help">${m.source_label || sourceText(m.source)} · ${relTime(m.updated_at)}
                  ${m.severity === "critical" && m.kind !== "info" ? html` · <b class="err">${t("inbox.sev_critical")}</b>` : ""}</span>
                ${m.status === "pending" && html`<span class="ib-pop-btns">
                  ${m.actionable
                    ? html`<button class="sm primary" onClick=${(e) => { e.preventDefault(); e.stopPropagation(); go("#inbox/" + m.id); }}>${t("inbox.review_and_decide")}</button>`
                    : html`<button class="sm primary needs-inbox-decide" onClick=${(e) => { e.preventDefault(); quick(e, m, "approve"); }}>${t("inbox.approve")}</button>
                      <button class="sm needs-inbox-decide" onClick=${(e) => { e.preventDefault(); quick(e, m, "reject"); }}>${t("inbox.reject")}</button>`}
                </span>`}
              </span>
              ${m.unread && html`<span class="sc-dot" title=${t("inbox.unread_dot")}></span>`}
            </a>`)}
      </div>
      <div class="ib-pop-foot"><a href="#inbox" onClick=${(e) => { e.preventDefault(); go("#inbox"); }}>${t("inbox.open_inbox_link")}</a></div>
    </div>`}
  </div>`;
}
