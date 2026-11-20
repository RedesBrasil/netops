// Central de Avisos: alertas, avisos e pedidos de aprovação vindos de tarefas agendadas, scripts e agentes.
// Backend: routers/inbox.py + scripts/engine/inbox/ (SQLite runs/inbox.db). Ver scripts/engine/inbox/SKILL.md.
// URLs (core/rules/urls-navegacao.md):
//   #inbox[?view=pending|unread|alerts|archived|all&kind=&sev=&q=]   #inbox/<id>
import { html, useState, useEffect, api, useResource, Spinner, toast, handleError, Modal, Tabs, can, useMe, t } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, MarkdownView, DataTable } from "../components.js";
import { KIND, SEVERITY, SOURCE, sourceText, KindBadge, StatusBadge, relTime, fmtTs, decideMsg, markRead, inboxChanged,
  openInClaude, useInboxSummary } from "../inbox.js";

const VIEWS = [
  { key: "open", label: "inbox.view_open" },
  { key: "pending", label: "inbox.view_pending" },
  { key: "unread", label: "inbox.view_unread" },
  { key: "alerts", label: "inbox.view_alerts" },
  { key: "archived", label: "inbox.view_archived" },
  { key: "all", label: "inbox.view_all" },
];
// Filter values live in the URL (?kind=aviso&sev=crítico): kept as-is.
const KIND_OPTS = { aviso: "info", alerta: "alert", "aprovação": "approval" };
const SEV_OPTS = { info: "info", "atenção": "warning", "crítico": "critical" };

function ActionBox({ act, label }) {
  if (!act) return null;
  return html`<div class="ib-action">
    <div class="ib-action-head">${label}</div>
    ${act.type === "command"
      ? html`<div class="help">${t("inbox.action_command")}</div><code class="sc-cmd">${act.command}</code>`
      : html`<div class="help">${act.resume !== false ? t("inbox.action_resume") : t("inbox.action_new_agent")}
          ${act.permissions === "full" ? html` ${t("inbox.action_with")} <b class="err">${t("inbox.action_full_perm")}</b>` : " " + t("inbox.action_restricted")}${act.prompt ? ":" : t("inbox.action_continues")}</div>
        ${act.prompt && html`<div class="ib-action-prompt">${act.prompt}</div>`}`}
    <div class="help">${t("inbox.action_timeout", { n: act.timeout_min || 15 })}</div>
  </div>`;
}

function ResultBox({ res }) {
  if (!res) return null;
  const running = res.state !== "done";
  return html`<div class=${"ib-result" + (running ? "" : res.status === "ok" ? " ok" : " fail")}>
    <div class="ib-action-head">${running ? t("inbox.result_running") : res.status === "ok" ? t("inbox.result_ok") : res.status === "skipped" ? t("inbox.result_skipped") : t("inbox.result_failed")}
      ${res.finished_at && res.started_at ? html` <span class="help">· ${Math.max(1, Math.round(res.finished_at - res.started_at))} s</span>` : ""}
      ${res.cost_usd ? html` <span class="help">· US$ ${Number(res.cost_usd).toFixed(3)}</span>` : ""}</div>
    ${res.error && html`<div class="sc-err">${res.error}</div>`}
    ${res.output && (res.type === "agent"
      ? html`<div class="card sc-md"><${MarkdownView} text=${res.output} /></div>`
      : html`<pre class="raw sc-out">${res.output}</pre>`)}
    ${res.session_id && html`<a href=${"#claude/" + encodeURIComponent(res.session_id)}>${t("inbox.continue_agent_claude")}</a>`}
    ${res.followups && res.followups.length > 0 && html`<div class="help">${t("inbox.followups")} ${res.followups.map((id) => html`<a href=${"#inbox/" + id}>#${id}</a> `)}</div>`}
  </div>`;
}

function MessageDetail({ id, onClose, onChanged }) {
  const me = useMe();
  const [rec, setRec] = useState(null);
  const [missing, setMissing] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true, timer = null;
    api.get("/inbox/" + encodeURIComponent(id)).then((d) => {
      if (!alive) return;
      setRec(d);
      if (d.unread) api.post("/inbox/read", { ids: [d.id] }).then(() => { inboxChanged(); onChanged(); }).catch(() => {});
      if (d.result && d.result.state !== "done") timer = setTimeout(() => setTick((n) => n + 1), 2500);
    }).catch(() => alive && setMissing(true));
    return () => { alive = false; clearTimeout(timer); };
  }, [id, tick]);
  async function decide(d) {
    setBusy(true);
    const r = await decideMsg(rec, d, note);
    setBusy(false);
    if (r) { setRec(r); onChanged(); if (r.result) setTimeout(() => setTick((n) => n + 1), 1500); }
    else setTick((n) => n + 1);
  }
  async function archive(flag) {
    try { await api.post("/inbox/archive", { ids: [rec.id], archived: flag }); toast.ok(flag ? t("inbox.archived_toast") : t("inbox.unarchived_toast")); inboxChanged(); onChanged(); if (flag) onClose(); else setTick((n) => n + 1); }
    catch (e) { handleError(e); }
  }
  async function unread() {
    try { await api.post(`/inbox/${rec.id}/unread`); inboxChanged(); onChanged(); onClose(); } catch (e) { handleError(e); }
  }
  const k = rec && (KIND[rec.kind] || KIND.info);
  const pending = rec && rec.status === "pending";
  const mayDecide = rec && can("inbox.decide", me) && (!rec.actionable || (me && me.is_admin));
  return html`<${Modal} title=${rec ? `${k.icon} ${rec.title}` : t("inbox.message_n", { id })} wide onClose=${onClose}>
    ${missing ? html`<div>${t("inbox.message_not_found", { id })} <a href="#inbox">${t("common.back")}</a></div>`
      : !rec ? html`<${Spinner} />` : html`<div class="ib-detail">
      <div class="sc-run-meta">
        <${KindBadge} msg=${rec} /> <${StatusBadge} msg=${rec} />
        ${rec.archived && html`<span class="badge">${t("inbox.archived_badge")}</span>`}
        <span class="help">#${rec.id} · ${rec.source_label || sourceText(rec.source)} · ${fmtTs(rec.created_at)}
          ${rec.updated_at - rec.created_at > 60 ? " · " + t("inbox.updated_rel", { when: relTime(rec.updated_at) }) : ""}
          ${rec.occurrences > 1 ? html` · <b>${t("inbox.repeated_n", { n: rec.occurrences })}</b>` : ""}</span>
        <span style="flex:1"></span>
        ${rec.link && html`<a href=${rec.link}>${rec.run_id ? t("inbox.view_run") : t("inbox.open_link")}</a>`}
        ${rec.session_id && html`<a href=${"#claude/" + encodeURIComponent(rec.session_id)} title=${t("inbox.agent_conversation_title")}>${t("inbox.agent_conversation")}</a>`}
      </div>
      ${rec.body ? html`<div class="card sc-md"><${MarkdownView} text=${rec.body} /></div>` : html`<div class="help">${t("inbox.no_details")}</div>`}
      ${rec.kind === "approval" && html`<div class="ib-approval">
        <${ActionBox} act=${rec.action} label=${t("inbox.if_approve")} />
        <${ActionBox} act=${rec.reject_action} label=${t("inbox.if_reject")} />
        ${!rec.actionable && pending && html`<div class="help">${t("inbox.no_auto_action_pre")}
          (<code>inbox/cli.py wait ${rec.id}</code>) ${t("inbox.no_auto_action_post")}</div>`}
        ${rec.expires_at && pending && html`<div class="help">${t("inbox.expires", { when: fmtTs(rec.expires_at) })}</div>`}
        ${pending ? html`
          <label class="ib-note"><span class="help">${t("inbox.note_label")}</span>
            <textarea rows="2" value=${note} onInput=${(e) => setNote(e.target.value)} placeholder=${t("inbox.note_placeholder")}></textarea></label>
          ${mayDecide ? html`<div class="ib-decide">
              <button class="primary ib-approve" disabled=${busy} onClick=${() => decide("approve")}>${t("inbox.approve_btn")}</button>
              <button class="danger" disabled=${busy} onClick=${() => decide("reject")}>${t("inbox.reject_btn")}</button>
              <button disabled=${busy} onClick=${() => openInClaude(rec, note)} title=${t("inbox.discuss_title")}>${t("inbox.discuss_btn")}</button>
            </div>`
            : html`<div class="help">${rec.actionable ? t("inbox.admins_decide") : t("inbox.no_decide_perm")}</div>`}`
        : rec.decided_at ? html`<div class="help">${rec.status === "approved" ? t("inbox.approved_by") : t("inbox.rejected_by")} <b>${rec.decided_by || "?"}</b> ${t("inbox.decided_at", { when: fmtTs(rec.decided_at) })}
            ${rec.decision_note ? html` — “${rec.decision_note}”` : ""}</div>`
        : rec.status === "expired" ? html`<div class="help">${t("inbox.expired_no_decision")}</div>` : ""}
        <${ResultBox} res=${rec.result} />
      </div>`}
      ${rec.log && rec.log.trim() && html`<details><summary class="help">${t("inbox.action_log")}</summary><pre class="raw sc-out">${rec.log}</pre></details>`}
    </div>`}
    <div class="modal-actions" style="margin-top:10px">
      ${rec && !pending && html`<button onClick=${() => openInClaude(rec)} title=${t("inbox.open_claude_title")}>${t("inbox.open_claude_btn")}</button>`}
      ${rec && html`<button onClick=${unread}>${t("inbox.mark_unread")}</button>`}
      ${rec && !pending && html`<button class="needs-inbox-decide" onClick=${() => archive(!rec.archived)}>${rec.archived ? t("inbox.unarchive") : t("inbox.archive")}</button>`}
      <button onClick=${onClose}>${t("common.close")}</button>
    </div>
  <//>`;
}

export function InboxPage() {
  const r = useMenuRoute("inbox");
  const view = VIEWS.some((v) => v.key === r.params.view) ? r.params.view : "open";
  const res = useResource("/inbox?view=" + view, [view]);
  const s = useInboxSummary(true);
  const q = r.params.q || "", kindF = r.params.kind || "", sevF = r.params.sev || "";
  useEffect(() => {
    const on = () => res.reload();
    addEventListener("netops:inbox", on);
    const tm = setInterval(res.reload, 30000);
    return () => { removeEventListener("netops:inbox", on); clearInterval(tm); };
  }, [view]);

  const items = (res.data && res.data.items) || [];
  const shown = items.filter((m) => matchText(q, m.title, m.body_excerpt, m.source_label, "#" + m.id)
    && (!kindF || m.kind === KIND_OPTS[kindF]) && (!sevF || m.severity === SEV_OPTS[sevF]));
  const openId = r.segments[0];

  async function archiveRead() {
    try { const d = await api.post("/inbox/archive", { read: true }); toast.ok(t("inbox.archived_n", { n: d.changed })); inboxChanged(); }
    catch (e) { handleError(e); }
  }
  async function quick(m, d) { if (await decideMsg(m, d)) res.reload(); }

  return html`<div>
    <div class="page-title"><h1>${t("inbox.title")}</h1>
      <span class="help">${t("inbox.subtitle")}</span>
      <span style="flex:1"></span>
      ${s.unread > 0 && html`<button class="sm" onClick=${() => markRead(null)}>${t("inbox.mark_all_read")}</button>`}
      <button class="sm needs-inbox-decide" onClick=${archiveRead} title=${t("inbox.archive_read_title")}>${t("inbox.archive_read")}</button>
    </div>
    <${Tabs} active=${view} onChange=${(k) => r.pushParams({ view: k === "open" ? "" : k })} tabs=${VIEWS.map((v) => ({
      key: v.key,
      label: t(v.label) + (v.key === "pending" && s.pending ? ` (${s.pending})` : v.key === "unread" && s.unread ? ` (${s.unread})` : ""),
    }))} />
    <div style="margin-top:12px">
      <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("inbox.search")} count=${shown.length} total=${items.length}
        selects=${[{ key: "kind", label: t("inbox.col_type"), value: kindF, options: Object.keys(KIND_OPTS) },
          { key: "sev", label: t("inbox.severity"), value: sevF, options: Object.keys(SEV_OPTS) }]} />
      ${res.error ? html`<div class="card">${t("inbox.load_error", { error: res.error.message })}</div>`
        : !res.data ? html`<${Spinner} />`
        : html`<${DataTable} tableId="inbox" urlSort defaultSort=${{ key: "when", dir: "desc" }}
          rows=${shown.map((m) => ({ ...m, _key: m.id }))}
          empty=${items.length ? t("inbox.empty_filtered") : view === "pending" ? t("inbox.empty_pending")
            : t("inbox.empty")}
          rowClass=${(m) => (m.unread ? "sc-unread" : "") + (m.status === "pending" ? " ib-row-pending" : "")}
          onRowClick=${(m) => r.open([String(m.id)])}
          columns=${[
            { key: "unread", label: "", menuLabel: t("inbox.col_unread"), width: 34, sort: (m) => (m.unread ? 1 : 0), render: (m) => m.unread ? html`<span class="sc-dot" title=${t("inbox.unread_dot")}></span>` : "" },
            { key: "kind", label: t("inbox.col_type"), sort: (m) => ({ approval: 0, alert: 1, info: 2 })[m.kind] * 10 - ({ critical: 2, warning: 1, info: 0 })[m.severity], render: (m) => html`<${KindBadge} msg=${m} />` },
            { key: "title", label: t("inbox.col_message"), hideable: false, tdClass: "sc-excerpt", sort: (m) => m.title, render: (m) => html`<a href=${"#inbox/" + m.id} onClick=${(e) => e.stopPropagation()}>${m.title}</a>
              ${m.occurrences > 1 ? html` <span class="badge" title=${t("inbox.repeated_title")}>×${m.occurrences}</span>` : ""}
              ${m.body_excerpt && html`<div class="help">${m.body_excerpt}</div>`}` },
            { key: "source", label: t("inbox.col_source"), sort: (m) => m.source_label || m.source, render: (m) => html`${m.source_label || sourceText(m.source)}
              <div class="help">${sourceText(m.source)}</div>` },
            { key: "status", label: t("inbox.col_status"), sort: (m) => m.status || (m.unread ? "nova" : "lida"), render: (m) => html`<${StatusBadge} msg=${m} />
              ${m.status === "pending" && !m.actionable ? html`<div class="ib-row-btns" onClick=${(e) => e.stopPropagation()}>
                <button class="sm primary needs-inbox-decide" onClick=${() => quick(m, "approve")}>${t("inbox.approve")}</button>
                <button class="sm needs-inbox-decide" onClick=${() => quick(m, "reject")}>${t("inbox.reject")}</button></div>` : ""}` },
            { key: "when", label: t("inbox.col_when"), sort: (m) => m.updated_at, render: (m) => html`<span title=${fmtTs(m.updated_at)}>${relTime(m.updated_at)}</span>` },
          ]} />`}
    </div>
    ${openId && html`<${MessageDetail} key=${openId} id=${openId} onClose=${() => r.close()} onChanged=${res.reload} />`}
  </div>`;
}
