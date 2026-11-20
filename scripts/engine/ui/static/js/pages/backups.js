// Backups: duas sub-abas.
//  - "Serviços de Backup": lista de serviços (estilo jobs do Proxmox); criar/editar em modal.
//  - "Armazenamento de Backup": visualizar/baixar os configs coletados.
// Config só — a execução no horário é feita por um runner externo.
import { html, useState, useEffect, useRef, api, useResource, Spinner, toast, handleError, Modal, Tabs, ConfirmDialog, t, fmtDateTime } from "../ui.js";
import { authToken } from "../api.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable } from "../components.js";

// Labels are catalog keys, translated at render time.
const FREQS = [["daily", "backups.freq_daily"], ["weekly", "backups.freq_weekly"], ["hourly", "backups.freq_hourly"]];
const WEEKDAYS = [["mon", "backups.wd_mon"], ["tue", "backups.wd_tue"], ["wed", "backups.wd_wed"], ["thu", "backups.wd_thu"],
  ["fri", "backups.wd_fri"], ["sat", "backups.wd_sat"], ["sun", "backups.wd_sun"]];
const WD = Object.fromEntries(WEEKDAYS);

const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort();
const fmtSize = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
const fmtTs = (s) => fmtDateTime(s);
const hostLabel = (host) => host.hostname || (host.host != null ? t("backups.host_n", { id: host.host }) : t("backups.unassigned_dir", { dir: host.directory }));

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
  const tm = (s && s.time) || "03:00";
  if (!s || s.frequency === "daily") return t("backups.sched_daily", { time: tm });
  if (s.frequency === "hourly") return t("backups.freq_hourly");
  if (s.frequency === "weekly") return t("backups.sched_weekly", { day: WD[s.weekday] ? t(WD[s.weekday]) : "", time: tm });
  return tm;
}
function targetsSummary(tg) {
  const g = (tg && tg.groups && tg.groups.length) || 0;
  const h = (tg && tg.hosts && tg.hosts.length) || 0;
  const parts = [];
  if (g) parts.push(t("backups.groups_count", { count: g }));
  if (h) parts.push(t("backups.hosts_count", { count: h }));
  return parts.length ? parts.join(", ") : t("backups.no_targets");
}
function retentionSummary(r) {
  if (!r) return t("backups.retain_backups", { count: 7 });
  return r.mode === "days"
    ? t("backups.retain_days", { count: r.value })
    : t("backups.retain_backups", { count: r.value });
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
    if (!name.trim()) { toast.err(t("backups.name_required")); return; }
    if (hosts.length === 0 && groups.length === 0) { toast.err(t("backups.targets_required")); return; }
    const id = isNew ? uniqueId(name, existingIds) : initial.id;
    onSave({ id, name: name.trim(), enabled,
      schedule: { frequency: freq, time, weekday },
      retention: { mode: retMode, value: Math.max(1, parseInt(retValue, 10) || 1) },
      targets: { hosts, groups } });
  }

  return html`<${Modal} title=${isNew ? t("backups.new_service_title") : t("backups.edit_service_title")} wide onClose=${onClose}>
    <div class="bk-form">
      <div class="bk-form-grid">
        <div class="bk-col-full">
          <h3>${t("backups.service_name")}</h3>
          <input class="bk-name-input" type="text" value=${name} placeholder=${t("backups.service_name_placeholder")}
            onInput=${(e) => setName(e.target.value)} />
          <label class="toggle" style="margin-top:10px">
            <input type="checkbox" checked=${enabled} onChange=${(e) => setEnabled(e.target.checked)} />
            <span class="track"><span class="thumb"></span></span>
            <span>${t("backups.service_enabled")}</span>
          </label>
        </div>

        <div>
          <h3>${t("backups.schedule")}</h3>
          <div class="bk-sched">
            <label>${t("backups.frequency")}
              <select value=${freq} onChange=${(e) => setFreq(e.target.value)}>
                ${FREQS.map(([v, l]) => html`<option key=${v} value=${v}>${t(l)}</option>`)}
              </select>
            </label>
            ${freq !== "hourly" && html`<label>${t("backups.time")}
              <input type="time" value=${time} onInput=${(e) => setTime(e.target.value)} />
            </label>`}
            ${freq === "weekly" && html`<label>${t("backups.weekday")}
              <select value=${weekday} onChange=${(e) => setWeekday(e.target.value)}>
                ${WEEKDAYS.map(([v, l]) => html`<option key=${v} value=${v}>${t(l)}</option>`)}
              </select>
            </label>`}
          </div>
        </div>

        <div>
          <h3>${t("backups.retention")}</h3>
          <div class="bk-sched">
            <label>${t("backups.keep_by")}
              <select value=${retMode} onChange=${(e) => setRetMode(e.target.value)}>
                <option value="count">${t("backups.keep_count")}</option>
                <option value="days">${t("backups.days")}</option>
              </select>
            </label>
            <label>${retMode === "days" ? t("backups.days") : t("backups.backups_per_device")}
              <input type="number" min="1" max="3650" value=${retValue}
                onInput=${(e) => setRetValue(e.target.value)} style="width:130px" />
            </label>
          </div>
          <div class="help" style="margin-top:4px">
            ${retMode === "days"
              ? t("backups.retention_days_help")
              : t("backups.retention_count_help")}
          </div>
        </div>

        <div class="bk-col-full">
          <h3>${t("backups.groups")} <span class="help" style="text-transform:none">${t("backups.groups_help")}</span></h3>
          ${allGroups.length === 0
            ? html`<div class="help">${t("backups.no_groups")}</div>`
            : html`<div class="bk-chips">
              ${allGroups.map((g) => html`<label key=${g.name} class=${"bk-chip" + (groups.includes(g.name) ? " on" : "")}>
                <input type="checkbox" checked=${groups.includes(g.name)}
                  onChange=${() => toggle(groups, setGroups, g.name)} />
                ${g.name} <span class="bk-count">${g.used_by}</span>
              </label>`)}
            </div>`}
        </div>
      </div>

      <h3>${t("backups.individual_hosts")}</h3>
      <div class="bk-toolbar">
        <input type="text" placeholder=${t("backups.filter_placeholder")} value=${filter} onInput=${(e) => setFilter(e.target.value)} />
        <select value=${groupFilter} onChange=${(e) => setGroupFilter(e.target.value)}>
          <option value="">${t("backups.group_all")}</option>
          ${allGroups.map((g) => html`<option key=${g.name} value=${g.name}>${g.name}</option>`)}
        </select>
        <select value=${vendorFilter} onChange=${(e) => setVendorFilter(e.target.value)}>
          <option value="">${t("backups.vendor_all")}</option>
          ${vendors.map((v) => html`<option key=${v} value=${v}>${v}</option>`)}
        </select>
        <select value=${roleFilter} onChange=${(e) => setRoleFilter(e.target.value)}>
          <option value="">${t("backups.role_all")}</option>
          ${roles.map((r) => html`<option key=${r} value=${r}>${r}</option>`)}
        </select>
        ${hasFilter && html`<button class="sm" onClick=${clearFilters}>${t("backups.clear_filters")}</button>`}
        <span class="badge accent bk-selcount">${t("backups.selected_n", { n: hosts.length })}</span>
      </div>
      <${DataTable} tableId="backup-service-hosts" wrapClass="bk-tablewrap" rows=${shown.map((h) => ({ ...h, _key: h.id }))}
        empty=${t("backups.no_hosts_filtered")} rowClass=${(h) => (hosts.includes(h.id) ? "on" : "")}
        onRowClick=${(h) => toggle(hosts, setHosts, h.id)}
        columns=${[
          { key: "check", pinned: true, width: 40, tdClass: "bk-col-check",
            label: html`<input type="checkbox" title=${t("backups.select_all_visible")} checked=${allShownOn} onChange=${toggleAllShown} />`,
            render: (h) => html`<input type="checkbox" checked=${hosts.includes(h.id)} onClick=${(e) => e.stopPropagation()} onChange=${() => toggle(hosts, setHosts, h.id)} />` },
          { key: "hostname", label: "Host", hideable: false, sort: (h) => h.hostname || h.mgmt_ip || "", render: (h) => h.hostname || h.mgmt_ip || t("backups.host_n", { id: h.id }) },
          { key: "vendor", label: "Vendor", sort: true, render: (h) => h.vendor || "" },
          { key: "role", label: t("backups.col_role"), sort: true, render: (h) => h.role || "" },
          { key: "group", label: t("backups.col_group"), sort: true, render: (h) => h.group || "" },
          { key: "mgmt_ip", label: "IP", sort: true, render: (h) => h.mgmt_ip || "" },
        ]} />
    </div>

    <div class="modal-actions">
      ${!isNew && html`<button class="danger" style="margin-right:auto" onClick=${onDelete}>${t("common.remove")}</button>`}
      <button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary needs-backups-edit" onClick=${submit}>${t("common.save")}</button>
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
  return html`<${Modal} title=${st ? t("backups.run_title_named", { name: st.service_name }) : t("backups.run_title")} wide onClose=${onClose}>
    ${!st ? html`<${Spinner} />` : html`<div>
      <div class="help" style="margin-bottom:8px">
        ${done ? t("backups.run_done") : t("backups.run_running")} — ${t("backups.run_progress", { done: finished, total: hosts.length })}${st.note ? " · " + st.note : ""}
      </div>
      <${DataTable} tableId="backup-run-progress" wrapClass="bk-tablewrap" rows=${hosts.map((h) => ({ ...h, _key: h.id }))} empty=${t("backups.service_no_targets")}
        columns=${[
          { key: "icon", label: "", menuLabel: t("backups.col_icon"), width: 40, render: (h) => html`<span class=${"bk-run-" + h.state} style="font-weight:700">${ic(h.state)}</span>` },
          { key: "hostname", label: "Host", hideable: false, sort: (h) => h.hostname || "", render: (h) => h.hostname || t("backups.host_n", { id: h.id }) },
          { key: "state", label: t("backups.col_state"), sort: true, render: (h) => html`<span class=${"bk-run-" + h.state}>${h.state}</span>` },
          { key: "detail", label: t("backups.col_detail"), sort: true, render: (h) => html`<span class="help">${h.detail || ""}</span>` },
        ]} />
    </div>`}
    <div class="modal-actions" style="margin-top:10px">
      <button onClick=${onClose}>${st && !done ? t("backups.close_keeps_running") : t("common.close")}</button>
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
  return html`<${Modal} title=${t("backups.diff_title")} wide onClose=${onClose}>
    <div class="help" style="margin-bottom:8px; display:flex; gap:10px; flex-wrap:wrap; align-items:center">
      <span><b>A:</b> ${data.a}</span><span><b>B:</b> ${data.b}</span>
      <span style="flex:1"></span>
      <span class="bk-d-add" style="padding:1px 8px; border-radius:4px">${t("backups.diff_added", { n: c.added })}</span>
      <span class="bk-d-del" style="padding:1px 8px; border-radius:4px">${t("backups.diff_removed", { n: c.removed })}</span>
      <span class="bk-d-chg" style="padding:1px 8px; border-radius:4px">${t("backups.diff_changed", { n: c.changed })}</span>
    </div>
    <div class="bk-diff bk-side">
      <div class="bk-side-head bk-col-a">A: ${data.a}</div><div class="bk-side-head bk-col-b">B: ${data.b}</div>
      ${rows.flatMap((r, i) => [
        html`<div key=${"l" + i} class=${"bk-d-line bk-col-a " + r.lc + (i === rows.length - 1 ? " bk-last" : "")}>${r.l == null ? " " : (r.l || " ")}</div>`,
        html`<div key=${"r" + i} class=${"bk-d-line bk-col-b " + r.rc + (i === rows.length - 1 ? " bk-last" : "")}>${r.r == null ? " " : (r.r || " ")}</div>`])}
    </div>
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>${t("common.close")}</button></div>
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
      el.setCustomValidity(t("backups.diff_select_two"));
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
  return html`<${Modal} title=${t("backups.host_backups_title", { host: hostLabel(host) })} wide onClose=${onClose}>
    <div class="bk-toolbar" style="margin-bottom:10px">
      <label class=${"bk-chip" + (allOn ? " on" : "")}>
        <input type="checkbox" checked=${allOn} onChange=${toggleAll} /> ${t("common.all")}
      </label>
      <span class="help">${t("backups.selected_of", { n: sel.length, total: items.length })}</span>
      <span style="flex:1"></span>
      <input ref=${anchorRef} class="bk-vanchor" tabindex="-1" aria-hidden="true" />
      <button class="sm" onClick=${doDiff}>Diff</button>
      <button class="btn-ok" disabled=${sel.length === 0}
        onClick=${() => onDownloadZip(sel, hostLabel(host) + "-" + t("backups.zip_selected_suffix"))}>${t("backups.download_n", { n: sel.length })}</button>
      <button class="danger" disabled=${sel.length === 0}
        onClick=${() => setConfirming(true)}>${t("backups.delete_n", { n: sel.length })}</button>
    </div>
    <${DataTable} tableId="backup-host-files" wrapClass="bk-tablewrap" rows=${items.map((b) => ({ ...b, _key: b.path }))}
      defaultSort=${{ key: "mtime", dir: "desc" }} rowClass=${(b) => (sel.includes(b.path) ? "on" : "")} onRowClick=${(b) => toggle(b.path)}
      actions=${(b) => html`<div class="bk-actions">
        <button class="sm" onClick=${() => onView(b.path)}>${t("backups.view")}</button>
        <button class="sm btn-ok" onClick=${() => onDownloadOne(b.path)}>${t("common.download")}</button></div>`}
      columns=${[
        { key: "check", pinned: true, width: 40, tdClass: "bk-col-check",
          label: html`<input type="checkbox" checked=${allOn} onChange=${toggleAll} />`,
          render: (b) => html`<input type="checkbox" checked=${sel.includes(b.path)} onClick=${(e) => e.stopPropagation()} onChange=${() => toggle(b.path)} />` },
        { key: "name", label: "Backup", hideable: false, sort: true, tdClass: "bk-id", render: (b) => b.name },
        { key: "size", label: t("backups.col_size"), sort: true, render: (b) => fmtSize(b.size) },
        { key: "mtime", label: t("backups.col_date"), sort: true, render: (b) => fmtTs(b.mtime) },
      ]} />
    <div class="modal-actions" style="margin-top:10px"><button onClick=${onClose}>${t("common.close")}</button></div>
    ${confirming && html`<${ConfirmDialog}
      title=${t("backups.delete_confirm_title")}
      message=${t("backups.delete_confirm_message", { n: sel.length, host: hostLabel(host) })}
      danger onConfirm=${doDelete} onClose=${() => setConfirming(false)} />`}
  <//>`;
}

export function BackupsPage() {
  const cfgRes = useResource("/backups");
  const candRes = useResource("/backups/candidates");
  const hostsRes = useResource("/backups/hosts");
  const runsRes = useResource("/backups/runs");
  // URL (core/rules/navigation-urls.md):
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
      setServices(next); setRev(r.rev); toast.ok(t("backups.services_saved")); return true;
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
      toast.ok(t("backups.deleted_n", { n: r.count || paths.length }));
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
    } catch (e) { toast.err(t("backups.download_failed", { error: e.message })); }
  }

  async function downloadZip(paths, name) {
    if (!paths || paths.length === 0) { toast.err(t("backups.none_selected")); return; }
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
    } catch (e) { toast.err(t("backups.download_failed", { error: e.message })); }
  }

  if (cfgRes.error) return html`<div class="card">${t("backups.load_error", { error: cfgRes.error.message })}</div>`;
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
      <div class="help">${t("backups.services_help")}</div>
      <span style="flex:1"></span>
      <button class="primary" onClick=${() => r.open(["services", "new"])}>${t("backups.create_service_btn")}</button>
    </div>
    ${services.length === 0
      ? html`<div class="card bk-empty">${t("backups.no_services_pre")} <b>${t("backups.create_service")}</b>.</div>`
      : html`<div class="bk-svc-list">
        ${shownServices.map((s) => html`<div key=${s.id} class="card bk-svc" onClick=${() => r.open(["services", s.id])}>
          <div class="bk-svc-main">
            <div class="bk-svc-name">
              <a href=${svcLink(s.id)} onClick=${(e) => e.stopPropagation()}>${s.name}</a>
              ${s.enabled !== false ? html`<span class="badge ok">${t("backups.badge_active")}</span>` : html`<span class="badge">${t("backups.badge_paused")}</span>`}
            </div>
            <div class="help">${scheduleSummary(s.schedule)} · ${targetsSummary(s.targets)} · ${retentionSummary(s.retention)}</div>
          </div>
          <div class="bk-svc-btns" onClick=${(e) => e.stopPropagation()}>
            <button class="sm primary needs-backups-run" onClick=${() => startRun(s.id)}>▶ Run</button>
            ${runs[s.id] && html`<button class="sm" onClick=${() => setRunModal(runs[s.id])}>${t("backups.follow")}</button>`}
            <button class="sm needs-backups-edit" onClick=${() => r.open(["services", s.id])}>${t("common.edit")}</button>
          </div>
        </div>`)}
      </div>`}
  </div>`;

  const armazenamento = html`<div>
    <div class="card">
      <h2>${t("backups.by_host")}</h2>
      <div class="help" style="margin-bottom:8px">${t("backups.directory")} <code>${storeDir}</code></div>
      ${(hostsRes.loading && !hostsRes.data)
        ? html`<${Spinner} />`
        : backupHosts.length === 0
          ? html`<div class="bk-empty">${t("backups.no_backups_yet")}</div>`
          : html`<${DataTable} tableId="backup-storage" urlSort wrapClass="bk-tablewrap" empty=${t("backups.no_hosts_filter")}
              rows=${shownHosts.map((h) => ({ ...h, _key: h.host != null ? h.host : "unassigned:" + h.directory }))}
              onRowClick=${(h) => r.open(["storage", hostKey(h)])}
              actions=${(h) => html`<div class="bk-actions">
                <button class="sm" onClick=${() => r.open(["storage", hostKey(h)])}>${t("backups.view_backups")}</button>
                <button class="sm btn-ok" onClick=${() => downloadZip(h.backups.map((b) => b.path), hostLabel(h) + "-backups")}>${t("backups.download_all")}</button></div>`}
              columns=${[
                { key: "host", label: "Host", hideable: false, sort: (h) => hostLabel(h), render: (h) => html`<a href=${"#backups/storage/" + encodeURIComponent(hostKey(h))} onClick=${(e) => e.stopPropagation()}>${hostLabel(h)}</a>` },
                { key: "count", label: "Backups", sort: true },
                { key: "latest_mtime", label: t("backups.col_latest"), sort: true, render: (h) => fmtTs(h.latest_mtime) },
                { key: "total_size", label: t("backups.col_size"), sort: true, render: (h) => fmtSize(h.total_size) },
              ]} />`}
      <button class="sm" style="margin-top:8px" onClick=${hostsRes.reload}>${t("common.refresh")}</button>
    </div>
  </div>`;

  return html`<div>
    <div class="page-title"><h1>Backups</h1></div>
    <${Tabs} active=${tab} onChange=${setTab} tabs=${[
      { key: "servicos", label: t("backups.tab_services") },
      { key: "armazenamento", label: t("backups.tab_storage") },
    ]} />
    <div style="margin-top:12px">
      <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${tab === "servicos" ? t("backups.search_service") : t("backups.search_host")}
        count=${tab === "servicos" ? shownServices.length : shownHosts.length} total=${tab === "servicos" ? services.length : backupHosts.length} />
      ${missing && html`<div class="card">${t("backups.item_not_found", { id: itemSeg })} <a href=${tab === "servicos" ? "#backups/services" : "#backups/storage"}>${t("common.back")}</a></div>`}
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
        ? html`<div class="help">${t("backups.binary_file")}</div>`
        : html`<pre class="raw md-readbox bk-viewer">${viewing.text}</pre>`}
      ${viewing.truncated && html`<div class="help" style="margin-top:6px">${t("backups.truncated")}</div>`}
      <div class="modal-actions" style="margin-top:10px">
        <button class="btn-ok" onClick=${() => download(viewing.path)}>${t("common.download")}</button>
        <button onClick=${() => r.pushParams({ file: "" })}>${t("common.close")}</button>
      </div>
    <//>`}
  </div>`;
}
