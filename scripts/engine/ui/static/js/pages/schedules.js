// Tarefas agendadas: lista (criar/editar/remover/executar) + histórico de execuções/notificações.
// Quem dispara é o cron do sistema (/etc/cron.d/netops-scheduler → scheduler/cli.py tick);
// a tela só edita network/schedules.yaml e lê runs/schedules/. Ver scripts/engine/scheduler/SKILL.md.
// URLs (core/rules/navigation-urls.md):
//   #schedules[?q=&kind=&status=]   #schedules/<id>   #schedules/new
//   #schedules/runs[?task=&status=&unread=1]   #schedules/runs/<tarefa>/<run>
import { html, useState, useEffect, api, useResource, Spinner, toast, handleError, Modal, Tabs, ConfirmDialog, t, fmtDateTime } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, MarkdownView, Toggle, DataTable } from "../components.js";

// Labels are catalog keys, translated at render time (t() is never called at module load).
export const KINDS = [
  { key: "script", label: "schedules.kind_script", short: "schedules.kind_script_short", cls: "sc-k-script",
    help: "schedules.kind_script_help" },
  { key: "agent", label: "schedules.kind_agent", short: "schedules.kind_agent_short", cls: "sc-k-agent",
    help: "schedules.kind_agent_help" },
  { key: "hybrid", label: "schedules.kind_hybrid", short: "schedules.kind_hybrid_short", cls: "sc-k-hybrid",
    help: "schedules.kind_hybrid_help" },
];
const KIND = Object.fromEntries(KINDS.map((k) => [k.key, k]));
// [cron value, catalog suffix, Portuguese fallback (scheduleText runs in node tests without a catalog)]
const WEEKDAYS = [["1", "mon", "Seg"], ["2", "tue", "Ter"], ["3", "wed", "Qua"], ["4", "thu", "Qui"], ["5", "fri", "Sex"], ["6", "sat", "Sáb"], ["0", "sun", "Dom"]];   // i18n-ok: fallback when no catalog (node test)
// Self-contained translation helper: tests/schedules.test.mjs evaluates this file with the imports stripped.
const tr = (key, vars, fallback) => { const out = globalThis.netopsT ? globalThis.netopsT(key, vars) : key; return out === key ? fallback : out; };
const wdName = (v) => { const w = WEEKDAYS.find((x) => x[0] === v); return w ? tr("schedules.wd_" + w[1], null, w[2]) : v; };
const NOTIFY = [["auto", "schedules.notify_auto"], ["always", "schedules.notify_always"],
  ["failure", "schedules.notify_failure"], ["never", "schedules.notify_never"]];
const STATUS = { ok: ["schedules.status_ok", "ok"], error: ["schedules.status_error", "danger"], timeout: ["schedules.status_timeout", "danger"],
  skipped: ["schedules.status_skipped", "warn"], missed: ["schedules.status_missed", "warn"] };

const pad = (n) => String(n).padStart(2, "0");
const fmtTs = (s) => s ? fmtDateTime(s, { dateStyle: "short", timeStyle: "short" }) : "—";
const fmtDur = (a, b) => (a && b) ? (b - a < 60 ? Math.round(b - a) + " s" : Math.round((b - a) / 60) + " min") : "";
function relTime(s) {
  if (!s) return "";
  const d = Math.round(s - Date.now() / 1000), a = Math.abs(d);
  const v = a < 60 ? a + " s" : a < 3600 ? Math.round(a / 60) + " min" : a < 86400 ? Math.round(a / 3600) + " h" : Math.round(a / 86400) + " d";
  return d >= 0 ? t("schedules.rel_future", { v }) : t("schedules.rel_past", { v });
}

// ---- Agenda: presets amigáveis <-> {type, expr|minutes|at} ---------------- //
// Exportadas p/ teste (tests/schedules.test.mjs).
export function toSchedule(p) {
  const [h, m] = (p.time || "09:00").split(":").map((x) => parseInt(x, 10) || 0);
  switch (p.preset) {
    case "interval": return { type: "interval", minutes: Math.max(1, parseInt(p.minutes, 10) || 1) };
    case "hourly": return { type: "cron", expr: `${parseInt(p.minute, 10) || 0} * * * *` };
    case "daily": return { type: "cron", expr: `${m} ${h} * * *` };
    case "weekdays": return { type: "cron", expr: `${m} ${h} * * 1-5` };
    case "weekly": return { type: "cron", expr: `${m} ${h} * * ${(p.days && p.days.length ? p.days : ["1"]).join(",")}` };
    case "monthly": return { type: "cron", expr: `${m} ${h} ${Math.min(31, Math.max(1, parseInt(p.day, 10) || 1))} * *` };
    case "once": return { type: "once", at: p.at || "" };
    default: return { type: "cron", expr: (p.expr || "").trim() };
  }
}
export function fromSchedule(s) {
  const base = { preset: "daily", time: "09:00", minutes: 60, minute: 0, days: ["1"], day: 1, at: "", expr: "" };
  if (!s) return base;
  if (s.type === "interval") return { ...base, preset: "interval", minutes: s.minutes };
  if (s.type === "once") return { ...base, preset: "once", at: String(s.at || "").slice(0, 16) };
  const expr = String(s.expr || "").trim();
  const f = expr.split(/\s+/);
  const num = (x) => /^\d+$/.test(x);
  if (f.length === 5 && num(f[0])) {
    const time = num(f[1]) ? pad(f[1]) + ":" + pad(f[0]) : null;
    if (f[1] === "*" && f[2] === "*" && f[3] === "*" && f[4] === "*") return { ...base, preset: "hourly", minute: +f[0], expr };
    if (time && f[2] === "*" && f[3] === "*") {
      if (f[4] === "*") return { ...base, preset: "daily", time, expr };
      if (f[4] === "1-5") return { ...base, preset: "weekdays", time, expr };
      if (/^[0-6](,[0-6])*$/.test(f[4])) return { ...base, preset: "weekly", time, days: f[4].split(","), expr };
    }
    if (time && num(f[2]) && f[3] === "*" && f[4] === "*") return { ...base, preset: "monthly", time, day: +f[2], expr };
  }
  return { ...base, preset: "cron", expr };
}
export function scheduleText(s) {
  if (!s) return "";
  const p = fromSchedule(s);
  switch (p.preset) {
    case "interval": return p.minutes % 60 === 0 && p.minutes >= 60
      ? tr("schedules.every_hours", { n: p.minutes / 60 }, `A cada ${p.minutes / 60} h`)
      : tr("schedules.every_minutes", { n: p.minutes }, `A cada ${p.minutes} min`);
    case "hourly": return tr("schedules.hourly_text", { minute: pad(p.minute) }, `De hora em hora (min ${pad(p.minute)})`);
    case "daily": return tr("schedules.daily_text", { time: p.time }, `Diária às ${p.time}`);
    case "weekdays": return tr("schedules.weekdays_text", { time: p.time }, `Seg–Sex às ${p.time}`);
    case "weekly": {
      const days = p.days.map(wdName).join(", ");
      return tr("schedules.weekly_text", { days, time: p.time }, `${days} às ${p.time}`);
    }
    case "monthly": return tr("schedules.monthly_text", { day: p.day, time: p.time }, `Mensal, dia ${p.day} às ${p.time}`);
    case "once": return tr("schedules.once_text", { at: p.at.replace("T", " ") }, `Uma vez: ${p.at.replace("T", " ")}`);
    default: return `cron: ${p.expr}`;
  }
}

function KindBadge({ kind }) {
  const k = KIND[kind];
  if (!k) return html`<span class="badge sc-kind">${kind}</span>`;
  return html`<span class=${"badge sc-kind " + k.cls} title=${t(k.label)}>${t(k.short)}</span>`;
}
function StatusBadge({ status }) {
  if (!status) return null;
  const [label, cls] = STATUS[status] ? [t(STATUS[status][0]), STATUS[status][1]] : [status, ""];
  return html`<span class=${"badge " + cls}>${label}</span>`;
}

// ---- Editor (modal) ------------------------------------------------------- //
function TaskEditor({ initial, scripts, onSave, onClose, onDelete }) {
  const isNew = !initial;
  const init = initial || {};
  const [name, setName] = useState(init.name || "");
  const [description, setDescription] = useState(init.description || "");
  const [enabled, setEnabled] = useState(init.enabled !== false);
  const [kind, setKind] = useState(init.kind || "script");
  const [sch, setSch] = useState(fromSchedule(init.schedule));
  const [script, setScript] = useState(init.script || "");
  const [prompt, setPrompt] = useState(init.prompt || "");
  const [perm, setPerm] = useState((init.agent && init.agent.permissions) || "restricted");
  const [model, setModel] = useState((init.agent && init.agent.model) || "");
  const [githubAs, setGithubAs] = useState((init.agent && init.agent.github_as) || "");
  const [notify, setNotify] = useState(init.notify || "auto");
  const [timeout, setTimeoutMin] = useState(init.timeout_min || 15);
  const [prev, setPrev] = useState({ next_runs: [], error: null });
  const [errors, setErrors] = useState({});
  const [confirmDel, setConfirmDel] = useState(false);
  const up = (patch) => setSch({ ...sch, ...patch });
  const schedule = toSchedule(sch);

  useEffect(() => {
    const tm = setTimeout(() => {
      const qs = new URLSearchParams({ type: schedule.type, expr: schedule.expr || "", minutes: schedule.minutes || 0, at: schedule.at || "" });
      api.get("/schedules/preview?" + qs).then(setPrev).catch(() => {});
    }, 300);
    return () => clearTimeout(tm);
  }, [JSON.stringify(schedule)]);

  async function submit() {
    const body = { name, description, enabled, kind, schedule, notify, timeout_min: parseInt(timeout, 10) || 15 };
    if (kind !== "agent") body.script = script;
    if (kind !== "script") { body.prompt = prompt; body.agent = { permissions: perm, model, ...(githubAs.trim() ? { github_as: githubAs.trim().toLowerCase() } : {}) }; }
    const errs = await onSave(body);
    if (errs) setErrors(Object.fromEntries(errs.map((e) => [e.loc.split("/")[0], e.msg])));
  }
  const err = (k) => errors[k] && html`<div class="err">${errors[k]}</div>`;
  const usesScript = kind !== "agent", usesAgent = kind !== "script";

  return html`<${Modal} title=${isNew ? t("schedules.new_task_title") : t("schedules.edit_task_title", { name: init.name })} wide onClose=${onClose}>
    <div class="sc-form">
      <div class="sc-row">
        <label class="sc-grow">${t("common.name")}
          <input type="text" value=${name} placeholder=${t("schedules.name_placeholder")} onInput=${(e) => setName(e.target.value)} />
          ${err("name")}
        </label>
        <div class="sc-toggle"><${Toggle} checked=${enabled} onChange=${setEnabled} label=${t("schedules.enabled_label")} /></div>
      </div>
      <label><span>${t("common.description")} <span class="help">(${t("common.optional")})</span></span>
        <input type="text" value=${description} onInput=${(e) => setDescription(e.target.value)} />
      </label>

      <h3>${t("schedules.exec_type")}</h3>
      <div class="sc-kinds" role="radiogroup">
        ${KINDS.map((k) => html`<label key=${k.key} class=${"sc-kind-opt " + k.cls + (kind === k.key ? " on" : "")}>
          <input type="radio" name="kind" checked=${kind === k.key} onChange=${() => setKind(k.key)} />
          <b>${t(k.label)}</b><span class="help">${t(k.help)}</span>
        </label>`)}
      </div>

      ${usesScript && html`<label>${kind === "hybrid" ? t("schedules.script_collect") : t("schedules.script_command")}
        <input type="text" class="mono" list="sc-scripts" value=${script} placeholder="python3 scripts/tools/... --host rt-core-01"
          onInput=${(e) => setScript(e.target.value)} />
        <datalist id="sc-scripts">${(scripts || []).map((s) => html`<option key=${s} value=${s} />`)}</datalist>
        <span class="help">${t("schedules.script_help_pre")} <code>bash</code> ${t("schedules.script_help_post")}
          ${kind === "hybrid" && html` ${t("schedules.hybrid_empty_pre")} <code>{"wakeAgent": false}</code>${t("schedules.hybrid_empty_post")}`}</span>
        ${err("script")}
      </label>`}

      ${usesAgent && html`<label>${kind === "hybrid" ? t("schedules.agent_prompt_hybrid") : t("schedules.agent_prompt")}
        <textarea rows="5" value=${prompt} placeholder=${kind === "hybrid"
          ? t("schedules.prompt_placeholder_hybrid")
          : t("schedules.prompt_placeholder_agent")}
          onInput=${(e) => setPrompt(e.target.value)}></textarea>
        <span class="help">${t("schedules.prompt_help_pre")} <code>[SILENT]</code> ${t("schedules.prompt_help_post")}</span>
        ${err("prompt")}
      </label>
      <div class="sc-row">
        <label>${t("schedules.agent_permissions")}
          <select value=${perm} onChange=${(e) => setPerm(e.target.value)}>
            <option value="restricted">${t("schedules.perm_restricted")}</option>
            <option value="full">${t("schedules.perm_full")}</option>
          </select>
        </label>
        <label><span>${t("schedules.model_label")} <span class="help">${t("schedules.model_help")}</span></span>
          <input type="text" value=${model} placeholder=${t("schedules.model_placeholder")} onInput=${(e) => setModel(e.target.value)} />
        </label>
        <label><span>${t("schedules.github_as_label")} <span class="help">${t("schedules.github_as_help")}</span></span>
          <input type="text" value=${githubAs} placeholder=${t("schedules.github_as_placeholder")} onInput=${(e) => setGithubAs(e.target.value)} />
        </label>
      </div>`}

      <h3>${t("schedules.when")}</h3>
      <div class="sc-row sc-sched">
        <label>${t("schedules.frequency")}
          <select value=${sch.preset} onChange=${(e) => up({ preset: e.target.value })}>
            <option value="interval">${t("schedules.preset_interval")}</option>
            <option value="hourly">${t("schedules.preset_hourly")}</option>
            <option value="daily">${t("schedules.preset_daily")}</option>
            <option value="weekdays">${t("schedules.preset_weekdays")}</option>
            <option value="weekly">${t("schedules.preset_weekly")}</option>
            <option value="monthly">${t("schedules.preset_monthly")}</option>
            <option value="once">${t("schedules.preset_once")}</option>
            <option value="cron">${t("schedules.preset_cron")}</option>
          </select>
        </label>
        ${sch.preset === "interval" && html`<label>${t("schedules.minutes")}
          <input type="number" min="1" value=${sch.minutes} onInput=${(e) => up({ minutes: e.target.value })} style="width:110px" /></label>`}
        ${sch.preset === "hourly" && html`<label>${t("schedules.at_minute")}
          <input type="number" min="0" max="59" value=${sch.minute} onInput=${(e) => up({ minute: e.target.value })} style="width:90px" /></label>`}
        ${["daily", "weekdays", "weekly", "monthly"].includes(sch.preset) && html`<label>${t("schedules.hour")}
          <input type="time" value=${sch.time} onInput=${(e) => up({ time: e.target.value })} /></label>`}
        ${sch.preset === "monthly" && html`<label>${t("schedules.day_of_month")}
          <input type="number" min="1" max="31" value=${sch.day} onInput=${(e) => up({ day: e.target.value })} style="width:90px" /></label>`}
        ${sch.preset === "once" && html`<label>${t("schedules.date_time")}
          <input type="datetime-local" value=${sch.at} onInput=${(e) => up({ at: e.target.value })} /></label>`}
        ${sch.preset === "cron" && html`<label class="sc-grow">${t("schedules.cron_expression")}
          <input type="text" class="mono" value=${sch.expr} placeholder="0 9 * * 1-5" onInput=${(e) => up({ expr: e.target.value })} /></label>`}
      </div>
      ${sch.preset === "weekly" && html`<div class="bk-chips">
        ${WEEKDAYS.map(([v]) => html`<label key=${v} class=${"bk-chip" + (sch.days.includes(v) ? " on" : "")}>
          <input type="checkbox" checked=${sch.days.includes(v)}
            onChange=${() => up({ days: sch.days.includes(v) ? sch.days.filter((d) => d !== v) : [...sch.days, v] })} />${wdName(v)}</label>`)}
      </div>`}
      <div class="help sc-preview">
        ${prev.error ? html`<span class="err">${prev.error}</span>`
          : prev.next_runs.length ? t("schedules.next_runs", { runs: prev.next_runs.map((x) => x.replace("T", " ").slice(0, 16)).join(" · ") })
          : t("schedules.no_next_runs")}
        ${schedule.type === "cron" && schedule.expr && html` · cron <code>${schedule.expr}</code>`}
      </div>
      ${err("schedule")}

      <div class="sc-row">
        <label>${t("schedules.notify")}
          <select value=${notify} onChange=${(e) => setNotify(e.target.value)}>
            ${NOTIFY.map(([v, l]) => html`<option key=${v} value=${v}>${t(l)}</option>`)}
          </select>
        </label>
        <label>${t("schedules.timeout_min")}
          <input type="number" min="1" max="1440" value=${timeout} onInput=${(e) => setTimeoutMin(e.target.value)} style="width:110px" />
          ${err("timeout_min")}
        </label>
      </div>
    </div>
    <div class="modal-actions">
      ${!isNew && html`<button class="danger" style="margin-right:auto" onClick=${() => setConfirmDel(true)}>${t("common.remove")}</button>`}
      <button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary needs-schedules-edit" onClick=${submit}>${t("common.save")}</button>
    </div>
    ${confirmDel && html`<${ConfirmDialog} title=${t("schedules.delete_confirm_title")} danger
      message=${t("schedules.delete_confirm_message", { name: init.name })}
      onConfirm=${onDelete} onClose=${() => setConfirmDel(false)} />`}
  <//>`;
}

// ---- Detalhe de uma execução (modal) ------------------------------------- //
function RunDetail({ taskId, runId, onClose, onRead }) {
  const [rec, setRec] = useState(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let alive = true;
    (function load() {
      api.get(`/schedules/runs/${encodeURIComponent(taskId)}/${encodeURIComponent(runId)}`).then((d) => {
        if (!alive) return;
        setRec(d);
        if (d.unread) api.post("/schedules/notifications/read", { keys: [taskId + "/" + runId] }).then(onRead).catch(() => {});
        if (d.state === "running") setTimeout(load, 2500);
      }).catch(() => alive && setMissing(true));
    })();
    return () => { alive = false; };
  }, [taskId, runId]);
  return html`<${Modal} title=${t("schedules.run_title", { name: rec ? rec.task_name : taskId })} wide onClose=${onClose}>
    ${missing ? html`<div>${t("schedules.run_not_found")} <a href="#schedules/runs">${t("common.back")}</a></div>`
      : !rec ? html`<${Spinner} />` : html`<div class="sc-run">
      <div class="sc-run-meta">
        <${KindBadge} kind=${rec.kind} />
        ${rec.state === "running" ? html`<span class="badge accent">${t("schedules.running_badge")}</span>` : html`<${StatusBadge} status=${rec.status} />`}
        ${rec.silent && rec.status === "ok" && html`<span class="badge">${t("schedules.no_news")}</span>`}
        <span class="help">${rec.trigger === "manual" ? t("schedules.trigger_manual") : t("schedules.trigger_scheduled")} · ${fmtTs(rec.started_at)}
          ${rec.finished_at ? " · " + fmtDur(rec.started_at, rec.finished_at) : ""}${rec.cost_usd ? " · US$ " + rec.cost_usd.toFixed(3) : ""}</span>
        <span style="flex:1"></span>
        <a href=${"#schedules/" + encodeURIComponent(rec.task_id)}>${t("schedules.edit_task_link")}</a>
        ${rec.session_id && html`<a href=${"#claude/" + encodeURIComponent(rec.session_id)} title=${t("schedules.continue_claude_title")}>${t("schedules.continue_claude")}</a>`}
      </div>
      ${rec.error && html`<div class="sc-err">${rec.error}</div>`}
      ${rec.agent_skipped && html`<div class="help">${rec.agent_skipped}</div>`}
      ${rec.agent_output && html`<h3>${t("schedules.agent_response")}</h3><div class="card sc-md"><${MarkdownView} text=${rec.agent_output} /></div>`}
      ${rec.script && html`<h3>Script</h3><code class="sc-cmd">${rec.script}</code>
        ${rec.exit_code != null && html` <span class="help">${t("schedules.exit_code", { code: rec.exit_code })}</span>`}`}
      ${rec.script_output != null && html`<pre class="raw sc-out">${rec.script_output || t("schedules.no_output")}</pre>`}
      ${rec.log && rec.log.trim() && html`<details><summary class="help">${t("schedules.executor_log")}</summary><pre class="raw sc-out">${rec.log}</pre></details>`}
    </div>`}
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>${t("common.close")}</button></div>
  <//>`;
}

// ---- Página --------------------------------------------------------------- //
export function SchedulesPage() {
  const ov = useResource("/schedules");
  const r = useMenuRoute("schedules");
  const tab = r.segments[0] === "runs" ? "runs" : "tasks";
  const runsRes = useResource("/schedules/runs", [tab]);
  const scriptsRes = useResource("/schedules/scripts");
  const q = r.params.q || "";

  // Recarrega enquanto há execução em andamento (lista mostra "rodando" e o resultado ao fim).
  const tasks = (ov.data && ov.data.config.tasks) || [];
  const anyRunning = tasks.some((tk) => tk.state.running);
  useEffect(() => {
    const tm = setInterval(() => { ov.reload(); if (tab === "runs") runsRes.reload(); }, anyRunning ? 4000 : 30000);
    return () => clearInterval(tm);
  }, [anyRunning, tab]);

  const refreshBadge = () => dispatchEvent(new Event("netops:schedules"));
  async function save(id, body) {
    try {
      const res = id ? await api.put("/schedules/tasks/" + encodeURIComponent(id), body, ov.data.rev)
        : await api.post("/schedules/tasks", body, ov.data.rev);
      toast.ok(id ? t("schedules.task_saved") : t("schedules.task_created"));
      await ov.reload(); r.open([]); return null;
    } catch (e) {
      if (e.status === 409) { toast.err(t("schedules.conflict_reloaded")); ov.reload(); return null; }
      return handleError(e);
    }
  }
  async function remove(id) {
    try { await api.del("/schedules/tasks/" + encodeURIComponent(id), ov.data.rev); toast.ok(t("schedules.task_removed")); await ov.reload(); r.open([]); }
    catch (e) { handleError(e); ov.reload(); }
  }
  async function runNow(task) {
    try {
      const res = await api.post("/schedules/tasks/" + encodeURIComponent(task.id) + "/run");
      toast.ok(t("schedules.running_toast", { name: task.name }));
      setTimeout(ov.reload, 800);
      r.openWith(["runs", task.id, res.run_id], { q: "" });
    } catch (e) { handleError(e); }
  }
  async function toggle(task) {
    try { await api.put("/schedules/tasks/" + encodeURIComponent(task.id), { enabled: task.enabled === false }, ov.data.rev); ov.reload(); }
    catch (e) { handleError(e); ov.reload(); }
  }
  async function readAll() {
    try { await api.post("/schedules/notifications/read", {}); runsRes.reload(); ov.reload(); refreshBadge(); } catch (e) { handleError(e); }
  }
  async function installCron() {
    try { const res = await api.post("/schedules/cron/install"); res.installed ? toast.ok(t("schedules.cron_installed")) : toast.err(res.error); ov.reload(); }
    catch (e) { handleError(e); }
  }

  if (ov.error) return html`<div class="card">${t("schedules.load_error", { error: ov.error.message })}</div>`;
  if (!ov.data) return html`<${Spinner} />`;
  const { cron, timezone, unread } = ov.data;
  const itemSeg = tab === "tasks" ? r.segments[0] : null;
  const editing = itemSeg === "new" ? { initial: null } : itemSeg ? (tasks.find((tk) => tk.id === itemSeg) ? { initial: tasks.find((tk) => tk.id === itemSeg) } : null) : null;
  const runOpen = tab === "runs" && r.segments[1] && r.segments[2] ? { task: r.segments[1], run: r.segments[2] } : null;

  const kindF = r.params.kind || "", statusF = r.params.status || "";
  // Filter values ("ativas", "pausadas", "com falha") live in the URL: keep them as-is.
  const shownTasks = tasks.filter((tk) => matchText(q, tk.name, tk.id, tk.description, tk.script, tk.prompt)
    && (!kindF || tk.kind === kindF)
    && (!statusF || (statusF === "ativas" ? tk.enabled !== false : statusF === "pausadas" ? tk.enabled === false
      : statusF === "com falha" ? ["error", "timeout"].includes(tk.state.last_status) : true)));
  const allRuns = (runsRes.data && runsRes.data.runs) || [];
  const taskF = r.params.task || "", runStatusF = r.params.rstatus || "", unreadF = r.params.unread === "1";
  const shownRuns = allRuns.filter((x) => matchText(q, x.task_name, x.excerpt, x.error)
    && (!taskF || x.task_id === taskF) && (!runStatusF || x.status === runStatusF) && (!unreadF || x.unread));

  const cronCard = !cron.healthy && html`<div class="card sc-cron-warn">
    ${!cron.installed
      ? html`<b>${t("schedules.cron_not_installed_title")}</b> ${t("schedules.cron_not_installed_body")}
          <button class="sm primary" onClick=${installCron}>${t("schedules.install_now")}</button>
          ${cron.error && html`<div class="help">${cron.error}</div>`}`
      : cron.daemon_active === false
        ? html`<b>${t("schedules.cron_daemon_title")}</b> ${t("schedules.cron_daemon_body")}
            <code>apt install cron && systemctl enable --now cron</code> ${t("schedules.cron_daemon_as_root")}`
        : tasks.length
          ? html`<b>${t("schedules.dispatcher_not_run_title")}</b>${cron.last_tick ? " " + t("schedules.dispatcher_since", { when: fmtTs(cron.last_tick) }) : ""} ${t("schedules.dispatcher_not_run_body")} <code>runs/schedules/tick.log</code>.`
          : t("schedules.create_first_task")}
    <div class="help mono" style="margin-top:6px">${cron.file}: ${cron.line}</div>
  </div>`;

  const tasksView = html`<div>
    ${cronCard}
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("schedules.search_task")} count=${shownTasks.length} total=${tasks.length}
      selects=${[{ key: "kind", label: t("schedules.type"), value: kindF, options: ["script", "agent", "hybrid"] },
        { key: "status", label: t("common.status"), value: statusF, options: ["ativas", "pausadas", "com falha"] }]} />
    ${tasks.length === 0
      ? html`<div class="card bk-empty">${t("schedules.empty_pre")} <b>${t("schedules.empty_new_task")}</b> ${t("schedules.empty_post")}</div>`
      : html`<div class="bk-svc-list">
        ${shownTasks.map((tk) => html`<div key=${tk.id} class=${"card bk-svc sc-task" + (tk.enabled === false ? " off" : "")} onClick=${() => r.open([tk.id])}>
          <div class="bk-svc-main">
            <div class="bk-svc-name">
              <a href=${"#schedules/" + encodeURIComponent(tk.id)} onClick=${(e) => e.stopPropagation()}>${tk.name}</a>
              <${KindBadge} kind=${tk.kind} />
              ${tk.enabled === false ? html`<span class="badge">${t("schedules.badge_paused")}</span>` : tk.state.completed ? html`<span class="badge">${t("schedules.badge_completed")}</span>` : html`<span class="badge ok">${t("schedules.badge_active")}</span>`}
              ${tk.state.running && html`<span class="badge accent">${t("schedules.badge_running")}</span>`}
              ${tk.created_by === "chat" && html`<span class="badge" title=${t("schedules.via_chat_title")}>${t("schedules.via_chat")}</span>`}
            </div>
            <div class="help">
              ${scheduleText(tk.schedule)}
              ${tk.state.next_run_at ? html` · ${t("schedules.next_label")} <b title=${fmtTs(tk.state.next_run_at)}>${relTime(tk.state.next_run_at)}</b>` : ""}
              ${tk.state.last_run_at ? html` · ${t("schedules.last_label")} ${fmtTs(tk.state.last_run_at)} ` : " · " + t("schedules.never_ran")}
              ${tk.state.last_run_id && html`<a href=${"#schedules/runs/" + encodeURIComponent(tk.id) + "/" + tk.state.last_run_id} onClick=${(e) => e.stopPropagation()}><${StatusBadge} status=${tk.state.last_status} /></a>`}
            </div>
            ${tk.description && html`<div class="help sc-desc">${tk.description}</div>`}
            <div class="help sc-what mono">${tk.kind === "agent" ? tk.prompt : tk.script}${tk.kind === "hybrid" ? html` <span class="sc-arrow">${t("schedules.arrow_agent")}</span> ${tk.prompt}` : ""}</div>
          </div>
          <div class="bk-svc-btns" onClick=${(e) => e.stopPropagation()}>
            <button class="sm primary needs-schedules-run" onClick=${() => runNow(tk)} disabled=${!!tk.state.running}>${t("schedules.run_now")}</button>
            <button class="sm" onClick=${() => toggle(tk)}>${tk.enabled === false ? t("schedules.enable") : t("schedules.pause")}</button>
            <button class="sm" onClick=${() => r.openWith(["runs"], { task: tk.id, q: "" })}>${t("schedules.history")}</button>
            <button class="sm" onClick=${() => r.open([tk.id])}>${t("common.edit")}</button>
          </div>
        </div>`)}
      </div>`}
  </div>`;

  const runsView = html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("schedules.search_result")} count=${shownRuns.length} total=${allRuns.length}
      selects=${[{ key: "task", label: t("schedules.task"), value: taskF, options: tasks.map((tk) => tk.id) },
        { key: "rstatus", label: t("common.status"), value: runStatusF, options: Object.keys(STATUS) }]} />
    <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px">
      <label class=${"bk-chip" + (unreadF ? " on" : "")}><input type="checkbox" checked=${unreadF}
        onChange=${() => r.setParams({ unread: unreadF ? "" : "1" })} /> ${t("schedules.unread_only", { n: unread })}</label>
      <span style="flex:1"></span>
      ${unread > 0 && html`<button class="sm" onClick=${readAll}>${t("schedules.mark_all_read")}</button>`}
      <button class="sm" onClick=${runsRes.reload}>${t("common.refresh")}</button>
    </div>
    ${!runsRes.data ? html`<${Spinner} />` : shownRuns.length === 0
      ? html`<div class="card bk-empty">${allRuns.length ? t("schedules.no_runs_filtered") : t("schedules.no_runs_yet")}</div>`
      : html`<${DataTable} tableId="schedule-runs" urlSort defaultSort=${{ key: "when", dir: "desc" }}
          rows=${shownRuns.map((x) => ({ ...x, _key: x.task_id + x.run_id }))}
          rowClass=${(x) => (x.unread ? "sc-unread" : "")} onRowClick=${(x) => r.open(["runs", x.task_id, x.run_id])}
          columns=${[
            { key: "unread", label: "", menuLabel: t("schedules.col_unread"), width: 34, sort: (x) => (x.unread ? 1 : 0), render: (x) => x.unread ? html`<span class="sc-dot" title=${t("schedules.unread_dot")}></span>` : "" },
            { key: "when", label: t("schedules.col_when"), hideable: false, sort: (x) => x.started_at || "", render: (x) => html`<a href=${"#schedules/runs/" + encodeURIComponent(x.task_id) + "/" + x.run_id} onClick=${(e) => e.stopPropagation()}>${fmtTs(x.started_at)}</a>
              <div class="help">${x.trigger === "manual" ? t("schedules.trigger_manual") : t("schedules.trigger_scheduled")}</div>` },
            { key: "task", label: t("schedules.task"), sort: (x) => x.task_name || "", render: (x) => x.task_name },
            { key: "kind", label: t("schedules.type"), sort: true, render: (x) => html`<${KindBadge} kind=${x.kind} />` },
            { key: "status", label: t("common.status"), sort: (x) => (x.state === "running" ? "running" : x.status || ""), render: (x) => html`${x.state === "running" ? html`<span class="badge accent">${t("schedules.badge_running")}</span>` : html`<${StatusBadge} status=${x.status} />`}
              ${x.silent && x.status === "ok" ? html` <span class="help">${t("schedules.no_news")}</span>` : ""}` },
            { key: "result", label: t("schedules.col_result"), tdClass: "sc-excerpt", sort: (x) => x.error || x.excerpt || "", render: (x) => html`${x.error ? html`<span class="err">${x.error}</span> ` : ""}${x.excerpt}` },
          ]} />`}
  </div>`;

  return html`<div>
    <div class="page-title"><h1>${t("schedules.title")}</h1>
      <span class="help">${t("schedules.timezone", { tz: timezone })}</span>
      <span style="flex:1"></span>
      <button class="primary needs-schedules-edit" onClick=${() => r.open(["new"])}>${t("schedules.new_task_btn")}</button>
    </div>
    <${Tabs} active=${tab} onChange=${(k) => r.openWith(k === "runs" ? ["runs"] : [], { q: "" })} tabs=${[
      { key: "tasks", label: t("schedules.tab_tasks", { n: tasks.length }) },
      { key: "runs", label: unread ? t("schedules.tab_runs_unread", { count: unread }) : t("schedules.tab_runs") },
    ]} />
    <div style="margin-top:12px">
      ${itemSeg && !editing && html`<div class="card">${t("schedules.task_not_found", { id: itemSeg })} <a href="#schedules">${t("common.back")}</a></div>`}
      ${tab === "runs" ? runsView : tasksView}
    </div>
    ${editing && html`<${TaskEditor} key=${itemSeg} initial=${editing.initial} scripts=${scriptsRes.data && scriptsRes.data.scripts}
      onClose=${() => r.open([])} onSave=${(body) => save(editing.initial && editing.initial.id, body)}
      onDelete=${() => remove(editing.initial.id)} />`}
    ${runOpen && html`<${RunDetail} key=${runOpen.run} taskId=${runOpen.task} runId=${runOpen.run}
      onClose=${() => r.openWith(["runs"], {})} onRead=${() => { runsRes.reload(); ov.reload(); refreshBadge(); }} />`}
  </div>`;
}
