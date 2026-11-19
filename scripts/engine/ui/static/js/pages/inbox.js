// Central de Avisos: alertas, avisos e pedidos de aprovação vindos de tarefas agendadas, scripts e agentes.
// Backend: routers/inbox.py + scripts/engine/inbox/ (SQLite runs/inbox.db). Ver scripts/engine/inbox/SKILL.md.
// URLs (core/rules/urls-navegacao.md):
//   #inbox[?view=pending|unread|alerts|archived|all&kind=&sev=&q=]   #inbox/<id>
import { html, useState, useEffect, api, useResource, Spinner, toast, handleError, Modal, Tabs, can, useMe } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, MarkdownView, DataTable } from "../components.js";
import { KIND, SEVERITY, SOURCE, KindBadge, StatusBadge, relTime, fmtTs, decideMsg, markRead, inboxChanged,
  openInClaude, useInboxSummary } from "../inbox.js";

const VIEWS = [
  { key: "open", label: "Caixa" },
  { key: "pending", label: "Aguardando aprovação" },
  { key: "unread", label: "Não lidas" },
  { key: "alerts", label: "Alertas" },
  { key: "archived", label: "Arquivadas" },
  { key: "all", label: "Todas" },
];
const KIND_OPTS = { aviso: "info", alerta: "alert", "aprovação": "approval" };
const SEV_OPTS = { info: "info", "atenção": "warning", "crítico": "critical" };

function ActionBox({ act, label }) {
  if (!act) return null;
  return html`<div class="ib-action">
    <div class="ib-action-head">${label}</div>
    ${act.type === "command"
      ? html`<div class="help">Roda este comando no servidor (como o usuário do console):</div><code class="sc-cmd">${act.command}</code>`
      : html`<div class="help">${act.resume !== false ? "Retoma a sessão do agente que pediu" : "Abre um agente novo"}
          ${act.permissions === "full" ? html` com <b class="err">permissão TOTAL (shell e escrita no servidor)</b>` : " com permissões restritas (só leitura)"}${act.prompt ? ":" : ", que continua o que propôs."}</div>
        ${act.prompt && html`<div class="ib-action-prompt">${act.prompt}</div>`}`}
    <div class="help">Tempo limite: ${act.timeout_min || 15} min.</div>
  </div>`;
}

function ResultBox({ res }) {
  if (!res) return null;
  const running = res.state !== "done";
  return html`<div class=${"ib-result" + (running ? "" : res.status === "ok" ? " ok" : " fail")}>
    <div class="ib-action-head">${running ? "Ação em andamento…" : res.status === "ok" ? "Ação concluída" : res.status === "skipped" ? "Sem ação" : "Ação falhou"}
      ${res.finished_at && res.started_at ? html` <span class="help">· ${Math.max(1, Math.round(res.finished_at - res.started_at))} s</span>` : ""}
      ${res.cost_usd ? html` <span class="help">· US$ ${Number(res.cost_usd).toFixed(3)}</span>` : ""}</div>
    ${res.error && html`<div class="sc-err">${res.error}</div>`}
    ${res.output && (res.type === "agent"
      ? html`<div class="card sc-md"><${MarkdownView} text=${res.output} /></div>`
      : html`<pre class="raw sc-out">${res.output}</pre>`)}
    ${res.session_id && html`<a href=${"#claude/" + encodeURIComponent(res.session_id)}>continuar a conversa do agente no Claude Code</a>`}
    ${res.followups && res.followups.length > 0 && html`<div class="help">Gerou novos avisos: ${res.followups.map((id) => html`<a href=${"#inbox/" + id}>#${id}</a> `)}</div>`}
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
    try { await api.post("/inbox/archive", { ids: [rec.id], archived: flag }); toast.ok(flag ? "Arquivado" : "Voltou para a caixa"); inboxChanged(); onChanged(); if (flag) onClose(); else setTick((n) => n + 1); }
    catch (e) { handleError(e); }
  }
  async function unread() {
    try { await api.post(`/inbox/${rec.id}/unread`); inboxChanged(); onChanged(); onClose(); } catch (e) { handleError(e); }
  }
  const k = rec && (KIND[rec.kind] || KIND.info);
  const pending = rec && rec.status === "pending";
  const mayDecide = rec && can("inbox.decide", me) && (!rec.actionable || (me && me.is_admin));
  return html`<${Modal} title=${rec ? `${k.icon} ${rec.title}` : "Aviso #" + id} wide onClose=${onClose}>
    ${missing ? html`<div>Aviso #${id} não encontrado (pode ter sido apagado na limpeza de arquivados). <a href="#inbox">Voltar</a></div>`
      : !rec ? html`<${Spinner} />` : html`<div class="ib-detail">
      <div class="sc-run-meta">
        <${KindBadge} msg=${rec} /> <${StatusBadge} msg=${rec} />
        ${rec.archived && html`<span class="badge">arquivado</span>`}
        <span class="help">#${rec.id} · ${rec.source_label || SOURCE[rec.source] || rec.source} · ${fmtTs(rec.created_at)}
          ${rec.updated_at - rec.created_at > 60 ? " · atualizado " + relTime(rec.updated_at) : ""}
          ${rec.occurrences > 1 ? html` · <b>repetiu ${rec.occurrences}×</b>` : ""}</span>
        <span style="flex:1"></span>
        ${rec.link && html`<a href=${rec.link}>${rec.run_id ? "ver a execução" : "abrir"}</a>`}
        ${rec.session_id && html`<a href=${"#claude/" + encodeURIComponent(rec.session_id)} title="Abre a conversa do agente que gerou o aviso">conversa do agente</a>`}
      </div>
      ${rec.body ? html`<div class="card sc-md"><${MarkdownView} text=${rec.body} /></div>` : html`<div class="help">(sem detalhes)</div>`}
      ${rec.kind === "approval" && html`<div class="ib-approval">
        <${ActionBox} act=${rec.action} label="Se você APROVAR:" />
        <${ActionBox} act=${rec.reject_action} label="Se você REPROVAR:" />
        ${!rec.actionable && pending && html`<div class="help">Sem ação automática: quem pediu consulta a decisão
          (<code>inbox/cli.py wait ${rec.id}</code>) e segue a partir dela.</div>`}
        ${rec.expires_at && pending && html`<div class="help">Expira ${fmtTs(rec.expires_at)} — sem decisão até lá, vale como reprovado.</div>`}
        ${pending ? html`
          <label class="ib-note"><span class="help">Observação (opcional — vai junto para o agente/script)</span>
            <textarea rows="2" value=${note} onInput=${(e) => setNote(e.target.value)} placeholder="ex.: pode apagar, mas mantenha os .tar de novembro"></textarea></label>
          ${mayDecide ? html`<div class="ib-decide">
              <button class="primary ib-approve" disabled=${busy} onClick=${() => decide("approve")}>✓ Aprovar</button>
              <button class="danger" disabled=${busy} onClick=${() => decide("reject")}>✕ Reprovar</button>
              <button disabled=${busy} onClick=${() => openInClaude(rec, note)} title="Leva este pedido para o prompt da aba Claude para conversar antes de decidir">💬 Discutir no Claude</button>
            </div>`
            : html`<div class="help">${rec.actionable ? "Este pedido executa uma ação no servidor: só administradores decidem." : "Seu grupo não tem permissão para decidir pedidos."}</div>`}`
        : rec.decided_at ? html`<div class="help">${rec.status === "approved" ? "Aprovado" : "Reprovado"} por <b>${rec.decided_by || "?"}</b> em ${fmtTs(rec.decided_at)}
            ${rec.decision_note ? html` — “${rec.decision_note}”` : ""}</div>`
        : rec.status === "expired" ? html`<div class="help">Expirou sem decisão.</div>` : ""}
        <${ResultBox} res=${rec.result} />
      </div>`}
      ${rec.log && rec.log.trim() && html`<details><summary class="help">Log da ação</summary><pre class="raw sc-out">${rec.log}</pre></details>`}
    </div>`}
    <div class="modal-actions" style="margin-top:10px">
      ${rec && !pending && html`<button onClick=${() => openInClaude(rec)} title="Leva o aviso para o prompt da aba Claude">💬 Abrir no Claude</button>`}
      ${rec && html`<button onClick=${unread}>Marcar como não lida</button>`}
      ${rec && !pending && html`<button class="needs-inbox-decide" onClick=${() => archive(!rec.archived)}>${rec.archived ? "Desarquivar" : "Arquivar"}</button>`}
      <button onClick=${onClose}>Fechar</button>
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
    const t = setInterval(res.reload, 30000);
    return () => { removeEventListener("netops:inbox", on); clearInterval(t); };
  }, [view]);

  const items = (res.data && res.data.items) || [];
  const shown = items.filter((m) => matchText(q, m.title, m.body_excerpt, m.source_label, "#" + m.id)
    && (!kindF || m.kind === KIND_OPTS[kindF]) && (!sevF || m.severity === SEV_OPTS[sevF]));
  const openId = r.segments[0];

  async function archiveRead() {
    try { const d = await api.post("/inbox/archive", { read: true }); toast.ok(`${d.changed} arquivado(s)`); inboxChanged(); }
    catch (e) { handleError(e); }
  }
  async function quick(m, d) { if (await decideMsg(m, d)) res.reload(); }

  return html`<div>
    <div class="page-title"><h1>Central de Avisos</h1>
      <span class="help">alertas, avisos e pedidos de aprovação das tarefas agendadas, scripts e agentes</span>
      <span style="flex:1"></span>
      ${s.unread > 0 && html`<button class="sm" onClick=${() => markRead(null)}>Marcar todas como lidas</button>`}
      <button class="sm needs-inbox-decide" onClick=${archiveRead} title="Tira da caixa tudo o que já foi lido e não está aguardando você">Arquivar lidas</button>
    </div>
    <${Tabs} active=${view} onChange=${(k) => r.pushParams({ view: k === "open" ? "" : k })} tabs=${VIEWS.map((v) => ({
      key: v.key,
      label: v.label + (v.key === "pending" && s.pending ? ` (${s.pending})` : v.key === "unread" && s.unread ? ` (${s.unread})` : ""),
    }))} />
    <div style="margin-top:12px">
      <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar aviso" count=${shown.length} total=${items.length}
        selects=${[{ key: "kind", label: "Tipo", value: kindF, options: Object.keys(KIND_OPTS) },
          { key: "sev", label: "Gravidade", value: sevF, options: Object.keys(SEV_OPTS) }]} />
      ${res.error ? html`<div class="card">Erro ao carregar: ${res.error.message}</div>`
        : !res.data ? html`<${Spinner} />`
        : html`<${DataTable} tableId="inbox" urlSort defaultSort=${{ key: "when", dir: "desc" }}
          rows=${shown.map((m) => ({ ...m, _key: m.id }))}
          empty=${items.length ? "Nenhum aviso com esses filtros." : view === "pending" ? "Nada aguardando sua aprovação."
            : "Nenhum aviso. Tarefas agendadas, scripts e agentes publicam aqui alertas e pedidos de aprovação (ver scripts/engine/inbox/SKILL.md)."}
          rowClass=${(m) => (m.unread ? "sc-unread" : "") + (m.status === "pending" ? " ib-row-pending" : "")}
          onRowClick=${(m) => r.open([String(m.id)])}
          columns=${[
            { key: "unread", label: "", menuLabel: "Não lida", width: 34, sort: (m) => (m.unread ? 1 : 0), render: (m) => m.unread ? html`<span class="sc-dot" title="não lida"></span>` : "" },
            { key: "kind", label: "Tipo", sort: (m) => ({ approval: 0, alert: 1, info: 2 })[m.kind] * 10 - ({ critical: 2, warning: 1, info: 0 })[m.severity], render: (m) => html`<${KindBadge} msg=${m} />` },
            { key: "title", label: "Aviso", hideable: false, tdClass: "sc-excerpt", sort: (m) => m.title, render: (m) => html`<a href=${"#inbox/" + m.id} onClick=${(e) => e.stopPropagation()}>${m.title}</a>
              ${m.occurrences > 1 ? html` <span class="badge" title="o mesmo achado repetiu">×${m.occurrences}</span>` : ""}
              ${m.body_excerpt && html`<div class="help">${m.body_excerpt}</div>`}` },
            { key: "source", label: "Origem", sort: (m) => m.source_label || m.source, render: (m) => html`${m.source_label || SOURCE[m.source] || m.source}
              <div class="help">${SOURCE[m.source] || m.source}</div>` },
            { key: "status", label: "Situação", sort: (m) => m.status || (m.unread ? "nova" : "lida"), render: (m) => html`<${StatusBadge} msg=${m} />
              ${m.status === "pending" && !m.actionable ? html`<div class="ib-row-btns" onClick=${(e) => e.stopPropagation()}>
                <button class="sm primary needs-inbox-decide" onClick=${() => quick(m, "approve")}>Aprovar</button>
                <button class="sm needs-inbox-decide" onClick=${() => quick(m, "reject")}>Reprovar</button></div>` : ""}` },
            { key: "when", label: "Quando", sort: (m) => m.updated_at, render: (m) => html`<span title=${fmtTs(m.updated_at)}>${relTime(m.updated_at)}</span>` },
          ]} />`}
    </div>
    ${openId && html`<${MessageDetail} key=${openId} id=${openId} onClose=${() => r.close()} onChanged=${res.reload} />`}
  </div>`;
}
