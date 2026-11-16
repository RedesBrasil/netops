// Painel: consumo do host (CPU/RAM/disco) e consumo de IA (tokens/valor por dia, modelo e tarefa).
// URL: #dashboard?range=7|30|90 | start=&end= | model= | metric=tokens|cost   (core/rules/urls-navegacao.md)
import { html, useState, useEffect, useMemo, useRef, api, Spinner, handleError } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { DataTable } from "../components.js";

const PALETTE = ["#2f81d4", "#e07b39", "#2fa86b", "#a45bd6", "#d6486b", "#c9a227", "#3aa6b9", "#7a8794"];
const nf = new Intl.NumberFormat("pt-BR");
const fmtTok = (n) => n >= 1e9 ? (n / 1e9).toFixed(2) + " B" : n >= 1e6 ? (n / 1e6).toFixed(2) + " M" : n >= 1e3 ? (n / 1e3).toFixed(1) + " mil" : String(n || 0);
const fmtUsd = (n) => "US$ " + (n || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtBytes = (b) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; b = b || 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return b.toFixed(i > 1 ? 1 : 0) + " " + u[i]; };
const fmtDay = (d) => d.slice(8) + "/" + d.slice(5, 7);
const levelColor = (p) => p >= 90 ? "var(--danger)" : p >= 75 ? "var(--warn)" : "var(--ok)";

function Sparkline({ values, color, height = 44 }) {
  const w = 240, n = values.length;
  if (n < 2) return html`<svg class="dash-spark" viewBox=${`0 0 ${w} ${height}`} preserveAspectRatio="none"></svg>`;
  const pts = values.map((v, i) => [(i / (n - 1)) * w, height - 2 - (Math.min(100, v) / 100) * (height - 4)]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  return html`<svg class="dash-spark" viewBox=${`0 0 ${w} ${height}`} preserveAspectRatio="none" role="img" aria-label="Histórico">
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
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!cur) return html`<${Spinner} />`;
  const up = cur.uptime ? `${Math.floor(cur.uptime / 86400)}d ${Math.floor((cur.uptime % 86400) / 3600)}h` : "—";
  return html`<div>
    <div class="dash-grid3">
      <${Gauge} title="CPU" percent=${cur.cpu.percent} history=${hist.cpu}
        detail=${`${cur.cpu.cores} núcleos · carga ${cur.cpu.load.join(" / ")}`} />
      <${Gauge} title="Memória RAM" percent=${cur.mem.percent} history=${hist.mem}
        detail=${`${fmtBytes(cur.mem.used)} de ${fmtBytes(cur.mem.total)}` + (cur.mem.swap_total ? ` · swap ${fmtBytes(cur.mem.swap_used)}/${fmtBytes(cur.mem.swap_total)}` : "")} />
      <${Gauge} title="Disco" percent=${cur.disk.percent} history=${hist.disk}
        detail=${`${fmtBytes(cur.disk.used)} de ${fmtBytes(cur.disk.total)} · ${cur.disk.path}`} />
    </div>
    <div class="help">Atualiza a cada 5 s · host ligado há ${up}. O gráfico mostra os últimos ${hist.cpu.length * 5}s desde que a tela foi aberta.</div>
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
  const seg = metric === "cost" ? null : [["output", "Saída", "#e07b39"], ["input", "Entrada", "#2f81d4"], ["cache_write", "Escrita de cache", "#a45bd6"], ["cache_read", "Leitura de cache", "#7a8794"]];
  const y = (v) => T + (H - T - B) * (1 - v / max);
  return html`<div class="dash-chart">
    <svg viewBox=${`0 0 ${W} ${H}`} role="img" aria-label=${"Consumo por dia (" + (metric === "cost" ? "valor" : "tokens") + ")"}>
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
    ${hover != null && html`<div class="dash-tip"><b>${days[hover].day.split("-").reverse().join("/")}</b><br />${fmtTok(days[hover].tokens)} tokens · ${fmtUsd(days[hover].cost)}<br />
      ${nf.format(days[hover].requests)} chamadas · saída ${fmtTok(days[hover].output)}</div>`}
    ${seg && html`<div class="dash-legend">${seg.map(([k, n, c]) => html`<span key=${k}><i style=${`background:${c}`}></i>${n}</span>`)}</div>`}
  </div>`;
}

function ModelBars({ models, metric, color }) {
  const val = (m) => metric === "cost" ? m.cost : m.tokens;
  const total = models.reduce((a, m) => a + val(m), 0) || 1;
  const max = Math.max(1e-9, ...models.map(val));
  if (!models.length) return html`<div class="help">Sem uso no período.</div>`;
  return html`<div class="dash-models">${models.map((m) => html`<div key=${m.model} class="dash-model">
    <div class="dash-model-h"><span><i style=${`background:${color(m.model)}`}></i>${m.model}</span>
      <b>${metric === "cost" ? fmtUsd(m.cost) : fmtTok(m.tokens)} <small>(${((val(m) / total) * 100).toFixed(1)}%)</small></b></div>
    <div class="dash-bar"><div style=${`width:${(val(m) / max) * 100}%;background:${color(m.model)}`}></div></div>
    <div class="dash-detail">${fmtUsd(m.cost)} · ${fmtTok(m.tokens)} tokens · entrada ${fmtTok(m.input)} · saída ${fmtTok(m.output)} · cache ${fmtTok(m.cache_read + m.cache_write)} · ${nf.format(m.requests)} chamadas</div>
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
  const rows = useMemo(() => (data ? data.tasks.map((t) => ({ ...t, _key: t.id })) : []), [data]);
  const cols = [
    { key: "title", label: "Tarefa / conversa", hideable: false, sort: true, render: (t) => t.origin === "conversa"
      ? html`<a href=${"#claude/" + t.id} title="Abrir conversa">${t.title}</a>` : html`<span>⏱ ${t.title}</span>` },
    { key: "origin", label: "Origem", sort: true },
    { key: "tokens", label: "Tokens", sort: true, render: (t) => html`<span title=${nf.format(t.tokens)}>${fmtTok(t.tokens)}</span>` },
    { key: "cost", label: "Valor (est.)", sort: true, render: (t) => fmtUsd(t.cost) },
    { key: "output", label: "Saída", sort: true, hidden: true, render: (t) => fmtTok(t.output) },
    { key: "input", label: "Entrada", sort: true, hidden: true, render: (t) => fmtTok(t.input) },
    { key: "cache_read", label: "Cache lido", sort: true, hidden: true, render: (t) => fmtTok(t.cache_read) },
    { key: "requests", label: "Chamadas", sort: true },
    { key: "models", label: "Modelos", render: (t) => t.models.join(", ") },
    { key: "last", label: "Último uso", sort: true, render: (t) => new Date(t.last * 1000).toLocaleString("pt-BR") },
  ];
  return html`<div>
    <div class="dash-filters">
      <div class="seg">${["1", "7", "30", "90"].map((v) => html`<button key=${v} class=${"sm" + (!custom && range === v ? " primary" : "")} onClick=${() => setRange(v)}>${v === "1" ? "Hoje" : v + " dias"}</button>`)}</div>
      <label>De <input type="date" value=${start} onInput=${(e) => r.setParams({ start: e.target.value, end: end || e.target.value })} /></label>
      <label>até <input type="date" value=${end} onInput=${(e) => r.setParams({ start: start || e.target.value, end: e.target.value })} /></label>
      ${custom && html`<button class="sm" onClick=${() => r.setParams({ start: "", end: "" })}>Limpar datas</button>`}
      <label>Modelo <select value=${model} onChange=${(e) => r.setParams({ model: e.target.value })}>
        <option value="">Todos</option>${(data?.available_models || []).map((m) => html`<option key=${m} value=${m}>${m}</option>`)}</select></label>
      <div class="seg"><button class=${"sm" + (metric === "tokens" ? " primary" : "")} onClick=${() => r.setParams({ metric: "" })}>Tokens</button>
        <button class=${"sm" + (metric === "cost" ? " primary" : "")} onClick=${() => r.setParams({ metric: "cost" })}>Valor</button></div>
    </div>
    ${err && html`<div class="card">Erro: ${err.message}</div>`}
    ${!data ? html`<${Spinner} />` : html`
      <div class="dash-grid4">
        <${Stat} label="Valor estimado" value=${fmtUsd(data.totals.cost)} sub=${`${data.start.split("-").reverse().join("/")} a ${data.end.split("-").reverse().join("/")}`} />
        <${Stat} label="Tokens (total)" value=${fmtTok(data.totals.tokens)} sub=${nf.format(data.totals.tokens)} />
        <${Stat} label="Entrada / Saída" value=${fmtTok(data.totals.input) + " / " + fmtTok(data.totals.output)} sub=${`cache: ${fmtTok(data.totals.cache_read)} lido · ${fmtTok(data.totals.cache_write)} escrito`} />
        <${Stat} label="Chamadas à API" value=${nf.format(data.totals.requests)} sub=${`${data.tasks.length} tarefas/conversas`} />
      </div>
      <div class="card"><h3 class="dash-h">${metric === "cost" ? "Valor por dia" : "Tokens por dia"}</h3><${DayChart} days=${data.days} metric=${metric} /></div>
      <div class="card"><h3 class="dash-h">Por modelo</h3><${ModelBars} models=${data.models} metric=${metric} color=${colorOf} /></div>
      <div class="card"><h3 class="dash-h">Tarefas que mais gastaram</h3>
        <${DataTable} tableId="dashboard-ai-tasks" urlSort="t" columns=${cols} rows=${rows} empty="Sem uso de IA no período." /></div>
      <div class="help">Valores em dólar são estimativa (tabela de preços por modelo calibrada com o custo informado pelo Claude Code); a fonte são os transcritos das conversas e das tarefas agendadas de agente neste servidor.</div>`}
  </div>`;
}

export function DashboardPage() {
  const r = useMenuRoute("dashboard");
  return html`<div class="dashboard">
    <div class="page-title"><h1>Painel</h1></div>
    <h2 class="dash-section">Host do NetOps</h2>
    <${HostSection} />
    <h2 class="dash-section">Consumo de IA</h2>
    <${AiSection} r=${r} />
  </div>`;
}
