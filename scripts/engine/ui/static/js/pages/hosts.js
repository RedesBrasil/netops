// Hosts e Grupos (network/hosts.yaml) — formulário ciente de herança de grupo.
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { FilterBar, DataTable, Field, EnumSelect, RefSelect, useEnums, ConfirmDialog, RenameCascadeHint, IconPicker as HostIconPicker } from "../components.js";
import { Modal, ConflictDialog } from "../ui.js";
import { useRoute, navigate, useMenuRoute, matchText } from "../route.js";

// Padrão de cadastro: tudo em MAIÚSCULAS, exceto site e notes (o backend também força).
const UP = (v) => typeof v === "string" ? v.toUpperCase() : v;
const MAX_EXTRA_IPS = 20;  // mesmo teto do backend (models.MAX_EXTRA_IPS)
const IP_ROLES = ["público", "interno", "VIP", "loopback", "gerência secundária"];  // sugestões; o campo é livre
const upList = (l) => (l || []).map(UP);
const UP_KEYS = new Set(["hostname", "group", "vendor", "role", "model", "version", "credential", "method"]);  // (credential/method dos métodos ficam em form.accesses)
const INHERIT = ["vendor", "role", "credential"];
const MAX_EXTRA_ACCESS = 10;  // mesmo teto do backend (models.MAX_EXTRA_ACCESS)
const bkLabel = (v) => v === true ? "sim" : v === false ? "não" : "padrão";

export function HostsPage() {
  const res = useResource("/hosts");
  // URL: #hosts[/<id>|/new][?q=&vendor=&role=&group=&sort=&dir=]  (core/rules/urls-navegacao.md)
  const route = useRoute();
  const { q = "", vendor = "", role = "", group = "" } = route.params;
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
    (!needle || [h.id, h.explicit.hostname, h.explicit.mgmt_ip, ...(h.explicit.extra_ips || []).map((x) => x.ip)].some((v) => String(v || "").toLowerCase().includes(needle))));

  const cols = [
    { key: "id", label: "ID", sort: (r) => String(r.id), render: (r) => html`<span class="mono">${r.id}</span>` },
    { key: "hostname", label: "Nome do host", hideable: false, sort: (r) => r.explicit.hostname || "", render: (r) => html`<a href=${"#hosts/" + encodeURIComponent(r.id)} onClick=${(e) => e.stopPropagation()}><b>${r.explicit.hostname}</b></a>` },
    { key: "mgmt_ip", label: "IP", sort: (r) => r.explicit.mgmt_ip || "", render: (r) => html`<span class="mono">${r.explicit.mgmt_ip}</span>` },
    { key: "vendor", label: "Vendor", sort: (r) => r.effective.vendor || "", render: (r) => html`<${Badge} kind="accent">${r.effective.vendor || "?"}<//>` },
    { key: "role", label: "Role", sort: (r) => r.effective.role || "", render: (r) => r.effective.role || "—" },
    { key: "group", label: "Grupo", sort: (r) => r.explicit.group || "", render: (r) => r.explicit.group || "—" },
    { key: "access", label: "Acesso", sort: (r) => (r.effective.access || {}).method || "", render: (r) => {
        const a = r.effective.access || {}; const more = (r.explicit.extra_access || []).map((x) => `${x.method}${x.port ? ":" + x.port : ""}`);
        return html`<span class="mono" title=${more.length ? "Alternativos: " + more.join(", ") : ""}>${a.method || "?"}:${a.port || "?"}${more.length ? ` +${more.length}` : ""}</span>`; } },
    // Ocultas por padrão — o usuário liga em ⚙ Colunas (preferência salva no navegador).
    { key: "credential", label: "Credencial", hidden: true, sort: (r) => r.effective.credential || "", render: (r) => r.effective.credential || "—" },
    { key: "model", label: "Modelo", hidden: true, sort: (r) => r.effective.model || "", render: (r) => r.effective.model || "—" },
    { key: "version", label: "Versão (SO/app)", hidden: true, sort: (r) => r.effective.version || "", render: (r) => r.effective.version || "—" },
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
    <${DataTable} tableId="hosts" urlSort columns=${cols} rows=${hosts.map((h) => ({ ...h, _key: h.id }))}
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
  const enums0 = useEnums();
  const enums = enums0 && { ...enums0, vendor: upList(enums0.vendor), role: upList(enums0.role), method: upList(enums0.method) };
  const [groupDetails, setGroupDetails] = useState({});
  const [creds, setCreds] = useState([]);
  const [conflict, setConflict] = useState(false);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [mapOptions, setMapOptions] = useState(null);
  const [mapChoice, setMapChoice] = useState("");
  const explicit = isNew ? initial : host.explicit;
  const [form, setForm] = useState({
    hostname: UP(explicit.hostname) || "", mgmt_ip: explicit.mgmt_ip || "",
    group: UP(explicit.group) || "", vendor: UP(explicit.vendor) ?? null, role: UP(explicit.role) ?? null,
    model: UP(explicit.model) || "", version: UP(explicit.version) || "", site: explicit.site || "", notes: explicit.notes || "", icon: explicit.icon || "",
    // Métodos de acesso em ordem de prioridade: o 1º é o principal (grava em access/credential); os demais em extra_access.
    accesses: [
      { method: UP((explicit.access || {}).method) ?? null, port: (explicit.access || {}).port ?? "", credential: UP(explicit.credential) ?? null },
      ...(explicit.extra_access || []).map((x) => ({ method: UP(x.method) ?? null, port: x.port ?? "", credential: UP(x.credential) ?? null })),
    ],
    extra_ips: (explicit.extra_ips || []).map((x) => ({ ip: x.ip || "", role: UP(x.role) || "", description: UP(x.description) || "" })),
  });

  useEffect(() => {
    if (isNew && !placement) api.get("/maps").then(setMapOptions).catch(() => {});
    api.get("/groups").then((g) => setGroupDetails(Object.fromEntries(g.groups.map((x) => [UP(x.name), x.fields]))));
    api.get("/credentials").then((c) => setCreds(c.credentials.map((x) => UP(x.name))));
  }, []);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: UP_KEYS.has(k) ? UP(v) : v }));
  const gfields = groupDetails[form.group] || {};
  const inh = (k) => gfields[k];                                  // valor herdado do grupo
  const inhAccess = (k) => (gfields.access || {})[k];

  function tag(k, accessKey, value = form[k]) {
    const explicitVal = value;
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
    for (const k of ["vendor", "role"]) payload[k] = form[k] || null;
    const [main, ...others] = form.accesses;
    payload.credential = main.credential || null;
    for (const k of ["model", "version", "site", "notes", "icon"]) payload[k] = form[k] || null;
    const acc = {};
    if (main.method) acc.method = main.method;
    if (main.port !== "" && main.port != null) acc.port = Number(main.port);
    payload.access = Object.keys(acc).length ? acc : null;
    const extraAcc = others.filter((a) => a.method).map((a) => {
      const item = { method: a.method };
      if (a.port !== "" && a.port != null) item.port = Number(a.port);
      if (a.credential) item.credential = a.credential;
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
  const setExtra = (i, k, v) => setForm((f) => ({ ...f, extra_ips: f.extra_ips.map((x, j) => j === i ? { ...x, [k]: k === "ip" ? v : UP(v) } : x) }));
  const addExtra = () => setForm((f) => f.extra_ips.length >= MAX_EXTRA_IPS ? f : { ...f, extra_ips: [...f.extra_ips, { ip: "", role: "", description: "" }] });
  const delExtra = (i) => setForm((f) => ({ ...f, extra_ips: f.extra_ips.filter((_, j) => j !== i) }));
  const setAcc = (i, k, v) => setForm((f) => ({ ...f, accesses: f.accesses.map((a, j) => j === i ? { ...a, [k]: k === "port" ? v : UP(v) } : a) }));
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

  return html`<${Modal} title=${isNew ? "Novo host" : `Editar ${explicit.hostname}`} cls="host-form" onClose=${onClose}>
    <div class="row">
      <${Field} label="Nome do host" error=${errFor("/hostname")}>
        <input value=${form.hostname} onInput=${(e) => set("hostname", e.target.value)} /><//>
      <${Field} label="IP de gerência" error=${errFor("/mgmt_ip")}>
        <input value=${form.mgmt_ip} onInput=${(e) => set("mgmt_ip", e.target.value)} /><//>
    </div>
    <div class="field extra-ips">
      <label>IPs adicionais <span class="muted">(${form.extra_ips.length}/${MAX_EXTRA_IPS}) — só informativo; a conexão usa o IP de gerência</span></label>
      <datalist id="extra-ip-roles">${IP_ROLES.map((r) => html`<option value=${r}></option>`)}</datalist>
      ${form.extra_ips.map((x, i) => html`<div class="extra-ip-row" key=${i}>
        <input class="mono" placeholder="IP (ex.: 200.1.2.3/29)" aria-label=${`IP adicional ${i + 1}`} value=${x.ip} onInput=${(e) => setExtra(i, "ip", e.target.value)} />
        <input list="extra-ip-roles" placeholder="Função" maxlength="40" aria-label=${`Função do IP ${i + 1}`} value=${x.role} onInput=${(e) => setExtra(i, "role", e.target.value)} />
        <input placeholder="Descrição" maxlength="200" aria-label=${`Descrição do IP ${i + 1}`} value=${x.description} onInput=${(e) => setExtra(i, "description", e.target.value)} />
        <button type="button" aria-label=${`Remover IP ${i + 1}`} title="Remover" onClick=${() => delExtra(i)}>×</button>
        ${extraErr(i) && html`<div class="err">${extraErr(i)}</div>`}
      </div>`)}
      <div><button type="button" disabled=${form.extra_ips.length >= MAX_EXTRA_IPS} onClick=${addExtra}>+ Adicionar IP</button>
        ${form.extra_ips.length >= MAX_EXTRA_IPS && html` <span class="muted">Limite de ${MAX_EXTRA_IPS} IPs atingido.</span>`}</div>
      ${extraGeneral && html`<div class="err">${extraGeneral}</div>`}
    </div>
    <${Field} label="Grupo (herança de defaults)">
      <${RefSelect} value=${form.group} options=${upList(groups)} placeholder="(sem grupo)" onChange=${(v) => set("group", v)} /><//>
    <div class="row">
      <${Field} label=${html`Vendor ${tag("vendor")}`} error=${errFor("/vendor")}>
        <${EnumSelect} value=${form.vendor} options=${enums?.vendor} allowInherit=${!!form.group}
          inheritLabel=${`herdar: ${inh("vendor") || "—"}`} onChange=${(v) => set("vendor", v)} /><//>
      <${Field} label=${html`Role ${tag("role")}`}>
        <${EnumSelect} value=${form.role} options=${enums?.role} allowInherit=${!!form.group}
          inheritLabel=${`herdar: ${inh("role") || "—"}`} onChange=${(v) => set("role", v)} /><//>
    </div>
    <div class="field access-methods">
      <label>Métodos de acesso <span class="muted">(${form.accesses.length}/${MAX_EXTRA_ACCESS + 1}) — o 1º é o principal; arraste ⠿ para reordenar</span></label>
      ${form.accesses.map((a, i) => html`<div class=${"access-row" + (drag.from === i ? " dragging" : "") + (drag.over === i && drag.from !== i ? (drag.from < i ? " drop-after" : " drop-before") : "")} key=${i}
        onDragOver=${(e) => { if (drag.from == null) return; e.preventDefault(); if (drag.over !== i) setDrag((d) => ({ ...d, over: i })); }}
        onDrop=${(e) => { e.preventDefault(); dropAcc(i); }}>
        <span class="access-handle" draggable="true" role="button" aria-label=${`Arrastar método ${i + 1} para reordenar`} title="Arraste para cima/baixo para mudar a prioridade"
          onDragStart=${(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); const row = e.target.closest(".access-row"); if (row) e.dataTransfer.setDragImage(row, 10, 10); setDrag({ from: i, over: i }); }}
          onDragEnd=${() => setDrag({ from: null, over: null })}>⠿</span>
        <span class="access-rank ${i === 0 ? "primary" : ""}" title=${i === 0 ? "Método principal" : `Alternativo ${i}`}>${i === 0 ? "Principal" : i + 1 + "º"}</span>
        <div class="access-fields">
          <div class="access-cell"><${EnumSelect} value=${a.method} options=${enums?.method} allowInherit=${i === 0 && !!form.group}
            inheritLabel=${`herdar: ${inhAccess("method") || "—"}`} onChange=${(v) => setAcc(i, "method", v)} />
            ${i === 0 && tag("method", "method", a.method)}</div>
          <div class="access-cell"><input type="number" min="1" max="65535" aria-label=${`Porta do método ${i + 1}`} placeholder=${i === 0 ? (inhAccess("port") ? `porta (herdada: ${inhAccess("port")})` : "porta") : "porta (padrão do método)"}
            value=${a.port} onInput=${(e) => setAcc(i, "port", e.target.value)} /></div>
          <div class="access-cell"><${RefSelect} value=${a.credential} options=${creds}
            placeholder=${i === 0 ? (form.group && inh("credential") ? `herdar: ${inh("credential")}` : "(credencial: nenhuma)") : "(credencial: nenhuma)"}
            onChange=${(v) => setAcc(i, "credential", v)} /></div>
        </div>
        <div class="access-actions">
          <button type="button" aria-label=${`Remover método ${i + 1}`} title="Remover" onClick=${() => delAcc(i)}>×</button>
        </div>
        ${i > 0 && !a.method && html`<div class="muted">Escolha o método — linha sem método é ignorada ao salvar.</div>`}
        ${accErr(i) && html`<div class="err">${accErr(i)}</div>`}
      </div>`)}
      <div><button type="button" disabled=${form.accesses.length > MAX_EXTRA_ACCESS} onClick=${addAcc}>+ Adicionar método de acesso</button></div>
    </div>
    ${isNew && !placement && mapOptions && html`<${Field} label="Também incluir em um mapa adicional">
      <select value=${mapChoice} onChange=${e => setMapChoice(e.target.value)}><option value="">Só geral e localidade (automático)</option>
        ${mapOptions.maps.filter(m => m.kind === "custom").map(m => html`<option value=${m.id}>${m.name}</option>`)}</select><//>`}
    <div class="row">
      <${Field} label="Modelo"><input value=${form.model} onInput=${(e) => set("model", e.target.value)} /><//>
      <${Field} label="Versão (SO ou aplicação)"><input placeholder="ex.: RouterOS 7.16.2, Debian 12, Zabbix 7.0.32" maxlength="80" value=${form.version} onInput=${(e) => set("version", e.target.value)} /><//>
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
    { key: "name", label: "Grupo", hideable: false, sort: (r) => r.name || "", render: (r) => html`<a href=${"#groups/" + encodeURIComponent(r.name)} onClick=${(e) => e.stopPropagation()}><b>${r.name}</b></a>` },
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
    <${DataTable} tableId="groups" urlSort columns=${cols} rows=${groups.map((g) => ({ ...g, _key: g.name }))}
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
