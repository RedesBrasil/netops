// Tarefas agendadas: lista (criar/editar/remover/executar) + histórico de execuções/notificações.
// Quem dispara é o cron do sistema (/etc/cron.d/netops-scheduler → scheduler/cli.py tick);
// a tela só edita network/schedules.yaml e lê runs/schedules/. Ver scripts/engine/scheduler/SKILL.md.
// URLs (core/rules/urls-navegacao.md):
//   #schedules[?q=&kind=&status=]   #schedules/<id>   #schedules/new
//   #schedules/runs[?task=&status=&unread=1]   #schedules/runs/<tarefa>/<run>
import { html, useState, useEffect, api, useResource, Spinner, toast, handleError, Modal, Tabs, ConfirmDialog } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, MarkdownView, Toggle } from "../components.js";

export const KINDS = [
  { key: "script", label: "Determinística / script", short: "Script", cls: "sc-k-script",
    help: "Roda um comando ou script. Sem IA: mesmo resultado sempre." },
  { key: "agent", label: "Agente de IA", short: "Agente IA", cls: "sc-k-agent",
    help: "Um agente de IA (Claude Code) executa o pedido em linguagem natural — pesquisa, analisa, decide." },
  { key: "hybrid", label: "Script + agente", short: "Script + agente", cls: "sc-k-hybrid",
    help: "O script coleta; a saída vai para o agente analisar. Saída vazia = o agente nem é acionado." },
];
const KIND = Object.fromEntries(KINDS.map((k) => [k.key, k]));
const WEEKDAYS = [["1", "Seg"], ["2", "Ter"], ["3", "Qua"], ["4", "Qui"], ["5", "Sex"], ["6", "Sáb"], ["0", "Dom"]];
const WD = Object.fromEntries(WEEKDAYS);
const NOTIFY = [["auto", "Automático (falhas + achados do agente)"], ["always", "Sempre"],
  ["failure", "Só em falha"], ["never", "Nunca"]];
const STATUS = { ok: ["ok", "ok"], error: ["falhou", "danger"], timeout: ["tempo esgotado", "danger"],
  skipped: ["pulada", "warn"], missed: ["perdida", "warn"] };

const pad = (n) => String(n).padStart(2, "0");
const fmtTs = (s) => s ? new Date(s * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—";
const fmtDur = (a, b) => (a && b) ? (b - a < 60 ? Math.round(b - a) + " s" : Math.round((b - a) / 60) + " min") : "";
function relTime(s) {
  if (!s) return "";
  const d = Math.round(s - Date.now() / 1000), a = Math.abs(d);
  const t = a < 60 ? a + " s" : a < 3600 ? Math.round(a / 60) + " min" : a < 86400 ? Math.round(a / 3600) + " h" : Math.round(a / 86400) + " d";
  return d >= 0 ? "em " + t : "há " + t;
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
    case "interval": return p.minutes % 60 === 0 && p.minutes >= 60 ? `A cada ${p.minutes / 60} h` : `A cada ${p.minutes} min`;
    case "hourly": return `De hora em hora (min ${pad(p.minute)})`;
    case "daily": return `Diária às ${p.time}`;
    case "weekdays": return `Seg–Sex às ${p.time}`;
    case "weekly": return `${p.days.map((d) => WD[d]).join(", ")} às ${p.time}`;
    case "monthly": return `Mensal, dia ${p.day} às ${p.time}`;
    case "once": return `Uma vez: ${p.at.replace("T", " ")}`;
    default: return `cron: ${p.expr}`;
  }
}

function KindBadge({ kind }) {
  const k = KIND[kind] || { short: kind, cls: "" };
  return html`<span class=${"badge sc-kind " + k.cls} title=${k.label}>${k.short}</span>`;
}
function StatusBadge({ status }) {
  if (!status) return null;
  const [label, cls] = STATUS[status] || [status, ""];
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
  const [notify, setNotify] = useState(init.notify || "auto");
  const [timeout, setTimeoutMin] = useState(init.timeout_min || 15);
  const [prev, setPrev] = useState({ next_runs: [], error: null });
  const [errors, setErrors] = useState({});
  const [confirmDel, setConfirmDel] = useState(false);
  const up = (patch) => setSch({ ...sch, ...patch });
  const schedule = toSchedule(sch);

  useEffect(() => {
    const t = setTimeout(() => {
      const qs = new URLSearchParams({ type: schedule.type, expr: schedule.expr || "", minutes: schedule.minutes || 0, at: schedule.at || "" });
      api.get("/schedules/preview?" + qs).then(setPrev).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [JSON.stringify(schedule)]);

  async function submit() {
    const body = { name, description, enabled, kind, schedule, notify, timeout_min: parseInt(timeout, 10) || 15 };
    if (kind !== "agent") body.script = script;
    if (kind !== "script") { body.prompt = prompt; body.agent = { permissions: perm, model }; }
    const errs = await onSave(body);
    if (errs) setErrors(Object.fromEntries(errs.map((e) => [e.loc.split("/")[0], e.msg])));
  }
  const err = (k) => errors[k] && html`<div class="err">${errors[k]}</div>`;
  const usesScript = kind !== "agent", usesAgent = kind !== "script";

  return html`<${Modal} title=${isNew ? "Nova tarefa agendada" : "Editar tarefa · " + init.name} wide onClose=${onClose}>
    <div class="sc-form">
      <div class="sc-row">
        <label class="sc-grow">Nome
          <input type="text" value=${name} placeholder="ex.: Changelog MikroTik diário" onInput=${(e) => setName(e.target.value)} />
          ${err("name")}
        </label>
        <div class="sc-toggle"><${Toggle} checked=${enabled} onChange=${setEnabled} label="Ativa" /></div>
      </div>
      <label><span>Descrição <span class="help">(opcional)</span></span>
        <input type="text" value=${description} onInput=${(e) => setDescription(e.target.value)} />
      </label>

      <h3>Tipo de execução</h3>
      <div class="sc-kinds" role="radiogroup">
        ${KINDS.map((k) => html`<label key=${k.key} class=${"sc-kind-opt " + k.cls + (kind === k.key ? " on" : "")}>
          <input type="radio" name="kind" checked=${kind === k.key} onChange=${() => setKind(k.key)} />
          <b>${k.label}</b><span class="help">${k.help}</span>
        </label>`)}
      </div>

      ${usesScript && html`<label>${kind === "hybrid" ? "Script de coleta" : "Comando / script"}
        <input type="text" class="mono" list="sc-scripts" value=${script} placeholder="python3 scripts/tools/... --host rt-core-01"
          onInput=${(e) => setScript(e.target.value)} />
        <datalist id="sc-scripts">${(scripts || []).map((s) => html`<option key=${s} value=${s} />`)}</datalist>
        <span class="help">Roda com <code>bash</code> na raiz do NetOps (venv no PATH). Código de saída ≠ 0 = falha.
          ${kind === "hybrid" && html` Saída vazia (ou última linha <code>{"wakeAgent": false}</code>) = o agente não é acionado.`}</span>
        ${err("script")}
      </label>`}

      ${usesAgent && html`<label>${kind === "hybrid" ? "O que o agente faz com a saída" : "Pedido para o agente"}
        <textarea rows="5" value=${prompt} placeholder=${kind === "hybrid"
          ? "ex.: Compare com o último backup e me avise só se houver mudança de firewall."
          : "ex.: Visite mikrotik.com/download/changelogs e veja se há versão nova; se citar correção do bug X, me avise."}
          onInput=${(e) => setPrompt(e.target.value)}></textarea>
        <span class="help">A resposta final vira a notificação. Se não houver nada relevante, o agente responde <code>[SILENT]</code> e você não é avisado.</span>
        ${err("prompt")}
      </label>
      <div class="sc-row">
        <label>Permissões do agente
          <select value=${perm} onChange=${(e) => setPerm(e.target.value)}>
            <option value="restricted">Restrito — ler arquivos e web (sem shell, sem escrita)</option>
            <option value="full">Completo — shell e escrita (hooks e regras do AGENTS.md valem)</option>
          </select>
        </label>
        <label><span>Modelo <span class="help">(vazio = padrão)</span></span>
          <input type="text" value=${model} placeholder="ex.: sonnet" onInput=${(e) => setModel(e.target.value)} />
        </label>
      </div>`}

      <h3>Quando</h3>
      <div class="sc-row sc-sched">
        <label>Frequência
          <select value=${sch.preset} onChange=${(e) => up({ preset: e.target.value })}>
            <option value="interval">A cada N minutos</option>
            <option value="hourly">De hora em hora</option>
            <option value="daily">Diária</option>
            <option value="weekdays">Dias úteis (seg–sex)</option>
            <option value="weekly">Semanal</option>
            <option value="monthly">Mensal</option>
            <option value="once">Uma vez</option>
            <option value="cron">Expressão cron (avançado)</option>
          </select>
        </label>
        ${sch.preset === "interval" && html`<label>Minutos
          <input type="number" min="1" value=${sch.minutes} onInput=${(e) => up({ minutes: e.target.value })} style="width:110px" /></label>`}
        ${sch.preset === "hourly" && html`<label>No minuto
          <input type="number" min="0" max="59" value=${sch.minute} onInput=${(e) => up({ minute: e.target.value })} style="width:90px" /></label>`}
        ${["daily", "weekdays", "weekly", "monthly"].includes(sch.preset) && html`<label>Hora
          <input type="time" value=${sch.time} onInput=${(e) => up({ time: e.target.value })} /></label>`}
        ${sch.preset === "monthly" && html`<label>Dia do mês
          <input type="number" min="1" max="31" value=${sch.day} onInput=${(e) => up({ day: e.target.value })} style="width:90px" /></label>`}
        ${sch.preset === "once" && html`<label>Data e hora
          <input type="datetime-local" value=${sch.at} onInput=${(e) => up({ at: e.target.value })} /></label>`}
        ${sch.preset === "cron" && html`<label class="sc-grow">Expressão (min hora dia mês dia-semana)
          <input type="text" class="mono" value=${sch.expr} placeholder="0 9 * * 1-5" onInput=${(e) => up({ expr: e.target.value })} /></label>`}
      </div>
      ${sch.preset === "weekly" && html`<div class="bk-chips">
        ${WEEKDAYS.map(([v, l]) => html`<label key=${v} class=${"bk-chip" + (sch.days.includes(v) ? " on" : "")}>
          <input type="checkbox" checked=${sch.days.includes(v)}
            onChange=${() => up({ days: sch.days.includes(v) ? sch.days.filter((d) => d !== v) : [...sch.days, v] })} />${l}</label>`)}
      </div>`}
      <div class="help sc-preview">
        ${prev.error ? html`<span class="err">${prev.error}</span>`
          : prev.next_runs.length ? html`Próximas: ${prev.next_runs.map((t) => t.replace("T", " ").slice(0, 16)).join(" · ")}`
          : "Sem próximas execuções."}
        ${schedule.type === "cron" && schedule.expr && html` · cron <code>${schedule.expr}</code>`}
      </div>
      ${err("schedule")}

      <div class="sc-row">
        <label>Notificar
          <select value=${notify} onChange=${(e) => setNotify(e.target.value)}>
            ${NOTIFY.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}
          </select>
        </label>
        <label>Tempo limite (min)
          <input type="number" min="1" max="1440" value=${timeout} onInput=${(e) => setTimeoutMin(e.target.value)} style="width:110px" />
          ${err("timeout_min")}
        </label>
      </div>
    </div>
    <div class="modal-actions">
      ${!isNew && html`<button class="danger" style="margin-right:auto" onClick=${() => setConfirmDel(true)}>Remover</button>`}
      <button onClick=${onClose}>Cancelar</button>
      <button class="primary" onClick=${submit}>Salvar</button>
    </div>
    ${confirmDel && html`<${ConfirmDialog} title="Remover tarefa?" danger
      message=${`A tarefa "${init.name}" deixa de rodar. O histórico de execuções fica em runs/schedules/.`}
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
  return html`<${Modal} title=${"Execução · " + (rec ? rec.task_name : taskId)} wide onClose=${onClose}>
    ${missing ? html`<div>Execução não encontrada. <a href="#schedules/runs">Voltar</a></div>`
      : !rec ? html`<${Spinner} />` : html`<div class="sc-run">
      <div class="sc-run-meta">
        <${KindBadge} kind=${rec.kind} />
        ${rec.state === "running" ? html`<span class="badge accent">em execução…</span>` : html`<${StatusBadge} status=${rec.status} />`}
        ${rec.silent && rec.status === "ok" && html`<span class="badge">sem novidade</span>`}
        <span class="help">${rec.trigger === "manual" ? "manual" : "agendada"} · ${fmtTs(rec.started_at)}
          ${rec.finished_at ? " · " + fmtDur(rec.started_at, rec.finished_at) : ""}${rec.cost_usd ? " · US$ " + rec.cost_usd.toFixed(3) : ""}</span>
        <span style="flex:1"></span>
        <a href=${"#schedules/" + encodeURIComponent(rec.task_id)}>editar tarefa</a>
        ${rec.session_id && html`<a href=${"#claude/" + encodeURIComponent(rec.session_id)} title="Abre a conversa do agente na aba Claude Code para continuar">continuar no Claude Code</a>`}
      </div>
      ${rec.error && html`<div class="sc-err">${rec.error}</div>`}
      ${rec.agent_skipped && html`<div class="help">${rec.agent_skipped}</div>`}
      ${rec.agent_output && html`<h3>Resposta do agente</h3><div class="card sc-md"><${MarkdownView} text=${rec.agent_output} /></div>`}
      ${rec.script && html`<h3>Script</h3><code class="sc-cmd">${rec.script}</code>
        ${rec.exit_code != null && html` <span class="help">código de saída ${rec.exit_code}</span>`}`}
      ${rec.script_output != null && html`<pre class="raw sc-out">${rec.script_output || "(sem saída)"}</pre>`}
      ${rec.log && rec.log.trim() && html`<details><summary class="help">Log do executor</summary><pre class="raw sc-out">${rec.log}</pre></details>`}
    </div>`}
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>Fechar</button></div>
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
  const anyRunning = tasks.some((t) => t.state.running);
  useEffect(() => {
    const t = setInterval(() => { ov.reload(); if (tab === "runs") runsRes.reload(); }, anyRunning ? 4000 : 30000);
    return () => clearInterval(t);
  }, [anyRunning, tab]);

  const refreshBadge = () => dispatchEvent(new Event("netops:schedules"));
  async function save(id, body) {
    try {
      const res = id ? await api.put("/schedules/tasks/" + encodeURIComponent(id), body, ov.data.rev)
        : await api.post("/schedules/tasks", body, ov.data.rev);
      toast.ok(id ? "Tarefa salva" : "Tarefa criada");
      await ov.reload(); r.open([]); return null;
    } catch (e) {
      if (e.status === 409) { toast.err("O cadastro mudou (outro operador ou o agente). Recarregado — revise e salve de novo."); ov.reload(); return null; }
      return handleError(e);
    }
  }
  async function remove(id) {
    try { await api.del("/schedules/tasks/" + encodeURIComponent(id), ov.data.rev); toast.ok("Tarefa removida"); await ov.reload(); r.open([]); }
    catch (e) { handleError(e); ov.reload(); }
  }
  async function runNow(t) {
    try {
      const res = await api.post("/schedules/tasks/" + encodeURIComponent(t.id) + "/run");
      toast.ok("Executando “" + t.name + "”…");
      setTimeout(ov.reload, 800);
      r.openWith(["runs", t.id, res.run_id], { q: "" });
    } catch (e) { handleError(e); }
  }
  async function toggle(t) {
    try { await api.put("/schedules/tasks/" + encodeURIComponent(t.id), { enabled: t.enabled === false }, ov.data.rev); ov.reload(); }
    catch (e) { handleError(e); ov.reload(); }
  }
  async function readAll() {
    try { await api.post("/schedules/notifications/read", {}); runsRes.reload(); ov.reload(); refreshBadge(); } catch (e) { handleError(e); }
  }
  async function installCron() {
    try { const res = await api.post("/schedules/cron/install"); res.installed ? toast.ok("Cron instalado") : toast.err(res.error); ov.reload(); }
    catch (e) { handleError(e); }
  }

  if (ov.error) return html`<div class="card">Erro ao carregar: ${ov.error.message}</div>`;
  if (!ov.data) return html`<${Spinner} />`;
  const { cron, timezone, unread } = ov.data;
  const itemSeg = tab === "tasks" ? r.segments[0] : null;
  const editing = itemSeg === "new" ? { initial: null } : itemSeg ? (tasks.find((t) => t.id === itemSeg) ? { initial: tasks.find((t) => t.id === itemSeg) } : null) : null;
  const runOpen = tab === "runs" && r.segments[1] && r.segments[2] ? { task: r.segments[1], run: r.segments[2] } : null;

  const kindF = r.params.kind || "", statusF = r.params.status || "";
  const shownTasks = tasks.filter((t) => matchText(q, t.name, t.id, t.description, t.script, t.prompt)
    && (!kindF || t.kind === kindF)
    && (!statusF || (statusF === "ativas" ? t.enabled !== false : statusF === "pausadas" ? t.enabled === false
      : statusF === "com falha" ? ["error", "timeout"].includes(t.state.last_status) : true)));
  const allRuns = (runsRes.data && runsRes.data.runs) || [];
  const taskF = r.params.task || "", runStatusF = r.params.rstatus || "", unreadF = r.params.unread === "1";
  const shownRuns = allRuns.filter((x) => matchText(q, x.task_name, x.excerpt, x.error)
    && (!taskF || x.task_id === taskF) && (!runStatusF || x.status === runStatusF) && (!unreadF || x.unread));

  const cronCard = !cron.healthy && html`<div class="card sc-cron-warn">
    ${!cron.installed
      ? html`<b>O cron do despachante não está instalado.</b> As tarefas não vão disparar sozinhas.
          <button class="sm primary" onClick=${installCron}>Instalar agora</button>
          ${cron.error && html`<div class="help">${cron.error}</div>`}`
      : cron.daemon_active === false
        ? html`<b>O cron não está rodando nesta máquina</b> — as tarefas não disparam sozinhas. Rode
            <code>apt install cron && systemctl enable --now cron</code> (como root).`
        : tasks.length
          ? html`<b>O despachante ainda não rodou</b>${cron.last_tick ? " desde " + fmtTs(cron.last_tick) : ""} — ele roda a cada minuto; se persistir, veja <code>runs/schedules/tick.log</code>.`
          : html`Crie a primeira tarefa — o despachante do cron já está instalado.`}
    <div class="help mono" style="margin-top:6px">${cron.file}: ${cron.line}</div>
  </div>`;

  const tasksView = html`<div>
    ${cronCard}
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar tarefa" count=${shownTasks.length} total=${tasks.length}
      selects=${[{ key: "kind", label: "Tipo", value: kindF, options: ["script", "agent", "hybrid"] },
        { key: "status", label: "Status", value: statusF, options: ["ativas", "pausadas", "com falha"] }]} />
    ${tasks.length === 0
      ? html`<div class="card bk-empty">Nenhuma tarefa agendada. Clique em <b>Nova tarefa</b> — ou peça na aba Claude Code
          (ex.: “todo dia às 8h veja o changelog do MikroTik e me avise se corrigirem o bug X”).</div>`
      : html`<div class="bk-svc-list">
        ${shownTasks.map((t) => html`<div key=${t.id} class=${"card bk-svc sc-task" + (t.enabled === false ? " off" : "")} onClick=${() => r.open([t.id])}>
          <div class="bk-svc-main">
            <div class="bk-svc-name">
              <a href=${"#schedules/" + encodeURIComponent(t.id)} onClick=${(e) => e.stopPropagation()}>${t.name}</a>
              <${KindBadge} kind=${t.kind} />
              ${t.enabled === false ? html`<span class="badge">pausada</span>` : t.state.completed ? html`<span class="badge">concluída</span>` : html`<span class="badge ok">ativa</span>`}
              ${t.state.running && html`<span class="badge accent">rodando…</span>`}
              ${t.created_by === "chat" && html`<span class="badge" title="Criada pelo agente na aba Claude Code">via chat</span>`}
            </div>
            <div class="help">
              ${scheduleText(t.schedule)}
              ${t.state.next_run_at ? html` · próxima <b title=${fmtTs(t.state.next_run_at)}>${relTime(t.state.next_run_at)}</b>` : ""}
              ${t.state.last_run_at ? html` · última ${fmtTs(t.state.last_run_at)} ` : " · nunca rodou"}
              ${t.state.last_run_id && html`<a href=${"#schedules/runs/" + encodeURIComponent(t.id) + "/" + t.state.last_run_id} onClick=${(e) => e.stopPropagation()}><${StatusBadge} status=${t.state.last_status} /></a>`}
            </div>
            ${t.description && html`<div class="help sc-desc">${t.description}</div>`}
            <div class="help sc-what mono">${t.kind === "agent" ? t.prompt : t.script}${t.kind === "hybrid" ? html` <span class="sc-arrow">→ agente:</span> ${t.prompt}` : ""}</div>
          </div>
          <div class="bk-svc-btns" onClick=${(e) => e.stopPropagation()}>
            <button class="sm primary" onClick=${() => runNow(t)} disabled=${!!t.state.running}>▶ Executar</button>
            <button class="sm" onClick=${() => toggle(t)}>${t.enabled === false ? "Ativar" : "Pausar"}</button>
            <button class="sm" onClick=${() => r.openWith(["runs"], { task: t.id, q: "" })}>Histórico</button>
            <button class="sm" onClick=${() => r.open([t.id])}>Editar</button>
          </div>
        </div>`)}
      </div>`}
  </div>`;

  const runsView = html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar no resultado" count=${shownRuns.length} total=${allRuns.length}
      selects=${[{ key: "task", label: "Tarefa", value: taskF, options: tasks.map((t) => t.id) },
        { key: "rstatus", label: "Status", value: runStatusF, options: Object.keys(STATUS) }]} />
    <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px">
      <label class=${"bk-chip" + (unreadF ? " on" : "")}><input type="checkbox" checked=${unreadF}
        onChange=${() => r.setParams({ unread: unreadF ? "" : "1" })} /> só não lidas (${unread})</label>
      <span style="flex:1"></span>
      ${unread > 0 && html`<button class="sm" onClick=${readAll}>Marcar todas como lidas</button>`}
      <button class="sm" onClick=${runsRes.reload}>Atualizar</button>
    </div>
    ${!runsRes.data ? html`<${Spinner} />` : shownRuns.length === 0
      ? html`<div class="card bk-empty">Nenhuma execução${allRuns.length ? " com esses filtros" : " ainda"}.</div>`
      : html`<div class="card bk-tablewrap"><table>
        <thead><tr><th></th><th>Quando</th><th>Tarefa</th><th>Tipo</th><th>Status</th><th>Resultado</th></tr></thead>
        <tbody>${shownRuns.map((x) => html`<tr key=${x.task_id + x.run_id} class=${"clickable" + (x.unread ? " sc-unread" : "")}
            onClick=${() => r.open(["runs", x.task_id, x.run_id])}>
          <td>${x.unread ? html`<span class="sc-dot" title="não lida"></span>` : ""}</td>
          <td><a href=${"#schedules/runs/" + encodeURIComponent(x.task_id) + "/" + x.run_id} onClick=${(e) => e.stopPropagation()}>${fmtTs(x.started_at)}</a>
            <div class="help">${x.trigger === "manual" ? "manual" : "agendada"}</div></td>
          <td>${x.task_name}</td>
          <td><${KindBadge} kind=${x.kind} /></td>
          <td>${x.state === "running" ? html`<span class="badge accent">rodando…</span>` : html`<${StatusBadge} status=${x.status} />`}
            ${x.silent && x.status === "ok" ? html` <span class="help">sem novidade</span>` : ""}</td>
          <td class="sc-excerpt">${x.error ? html`<span class="err">${x.error}</span> ` : ""}${x.excerpt}</td>
        </tr>`)}</tbody>
      </table></div>`}
  </div>`;

  return html`<div>
    <div class="page-title"><h1>Tarefas agendadas</h1>
      <span class="help">fuso ${timezone}</span>
      <span style="flex:1"></span>
      <button class="primary" onClick=${() => r.open(["new"])}>＋ Nova tarefa</button>
    </div>
    <${Tabs} active=${tab} onChange=${(k) => r.openWith(k === "runs" ? ["runs"] : [], { q: "" })} tabs=${[
      { key: "tasks", label: `Tarefas (${tasks.length})` },
      { key: "runs", label: "Execuções" + (unread ? ` · ${unread} nova${unread > 1 ? "s" : ""}` : "") },
    ]} />
    <div style="margin-top:12px">
      ${itemSeg && !editing && html`<div class="card">Tarefa '${itemSeg}' não encontrada. <a href="#schedules">Voltar</a></div>`}
      ${tab === "runs" ? runsView : tasksView}
    </div>
    ${editing && html`<${TaskEditor} key=${itemSeg} initial=${editing.initial} scripts=${scriptsRes.data && scriptsRes.data.scripts}
      onClose=${() => r.open([])} onSave=${(body) => save(editing.initial && editing.initial.id, body)}
      onDelete=${() => remove(editing.initial.id)} />`}
    ${runOpen && html`<${RunDetail} key=${runOpen.run} taskId=${runOpen.task} runId=${runOpen.run}
      onClose=${() => r.openWith(["runs"], {})} onRead=${() => { runsRes.reload(); ov.reload(); refreshBadge(); }} />`}
  </div>`;
}
