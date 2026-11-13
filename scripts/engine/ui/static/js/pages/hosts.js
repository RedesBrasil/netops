// Hosts e Grupos (network/hosts.yaml) — formulário ciente de herança de grupo.
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { FilterBar, ResourceTable, Field, EnumSelect, RefSelect, useEnums, ConfirmDialog, RenameCascadeHint, IconPicker as HostIconPicker } from "../components.js";
import { Modal, ConflictDialog } from "../ui.js";
import { useRoute, navigate, useMenuRoute, matchText } from "../route.js";

const INHERIT = ["vendor", "role", "credential"];
const bkLabel = (v) => v === true ? "sim" : v === false ? "não" : "padrão";

export function HostsPage() {
  const res = useResource("/hosts");
  // URL: #hosts[/<id>|/new][?q=&vendor=&role=&group=&sort=&dir=]  (core/rules/urls-navegacao.md)
  const route = useRoute();
  const { q = "", vendor = "", role = "", group = "", sort = "", dir = "asc" } = route.params;
  const setParams = (patch) => navigate({ menu: "hosts", segments: route.segments, params: { ...route.params, ...patch } }, { replace: true });
  const [confirm, setConfirm] = useState(null);
  const [deleteRefs, setDeleteRefs] = useState(null);
  useEffect(() => {
    setDeleteRefs(null);
    if (confirm) api.get(`/hosts/${encodeURIComponent(confirm)}/references`).then(setDeleteRefs).catch(handleError);
  }, [confirm]);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { hosts: allHosts, rev, groups } = res.data;
  const seg = route.segments[0];
  const editing = seg === "new" ? { __new: true } : seg ? allHosts.find((h) => String(h.id) === seg) || null : null;
  const setEditing = (h) => navigate({ menu: "hosts", segments: h ? [h.__new ? "new" : String(h.id)] : [], params: route.params });
  const opts = (f) => [...new Set(allHosts.map(f).filter(Boolean))].sort();
  const needle = q.trim().toLowerCase();
  const hosts = allHosts.filter((h) =>
    (!vendor || h.effective.vendor === vendor) && (!role || h.effective.role === role) && (!group || h.explicit.group === group) &&
    (!needle || [h.id, h.explicit.hostname, h.explicit.mgmt_ip].some((v) => String(v || "").toLowerCase().includes(needle))));

  const cols = [
    { key: "id", label: "ID", sort: (r) => String(r.id), render: (r) => html`<span class="mono">${r.id}</span>` },
    { key: "hostname", label: "Nome do host", hideable: false, sort: (r) => r.explicit.hostname || "", render: (r) => html`<a href=${"#hosts/" + encodeURIComponent(r.id)} onClick=${(e) => e.stopPropagation()}><b>${r.explicit.hostname}</b></a>` },
    { key: "mgmt_ip", label: "IP", sort: (r) => r.explicit.mgmt_ip || "", render: (r) => html`<span class="mono">${r.explicit.mgmt_ip}</span>` },
    { key: "vendor", label: "Vendor", sort: (r) => r.effective.vendor || "", render: (r) => html`<${Badge} kind="accent">${r.effective.vendor || "?"}<//>` },
    { key: "role", label: "Role", sort: (r) => r.effective.role || "", render: (r) => r.effective.role || "—" },
    { key: "group", label: "Grupo", sort: (r) => r.explicit.group || "", render: (r) => r.explicit.group || "—" },
    { key: "access", label: "Acesso", sort: (r) => (r.effective.access || {}).method || "", render: (r) => {
        const a = r.effective.access || {}; return html`<span class="mono">${a.method || "?"}:${a.port || "?"}</span>`; } },
    // Ocultas por padrão — o usuário liga em ⚙ Colunas (preferência salva no navegador).
    { key: "credential", label: "Credencial", hidden: true, sort: (r) => r.effective.credential || "", render: (r) => r.effective.credential || "—" },
    { key: "model", label: "Modelo", hidden: true, sort: (r) => r.effective.model || "", render: (r) => r.effective.model || "—" },
    { key: "site", label: "Site", hidden: true, sort: (r) => r.effective.site || "", render: (r) => r.effective.site || "—" },
    { key: "backup", label: "Backup pré-mudança", hidden: true, sort: (r) => bkLabel(r.effective.backup_before_change), render: (r) => bkLabel(r.effective.backup_before_change) },
    { key: "notes", label: "Notas", hidden: true, sort: (r) => r.effective.notes || "", render: (r) => html`<span title=${r.effective.notes || ""}>${r.effective.notes || "—"}</span>` },
  ];

  return html`<div>
    <div class="page-title"><h1>Hosts</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => setEditing({ __new: true })}>+ Novo host</button></div>
    <${FilterBar} q=${q} onChange=${setParams} placeholder="Buscar por ID, nome ou IP" count=${hosts.length} total=${allHosts.length}
      selects=${[{ key: "vendor", label: "Vendor", value: vendor, options: opts((h) => h.effective.vendor) },
                 { key: "role", label: "Role", value: role, options: opts((h) => h.effective.role) },
                 { key: "group", label: "Grupo", value: group, options: opts((h) => h.explicit.group) }]} />
    ${seg && seg !== "new" && !editing && html`<div class="card">Host '${seg}' não encontrado. <a href="#hosts">Voltar aos hosts</a></div>`}
    <${ResourceTable} tableId="hosts" columns=${cols} rows=${hosts.map((h) => ({ ...h, _key: h.id }))}
      sortState=${{ key: sort || null, dir }} onSortChange=${(n) => setParams({ sort: n.key || "", dir: n.dir === "desc" ? "desc" : "" })}
      onRowClick=${(r) => setEditing(r)}
      actions=${(r) => html`<button class="sm danger" onClick=${() => setConfirm(r.id)}>Excluir</button>`}
      empty="Nenhum host. Clique em + Novo host." />

    ${editing && html`<${HostForm} host=${editing} groups=${groups} rev=${rev}
        onClose=${() => setEditing(null)} onSaved=${() => { setEditing(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir host" danger=true
        message=${`Remover o host '${hosts.find(h => h.id === confirm)?.explicit.hostname || "selecionado"}' do inventário? Seus enlaces e referências nos mapas também serão removidos. ${deleteRefs ? `${deleteRefs.count} referência(s) afetada(s): ${deleteRefs.references.map(r => r.label).join(', ') || 'nenhuma'}.` : 'Verificando referências…'}`}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/hosts/${confirm}`, rev); toast.ok("Host removido"); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

export function HostForm({ host, groups, rev, onClose, onSaved, placement, initial = {} }) {
  const isNew = !!host.__new;
  const enums = useEnums();
  const [groupDetails, setGroupDetails] = useState({});
  const [creds, setCreds] = useState([]);
  const [conflict, setConflict] = useState(false);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [mapOptions, setMapOptions] = useState(null);
  const [mapChoice, setMapChoice] = useState("");
  const explicit = isNew ? initial : host.explicit;
  const [form, setForm] = useState({
    hostname: explicit.hostname || "", mgmt_ip: explicit.mgmt_ip || "",
    group: explicit.group || "", vendor: explicit.vendor ?? null, role: explicit.role ?? null,
    model: explicit.model || "", site: explicit.site || "", notes: explicit.notes || "", icon: explicit.icon || "",
    credential: explicit.credential ?? null,
    method: (explicit.access || {}).method ?? null, port: (explicit.access || {}).port ?? "",
  });

  useEffect(() => {
    if (isNew && !placement) api.get("/maps").then(setMapOptions).catch(() => {});
    api.get("/groups").then((g) => setGroupDetails(Object.fromEntries(g.groups.map((x) => [x.name, x.fields]))));
    api.get("/credentials").then((c) => setCreds(c.credentials.map((x) => x.name)));
  }, []);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const gfields = groupDetails[form.group] || {};
  const inh = (k) => gfields[k];                                  // valor herdado do grupo
  const inhAccess = (k) => (gfields.access || {})[k];

  function tag(k, accessKey) {
    const explicitVal = accessKey ? form[k] : form[k];
    const isSet = explicitVal !== null && explicitVal !== "" && explicitVal !== undefined;
    if (isSet) return html`<span class="tag-explicit">explícito</span>`;
    const v = accessKey ? inhAccess(accessKey) : inh(k);
    return v ? html`<span class="tag-inherit">herdado de ${form.group}: ${v}</span>` : null;
  }

  async function save() {
    if (saving) return;
    setSaving(true);
    setErrors({});
    const payload = {};
    // obrigatórios
    payload.hostname = form.hostname; payload.mgmt_ip = form.mgmt_ip;
    if (form.group) payload.group = form.group; else if (!isNew) payload.group = null;
    for (const k of ["vendor", "role", "credential"]) payload[k] = form[k] || null;
    for (const k of ["model", "site", "notes", "icon"]) payload[k] = form[k] || null;
    const acc = {};
    if (form.method) acc.method = form.method;
    if (form.port !== "" && form.port != null) acc.port = Number(form.port);
    payload.access = Object.keys(acc).length ? acc : null;
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
      toast.ok(isNew ? "Host criado" : "Host atualizado");
      onSaved(savedId);
    } catch (e) {
      if (e.name === "ConflictError" || e.constructor?.name === "ConflictError") return setConflict(true);
      const fe = handleError(e);
      const map = {}; fe.forEach((x) => { map[x.loc] = x.msg; });
      setErrors(map);
    } finally { setSaving(false); }
  }
  const errFor = (suffix) => Object.entries(errors).find(([k]) => k.endsWith(suffix))?.[1];

  return html`<${Modal} title=${isNew ? "Novo host" : `Editar ${explicit.hostname}`} onClose=${onClose}>
    <div class="row">
      <${Field} label="Nome do host" error=${errFor("/hostname")}>
        <input value=${form.hostname} onInput=${(e) => set("hostname", e.target.value)} /><//>
      <${Field} label="IP de gerência" error=${errFor("/mgmt_ip")}>
        <input value=${form.mgmt_ip} onInput=${(e) => set("mgmt_ip", e.target.value)} /><//>
    </div>
    <${Field} label="Grupo (herança de defaults)">
      <${RefSelect} value=${form.group} options=${groups} placeholder="(sem grupo)" onChange=${(v) => set("group", v)} /><//>
    <div class="row">
      <${Field} label=${html`Vendor ${tag("vendor")}`} error=${errFor("/vendor")}>
        <${EnumSelect} value=${form.vendor} options=${enums?.vendor} allowInherit=${!!form.group}
          inheritLabel=${`herdar: ${inh("vendor") || "—"}`} onChange=${(v) => set("vendor", v)} /><//>
      <${Field} label=${html`Role ${tag("role")}`}>
        <${EnumSelect} value=${form.role} options=${enums?.role} allowInherit=${!!form.group}
          inheritLabel=${`herdar: ${inh("role") || "—"}`} onChange=${(v) => set("role", v)} /><//>
    </div>
    <div class="row">
      <${Field} label=${html`Método de acesso ${tag("method", "method")}`} error=${errFor("access/method")}>
        <${EnumSelect} value=${form.method} options=${enums?.method} allowInherit=${!!form.group}
          inheritLabel=${`herdar: ${inhAccess("method") || "—"}`} onChange=${(v) => set("method", v)} /><//>
      <${Field} label=${html`Porta ${tag("port", "port")}`} error=${errFor("access/port")}>
        <input type="number" value=${form.port} placeholder=${inhAccess("port") || ""}
          onInput=${(e) => set("port", e.target.value)} /><//>
    </div>
    <${Field} label=${html`Credencial ${tag("credential")}`} error=${errFor("/credential")}>
      <${RefSelect} value=${form.credential} options=${creds}
        placeholder=${form.group && inh("credential") ? `herdar: ${inh("credential")}` : "(nenhuma)"}
        onChange=${(v) => set("credential", v)} /><//>
    ${isNew && !placement && mapOptions && html`<${Field} label="Também incluir em um mapa adicional">
      <select value=${mapChoice} onChange=${e => setMapChoice(e.target.value)}><option value="">Só geral e localidade (automático)</option>
        ${mapOptions.maps.filter(m => m.kind === "custom").map(m => html`<option value=${m.id}>${m.name}</option>`)}</select><//>`}
    <div class="row">
      <${Field} label="Modelo"><input value=${form.model} onInput=${(e) => set("model", e.target.value)} /><//>
      <${Field} label="Site"><input value=${form.site} onInput=${(e) => set("site", e.target.value)} /><//>
    </div>
    <${HostIconPicker} value=${form.icon} onChange=${value => set("icon", value)} error=${errFor("/icon") || errors.icon} />
    <${Field} label="Notas"><textarea value=${form.notes} onInput=${(e) => set("notes", e.target.value)}></textarea><//>
    <div class="modal-actions">
      <button onClick=${onClose}>Cancelar</button>
      <button class="primary" disabled=${saving} onClick=${save}>${saving ? "Salvando…" : isNew ? "Criar" : "Salvar"}</button>
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
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { groups: allGroups, rev } = res.data;
  const seg = r.segments[0];
  const editing = seg === "new" ? { __new: true } : seg ? allGroups.find((g) => g.name === seg) || null : null;
  const setEditing = (g) => (g ? r.open(g.__new ? "new" : g.name) : r.close());
  const groups = allGroups.filter((g) => (!vendor || g.fields.vendor === vendor) && (!role || g.fields.role === role) && matchText(q, g.name, g.fields.credential));
  const optsOf = (f) => [...new Set(allGroups.map((g) => g.fields[f]).filter(Boolean))].sort();
  const cols = [
    { key: "name", label: "Grupo", sort: (r) => r.name || "", render: (r) => html`<a href=${"#groups/" + encodeURIComponent(r.name)} onClick=${(e) => e.stopPropagation()}><b>${r.name}</b></a>` },
    { key: "vendor", label: "Vendor", sort: (r) => r.fields.vendor || "", render: (r) => r.fields.vendor || "—" },
    { key: "role", label: "Role", sort: (r) => r.fields.role || "", render: (r) => r.fields.role || "—" },
    { key: "access", label: "Acesso", sort: (r) => (r.fields.access || {}).method || "", render: (r) => { const a = r.fields.access || {}; return html`<span class="mono">${a.method || "?"}:${a.port || "?"}</span>`; } },
    { key: "credential", label: "Credencial", sort: (r) => r.fields.credential || "", render: (r) => r.fields.credential || "—" },
    { key: "used_by", label: "Hosts", sort: (r) => r.used_by, render: (r) => html`<${Badge}>${r.used_by}<//>` },
  ];
  return html`<div>
    <div class="page-title"><h1>Grupos</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => setEditing({ __new: true })}>+ Novo grupo</button></div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar grupo" count=${groups.length} total=${allGroups.length}
      selects=${[{ key: "vendor", label: "Vendor", value: vendor, options: optsOf("vendor") }, { key: "role", label: "Role", value: role, options: optsOf("role") }]} />
    ${seg && seg !== "new" && !editing && html`<div class="card">Grupo '${seg}' não encontrado. <a href="#groups">Voltar aos grupos</a></div>`}
    <${ResourceTable} columns=${cols} rows=${groups.map((g) => ({ ...g, _key: g.name }))}
      onRowClick=${(r) => setEditing(r)}
      actions=${(r) => html`<button class="sm danger" onClick=${() => setConfirm(r)}>Excluir</button>`}
      empty="Nenhum grupo." />
    ${editing && html`<${GroupForm} key=${editing.name || "new"} group=${editing} rev=${rev}
        onClose=${() => setEditing(null)} onSaved=${() => { setEditing(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir grupo" danger=true
        message=${confirm.used_by ? `Grupo em uso por ${confirm.used_by} host(s). Excluir mesmo assim?` : `Excluir o grupo '${confirm.name}'?`}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/groups/${confirm.name}?force=${confirm.used_by > 0}`, rev); toast.ok("Grupo removido"); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function GroupForm({ group, rev, onClose, onSaved }) {
  const isNew = !!group.__new;
  const enums = useEnums();
  const [creds, setCreds] = useState([]);
  const f0 = isNew ? {} : group.fields;
  const a0 = f0.access || {};
  const [form, setForm] = useState({
    name: isNew ? "" : group.name, vendor: f0.vendor ?? null, role: f0.role ?? null,
    credential: f0.credential ?? null, method: a0.method ?? null, port: a0.port ?? "",
  });
  useEffect(() => { api.get("/credentials").then((c) => setCreds(c.credentials.map((x) => x.name))); }, []);
  const set = (k, v) => setForm((x) => ({ ...x, [k]: v }));
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
      toast.ok(isNew ? "Grupo criado" : "Grupo atualizado"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? "Novo grupo" : `Editar ${group.name}`} onClose=${onClose}>
    <${Field} label=${isNew ? "Nome do grupo" : "Nome (alterar = renomear, atualiza os hosts)"}>
      <input value=${form.name} placeholder="ex.: mikrotik-core" onInput=${(e) => set("name", e.target.value)} /><//>
    ${!isNew && html`<${RenameCascadeHint} refsPath=${`/groups/${group.name}/references`} changed=${form.name !== group.name} />`}
    <div class="row">
      <${Field} label="Vendor"><${EnumSelect} value=${form.vendor} options=${enums?.vendor} onChange=${(v) => set("vendor", v)} /><//>
      <${Field} label="Role"><${EnumSelect} value=${form.role} options=${enums?.role} onChange=${(v) => set("role", v)} /><//>
    </div>
    <div class="row">
      <${Field} label="Método"><${EnumSelect} value=${form.method} options=${enums?.method} onChange=${(v) => set("method", v)} /><//>
      <${Field} label="Porta"><input type="number" value=${form.port} onInput=${(e) => set("port", e.target.value)} /><//>
    </div>
    <${Field} label="Credencial"><${RefSelect} value=${form.credential} options=${creds} onChange=${(v) => set("credential", v)} /><//>
    <div class="modal-actions">
      <button onClick=${onClose}>Cancelar</button>
      <button class="primary" onClick=${save}>${isNew ? "Criar" : "Salvar"}</button>
    </div>
  <//>`;
}
