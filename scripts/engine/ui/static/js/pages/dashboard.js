// Painel: consumo do host (CPU/RAM/disco) e consumo de IA (tokens/valor por dia, modelo e tarefa).
// URL: #dashboard?range=7|30|90 | start=&end= | model= | metric=tokens|cost   (core/rules/navigation-urls.md)
import { html, useState, useEffect, useMemo, useRef, api, Spinner, handleError, t, fmtNumber, fmtDate, fmtDateTime } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { DataTable } from "../components.js";

const PALETTE = ["#2f81d4", "#e07b39", "#2fa86b", "#a45bd6", "#d6486b", "#c9a227", "#3aa6b9", "#7a8794"];
const nf = { format: (n) => fmtNumber(n) };
const fmtTok = (n) => n >= 1e9 ? (n / 1e9).toFixed(2) + " B" : n >= 1e6 ? (n / 1e6).toFixed(2) + " M" : n >= 1e3 ? (n / 1e3).toFixed(1) + " " + t("dashboard.unit_thousand") : String(n || 0);
const fmtUsd = (n) => "US$ " + fmtNumber(n || 0, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtBytes = (b) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; b = b || 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return b.toFixed(i > 1 ? 1 : 0) + " " + u[i]; };
const fmtDay = (d) => fmtDate(d + "T00:00:00", { day: "2-digit", month: "2-digit" });
const fmtFullDay = (d) => fmtDate(d + "T00:00:00");
// Server values for the "origin" column ("conversa" is also compared): display only is translated.
const ORIGIN = { conversa: "dashboard.origin_conversation", agendada: "dashboard.origin_scheduled" };
const levelColor = (p) => p >= 90 ? "var(--danger)" : p >= 75 ? "var(--warn)" : "var(--ok)";

function Sparkline({ values, color, height = 44 }) {
  const w = 240, n = values.length;
  if (n < 2) return html`<svg class="dash-spark" viewBox=${`0 0 ${w} ${height}`} preserveAspectRatio="none"></svg>`;
  const pts = values.map((v, i) => [(i / (n - 1)) * w, height - 2 - (Math.min(100, v) / 100) * (height - 4)]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  return html`<svg class="dash-spark" viewBox=${`0 0 ${w} ${height}`} preserveAspectRatio="none" role="img" aria-label=${t("dashboard.history")}>
    <path d=${line + ` L${w} ${height} L0 ${height} Z`} fill=${color} opacity="0.15" />
    <path d=${line} fill="none" stroke=${color} stroke-width="1.6" vector-effect="non-scaling-stroke" /></svg>`;
}

function Gauge({ title, percent, detail, history }) {
  const c = levelColor(percent);
  return html`<div class="card dash-gauge">
    <div class="dash-gauge-top"><span class="dash-label">${title}</span><b class="dash-big" style=${`color:${c}`}>${percent.toFixed(1)}%</b></div>
    <div class="dash-bar"><div style=${`width:${Math.min(100, percent)}%;background:${c}`}></div></div>
    <div class="dash-detail">${detail}</div>
    <${Sparkline} values=${history} color=${c} />
  </div>`;
}

function HostSection() {
  const [cur, setCur] = useState(null);
  const [hist, setHist] = useState({ cpu: [], mem: [], disk: [] });
  useEffect(() => {
    let alive = true;
    const load = () => api.get("/dashboard/host").then((d) => {
      if (!alive) return;
      setCur(d);
      setHist((h) => ({ cpu: [...h.cpu, d.cpu.percent].slice(-60), mem: [...h.mem, d.mem.percent].slice(-60), disk: [...h.disk, d.disk.percent].slice(-60) }));
    }).catch(() => {});
    load();
    const tm = setInterval(load, 5000);
    return () => { alive = false; clearInterval(tm); };
  }, []);
  if (!cur) return html`<${Spinner} />`;
  const up = cur.uptime ? `${Math.floor(cur.uptime / 86400)}d ${Math.floor((cur.uptime % 86400) / 3600)}h` : "—";
  return html`<div>
    <div class="dash-grid3">
      <${Gauge} title="CPU" percent=${cur.cpu.percent} history=${hist.cpu}
        detail=${t("dashboard.cpu_detail", { cores: cur.cpu.cores, load: cur.cpu.load.join(" / ") })} />
      <${Gauge} title=${t("dashboard.ram")} percent=${cur.mem.percent} history=${hist.mem}
        detail=${t("dashboard.used_of", { used: fmtBytes(cur.mem.used), total: fmtBytes(cur.mem.total) }) + (cur.mem.swap_total ? ` · swap ${fmtBytes(cur.mem.swap_used)}/${fmtBytes(cur.mem.swap_total)}` : "")} />
      <${Gauge} title=${t("dashboard.disk")} percent=${cur.disk.percent} history=${hist.disk}
        detail=${t("dashboard.used_of", { used: fmtBytes(cur.disk.used), total: fmtBytes(cur.disk.total) }) + ` · ${cur.disk.path}`} />
    </div>
    <div class="help">${t("dashboard.host_help", { up, secs: hist.cpu.length * 5 })}</div>
  </div>`;
}

function Stat({ label, value, sub }) {
  return html`<div class="card dash-stat"><span class="dash-label">${label}</span><b class="dash-big">${value}</b>${sub && html`<span class="dash-detail">${sub}</span>`}</div>`;
}

// Barras empilhadas por dia (tokens: entrada/saída/cache; valor: custo).
function DayChart({ days, metric }) {
  const [hover, setHover] = useState(null);
  const W = 900, H = 240, L = 54, B = 26, T = 10, R = 8;
  const val = (d) => metric === "cost" ? d.cost : d.tokens;
  const max = Math.max(1e-9, ...days.map(val));
  const bw = (W - L - R) / days.length;
  const fmt = metric === "cost" ? fmtUsd : fmtTok;
  const step = Math.ceil(days.length / 12);
  const seg = metric === "cost" ? null : [["output", t("dashboard.output"), "#e07b39"], ["input", t("dashboard.input"), "#2f81d4"], ["cache_write", t("dashboard.cache_write"), "#a45bd6"], ["cache_read", t("dashboard.cache_read"), "#7a8794"]];
  const y = (v) => T + (H - T - B) * (1 - v / max);
  return html`<div class="dash-chart">
    <svg viewBox=${`0 0 ${W} ${H}`} role="img" aria-label=${metric === "cost" ? t("dashboard.chart_aria_cost") : t("dashboard.chart_aria_tokens")}>
      ${[0, 0.25, 0.5, 0.75, 1].map((f) => html`<g key=${f}><line x1=${L} x2=${W - R} y1=${y(max * f)} y2=${y(max * f)} stroke="var(--border)" stroke-width="1" />
        <text x=${L - 6} y=${y(max * f) + 4} text-anchor="end" class="dash-axis">${fmt(max * f)}</text></g>`)}
      ${days.map((d, i) => {
        const x = L + i * bw + bw * 0.12, w = bw * 0.76;
        let acc = 0;
        const parts = seg ? seg.map(([k, , c]) => { const h = (d[k] / max) * (H - T - B); acc += h; return html`<rect key=${k} x=${x} y=${H - B - acc} width=${w} height=${Math.max(0, h)} fill=${c} />`; })
          : html`<rect x=${x} y=${y(d.cost)} width=${w} height=${Math.max(0, H - B - y(d.cost))} fill="#2f81d4" />`;
        return html`<g key=${d.day} onMouseEnter=${() => setHover(i)} onMouseLeave=${() => setHover(null)}>
          <rect x=${L + i * bw} y=${T} width=${bw} height=${H - T - B} fill=${hover === i ? "var(--accent-weak)" : "transparent"} opacity="0.5" />${parts}
          ${i % step === 0 && html`<text x=${x + w / 2} y=${H - 8} text-anchor="middle" class="dash-axis">${fmtDay(d.day)}</text>`}</g>`;
      })}
    </svg>
    ${hover != null && html`<div class="dash-tip"><b>${fmtFullDay(days[hover].day)}</b><br />${fmtTok(days[hover].tokens)} tokens · ${fmtUsd(days[hover].cost)}<br />
      ${t("dashboard.tip_calls_output", { calls: nf.format(days[hover].requests), output: fmtTok(days[hover].output) })}</div>`}
    ${seg && html`<div class="dash-legend">${seg.map(([k, n, c]) => html`<span key=${k}><i style=${`background:${c}`}></i>${n}</span>`)}</div>`}
  </div>`;
}

function ModelBars({ models, metric, color }) {
  const val = (m) => metric === "cost" ? m.cost : m.tokens;
  const total = models.reduce((a, m) => a + val(m), 0) || 1;
  const max = Math.max(1e-9, ...models.map(val));
  if (!models.length) return html`<div class="help">${t("dashboard.no_usage")}</div>`;
  return html`<div class="dash-models">${models.map((m) => html`<div key=${m.model} class="dash-model">
    <div class="dash-model-h"><span><i style=${`background:${color(m.model)}`}></i>${m.model}</span>
      <b>${metric === "cost" ? fmtUsd(m.cost) : fmtTok(m.tokens)} <small>(${((val(m) / total) * 100).toFixed(1)}%)</small></b></div>
    <div class="dash-bar"><div style=${`width:${(val(m) / max) * 100}%;background:${color(m.model)}`}></div></div>
    <div class="dash-detail">${fmtUsd(m.cost)} · ${t("dashboard.model_detail", { tokens: fmtTok(m.tokens), input: fmtTok(m.input), output: fmtTok(m.output), cache: fmtTok(m.cache_read + m.cache_write), calls: nf.format(m.requests) })}</div>
  </div>`)}</div>`;
}

function AiSection({ r }) {
  const { range = "30", start = "", end = "", model = "", metric = "tokens" } = r.params;
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const reqId = useRef(0);
  useEffect(() => {
    const id = ++reqId.current;
    const qs = new URLSearchParams({ tz: String(new Date().getTimezoneOffset()) });
    if (start) { qs.set("start", start); if (end) qs.set("end", end); } else qs.set("days", range);
    if (model) qs.set("model", model);
    setErr(null);
    api.get("/dashboard/ai?" + qs).then((d) => { if (id === reqId.current) setData(d); }).catch((e) => { if (id === reqId.current) { setErr(e); handleError(e); } });
  }, [range, start, end, model]);
  const colorOf = useMemo(() => {
    const all = data ? data.available_models : [];
    return (m) => PALETTE[Math.max(0, all.indexOf(m)) % PALETTE.length];
  }, [data]);
  const custom = !!start;
  const setRange = (v) => r.setParams({ range: v === "30" ? "" : v, start: "", end: "" });
  const rows = useMemo(() => (data ? data.tasks.map((tk) => ({ ...tk, _key: tk.id })) : []), [data]);
  const cols = [
    { key: "title", label: t("dashboard.col_task"), hideable: false, sort: true, render: (tk) => tk.origin === "conversa"
      ? html`<a href=${"#claude/" + tk.id} title=${t("dashboard.open_conversation")}>${tk.title}</a>` : html`<span>⏱ ${tk.title}</span>` },
    { key: "origin", label: t("dashboard.col_origin"), sort: true, render: (tk) => (ORIGIN[tk.origin] ? t(ORIGIN[tk.origin]) : tk.origin) },
    { key: "tokens", label: "Tokens", sort: true, render: (tk) => html`<span title=${nf.format(tk.tokens)}>${fmtTok(tk.tokens)}</span>` },
    { key: "cost", label: t("dashboard.col_cost"), sort: true, render: (tk) => fmtUsd(tk.cost) },
    { key: "output", label: t("dashboard.output"), sort: true, hidden: true, render: (tk) => fmtTok(tk.output) },
    { key: "input", label: t("dashboard.input"), sort: true, hidden: true, render: (tk) => fmtTok(tk.input) },
    { key: "cache_read", label: t("dashboard.col_cache_read"), sort: true, hidden: true, render: (tk) => fmtTok(tk.cache_read) },
    { key: "requests", label: t("dashboard.col_calls"), sort: true },
    { key: "models", label: t("dashboard.col_models"), render: (tk) => tk.models.join(", ") },
    { key: "last", label: t("dashboard.col_last_used"), sort: true, render: (tk) => fmtDateTime(tk.last) },
  ];
  return html`<div>
    <div class="dash-filters">
      <div class="seg">${["1", "7", "30", "90"].map((v) => html`<button key=${v} class=${"sm" + (!custom && range === v ? " primary" : "")} onClick=${() => setRange(v)}>${v === "1" ? t("dashboard.range_today") : t("dashboard.range_days", { n: v })}</button>`)}</div>
      <label>${t("dashboard.date_from")} <input type="date" value=${start} onInput=${(e) => r.setParams({ start: e.target.value, end: end || e.target.value })} /></label>
      <label>${t("dashboard.date_to")} <input type="date" value=${end} onInput=${(e) => r.setParams({ start: start || e.target.value, end: e.target.value })} /></label>
      ${custom && html`<button class="sm" onClick=${() => r.setParams({ start: "", end: "" })}>${t("dashboard.clear_dates")}</button>`}
      <label>${t("dashboard.model")} <select value=${model} onChange=${(e) => r.setParams({ model: e.target.value })}>
        <option value="">${t("common.all")}</option>${(data?.available_models || []).map((m) => html`<option key=${m} value=${m}>${m}</option>`)}</select></label>
      <div class="seg"><button class=${"sm" + (metric === "tokens" ? " primary" : "")} onClick=${() => r.setParams({ metric: "" })}>Tokens</button>
        <button class=${"sm" + (metric === "cost" ? " primary" : "")} onClick=${() => r.setParams({ metric: "cost" })}>${t("dashboard.metric_cost")}</button></div>
    </div>
    ${err && html`<div class="card">${t("dashboard.error", { error: err.message })}</div>`}
    ${!data ? html`<${Spinner} />` : html`
      <div class="dash-grid4">
        <${Stat} label=${t("dashboard.stat_cost")} value=${fmtUsd(data.totals.cost)} sub=${t("dashboard.period", { start: fmtFullDay(data.start), end: fmtFullDay(data.end) })} />
        <${Stat} label=${t("dashboard.stat_tokens")} value=${fmtTok(data.totals.tokens)} sub=${nf.format(data.totals.tokens)} />
        <${Stat} label=${t("dashboard.stat_in_out")} value=${fmtTok(data.totals.input) + " / " + fmtTok(data.totals.output)} sub=${t("dashboard.stat_cache", { read: fmtTok(data.totals.cache_read), written: fmtTok(data.totals.cache_write) })} />
        <${Stat} label=${t("dashboard.stat_calls")} value=${nf.format(data.totals.requests)} sub=${t("dashboard.stat_tasks", { n: data.tasks.length })} />
      </div>
      <div class="card"><h3 class="dash-h">${metric === "cost" ? t("dashboard.cost_per_day") : t("dashboard.tokens_per_day")}</h3><${DayChart} days=${data.days} metric=${metric} /></div>
      <div class="card"><h3 class="dash-h">${t("dashboard.by_model")}</h3><${ModelBars} models=${data.models} metric=${metric} color=${colorOf} /></div>
      <div class="card"><h3 class="dash-h">${t("dashboard.top_tasks")}</h3>
        <${DataTable} tableId="dashboard-ai-tasks" urlSort="t" columns=${cols} rows=${rows} empty=${t("dashboard.no_ai_usage")} /></div>
      <div class="help">${t("dashboard.cost_note")}</div>`}
  </div>`;
}

export function DashboardPage() {
  const r = useMenuRoute("dashboard");
  return html`<div class="dashboard">
    <div class="page-title"><h1>${t("dashboard.title")}</h1></div>
    <h2 class="dash-section">${t("dashboard.host_section")}</h2>
    <${HostSection} />
    <h2 class="dash-section">${t("dashboard.ai_section")}</h2>
    <${AiSection} r=${r} />
  </div>`;
}
