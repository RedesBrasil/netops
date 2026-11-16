// Backups: duas sub-abas.
//  - "Serviços de Backup": lista de serviços (estilo jobs do Proxmox); criar/editar em modal.
//  - "Armazenamento de Backup": visualizar/baixar os configs coletados.
// Config só — a execução no horário é feita por um runner externo.
import { html, useState, useEffect, useRef, api, useResource, Spinner, toast, handleError, Modal, Tabs, ConfirmDialog } from "../ui.js";
import { authToken } from "../api.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable } from "../components.js";

const FREQS = [["daily", "Diária"], ["weekly", "Semanal"], ["hourly", "De hora em hora"]];
const WEEKDAYS = [["mon", "Seg"], ["tue", "Ter"], ["wed", "Qua"], ["thu", "Qui"],
  ["fri", "Sex"], ["sat", "Sáb"], ["sun", "Dom"]];
const WD = Object.fromEntries(WEEKDAYS);

const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort();
const fmtSize = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
const fmtDate = (s) => new Date(s * 1000).toLocaleString();
const hostLabel = (host) => host.hostname || (host.host != null ? "Host " + host.host : "Sem vínculo · " + host.directory);

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
    (!filter || [h.hostname, h.mgmt_ip].some((v) => String(v || "").toLowerCase().includes(filter.toLowerCase()))));
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
      <div class="bk-form-grid">
        <div class="bk-col-full">
          <h3>Nome do serviço</h3>
          <input class="bk-name-input" type="text" value=${name} placeholder="ex.: Núcleo MikroTik diário"
            onInput=${(e) => setName(e.target.value)} />
          <label class="toggle" style="margin-top:10px">
            <input type="checkbox" checked=${enabled} onChange=${(e) => setEnabled(e.target.checked)} />
            <span class="track"><span class="thumb"></span></span>
            <span>Serviço ativo</span>
          </label>
        </div>

        <div>
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
        </div>

        <div>
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
        </div>

        <div class="bk-col-full">
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
        </div>
      </div>

      <h3>Hosts individuais</h3>
      <div class="bk-toolbar">
        <input type="text" placeholder="filtrar por nome ou IP…" value=${filter} onInput=${(e) => setFilter(e.target.value)} />
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
      <${DataTable} tableId="backup-service-hosts" wrapClass="bk-tablewrap" rows=${shown.map((h) => ({ ...h, _key: h.id }))}
        empty="Nenhum host com esses filtros." rowClass=${(h) => (hosts.includes(h.id) ? "on" : "")}
        onRowClick=${(h) => toggle(hosts, setHosts, h.id)}
        columns=${[
          { key: "check", pinned: true, width: 40, tdClass: "bk-col-check",
            label: html`<input type="checkbox" title="selecionar todos os visíveis" checked=${allShownOn} onChange=${toggleAllShown} />`,
            render: (h) => html`<input type="checkbox" checked=${hosts.includes(h.id)} onClick=${(e) => e.stopPropagation()} onChange=${() => toggle(hosts, setHosts, h.id)} />` },
          { key: "hostname", label: "Host", hideable: false, sort: (h) => h.hostname || h.mgmt_ip || "", render: (h) => h.hostname || h.mgmt_ip || "Host " + h.id },
          { key: "vendor", label: "Vendor", sort: true, render: (h) => h.vendor || "" },
          { key: "role", label: "Função", sort: true, render: (h) => h.role || "" },
          { key: "group", label: "Grupo", sort: true, render: (h) => h.group || "" },
          { key: "mgmt_ip", label: "IP", sort: true, render: (h) => h.mgmt_ip || "" },
        ]} />
    </div>

    <div class="modal-actions">
      ${!isNew && html`<button class="danger" style="margin-right:auto" onClick=${onDelete}>Remover</button>`}
      <button onClick=${onClose}>Cancelar</button>
      <button class="primary needs-backups-edit" onClick=${submit}>Salvar</button>
    </div>
  <//>`;
}

// ---- Página --------------------------------------------------------------- //
// ---- Modal de progresso do Run (polling; fechável sem parar o job) -------- //
function RunModal({ runId, onClose, onDone }) {
  const [st, setSt] = useState(null);
  useEffect(() => {
    let alive = true;
    (function tick() {
      api.get("/backups/runs/" + encodeURIComponent(runId))
        .then((d) => { if (!alive) return; setSt(d); if (d.state !== "done") setTimeout(tick, 1500); else onDone && onDone(); })
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
      <${DataTable} tableId="backup-run-progress" wrapClass="bk-tablewrap" rows=${hosts.map((h) => ({ ...h, _key: h.id }))} empty="Serviço sem alvos."
        columns=${[
          { key: "icon", label: "", menuLabel: "Ícone", width: 40, render: (h) => html`<span class=${"bk-run-" + h.state} style="font-weight:700">${ic(h.state)}</span>` },
          { key: "hostname", label: "Host", hideable: false, sort: (h) => h.hostname || "", render: (h) => h.hostname || "Host " + h.id },
          { key: "state", label: "Estado", sort: true, render: (h) => html`<span class=${"bk-run-" + h.state}>${h.state}</span>` },
          { key: "detail", label: "Detalhe", sort: true, render: (h) => html`<span class="help">${h.detail || ""}</span>` },
        ]} />
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
  // lado a lado: A (esquerda) x B (direita); blocos de removidas/adicionadas são pareados linha a linha
  const rows = [];
  let del = [], add = [];
  const flush = () => {
    const n = Math.max(del.length, add.length);
    for (let k = 0; k < n; k++) rows.push({
      l: k < del.length ? del[k] : null, lc: k < del.length ? "bk-d-del" : "bk-d-empty",
      r: k < add.length ? add[k] : null, rc: k < add.length ? "bk-d-add" : "bk-d-empty" });
    del = []; add = [];
  };
  for (const l of lines) {
    if (l.type === "removed") del.push(l.text);
    else if (l.type === "added") add.push(l.text);
    else {
      flush();
      if (l.type === "changed") rows.push({ l: l.old, lc: "bk-d-chg", r: l.text, rc: "bk-d-chg" });
      else rows.push({ l: l.text, lc: "", r: l.text, rc: "" });
    }
  }
  flush();
  return html`<${Modal} title="Diferença entre backups" wide onClose=${onClose}>
    <div class="help" style="margin-bottom:8px; display:flex; gap:10px; flex-wrap:wrap; align-items:center">
      <span><b>A:</b> ${data.a}</span><span><b>B:</b> ${data.b}</span>
      <span style="flex:1"></span>
      <span class="bk-d-add" style="padding:1px 8px; border-radius:4px">${c.added} adicionada(s)</span>
      <span class="bk-d-del" style="padding:1px 8px; border-radius:4px">${c.removed} removida(s)</span>
      <span class="bk-d-chg" style="padding:1px 8px; border-radius:4px">${c.changed} alterada(s)</span>
    </div>
    <div class="bk-diff bk-side">
      <div class="bk-side-head bk-col-a">A: ${data.a}</div><div class="bk-side-head bk-col-b">B: ${data.b}</div>
      ${rows.flatMap((r, i) => [
        html`<div key=${"l" + i} class=${"bk-d-line bk-col-a " + r.lc + (i === rows.length - 1 ? " bk-last" : "")}>${r.l == null ? " " : (r.l || " ")}</div>`,
        html`<div key=${"r" + i} class=${"bk-d-line bk-col-b " + r.rc + (i === rows.length - 1 ? " bk-last" : "")}>${r.r == null ? " " : (r.r || " ")}</div>`])}
    </div>
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>Fechar</button></div>
  <//>`;
}

// ---- Modal "Ver Backups" de um host (seleção + baixar em lote) ------------ //
function HostBackupsModal({ host, onView, onDownloadOne, onDownloadZip, onDiff, onDelete, onClose }) {
  const [items, setItems] = useState((host && host.backups) || []);
  const [sel, setSel] = useState([]);
  const [confirming, setConfirming] = useState(false);
  const allOn = items.length > 0 && sel.length === items.length;
  const toggle = (p) => setSel(sel.includes(p) ? sel.filter((x) => x !== p) : [...sel, p]);
  const toggleAll = () => setSel(allOn ? [] : items.map((b) => b.path));
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
    const chosen = sel.map((path) => items.find((b) => b.path === path))
      .filter(Boolean).sort((a, b) => a.mtime - b.mtime);
    onDiff(chosen[0].path, chosen[1].path);
  }
  async function doDelete() {
    const ok = await onDelete(sel);
    if (ok) { setItems(items.filter((b) => !sel.includes(b.path))); setSel([]); }
  }
  return html`<${Modal} title=${"Backups · " + hostLabel(host)} wide onClose=${onClose}>
    <div class="bk-toolbar" style="margin-bottom:10px">
      <label class=${"bk-chip" + (allOn ? " on" : "")}>
        <input type="checkbox" checked=${allOn} onChange=${toggleAll} /> Todos
      </label>
      <span class="help">${sel.length} de ${items.length} selecionado(s)</span>
      <span style="flex:1"></span>
      <input ref=${anchorRef} class="bk-vanchor" tabindex="-1" aria-hidden="true" />
      <button class="sm" onClick=${doDiff}>Diff</button>
      <button class="btn-ok" disabled=${sel.length === 0}
        onClick=${() => onDownloadZip(sel, hostLabel(host) + "-selecionados")}>Baixar (${sel.length})</button>
      <button class="danger" disabled=${sel.length === 0}
        onClick=${() => setConfirming(true)}>Apagar (${sel.length})</button>
    </div>
    <${DataTable} tableId="backup-host-files" wrapClass="bk-tablewrap" rows=${items.map((b) => ({ ...b, _key: b.path }))}
      defaultSort=${{ key: "mtime", dir: "desc" }} rowClass=${(b) => (sel.includes(b.path) ? "on" : "")} onRowClick=${(b) => toggle(b.path)}
      actions=${(b) => html`<div class="bk-actions">
        <button class="sm" onClick=${() => onView(b.path)}>Visualizar</button>
        <button class="sm btn-ok" onClick=${() => onDownloadOne(b.path)}>Baixar</button></div>`}
      columns=${[
        { key: "check", pinned: true, width: 40, tdClass: "bk-col-check",
          label: html`<input type="checkbox" checked=${allOn} onChange=${toggleAll} />`,
          render: (b) => html`<input type="checkbox" checked=${sel.includes(b.path)} onClick=${(e) => e.stopPropagation()} onChange=${() => toggle(b.path)} />` },
        { key: "name", label: "Backup", hideable: false, sort: true, tdClass: "bk-id", render: (b) => b.name },
        { key: "size", label: "Tamanho", sort: true, render: (b) => fmtSize(b.size) },
        { key: "mtime", label: "Data", sort: true, render: (b) => fmtDate(b.mtime) },
      ]} />
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>Fechar</button></div>
    ${confirming && html`<${ConfirmDialog}
      title="Apagar backups selecionados?"
      message=${"Isto vai apagar " + sel.length + " backup(s) de " + hostLabel(host) + ". Esta ação é permanente — não será possível reaver os backups apagados."}
      danger onConfirm=${doDelete} onClose=${() => setConfirming(false)} />`}
  <//>`;
}

export function BackupsPage() {
  const cfgRes = useResource("/backups");
  const candRes = useResource("/backups/candidates");
  const hostsRes = useResource("/backups/hosts");
  const runsRes = useResource("/backups/runs");
  // URL (core/rules/urls-navegacao.md):
  //   #backups[/services[/<id>|/new]]  #backups/storage[/<host>]  ?q=  &run=<id>  &file=<caminho>  &diffa=&diffb=
  const r = useMenuRoute("backups");
  const tab = r.segments[0] === "storage" ? "armazenamento" : "servicos";
  const itemSeg = r.segments[1] || null;
  const q = r.params.q || "";
  const setTab = (k) => r.openWith(k === "armazenamento" ? ["storage"] : [], { q: "" });
  const [services, setServices] = useState([]);
  const [rev, setRev] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [runs, setRuns] = useState({});         // serviceId -> run_id (mais recente)
  const runModal = r.params.run || null;
  const setRunModal = (id) => r.pushParams({ run: id || "" });
  const [diffModal, setDiffModal] = useState(null);
  const closeItem = () => r.openWith(tab === "armazenamento" ? ["storage"] : ["services"]);
  const fileParam = r.params.file || "", diffA = r.params.diffa || "", diffB = r.params.diffb || "";
  useEffect(() => {
    if (!fileParam) { setViewing(null); return; }
    api.get("/backups/files/view?path=" + encodeURIComponent(fileParam)).then(setViewing).catch((e) => { handleError(e); r.setParams({ file: "" }); });
  }, [fileParam]);
  useEffect(() => {
    if (!diffA || !diffB) { setDiffModal(null); return; }
    api.get("/backups/files/diff?a=" + encodeURIComponent(diffA) + "&b=" + encodeURIComponent(diffB)).then(setDiffModal).catch((e) => { handleError(e); r.setParams({ diffa: "", diffb: "" }); });
  }, [diffA, diffB]);

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

  // Ao entrar na aba Armazenamento, refaz a busca — pega backups recém-criados
  // sem precisar recarregar a página.
  useEffect(() => { if (tab === "armazenamento") hostsRes.reload(); }, [tab]);

  async function persist(next) {
    try {
      const legacy_sources = (cfgRes.data && cfgRes.data.config && cfgRes.data.config.legacy_sources) || [];
      const r = await api.put("/backups", { version: 3, services: next, legacy_sources }, rev);
      setServices(next); setRev(r.rev); toast.ok("Serviços salvos"); return true;
    } catch (e) { handleError(e); return false; }
  }
  async function upsertService(svc) {
    const exists = services.some((s) => s.id === svc.id);
    const next = exists ? services.map((s) => (s.id === svc.id ? svc : s)) : [...services, svc];
    if (await persist(next)) closeItem();
  }
  async function removeService(id) {
    if (await persist(services.filter((s) => s.id !== id))) closeItem();
  }

  async function startRun(sid) {
    try {
      const r = await api.post("/backups/" + encodeURIComponent(sid) + "/run");
      setRuns({ ...runs, [sid]: r.run_id });
      setRunModal(r.run_id);
    } catch (e) { handleError(e); }
  }

  async function deleteBackups(paths) {
    try {
      const r = await api.post("/backups/files/delete", { paths });
      hostsRes.reload();
      toast.ok((r.count || paths.length) + " backup(s) apagado(s)");
      return true;
    } catch (e) { handleError(e); return false; }
  }

  async function openDiff(a, b) {
    r.pushParams({ diffa: a, diffb: b });
  }

  async function view(path) {
    r.pushParams({ file: path });
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
  const hostKey = (h) => (h.host != null ? String(h.host) : "dir-" + h.directory);
  const editing = tab === "servicos" && itemSeg
    ? (itemSeg === "new" ? { initial: null } : services.find((x) => x.id === itemSeg) ? { initial: services.find((x) => x.id === itemSeg) } : null) : null;
  const hostModal = tab === "armazenamento" && itemSeg ? backupHosts.find((h) => hostKey(h) === itemSeg) || null : null;
  const missing = itemSeg && !editing && !hostModal && !(tab === "armazenamento" && hostsRes.loading && !hostsRes.data);
  const svcLink = (id) => "#backups/services/" + encodeURIComponent(id);
  const shownServices = services.filter((x) => matchText(q, x.name, x.id));
  const shownHosts = backupHosts.filter((h) => matchText(q, hostLabel(h), h.directory));

  const servicos = html`<div>
    <div style="display:flex; align-items:center; gap:12px; margin:4px 0 12px">
      <div class="help">Cada serviço define seus próprios hosts/grupos e agendamento.</div>
      <span style="flex:1"></span>
      <button class="primary" onClick=${() => r.open(["services", "new"])}>＋ Criar serviço</button>
    </div>
    ${services.length === 0
      ? html`<div class="card bk-empty">Nenhum serviço de backup configurado. Clique em <b>Criar serviço</b>.</div>`
      : html`<div class="bk-svc-list">
        ${shownServices.map((s) => html`<div key=${s.id} class="card bk-svc" onClick=${() => r.open(["services", s.id])}>
          <div class="bk-svc-main">
            <div class="bk-svc-name">
              <a href=${svcLink(s.id)} onClick=${(e) => e.stopPropagation()}>${s.name}</a>
              ${s.enabled !== false ? html`<span class="badge ok">ativo</span>` : html`<span class="badge">pausado</span>`}
            </div>
            <div class="help">${scheduleSummary(s.schedule)} · ${targetsSummary(s.targets)} · ${retentionSummary(s.retention)}</div>
          </div>
          <div class="bk-svc-btns" onClick=${(e) => e.stopPropagation()}>
            <button class="sm primary needs-backups-run" onClick=${() => startRun(s.id)}>▶ Run</button>
            ${runs[s.id] && html`<button class="sm" onClick=${() => setRunModal(runs[s.id])}>acompanhar</button>`}
            <button class="sm needs-backups-edit" onClick=${() => r.open(["services", s.id])}>Editar</button>
          </div>
        </div>`)}
      </div>`}
  </div>`;

  const armazenamento = html`<div>
    <div class="card">
      <h2>Backups por host</h2>
      <div class="help" style="margin-bottom:8px">Diretório: <code>${storeDir}</code></div>
      ${(hostsRes.loading && !hostsRes.data)
        ? html`<${Spinner} />`
        : backupHosts.length === 0
          ? html`<div class="bk-empty">Nenhum backup ainda. Os hosts aparecem aqui após a primeira coleta.</div>`
          : html`<${DataTable} tableId="backup-storage" urlSort wrapClass="bk-tablewrap" empty="Nenhum host com esse filtro."
              rows=${shownHosts.map((h) => ({ ...h, _key: h.host != null ? h.host : "unassigned:" + h.directory }))}
              onRowClick=${(h) => r.open(["storage", hostKey(h)])}
              actions=${(h) => html`<div class="bk-actions">
                <button class="sm" onClick=${() => r.open(["storage", hostKey(h)])}>Ver Backups</button>
                <button class="sm btn-ok" onClick=${() => downloadZip(h.backups.map((b) => b.path), hostLabel(h) + "-backups")}>Baixar todos</button></div>`}
              columns=${[
                { key: "host", label: "Host", hideable: false, sort: (h) => hostLabel(h), render: (h) => html`<a href=${"#backups/storage/" + encodeURIComponent(hostKey(h))} onClick=${(e) => e.stopPropagation()}>${hostLabel(h)}</a>` },
                { key: "count", label: "Backups", sort: true },
                { key: "latest_mtime", label: "Último", sort: true, render: (h) => fmtDate(h.latest_mtime) },
                { key: "total_size", label: "Tamanho", sort: true, render: (h) => fmtSize(h.total_size) },
              ]} />`}
      <button class="sm" style="margin-top:8px" onClick=${hostsRes.reload}>Atualizar</button>
    </div>
  </div>`;

  return html`<div>
    <div class="page-title"><h1>Backups</h1></div>
    <${Tabs} active=${tab} onChange=${setTab} tabs=${[
      { key: "servicos", label: "Serviços de Backup" },
      { key: "armazenamento", label: "Armazenamento de Backup" },
    ]} />
    <div style="margin-top:12px">
      <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${tab === "servicos" ? "Buscar serviço" : "Buscar host"}
        count=${tab === "servicos" ? shownServices.length : shownHosts.length} total=${tab === "servicos" ? services.length : backupHosts.length} />
      ${missing && html`<div class="card">Item '${itemSeg}' não encontrado. <a href=${tab === "servicos" ? "#backups/services" : "#backups/storage"}>Voltar</a></div>`}
      ${tab === "servicos" ? servicos : armazenamento}</div>

    ${editing && html`<${ServiceEditor} key=${itemSeg}
      initial=${editing.initial}
      allHosts=${allHosts} allGroups=${allGroups}
      existingIds=${services.map((s) => s.id)}
      onClose=${closeItem}
      onSave=${upsertService}
      onDelete=${() => removeService(editing.initial.id)} />`}

    ${runModal && html`<${RunModal} runId=${runModal} onClose=${() => setRunModal(null)} onDone=${() => hostsRes.reload()} />`}

    ${hostModal && html`<${HostBackupsModal} host=${hostModal} onView=${view} onDownloadOne=${download}
      onDownloadZip=${downloadZip} onDiff=${openDiff} onDelete=${deleteBackups} onClose=${closeItem} />`}

    ${diffModal && html`<${DiffModal} data=${diffModal} onClose=${() => r.pushParams({ diffa: "", diffb: "" })} />`}

    ${viewing && html`<${Modal} title=${viewing.path} wide onClose=${() => r.pushParams({ file: "" })}>
      ${viewing.binary
        ? html`<div class="help">Arquivo binário — use “Baixar”.</div>`
        : html`<pre class="raw md-readbox bk-viewer">${viewing.text}</pre>`}
      ${viewing.truncated && html`<div class="help" style="margin-top:6px">Exibindo os primeiros 2 MB do arquivo.</div>`}
      <div class="modal-actions" style="margin-top:10px">
        <button class="btn-ok" onClick=${() => download(viewing.path)}>Baixar</button>
        <button onClick=${() => r.pushParams({ file: "" })}>Fechar</button>
      </div>
    <//>`}
  </div>`;
}
