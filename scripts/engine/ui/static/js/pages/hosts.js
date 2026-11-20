// Hosts e Grupos (network/hosts.yaml) — formulário ciente de herança de grupo.
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError, t } from "../ui.js";
import { FilterBar, DataTable, Field, EnumSelect, RefSelect, useEnums, ConfirmDialog, RenameCascadeHint, IconPicker as HostIconPicker } from "../components.js";
import { Modal, ConflictDialog } from "../ui.js";
import { useRoute, navigate, useMenuRoute, matchText } from "../route.js";
import { accessEntries, openEntry, AccessChooser } from "./host-term.js";

// Padrão de cadastro: tudo em MAIÚSCULAS, exceto site e notes (o backend também força).
const UP = (v) => typeof v === "string" ? v.toUpperCase() : v;
const MAX_EXTRA_IPS = 20;  // mesmo teto do backend (models.MAX_EXTRA_IPS)
const IP_ROLES = () => [t("hosts.ip_role_public"), t("hosts.ip_role_internal"), "VIP", "loopback", t("hosts.ip_role_secondary_mgmt")];  // sugestões; o campo é livre
const upList = (l) => (l || []).map(UP);
const UP_KEYS = new Set(["hostname", "group", "vendor", "role", "model", "os", "os_version", "version", "credential", "method"]);
const MAX_APPS = 10;  // mesmo teto do backend (models.MAX_APPS)
// Sugestões (campos livres). Regra: SO = o que o equipamento informa (/etc/os-release, /system resource); o resto é aplicação.
const OS_SUGGEST = ["ROUTEROS", "DEBIAN", "UBUNTU", "ROCKY LINUX", "ALMALINUX", "CENTOS", "WINDOWS SERVER", "VRP", "IOS", "IOS-XE", "NX-OS", "JUNOS", "FIRMWARE"];
const APP_SUGGEST = ["ZABBIX SERVER", "ZABBIX PROXY", "ZABBIX FRONTEND", "ZABBIX AGENT", "PROXMOX VE", "PROXMOX BACKUP SERVER", "EVE-NG", "POSTGRESQL", "MYSQL", "MARIADB", "DOCKER", "COOLIFY", "NGINX", "APACHE", "GRAFANA", "NETOPS"];
// Texto do SO (o campo legado `version` é tratado à parte, para hosts ainda não migrados).
export const osText = (e) => [e.os, e.os_version].filter(Boolean).join(" ");
// Host Local = este servidor (access.method=local; criado pelo instalador, protegido — ver scripts/engine/localadmin)
export const isLocalHost = (h) => String(((h && (h.explicit || h).access) || {}).method || "").toLowerCase() === "local";
const appText = (a) => [a.name, a.version].filter(Boolean).join(" ");  // (credential/method dos métodos ficam em form.accesses)
const INHERIT = ["vendor", "role", "credential"];
const MAX_EXTRA_ACCESS = 10;  // mesmo teto do backend (models.MAX_EXTRA_ACCESS)
const bkLabel = (v) => v === true ? t("hosts.backup_yes") : v === false ? t("hosts.backup_no") : t("hosts.backup_default");

export function HostsPage() {
  const res = useResource("/hosts");
  // URL: #hosts[/<id>|/new][?q=&vendor=&role=&group=&sort=&dir=]  (core/rules/urls-navegacao.md)
  const route = useRoute();
  const { q = "", vendor = "", role = "", group = "", os = "", app = "" } = route.params;
  const setParams = (patch) => navigate({ menu: "hosts", segments: route.segments, params: { ...route.params, ...patch } }, { replace: true });
  const [confirm, setConfirm] = useState(null);
  const [deleteRefs, setDeleteRefs] = useState(null);
  useEffect(() => {
    setDeleteRefs(null);
    if (confirm) api.get(`/hosts/${encodeURIComponent(confirm)}/references`).then(setDeleteRefs).catch(handleError);
  }, [confirm]);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("hosts.load_error", { message: res.error.message })}</div>`;
  const { hosts: allHosts, rev, groups } = res.data;
  const seg = route.segments[0];
  const editing = seg === "new" ? { __new: true } : seg ? allHosts.find((h) => String(h.id) === seg) || null : null;
  // Popup "SSH ou Telnet?" com URL própria (#hosts?access=<id>): Voltar fecha.
  const accessHost = route.params.access ? allHosts.find((h) => String(h.id) === route.params.access) || null : null;
  const openAccess = (id) => navigate({ menu: "hosts", segments: route.segments, params: { ...route.params, access: id ? String(id) : "" } }, { replace: !id });
  const setEditing = (h) => navigate({ menu: "hosts", segments: h ? [h.__new ? "new" : String(h.id)] : [], params: route.params });
  const opts = (f) => [...new Set(allHosts.map(f).filter(Boolean))].sort();
  const needle = q.trim().toLowerCase();
  const hosts = allHosts.filter((h) =>
    (!vendor || h.effective.vendor === vendor) && (!role || h.effective.role === role) && (!group || h.explicit.group === group) &&
    (!os || h.effective.os === os) && (!app || (h.explicit.apps || []).some((a) => a.name === app)) &&
    (!needle || [h.id, h.explicit.hostname, h.explicit.mgmt_ip, ...(h.explicit.extra_ips || []).map((x) => x.ip),
      osText(h.effective), h.effective.version, ...(h.explicit.apps || []).map(appText)].some((v) => String(v || "").toLowerCase().includes(needle))));
  const byId = Object.fromEntries(allHosts.map((h) => [String(h.id), h]));

  const cols = [
    { key: "id", label: "ID", sort: (r) => String(r.id), render: (r) => html`<span class="mono">${r.id}</span>` },
    { key: "hostname", label: t("hosts.col_hostname"), hideable: false, sort: (r) => r.explicit.hostname || "", render: (r) => html`<a href=${"#hosts/" + encodeURIComponent(r.id)} onClick=${(e) => e.stopPropagation()}><b>${r.explicit.hostname}</b></a>${isLocalHost(r) ? html` <${Badge} kind="accent" title=${t("hosts.local_badge_title")}>LOCAL<//>` : ""}` },
    { key: "mgmt_ip", label: "IP", sort: (r) => r.explicit.mgmt_ip || "", render: (r) => html`<span class="mono">${r.explicit.mgmt_ip}</span>` },
    { key: "vendor", label: "Vendor", sort: (r) => r.effective.vendor || "", render: (r) => html`<${Badge} kind="accent">${r.effective.vendor || "?"}<//>` },
    { key: "role", label: "Role", sort: (r) => r.effective.role || "", render: (r) => r.effective.role || "—" },
    { key: "group", label: t("hosts.col_group"), sort: (r) => r.explicit.group || "", render: (r) => r.explicit.group || "—" },
    { key: "os", label: t("hosts.col_os"), sort: (r) => osText(r.effective) || r.effective.version || "", render: (r) => osText(r.effective)
        ? html`<span class="os-cell">${r.effective.os}${r.effective.os_version && html` <span class="muted">${r.effective.os_version}</span>`}</span>`
        : r.effective.version ? html`<span class="muted legacy" title=${t("hosts.legacy_version_title")}>${r.effective.version}</span>` : "—" },
    { key: "apps", label: t("hosts.col_apps"), sort: (r) => (r.explicit.apps || []).map(appText).join(", "), render: (r) => (r.explicit.apps || []).length
        ? html`<span class="app-chips">${r.explicit.apps.map((a, i) => html`<span key=${i} class=${"badge app-chip" + (i === 0 ? " accent" : "")} title=${i === 0 ? t("hosts.main_app") : ""}>${a.name}${a.version && html` <b>${a.version}</b>`}</span>`)}</span>`
        : "—" },
    { key: "access", label: t("hosts.col_access"), sort: (r) => (r.effective.access || {}).method || "", render: (r) => {
        const a = r.effective.access || {}; const more = (r.explicit.extra_access || []).map((x) => `${x.method}${x.port ? ":" + x.port : ""}`);
        return html`<span class="mono" title=${more.length ? t("hosts.alternatives_title", { list: more.join(", ") }) : ""}>${a.method || "?"}:${a.port || "?"}${more.length ? ` +${more.length}` : ""}</span>`; } },
    // Ocultas por padrão — o usuário liga em ⚙ Colunas (preferência salva no navegador).
    { key: "credential", label: t("hosts.col_credential"), hidden: true, sort: (r) => r.effective.credential || "", render: (r) => r.effective.credential || "—" },
    { key: "model", label: t("hosts.col_model"), hidden: true, sort: (r) => r.effective.model || "", render: (r) => r.effective.model || "—" },
    { key: "runs_on", label: t("hosts.col_runs_on"), hidden: true, sort: (r) => byId[String(r.explicit.runs_on)]?.explicit.hostname || "", render: (r) => {
        const p = r.explicit.runs_on != null ? byId[String(r.explicit.runs_on)] : null;
        return p ? html`<a href=${"#hosts/" + encodeURIComponent(p.id)} onClick=${(e) => e.stopPropagation()}>${p.explicit.hostname}</a>` : "—"; } },
    { key: "site", label: "Site", hidden: true, sort: (r) => r.effective.site || "", render: (r) => r.effective.site || "—" },
    { key: "backup", label: t("hosts.col_backup"), hidden: true, sort: (r) => bkLabel(r.effective.backup_before_change), render: (r) => bkLabel(r.effective.backup_before_change) },
    { key: "notes", label: t("hosts.col_notes"), hidden: true, sort: (r) => r.effective.notes || "", render: (r) => html`<span title=${r.effective.notes || ""}>${r.effective.notes || "—"}</span>` },
  ];

  return html`<div>
    <div class="page-title"><h1>${t("hosts.title")}</h1><span class="spacer"></span>
      <button class="primary needs-hosts-edit" onClick=${() => setEditing({ __new: true })}>${t("hosts.new_host_btn")}</button></div>
    <${FilterBar} q=${q} onChange=${setParams} placeholder=${t("hosts.search_placeholder")} count=${hosts.length} total=${allHosts.length}
      selects=${[{ key: "vendor", label: "Vendor", value: vendor, options: opts((h) => h.effective.vendor) },
                 { key: "role", label: "Role", value: role, options: opts((h) => h.effective.role) },
                 { key: "group", label: t("hosts.col_group"), value: group, options: opts((h) => h.explicit.group) },
                 { key: "os", label: t("hosts.col_os"), value: os, options: opts((h) => h.effective.os) },
                 { key: "app", label: t("hosts.filter_app"), value: app, options: [...new Set(allHosts.flatMap((h) => (h.explicit.apps || []).map((a) => a.name)))].sort() }]} />
    ${seg && seg !== "new" && !editing && html`<div class="card">${t("hosts.not_found", { id: seg })} <a href="#hosts">${t("hosts.back_to_hosts")}</a></div>`}
    <${DataTable} tableId="hosts" urlSort columns=${cols} rows=${hosts.map((h) => ({ ...h, _key: h.id }))}
      onRowClick=${(r) => setEditing(r)}
      actions=${(r) => { const te = accessEntries(r);
        return html`<button class="sm needs-host-terminal" disabled=${!te.length}
            title=${te.length ? t("hosts.access_title", { list: te.map((e) => (e.kind === "web" ? "WEB " : "") + e.method.toUpperCase() + ":" + e.port).join(", ") }) : t("hosts.no_access_title")}
            onClick=${() => te.length === 1 ? openEntry(r.id, te[0]) : openAccess(r.id)}>${t("hosts.access_btn")}</button>
          ${isLocalHost(r) ? html`<span class="muted" title=${t("hosts.protected_title")}>${t("hosts.protected")}</span>`
            : html`<button class="sm danger needs-hosts-edit" onClick=${() => setConfirm(r.id)}>${t("common.delete")}</button>`}`; }}
      empty=${t("hosts.empty")} />

    ${accessHost && html`<${AccessChooser} host=${accessHost} entries=${accessEntries(accessHost)} onClose=${() => openAccess("")} />`}
    ${editing && html`<${HostForm} host=${editing} groups=${groups} rev=${rev}
        onClose=${() => setEditing(null)} onSaved=${() => { setEditing(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title=${t("hosts.delete_title")} danger=true
        message=${t("hosts.delete_confirm", { name: hosts.find(h => h.id === confirm)?.explicit.hostname || t("hosts.delete_selected_fallback"),
          refs: deleteRefs ? t("hosts.delete_refs", { count: deleteRefs.count, list: deleteRefs.references.map(r => r.label).join(', ') || t("hosts.delete_refs_none") }) : t("hosts.delete_refs_checking") })}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/hosts/${confirm}`, rev); toast.ok(t("hosts.host_removed")); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

export function HostForm({ host, groups, rev, onClose, onSaved, placement, initial = {} }) {
  const isNew = !!host.__new;
  const enums0 = useEnums();
  const local = !isNew && isLocalHost(host);
  const enums = enums0 && { ...enums0, vendor: upList(enums0.vendor), role: upList(enums0.role),
    method: upList(enums0.method).filter((m) => local || m !== "LOCAL") };
  const [groupDetails, setGroupDetails] = useState({});
  const [creds, setCreds] = useState([]);
  const [conflict, setConflict] = useState(false);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [mapOptions, setMapOptions] = useState(null);
  const [mapChoice, setMapChoice] = useState("");
  const [hostOpts, setHostOpts] = useState([]);
  const explicit = isNew ? initial : host.explicit;
  const [form, setForm] = useState({
    hostname: UP(explicit.hostname) || "", mgmt_ip: explicit.mgmt_ip || "",
    group: UP(explicit.group) || "", vendor: UP(explicit.vendor) ?? null, role: UP(explicit.role) ?? null,
    model: UP(explicit.model) || "", os: UP(explicit.os) || "", os_version: UP(explicit.os_version) || "",
    apps: (explicit.apps || []).map((a) => ({ name: UP(a.name) || "", version: UP(a.version) || "" })),
    runs_on: explicit.runs_on != null ? String(explicit.runs_on) : "", site: explicit.site || "", notes: explicit.notes || "", icon: explicit.icon || "",
    // Métodos de acesso em ordem de prioridade: o 1º é o principal (grava em access/credential); os demais em extra_access.
    accesses: [
      { method: UP((explicit.access || {}).method) ?? null, port: (explicit.access || {}).port ?? "", credential: UP(explicit.credential) ?? null },
      ...(explicit.extra_access || []).map((x) => ({ method: UP(x.method) ?? null, port: x.port ?? "", credential: UP(x.credential) ?? null, app: x.app || "", path: x.path || "" })),
    ],
    extra_ips: (explicit.extra_ips || []).map((x) => ({ ip: x.ip || "", role: UP(x.role) || "", description: UP(x.description) || "" })),
  });

  useEffect(() => {
    if (isNew && !placement) api.get("/maps").then(setMapOptions).catch(() => {});
    api.get("/groups").then((g) => setGroupDetails(Object.fromEntries(g.groups.map((x) => [UP(x.name), x.fields]))));
    api.get("/credentials").then((c) => setCreds(c.credentials.map((x) => UP(x.name))));
    api.get("/hosts").then((h) => setHostOpts(h.hosts.filter((x) => String(x.id) !== String(host.id))
      .map((x) => ({ id: String(x.id), label: `${x.explicit.hostname} (#${x.id})` }))
      .sort((a, b) => a.label.localeCompare(b.label)))).catch(() => {});
  }, []);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: UP_KEYS.has(k) ? UP(v) : v }));
  const legacyVersion = explicit.version || "";  // campo antigo: some ao salvar com SO/aplicação preenchidos
  const gfields = groupDetails[form.group] || {};
  const inh = (k) => gfields[k];                                  // valor herdado do grupo
  const inhAccess = (k) => (gfields.access || {})[k];

  function tag(k, accessKey, value = form[k]) {
    const explicitVal = value;
    const isSet = explicitVal !== null && explicitVal !== "" && explicitVal !== undefined;
    if (isSet) return html`<span class="tag-explicit">${t("hosts.tag_explicit")}</span>`;
    const v = accessKey ? inhAccess(accessKey) : inh(k);
    return v ? html`<span class="tag-inherit">${t("hosts.tag_inherited", { group: form.group, value: v })}</span>` : null;
  }

  async function save() {
    if (saving) return;
    setSaving(true);
    setErrors({});
    const payload = {};
    // obrigatórios
    payload.hostname = form.hostname; payload.mgmt_ip = form.mgmt_ip;
    if (form.group) payload.group = form.group; else if (!isNew) payload.group = null;
    for (const k of ["vendor", "role"]) payload[k] = form[k] || null;
    const [main, ...others] = form.accesses;
    payload.credential = main.credential || null;
    for (const k of ["model", "os", "os_version", "site", "notes", "icon"]) payload[k] = form[k] || null;
    const apps = form.apps.filter((a) => a.name.trim()).map((a) => (a.version.trim() ? { name: a.name.trim(), version: a.version.trim() } : { name: a.name.trim() }));
    if (apps.length) payload.apps = apps; else if (!isNew) payload.apps = null;
    if (form.runs_on) payload.runs_on = Number(form.runs_on); else if (!isNew) payload.runs_on = null;
    if (legacyVersion && (form.os || apps.length)) payload.version = null;  // migrou: remove o campo antigo
    const acc = {};
    if (main.method) acc.method = main.method;
    if (main.port !== "" && main.port != null) acc.port = Number(main.port);
    payload.access = Object.keys(acc).length ? acc : null;
    const extraAcc = others.filter((a) => a.method).map((a) => {
      const item = { method: a.method };
      if (a.port !== "" && a.port != null) item.port = Number(a.port);
      if (a.credential) item.credential = a.credential;
      if (["HTTP", "HTTPS"].includes(String(a.method).toUpperCase())) {   // login web automático (lib/web_login)
        if (a.app) item.app = a.app;
        if (a.path && a.path !== "/") item.path = a.path;
      }
      return item;
    });
    if (extraAcc.length) payload.extra_access = extraAcc; else if (!isNew) payload.extra_access = null;
    const extras = form.extra_ips.filter((x) => x.ip.trim()).map((x) => {
      const item = { ip: x.ip.trim() };
      if (x.role.trim()) item.role = x.role.trim();
      if (x.description.trim()) item.description = x.description.trim();
      return item;
    });
    if (extras.length) payload.extra_ips = extras; else if (!isNew) payload.extra_ips = null;
    try {
      let savedId = host.id;
      if (isNew) {
        if (placement) payload.placement = placement;
        else if (mapChoice && mapOptions) payload.placement = { map_id: mapChoice, maps_rev: mapOptions.rev, x: 80, y: 80 };
        const created = await api.post("/hosts", payload, rev);
        savedId = created.id;
      } else {
        await api.patch(`/hosts/${host.id}`, payload, rev);
      }
      toast.ok(isNew ? t("hosts.host_created") : t("hosts.host_updated"));
      onSaved(savedId);
    } catch (e) {
      if (e.name === "ConflictError" || e.constructor?.name === "ConflictError") return setConflict(true);
      const fe = handleError(e);
      const map = {}; fe.forEach((x) => { map[x.loc] = x.msg; });
      setErrors(map);
    } finally { setSaving(false); }
  }
  const errFor = (suffix) => Object.entries(errors).find(([k]) => k.endsWith(suffix))?.[1];
  const setExtra = (i, k, v) => setForm((f) => ({ ...f, extra_ips: f.extra_ips.map((x, j) => j === i ? { ...x, [k]: k === "ip" ? v : UP(v) } : x) }));
  const addExtra = () => setForm((f) => f.extra_ips.length >= MAX_EXTRA_IPS ? f : { ...f, extra_ips: [...f.extra_ips, { ip: "", role: "", description: "" }] });
  const delExtra = (i) => setForm((f) => ({ ...f, extra_ips: f.extra_ips.filter((_, j) => j !== i) }));
  const setApp = (i, k, v) => setForm((f) => ({ ...f, apps: f.apps.map((a, j) => j === i ? { ...a, [k]: UP(v) } : a) }));
  const addApp = () => setForm((f) => f.apps.length >= MAX_APPS ? f : { ...f, apps: [...f.apps, { name: "", version: "" }] });
  const delApp = (i) => setForm((f) => ({ ...f, apps: f.apps.filter((_, j) => j !== i) }));
  const appErr = (i) => Object.entries(errors).find(([k]) => k.includes(`/apps/${i}`))?.[1];
  const setAcc = (i, k, v) => setForm((f) => ({ ...f, accesses: f.accesses.map((a, j) => j === i ? { ...a, [k]: ["port", "app", "path"].includes(k) ? v : UP(v) } : a) }));
  const addAcc = () => setForm((f) => f.accesses.length > MAX_EXTRA_ACCESS ? f : { ...f, accesses: [...f.accesses, { method: null, port: "", credential: null }] });
  const delAcc = (i) => setForm((f) => ({ ...f, accesses: f.accesses.length <= 1 ? [{ method: null, port: "", credential: null }] : f.accesses.filter((_, j) => j !== i) }));
  const [drag, setDrag] = useState({ from: null, over: null });   // arrastar para reordenar (1ª linha = principal)
  const dropAcc = (to) => {
    const from = drag.from;
    setDrag({ from: null, over: null });
    if (from == null || to == null || from === to) return;
    setForm((f) => {
      const l = [...f.accesses];
      const [it] = l.splice(from, 1);
      l.splice(to, 0, it);
      return { ...f, accesses: l };
    });
  };
  const accErr = (i) => Object.entries(errors).find(([k]) => k.includes(i === 0 ? "/access/" : `/extra_access/${i - 1}/`))?.[1]
    || (i === 0 ? errFor("/credential") : null);
  const extraErr = (i) => Object.entries(errors).find(([k]) => k.includes(`/extra_ips/${i}/`))?.[1];
  const extraGeneral = Object.entries(errors).find(([k]) => k.endsWith("/extra_ips") || k === "" || k === "/")?.[1];

  return html`<${Modal} title=${isNew ? t("hosts.form_new_title") : t("hosts.form_edit_title", { name: explicit.hostname })} cls="host-form" onClose=${onClose}>
    <div class="row">
      <${Field} label=${t("hosts.col_hostname")} error=${errFor("/hostname")}>
        <input value=${form.hostname} onInput=${(e) => set("hostname", e.target.value)} /><//>
      <${Field} label=${t("hosts.field_mgmt_ip")} error=${errFor("/mgmt_ip")}>
        <input value=${form.mgmt_ip} onInput=${(e) => set("mgmt_ip", e.target.value)} /><//>
    </div>
    <div class="field extra-ips">
      <label>${t("hosts.extra_ips_label")} <span class="muted">${t("hosts.extra_ips_hint", { n: form.extra_ips.length, max: MAX_EXTRA_IPS })}</span></label>
      <datalist id="extra-ip-roles">${IP_ROLES().map((r) => html`<option value=${r}></option>`)}</datalist>
      ${form.extra_ips.map((x, i) => html`<div class="extra-ip-row" key=${i}>
        <input class="mono" placeholder=${t("hosts.extra_ip_placeholder")} aria-label=${t("hosts.extra_ip_aria", { n: i + 1 })} value=${x.ip} onInput=${(e) => setExtra(i, "ip", e.target.value)} />
        <input list="extra-ip-roles" placeholder=${t("hosts.ip_role_placeholder")} maxlength="40" aria-label=${t("hosts.ip_role_aria", { n: i + 1 })} value=${x.role} onInput=${(e) => setExtra(i, "role", e.target.value)} />
        <input placeholder=${t("common.description")} maxlength="200" aria-label=${t("hosts.ip_description_aria", { n: i + 1 })} value=${x.description} onInput=${(e) => setExtra(i, "description", e.target.value)} />
        <button type="button" aria-label=${t("hosts.remove_ip_aria", { n: i + 1 })} title=${t("common.remove")} onClick=${() => delExtra(i)}>×</button>
        ${extraErr(i) && html`<div class="err">${extraErr(i)}</div>`}
      </div>`)}
      <div><button type="button" disabled=${form.extra_ips.length >= MAX_EXTRA_IPS} onClick=${addExtra}>${t("hosts.add_ip")}</button>
        ${form.extra_ips.length >= MAX_EXTRA_IPS && html` <span class="muted">${t("hosts.ip_limit", { max: MAX_EXTRA_IPS })}</span>`}</div>
      ${extraGeneral && html`<div class="err">${extraGeneral}</div>`}
    </div>
    <${Field} label=${t("hosts.field_group")}>
      <${RefSelect} value=${form.group} options=${upList(groups)} placeholder=${t("hosts.no_group")} onChange=${(v) => set("group", v)} /><//>
    <div class="row">
      <${Field} label=${html`Vendor ${tag("vendor")}`} error=${errFor("/vendor")}>
        <${EnumSelect} value=${form.vendor} options=${enums?.vendor} allowInherit=${!!form.group}
          inheritLabel=${t("hosts.inherit_label", { value: inh("vendor") || "—" })} onChange=${(v) => set("vendor", v)} /><//>
      <${Field} label=${html`Role ${tag("role")}`}>
        <${EnumSelect} value=${form.role} options=${enums?.role} allowInherit=${!!form.group}
          inheritLabel=${t("hosts.inherit_label", { value: inh("role") || "—" })} onChange=${(v) => set("role", v)} /><//>
    </div>
    ${local && html`<div class="card warn" role="note">🛡 <b>${t("hosts.local_note_title")}</b> ${t("hosts.local_note_1")}
      <span class="mono">netops-admin</span> ${t("hosts.local_note_2")}
      <span class="mono">sudo scripts/engine/localadmin/provision.py disable</span>.</div>`}
    <fieldset class="field access-methods" disabled=${local} style="border:0;padding:0;margin:0;min-width:0">
      <label>${t("hosts.access_methods_label")} <span class="muted">${t("hosts.access_methods_hint", { n: form.accesses.length, max: MAX_EXTRA_ACCESS + 1 })}</span></label>
      ${form.accesses.map((a, i) => html`<div class=${"access-row" + (drag.from === i ? " dragging" : "") + (drag.over === i && drag.from !== i ? (drag.from < i ? " drop-after" : " drop-before") : "")} key=${i}
        onDragOver=${(e) => { if (drag.from == null) return; e.preventDefault(); if (drag.over !== i) setDrag((d) => ({ ...d, over: i })); }}
        onDrop=${(e) => { e.preventDefault(); dropAcc(i); }}>
        <span class="access-handle" draggable="true" role="button" aria-label=${t("hosts.drag_method_aria", { n: i + 1 })} title=${t("hosts.drag_method_title")}
          onDragStart=${(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); const row = e.target.closest(".access-row"); if (row) e.dataTransfer.setDragImage(row, 10, 10); setDrag({ from: i, over: i }); }}
          onDragEnd=${() => setDrag({ from: null, over: null })}>⠿</span>
        <span class="access-rank ${i === 0 ? "primary" : ""}" title=${i === 0 ? t("hosts.rank_main_title") : t("hosts.rank_alt_title", { n: i })}>${i === 0 ? t("hosts.rank_main") : t("hosts.rank_nth", { n: i + 1 })}</span>
        <div class="access-fields">
          <div class="access-cell"><${EnumSelect} value=${a.method} options=${enums?.method} allowInherit=${i === 0 && !!form.group}
            inheritLabel=${t("hosts.inherit_label", { value: inhAccess("method") || "—" })} onChange=${(v) => setAcc(i, "method", v)} />
            ${i === 0 && tag("method", "method", a.method)}</div>
          <div class="access-cell"><input type="number" min="1" max="65535" aria-label=${t("hosts.port_aria", { n: i + 1 })} placeholder=${i === 0 ? (inhAccess("port") ? t("hosts.port_inherited", { port: inhAccess("port") }) : t("hosts.port_placeholder")) : t("hosts.port_default")}
            value=${a.port} onInput=${(e) => setAcc(i, "port", e.target.value)} /></div>
          <div class="access-cell"><${RefSelect} value=${a.credential} options=${creds}
            placeholder=${i === 0 ? (form.group && inh("credential") ? t("hosts.inherit_label", { value: inh("credential") }) : t("hosts.credential_none")) : t("hosts.credential_none")}
            onChange=${(v) => setAcc(i, "credential", v)} /></div>
        </div>
        ${i > 0 && ["HTTP", "HTTPS"].includes(String(a.method).toUpperCase()) && html`<div class="access-fields" style="margin-top:.4rem">
          <div class="access-cell"><select aria-label=${t("hosts.web_app_aria", { n: i + 1 })} value=${a.app || ""} onChange=${(e) => setAcc(i, "app", e.target.value)}>
            <option value="">${t("hosts.web_app_manual")}</option>
            <option value="proxmox">${t("hosts.web_app_proxmox")}</option>
            <option value="zabbix">${t("hosts.web_app_zabbix")}</option></select></div>
          <div class="access-cell"><input aria-label=${t("hosts.path_aria", { n: i + 1 })} placeholder=${t("hosts.path_placeholder")} value=${a.path || ""} onInput=${(e) => setAcc(i, "path", e.target.value)} /></div>
        </div>`}
        <div class="access-actions">
          <button type="button" aria-label=${t("hosts.remove_method_aria", { n: i + 1 })} title=${t("common.remove")} onClick=${() => delAcc(i)}>×</button>
        </div>
        ${i > 0 && !a.method && html`<div class="muted">${t("hosts.method_missing")}</div>`}
        ${accErr(i) && html`<div class="err">${accErr(i)}</div>`}
      </div>`)}
      <div><button type="button" disabled=${form.accesses.length > MAX_EXTRA_ACCESS} onClick=${addAcc}>${t("hosts.add_access")}</button></div>
    </fieldset>
    ${isNew && !placement && mapOptions && html`<${Field} label=${t("hosts.extra_map_label")}>
      <select value=${mapChoice} onChange=${e => setMapChoice(e.target.value)}><option value="">${t("hosts.extra_map_none")}</option>
        ${mapOptions.maps.filter(m => m.kind === "custom").map(m => html`<option value=${m.id}>${m.name}</option>`)}</select><//>`}
    <fieldset class="sys-box">
      <legend>${t("hosts.sys_legend")}</legend>
      <datalist id="os-suggest">${OS_SUGGEST.map((o) => html`<option value=${o}></option>`)}</datalist>
      <datalist id="app-suggest">${APP_SUGGEST.map((o) => html`<option value=${o}></option>`)}</datalist>
      <div class="sys-grid">
        <${Field} label=${t("hosts.field_model")}><input placeholder=${t("hosts.model_placeholder")} value=${form.model} onInput=${(e) => set("model", e.target.value)} /><//>
        <${Field} label=${t("hosts.field_os")} error=${errFor("/os")}><input list="os-suggest" placeholder=${t("hosts.os_placeholder")} maxlength="60" value=${form.os} onInput=${(e) => set("os", e.target.value)} /><//>
        <${Field} label=${t("hosts.field_os_version")} error=${errFor("/os_version")}><input class="mono" placeholder=${t("hosts.os_version_placeholder")} maxlength="60" value=${form.os_version} onInput=${(e) => set("os_version", e.target.value)} /><//>
        <${Field} label=${t("hosts.field_runs_on")} error=${errFor("/runs_on")}>
          <${RefSelect} value=${form.runs_on} options=${hostOpts} placeholder=${t("hosts.runs_on_placeholder")} onChange=${(v) => set("runs_on", v || "")} /><//>
      </div>
      ${legacyVersion && html`<div class="legacy-note">${t("hosts.legacy_note_1")} <b>${t("hosts.legacy_note_field")}</b>: <span class="mono">${legacyVersion}</span> ${t("hosts.legacy_note_2")}</div>`}
      <div class="field apps-list">
        <label>${t("hosts.col_apps")} <span class="muted">${t("hosts.apps_hint", { n: form.apps.length, max: MAX_APPS })}</span></label>
        ${form.apps.map((a, i) => html`<div class="app-row" key=${i}>
          <span class=${"access-rank" + (i === 0 ? " primary" : "")}>${i === 0 ? t("hosts.rank_main") : t("hosts.rank_nth", { n: i + 1 })}</span>
          <input list="app-suggest" placeholder=${t("hosts.app_placeholder")} maxlength="60" aria-label=${t("hosts.app_aria", { n: i + 1 })} value=${a.name} onInput=${(e) => setApp(i, "name", e.target.value)} />
          <input class="mono" placeholder=${t("hosts.app_version_placeholder")} maxlength="60" aria-label=${t("hosts.app_version_aria", { n: i + 1 })} value=${a.version} onInput=${(e) => setApp(i, "version", e.target.value)} />
          <button type="button" aria-label=${t("hosts.remove_app_aria", { n: i + 1 })} title=${t("common.remove")} onClick=${() => delApp(i)}>×</button>
          ${appErr(i) && html`<div class="err">${appErr(i)}</div>`}
        </div>`)}
        <div><button type="button" disabled=${form.apps.length >= MAX_APPS} onClick=${addApp}>${t("hosts.add_app")}</button></div>
      </div>
    </fieldset>
    <${Field} label=${t("hosts.field_site")}><input value=${form.site} onInput=${(e) => set("site", e.target.value)} /><//>
    <${HostIconPicker} value=${form.icon} onChange=${value => set("icon", value)} error=${errFor("/icon") || errors.icon} />
    <${Field} label=${t("hosts.col_notes")}><textarea value=${form.notes} onInput=${(e) => set("notes", e.target.value)}></textarea><//>
    <div class="modal-actions">
      <button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary needs-hosts-edit" disabled=${saving} onClick=${save}>${saving ? t("common.saving") : isNew ? t("common.create") : t("common.save")}</button>
    </div>
    ${conflict && html`<${ConflictDialog} onReload=${onSaved} onClose=${() => setConflict(false)} />`}
  <//>`;
}

/* ------------------------------- Grupos --------------------------------- */
// URL: #groups[/<nome>|/new][?q=&vendor=&role=]  (core/rules/urls-navegacao.md)
export function GroupsPage() {
  const res = useResource("/groups");
  const r = useMenuRoute("groups");
  const { q = "", vendor = "", role = "" } = r.params;
  const [confirm, setConfirm] = useState(null);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("hosts.load_error", { message: res.error.message })}</div>`;
  const { groups: allGroups, rev } = res.data;
  const seg = r.segments[0];
  const editing = seg === "new" ? { __new: true } : seg ? allGroups.find((g) => g.name === seg) || null : null;
  const setEditing = (g) => (g ? r.open(g.__new ? "new" : g.name) : r.close());
  const groups = allGroups.filter((g) => (!vendor || g.fields.vendor === vendor) && (!role || g.fields.role === role) && matchText(q, g.name, g.fields.credential));
  const optsOf = (f) => [...new Set(allGroups.map((g) => g.fields[f]).filter(Boolean))].sort();
  const cols = [
    { key: "name", label: t("hosts.col_group"), hideable: false, sort: (r) => r.name || "", render: (r) => html`<a href=${"#groups/" + encodeURIComponent(r.name)} onClick=${(e) => e.stopPropagation()}><b>${r.name}</b></a>` },
    { key: "vendor", label: "Vendor", sort: (r) => r.fields.vendor || "", render: (r) => r.fields.vendor || "—" },
    { key: "role", label: "Role", sort: (r) => r.fields.role || "", render: (r) => r.fields.role || "—" },
    { key: "access", label: t("hosts.col_access"), sort: (r) => (r.fields.access || {}).method || "", render: (r) => { const a = r.fields.access || {}; return html`<span class="mono">${a.method || "?"}:${a.port || "?"}</span>`; } },
    { key: "credential", label: t("hosts.col_credential"), sort: (r) => r.fields.credential || "", render: (r) => r.fields.credential || "—" },
    { key: "used_by", label: t("hosts.title"), sort: (r) => r.used_by, render: (r) => html`<${Badge}>${r.used_by}<//>` },
  ];
  return html`<div>
    <div class="page-title"><h1>${t("hosts.groups_title")}</h1><span class="spacer"></span>
      <button class="primary needs-hosts-edit" onClick=${() => setEditing({ __new: true })}>${t("hosts.new_group_btn")}</button></div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("hosts.search_group")} count=${groups.length} total=${allGroups.length}
      selects=${[{ key: "vendor", label: "Vendor", value: vendor, options: optsOf("vendor") }, { key: "role", label: "Role", value: role, options: optsOf("role") }]} />
    ${seg && seg !== "new" && !editing && html`<div class="card">${t("hosts.group_not_found", { name: seg })} <a href="#groups">${t("hosts.back_to_groups")}</a></div>`}
    <${DataTable} tableId="groups" urlSort columns=${cols} rows=${groups.map((g) => ({ ...g, _key: g.name }))}
      onRowClick=${(r) => setEditing(r)}
      actions=${(r) => html`<button class="sm danger needs-hosts-edit" onClick=${() => setConfirm(r)}>${t("common.delete")}</button>`}
      empty=${t("hosts.groups_empty")} />
    ${editing && html`<${GroupForm} key=${editing.name || "new"} group=${editing} rev=${rev}
        onClose=${() => setEditing(null)} onSaved=${() => { setEditing(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title=${t("hosts.delete_group_title")} danger=true
        message=${confirm.used_by ? t("hosts.delete_group_in_use", { count: confirm.used_by }) : t("hosts.delete_group_confirm", { name: confirm.name })}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/groups/${confirm.name}?force=${confirm.used_by > 0}`, rev); toast.ok(t("hosts.group_removed")); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function GroupForm({ group, rev, onClose, onSaved }) {
  const isNew = !!group.__new;
  const enums0 = useEnums();
  const enums = enums0 && { ...enums0, vendor: upList(enums0.vendor), role: upList(enums0.role), method: upList(enums0.method) };
  const [creds, setCreds] = useState([]);
  const f0 = isNew ? {} : group.fields;
  const a0 = f0.access || {};
  const [form, setForm] = useState({
    name: isNew ? "" : UP(group.name), vendor: UP(f0.vendor) ?? null, role: UP(f0.role) ?? null,
    credential: UP(f0.credential) ?? null, method: UP(a0.method) ?? null, port: a0.port ?? "",
  });
  useEffect(() => { api.get("/credentials").then((c) => setCreds(c.credentials.map((x) => UP(x.name)))); }, []);
  const set = (k, v) => setForm((x) => ({ ...x, [k]: UP_KEYS.has(k) || k === "name" ? UP(v) : v }));
  async function save() {
    const acc = {}; if (form.method) acc.method = form.method;
    if (form.port !== "" && form.port != null) acc.port = Number(form.port);
    const payload = { vendor: form.vendor || null, role: form.role || null,
      credential: form.credential || null, access: Object.keys(acc).length ? acc : null };
    try {
      if (isNew) {
        await api.post("/groups", { name: form.name, ...payload }, rev);
      } else {
        let curRev = rev;
        if (form.name !== group.name) {                     // renomeia primeiro (cascade nos hosts)
          curRev = (await api.post(`/groups/${group.name}/rename`, { to: form.name }, curRev)).rev;
        }
        await api.patch(`/groups/${form.name}`, payload, curRev);
      }
      toast.ok(isNew ? t("hosts.group_created") : t("hosts.group_updated")); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? t("hosts.new_group_title") : t("hosts.form_edit_title", { name: group.name })} onClose=${onClose}>
    <${Field} label=${isNew ? t("hosts.field_group_name") : t("hosts.field_group_rename")}>
      <input value=${form.name} placeholder=${t("hosts.group_name_placeholder")} onInput=${(e) => set("name", e.target.value)} /><//>
    ${!isNew && html`<${RenameCascadeHint} refsPath=${`/groups/${group.name}/references`} changed=${form.name !== group.name} />`}
    <div class="row">
      <${Field} label="Vendor"><${EnumSelect} value=${form.vendor} options=${enums?.vendor} onChange=${(v) => set("vendor", v)} /><//>
      <${Field} label="Role"><${EnumSelect} value=${form.role} options=${enums?.role} onChange=${(v) => set("role", v)} /><//>
    </div>
    <div class="row">
      <${Field} label=${t("hosts.field_method")}><${EnumSelect} value=${form.method} options=${enums?.method} onChange=${(v) => set("method", v)} /><//>
      <${Field} label=${t("hosts.field_port")}><input type="number" value=${form.port} onInput=${(e) => set("port", e.target.value)} /><//>
    </div>
    <${Field} label=${t("hosts.col_credential")}><${RefSelect} value=${form.credential} options=${creds} onChange=${(v) => set("credential", v)} /><//>
    <div class="modal-actions">
      <button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary needs-hosts-edit" onClick=${save}>${isNew ? t("common.create") : t("common.save")}</button>
    </div>
  <//>`;
}
