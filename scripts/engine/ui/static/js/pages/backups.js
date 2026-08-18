// Backups: duas sub-abas.
//  - "Serviços de Backup": lista de serviços (estilo jobs do Proxmox); criar/editar em modal.
//  - "Armazenamento de Backup": visualizar/baixar os configs coletados.
// Config só — a execução no horário é feita por um runner externo.
import { html, useState, useEffect, useRef, api, useResource, Spinner, toast, handleError, Modal, Tabs } from "../ui.js";
import { authToken } from "../api.js";

const FREQS = [["daily", "Diária"], ["weekly", "Semanal"], ["hourly", "De hora em hora"]];
const WEEKDAYS = [["mon", "Seg"], ["tue", "Ter"], ["wed", "Qua"], ["thu", "Qui"],
  ["fri", "Sex"], ["sat", "Sáb"], ["sun", "Dom"]];
const WD = Object.fromEntries(WEEKDAYS);

const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort();
const fmtSize = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
const fmtDate = (s) => new Date(s * 1000).toLocaleString();

function slugify(s) {
  const base = (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return base || "servico";
}
function uniqueId(name, existing) {
  const base = slugify(name);
  if (!existing.includes(base)) return base;
  let i = 2;
  while (existing.includes(base + "-" + i)) i++;
  return base + "-" + i;
}
function scheduleSummary(s) {
  const t = (s && s.time) || "03:00";
  if (!s || s.frequency === "daily") return "Diária às " + t;
  if (s.frequency === "hourly") return "De hora em hora";
  if (s.frequency === "weekly") return "Semanal · " + (WD[s.weekday] || "") + " às " + t;
  return t;
}
function targetsSummary(t) {
  const g = (t && t.groups && t.groups.length) || 0;
  const h = (t && t.hosts && t.hosts.length) || 0;
  const parts = [];
  if (g) parts.push(g + " grupo" + (g > 1 ? "s" : ""));
  if (h) parts.push(h + " host" + (h > 1 ? "s" : ""));
  return parts.length ? parts.join(", ") : "sem alvos";
}
function retentionSummary(r) {
  if (!r) return "retém 7 backups";
  return r.mode === "days"
    ? "retém " + r.value + " dia" + (r.value > 1 ? "s" : "")
    : "retém " + r.value + " backup" + (r.value > 1 ? "s" : "");
}

// ---- Editor de serviço (modal de criar/editar) ---------------------------- //
function ServiceEditor({ initial, allHosts, allGroups, existingIds, onSave, onClose, onDelete }) {
  const isNew = !initial;
  const [name, setName] = useState(initial ? initial.name : "");
  const [enabled, setEnabled] = useState(initial ? initial.enabled !== false : true);
  const [freq, setFreq] = useState(initial && initial.schedule ? initial.schedule.frequency : "daily");
  const [time, setTime] = useState(initial && initial.schedule ? initial.schedule.time : "03:00");
  const [weekday, setWeekday] = useState(initial && initial.schedule ? initial.schedule.weekday : "sun");
  const [hosts, setHosts] = useState(initial && initial.targets ? (initial.targets.hosts || []) : []);
  const [groups, setGroups] = useState(initial && initial.targets ? (initial.targets.groups || []) : []);
  const [filter, setFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [vendorFilter, setVendorFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [retMode, setRetMode] = useState(initial && initial.retention ? initial.retention.mode : "count");
  const [retValue, setRetValue] = useState(initial && initial.retention ? initial.retention.value : 7);

  function toggle(list, setList, id) {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  }
  const vendors = uniq(allHosts.map((h) => h.vendor));
  const roles = uniq(allHosts.map((h) => h.role));
  const shown = allHosts.filter((h) =>
    (!groupFilter || h.group === groupFilter) &&
    (!vendorFilter || h.vendor === vendorFilter) &&
    (!roleFilter || h.role === roleFilter) &&
    (!filter || h.id.toLowerCase().includes(filter.toLowerCase())));
  const allShownOn = shown.length > 0 && shown.every((h) => hosts.includes(h.id));
  const hasFilter = filter || groupFilter || vendorFilter || roleFilter;
  function clearFilters() { setFilter(""); setGroupFilter(""); setVendorFilter(""); setRoleFilter(""); }
  function toggleAllShown() {
    const ids = shown.map((h) => h.id);
    if (allShownOn) setHosts(hosts.filter((x) => !ids.includes(x)));
    else setHosts([...new Set([...hosts, ...ids])]);
  }

  function submit() {
    if (!name.trim()) { toast.err("Dê um nome ao serviço"); return; }
    if (hosts.length === 0 && groups.length === 0) { toast.err("Selecione ao menos um host ou grupo"); return; }
    const id = isNew ? uniqueId(name, existingIds) : initial.id;
    onSave({ id, name: name.trim(), enabled,
      schedule: { frequency: freq, time, weekday },
      retention: { mode: retMode, value: Math.max(1, parseInt(retValue, 10) || 1) },
      targets: { hosts, groups } });
  }

  return html`<${Modal} title=${isNew ? "Novo serviço de backup" : "Editar serviço"} wide onClose=${onClose}>
    <div class="bk-form">
      <div>
        <h3>Nome do serviço</h3>
        <input class="bk-name-input" type="text" value=${name} placeholder="ex.: Núcleo MikroTik diário"
          onInput=${(e) => setName(e.target.value)} />
      </div>

      <label class="toggle" style="margin-top:12px">
        <input type="checkbox" checked=${enabled} onChange=${(e) => setEnabled(e.target.checked)} />
        <span class="track"><span class="thumb"></span></span>
        <span>Serviço ativo</span>
      </label>

      <h3>Agendamento</h3>
      <div class="bk-sched">
        <label>Frequência
          <select value=${freq} onChange=${(e) => setFreq(e.target.value)}>
            ${FREQS.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}
          </select>
        </label>
        ${freq !== "hourly" && html`<label>Hora
          <input type="time" value=${time} onInput=${(e) => setTime(e.target.value)} />
        </label>`}
        ${freq === "weekly" && html`<label>Dia da semana
          <select value=${weekday} onChange=${(e) => setWeekday(e.target.value)}>
            ${WEEKDAYS.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}
          </select>
        </label>`}
      </div>

      <h3>Retenção</h3>
      <div class="bk-sched">
        <label>Manter por
          <select value=${retMode} onChange=${(e) => setRetMode(e.target.value)}>
            <option value="count">Quantidade de backups</option>
            <option value="days">Dias</option>
          </select>
        </label>
        <label>${retMode === "days" ? "Dias" : "Backups por dispositivo"}
          <input type="number" min="1" max="3650" value=${retValue}
            onInput=${(e) => setRetValue(e.target.value)} style="width:130px" />
        </label>
      </div>
      <div class="help" style="margin-top:4px">
        ${retMode === "days"
          ? "Remove backups mais antigos que o número de dias."
          : "Mantém apenas os N backups mais recentes de cada dispositivo."}
      </div>

      <h3>Grupos <span class="help" style="text-transform:none">(todo host do grupo entra)</span></h3>
      ${allGroups.length === 0
        ? html`<div class="help">Nenhum grupo no inventário.</div>`
        : html`<div class="bk-chips">
          ${allGroups.map((g) => html`<label key=${g.name} class=${"bk-chip" + (groups.includes(g.name) ? " on" : "")}>
            <input type="checkbox" checked=${groups.includes(g.name)}
              onChange=${() => toggle(groups, setGroups, g.name)} />
            ${g.name} <span class="bk-count">${g.used_by}</span>
          </label>`)}
        </div>`}

      <h3>Hosts individuais</h3>
      <div class="bk-toolbar">
        <input type="text" placeholder="filtrar por id…" value=${filter} onInput=${(e) => setFilter(e.target.value)} />
        <select value=${groupFilter} onChange=${(e) => setGroupFilter(e.target.value)}>
          <option value="">grupo: todos</option>
          ${allGroups.map((g) => html`<option key=${g.name} value=${g.name}>${g.name}</option>`)}
        </select>
        <select value=${vendorFilter} onChange=${(e) => setVendorFilter(e.target.value)}>
          <option value="">vendor: todos</option>
          ${vendors.map((v) => html`<option key=${v} value=${v}>${v}</option>`)}
        </select>
        <select value=${roleFilter} onChange=${(e) => setRoleFilter(e.target.value)}>
          <option value="">função: todas</option>
          ${roles.map((r) => html`<option key=${r} value=${r}>${r}</option>`)}
        </select>
        ${hasFilter && html`<button class="sm" onClick=${clearFilters}>limpar filtros</button>`}
        <span class="badge accent bk-selcount">${hosts.length} selecionado(s)</span>
      </div>
      <div class="bk-tablewrap">
        <table>
          <thead><tr>
            <th class="bk-col-check"><input type="checkbox" title="selecionar todos os visíveis"
              checked=${allShownOn} onChange=${toggleAllShown} /></th>
            <th>ID</th><th>Vendor</th><th>Função</th><th>Grupo</th><th>IP</th>
          </tr></thead>
          <tbody>
            ${shown.length === 0 && html`<tr><td colspan="6" class="help" style="padding:12px">Nenhum host com esses filtros.</td></tr>`}
            ${shown.map((h) => {
              const on = hosts.includes(h.id);
              return html`<tr key=${h.id} class=${on ? "on" : ""} onClick=${() => toggle(hosts, setHosts, h.id)}>
                <td class="bk-col-check"><input type="checkbox" checked=${on}
                  onClick=${(e) => e.stopPropagation()} onChange=${() => toggle(hosts, setHosts, h.id)} /></td>
                <td class="bk-id">${h.id}</td>
                <td>${h.vendor || ""}</td>
                <td>${h.role || ""}</td>
                <td>${h.group || ""}</td>
                <td>${h.mgmt_ip || ""}</td>
              </tr>`;
            })}
          </tbody>
        </table>
      </div>
    </div>

    <div class="modal-actions">
      ${!isNew && html`<button class="danger" style="margin-right:auto" onClick=${onDelete}>Remover</button>`}
      <button onClick=${onClose}>Cancelar</button>
      <button class="primary" onClick=${submit}>Salvar</button>
    </div>
  <//>`;
}

// ---- Página --------------------------------------------------------------- //
// ---- Modal de progresso do Run (polling; fechável sem parar o job) -------- //
function RunModal({ runId, onClose }) {
  const [st, setSt] = useState(null);
  useEffect(() => {
    let alive = true;
    (function tick() {
      api.get("/backups/runs/" + encodeURIComponent(runId))
        .then((d) => { if (!alive) return; setSt(d); if (d.state !== "done") setTimeout(tick, 1500); })
        .catch(() => { if (alive) setTimeout(tick, 3000); });
    })();
    return () => { alive = false; };
  }, [runId]);

  const hosts = (st && st.hosts) || [];
  const finished = hosts.filter((h) => ["ok", "fail", "skip"].includes(h.state)).length;
  const ic = (s) => s === "ok" ? "✓" : s === "fail" ? "✕" : s === "skip" ? "—" : s === "running" ? "…" : "·";
  const done = st && st.state === "done";
  return html`<${Modal} title=${"Execução" + (st ? " · " + st.service_name : "")} wide onClose=${onClose}>
    ${!st ? html`<${Spinner} />` : html`<div>
      <div class="help" style="margin-bottom:8px">
        ${done ? "Concluído" : "Em execução…"} — ${finished}/${hosts.length} host(s)${st.note ? " · " + st.note : ""}
      </div>
      <div class="bk-tablewrap">
        <table>
          <thead><tr><th style="width:34px"></th><th>Host</th><th>Estado</th><th>Detalhe</th></tr></thead>
          <tbody>
            ${hosts.length === 0 && html`<tr><td colspan="4" class="help" style="padding:12px">Serviço sem alvos.</td></tr>`}
            ${hosts.map((h) => html`<tr key=${h.id}>
              <td class=${"bk-run-" + h.state} style="text-align:center; font-weight:700">${ic(h.state)}</td>
              <td class="bk-id">${h.id}</td>
              <td class=${"bk-run-" + h.state}>${h.state}</td>
              <td class="help">${h.detail || ""}</td>
            </tr>`)}
          </tbody>
        </table>
      </div>
    </div>`}
    <div class="modal-actions" style="margin-top:10px">
      <button onClick=${onClose}>Fechar${st && !done ? " (continua em segundo plano)" : ""}</button>
    </div>
  <//>`;
}

// ---- Modal de diff entre dois backups (marca-texto: +verde -vermelho ~amarelo) --- //
function DiffModal({ data, onClose }) {
  const lines = (data && data.lines) || [];
  const c = (data && data.counts) || { added: 0, removed: 0, changed: 0 };
  const cls = (t) => t === "added" ? "bk-d-add" : t === "removed" ? "bk-d-del" : t === "changed" ? "bk-d-chg" : "";
  return html`<${Modal} title="Diferença entre backups" wide onClose=${onClose}>
    <div class="help" style="margin-bottom:8px; display:flex; gap:10px; flex-wrap:wrap; align-items:center">
      <span><b>A:</b> ${data.a}</span><span><b>B:</b> ${data.b}</span>
      <span style="flex:1"></span>
      <span class="bk-d-add" style="padding:1px 8px; border-radius:4px">${c.added} adicionada(s)</span>
      <span class="bk-d-del" style="padding:1px 8px; border-radius:4px">${c.removed} removida(s)</span>
      <span class="bk-d-chg" style="padding:1px 8px; border-radius:4px">${c.changed} alterada(s)</span>
    </div>
    <div class="bk-diff">
      ${lines.map((l, i) => html`<div key=${i} class=${"bk-d-line " + cls(l.type)}>${l.text || " "}</div>`)}
    </div>
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>Fechar</button></div>
  <//>`;
}

// ---- Modal "Ver Backups" de um host (seleção + baixar em lote) ------------ //
function HostBackupsModal({ host, onView, onDownloadOne, onDownloadZip, onDiff, onClose }) {
  const backups = (host && host.backups) || [];
  const [sel, setSel] = useState([]);
  const allOn = backups.length > 0 && sel.length === backups.length;
  const toggle = (p) => setSel(sel.includes(p) ? sel.filter((x) => x !== p) : [...sel, p]);
  const toggleAll = () => setSel(allOn ? [] : backups.map((b) => b.path));
  const anchorRef = useRef(null);
  function doDiff() {
    const el = anchorRef.current;
    if (sel.length !== 2) {
      el.setCustomValidity("Selecione exatamente 2 backups para comparar.");
      el.reportValidity();
      return;
    }
    el.setCustomValidity("");
    // Base = o MAIS ANTIGO, comparado até o mais novo (independe da ordem de clique),
    // p/ que adições fiquem verdes e remoções vermelhas de forma cronológica.
    const chosen = sel.map((path) => backups.find((b) => b.path === path))
      .filter(Boolean).sort((a, b) => a.mtime - b.mtime);
    onDiff(chosen[0].path, chosen[1].path);
  }
  return html`<${Modal} title=${"Backups · " + host.host} wide onClose=${onClose}>
    <div class="bk-toolbar" style="margin-bottom:10px">
      <label class=${"bk-chip" + (allOn ? " on" : "")}>
        <input type="checkbox" checked=${allOn} onChange=${toggleAll} /> Todos
      </label>
      <span class="help">${sel.length} de ${backups.length} selecionado(s)</span>
      <span style="flex:1"></span>
      <input ref=${anchorRef} class="bk-vanchor" tabindex="-1" aria-hidden="true" />
      <button class="sm" onClick=${doDiff}>Diff</button>
      <button class="btn-ok" disabled=${sel.length === 0}
        onClick=${() => onDownloadZip(sel, host.host + "-selecionados")}>Baixar (${sel.length})</button>
    </div>
    <div class="bk-tablewrap">
      <table>
        <thead><tr>
          <th class="bk-col-check"><input type="checkbox" checked=${allOn} onChange=${toggleAll} /></th>
          <th>Backup</th><th>Tamanho</th><th>Data</th><th style="text-align:right">Ações</th>
        </tr></thead>
        <tbody>
          ${backups.map((b) => {
            const on = sel.includes(b.path);
            return html`<tr key=${b.path} class=${on ? "on" : ""} onClick=${() => toggle(b.path)}>
              <td class="bk-col-check"><input type="checkbox" checked=${on}
                onClick=${(e) => e.stopPropagation()} onChange=${() => toggle(b.path)} /></td>
              <td class="bk-id">${b.name}</td>
              <td>${fmtSize(b.size)}</td>
              <td>${fmtDate(b.mtime)}</td>
              <td><div class="bk-actions" onClick=${(e) => e.stopPropagation()}>
                <button class="sm" onClick=${() => onView(b.path)}>Visualizar</button>
                <button class="sm btn-ok" onClick=${() => onDownloadOne(b.path)}>Baixar</button>
              </div></td>
            </tr>`;
          })}
        </tbody>
      </table>
    </div>
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>Fechar</button></div>
  <//>`;
}

export function BackupsPage() {
  const cfgRes = useResource("/backups");
  const candRes = useResource("/backups/candidates");
  const hostsRes = useResource("/backups/hosts");
  const runsRes = useResource("/backups/runs");
  const [tab, setTab] = useState("servicos");
  const [services, setServices] = useState([]);
  const [rev, setRev] = useState(null);
  const [editing, setEditing] = useState(null);   // { initial: service|null } ou null
  const [viewing, setViewing] = useState(null);
  const [runs, setRuns] = useState({});         // serviceId -> run_id (mais recente)
  const [runModal, setRunModal] = useState(null);
  const [hostModal, setHostModal] = useState(null);
  const [diffModal, setDiffModal] = useState(null);

  useEffect(() => {
    if (!cfgRes.data) return;
    setServices((cfgRes.data.config && cfgRes.data.config.services) || []);
    setRev(cfgRes.data.rev);
  }, [cfgRes.data]);

  useEffect(() => {
    if (!runsRes.data) return;
    const m = {};
    for (const sid in runsRes.data) m[sid] = runsRes.data[sid].run_id;
    setRuns(m);
  }, [runsRes.data]);

  async function persist(next) {
    try {
      const r = await api.put("/backups", { version: 2, services: next }, rev);
      setServices(next); setRev(r.rev); toast.ok("Serviços salvos"); return true;
    } catch (e) { handleError(e); return false; }
  }
  async function upsertService(svc) {
    const exists = services.some((s) => s.id === svc.id);
    const next = exists ? services.map((s) => (s.id === svc.id ? svc : s)) : [...services, svc];
    if (await persist(next)) setEditing(null);
  }
  async function removeService(id) {
    if (await persist(services.filter((s) => s.id !== id))) setEditing(null);
  }

  async function startRun(sid) {
    try {
      const r = await api.post("/backups/" + encodeURIComponent(sid) + "/run");
      setRuns({ ...runs, [sid]: r.run_id });
      setRunModal(r.run_id);
    } catch (e) { handleError(e); }
  }

  async function openDiff(a, b) {
    try { setDiffModal(await api.get("/backups/files/diff?a=" + encodeURIComponent(a) + "&b=" + encodeURIComponent(b))); }
    catch (e) { handleError(e); }
  }

  async function view(path) {
    try { setViewing(await api.get("/backups/files/view?path=" + encodeURIComponent(path))); }
    catch (e) { handleError(e); }
  }
  async function download(path) {
    try {
      const res = await fetch("/api/backups/files/download?path=" + encodeURIComponent(path),
        { headers: authToken() ? { "X-Netops-Session": authToken() } : {} });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = path.split("/").pop();
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { toast.err("Falha ao baixar: " + e.message); }
  }

  async function downloadZip(paths, name) {
    if (!paths || paths.length === 0) { toast.err("Nenhum backup selecionado"); return; }
    try {
      const qs = paths.map((p) => "path=" + encodeURIComponent(p)).join("&") + "&name=" + encodeURIComponent(name || "backups");
      const res = await fetch("/api/backups/files/zip?" + qs,
        { headers: authToken() ? { "X-Netops-Session": authToken() } : {} });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = (name || "backups") + ".zip";
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { toast.err("Falha ao baixar: " + e.message); }
  }

  if (cfgRes.error) return html`<div class="card">Erro ao carregar: ${cfgRes.error.message}</div>`;
  if (cfgRes.loading || rev === null) return html`<${Spinner} />`;

  const allHosts = (candRes.data && candRes.data.hosts) || [];
  const allGroups = (candRes.data && candRes.data.groups) || [];
  const backupHosts = (hostsRes.data && hostsRes.data.hosts) || [];
  const storeDir = (hostsRes.data && hostsRes.data.dir) || "";

  const servicos = html`<div>
    <div style="display:flex; align-items:center; gap:12px; margin:4px 0 12px">
      <div class="help">Cada serviço define seus próprios hosts/grupos e agendamento.</div>
      <span style="flex:1"></span>
      <button class="primary" onClick=${() => setEditing({ initial: null })}>＋ Criar serviço</button>
    </div>
    ${services.length === 0
      ? html`<div class="card bk-empty">Nenhum serviço de backup configurado. Clique em <b>Criar serviço</b>.</div>`
      : html`<div class="bk-svc-list">
        ${services.map((s) => html`<div key=${s.id} class="card bk-svc" onClick=${() => setEditing({ initial: s })}>
          <div class="bk-svc-main">
            <div class="bk-svc-name">
              ${s.name}
              ${s.enabled !== false ? html`<span class="badge ok">ativo</span>` : html`<span class="badge">pausado</span>`}
            </div>
            <div class="help">${scheduleSummary(s.schedule)} · ${targetsSummary(s.targets)} · ${retentionSummary(s.retention)}</div>
          </div>
          <div class="bk-svc-btns" onClick=${(e) => e.stopPropagation()}>
            <button class="sm primary" onClick=${() => startRun(s.id)}>▶ Run</button>
            ${runs[s.id] && html`<button class="sm" onClick=${() => setRunModal(runs[s.id])}>acompanhar</button>`}
            <button class="sm" onClick=${() => setEditing({ initial: s })}>Editar</button>
          </div>
        </div>`)}
      </div>`}
  </div>`;

  const armazenamento = html`<div>
    <div class="card">
      <h2>Backups por host</h2>
      <div class="help" style="margin-bottom:8px">Diretório: <code>${storeDir}</code></div>
      ${hostsRes.loading
        ? html`<${Spinner} />`
        : backupHosts.length === 0
          ? html`<div class="bk-empty">Nenhum backup ainda. Os hosts aparecem aqui após a primeira coleta.</div>`
          : html`<div class="bk-tablewrap">
            <table>
              <thead><tr><th>Host</th><th>Backups</th><th>Último</th><th>Tamanho</th><th style="text-align:right">Ações</th></tr></thead>
              <tbody>
                ${backupHosts.map((h) => html`<tr key=${h.host}>
                  <td class="bk-id">${h.host}</td>
                  <td>${h.count}</td>
                  <td>${fmtDate(h.latest_mtime)}</td>
                  <td>${fmtSize(h.total_size)}</td>
                  <td><div class="bk-actions">
                    <button class="sm" onClick=${() => setHostModal(h)}>Ver Backups</button>
                    <button class="sm btn-ok" onClick=${() => downloadZip(h.backups.map((b) => b.path), h.host + "-backups")}>Baixar todos</button>
                  </div></td>
                </tr>`)}
              </tbody>
            </table>
          </div>`}
      <button class="sm" style="margin-top:8px" onClick=${hostsRes.reload}>Atualizar</button>
    </div>
  </div>`;

  return html`<div>
    <div class="page-title"><h1>Backups</h1></div>
    <${Tabs} active=${tab} onChange=${setTab} tabs=${[
      { key: "servicos", label: "Serviços de Backup" },
      { key: "armazenamento", label: "Armazenamento de Backup" },
    ]} />
    <div style="margin-top:12px">${tab === "servicos" ? servicos : armazenamento}</div>

    ${editing && html`<${ServiceEditor}
      initial=${editing.initial}
      allHosts=${allHosts} allGroups=${allGroups}
      existingIds=${services.map((s) => s.id)}
      onClose=${() => setEditing(null)}
      onSave=${upsertService}
      onDelete=${() => removeService(editing.initial.id)} />`}

    ${runModal && html`<${RunModal} runId=${runModal} onClose=${() => setRunModal(null)} />`}

    ${hostModal && html`<${HostBackupsModal} host=${hostModal} onView=${view} onDownloadOne=${download}
      onDownloadZip=${downloadZip} onDiff=${openDiff} onClose=${() => setHostModal(null)} />`}

    ${diffModal && html`<${DiffModal} data=${diffModal} onClose=${() => setDiffModal(null)} />`}

    ${viewing && html`<${Modal} title=${viewing.path} wide onClose=${() => setViewing(null)}>
      ${viewing.binary
        ? html`<div class="help">Arquivo binário — use “Baixar”.</div>`
        : html`<pre class="raw md-readbox bk-viewer">${viewing.text}</pre>`}
      ${viewing.truncated && html`<div class="help" style="margin-top:6px">Exibindo os primeiros 2 MB do arquivo.</div>`}
      <div class="modal-actions" style="margin-top:10px">
        <button class="btn-ok" onClick=${() => download(viewing.path)}>Baixar</button>
        <button onClick=${() => setViewing(null)}>Fechar</button>
      </div>
    <//>`}
  </div>`;
}
