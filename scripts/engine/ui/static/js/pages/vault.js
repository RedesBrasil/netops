// Cofre de senhas (network/vault.yaml): segredos que NÃO são de host (portais, APIs, tokens).
// Texto puro aparece sempre; segredo só abre (revelar/copiar/gravar) com o cofre destrancado.
// URL (core/rules/urls-navegacao.md):
//   #vault[?q=&tpl=]  #vault/new  #vault/<id>  #vault/<id>/edit
//   #vault/templates  #vault/templates/new  #vault/templates/<id>
//   #vault/fields     #vault/fields/new     #vault/fields/<nome>
import { html, useState, api, useResource, useStore, vaultStore, Spinner, Badge, toast, handleError, can, Modal, ConfirmDialog, t } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, PasswordInput, VaultBanner } from "../components.js";

const KIND_LABEL = { secret: "vault.kind_secret", text: "vault.kind_text" };   // i18n keys, translated at render time
const kindLabel = (kind) => (KIND_LABEL[kind] ? t(KIND_LABEL[kind]) : kind);
const MASK = "••••••••";
// Mesmo slug de lib/pwvault.slugify: referência usada no .env (scripts/tools/secrets/run.py).
const slug = (s) => String(s || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48).replace(/-+$/, "") || "item";
export const vaultRef = (itemId, field) => `nvault://${itemId}/${slug(field)}`;

async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (_) {}
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (_) {}
  ta.remove(); return ok;
}

export function VaultPage() {
  const res = useResource("/vault/items");
  const v = useStore(vaultStore);
  const r = useMenuRoute("vault");
  if (res.loading && !res.data) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("vault.load_error", { message: res.error.message })}</div>`;
  const unlocked = v.state === "cache" || v.state === "env";
  const [seg] = r.segments;
  const tab = seg === "templates" || seg === "fields" ? seg : "items";
  const tabBtn = (key, label, go) => html`<button class=${tab === key ? "active" : ""} onClick=${go}>${label}</button>`;
  const ctx = { data: res.data, reload: res.reload, r, unlocked };
  const newBtn = tab === "items" ? html`<button class="primary sm needs-vault-edit" onClick=${() => r.open("new")}>${t("vault.new_item_btn")}</button>`
    : tab === "templates" ? html`<button class="primary sm needs-vault-templates" onClick=${() => r.open(["templates", "new"])}>${t("vault.new_template_btn")}</button>`
    : html`<button class="primary sm needs-vault-templates" onClick=${() => r.open(["fields", "new"])}>${t("vault.new_field_btn")}</button>`;
  return html`<div class="vault-page">
    <div class="page-title"><h1 title=${t("vault.title_hint")}>${t("vault.title")}</h1>
      <span class="spacer"></span>
      <span class=${"vault-state " + (unlocked ? "ok" : "locked")}>${unlocked ? t("vault.state_unlocked") : t("vault.state_locked")}</span>
      <${VaultBanner} compact=${true} /></div>
    <div class="tabs">
      ${tabBtn("items", t("vault.tab_items"), () => r.close())}
      ${tabBtn("templates", t("vault.tab_templates"), () => r.open("templates"))}
      ${tabBtn("fields", t("vault.tab_fields"), () => r.open("fields"))}
      <span class="tabs-actions">${newBtn}</span>
    </div>
    ${tab === "items" && html`<${ItemsTab} ...${ctx} />`}
    ${tab === "templates" && html`<${TemplatesTab} ...${ctx} />`}
    ${tab === "fields" && html`<${FieldsTab} ...${ctx} />`}
  </div>`;
}

/* --------------------------------- Itens --------------------------------- */
function ItemsTab({ data, reload, r, unlocked }) {
  const [confirm, setConfirm] = useState(null);
  const { items: all, templates, rev } = data;
  const tplById = Object.fromEntries(templates.map((tp) => [tp.id, tp]));
  const q = r.params.q || "";
  const tplLabel = r.params.tpl || "";
  const textOf = (it) => it.values.filter((x) => x.kind === "text").map((x) => x.value);
  const items = all.filter((it) => (!tplLabel || (it.template_label || "—") === tplLabel)
    && matchText(q, it.title, it.template_label, it.notes, ...textOf(it)));
  const tplOptions = [...new Set(all.map((it) => it.template_label || "—"))].sort();
  const [seg, sub] = r.segments;
  // ID numérico (estável); o slug antigo (apelido) também abre o item.
  const found = seg && seg !== "new" ? all.find((it) => String(it.id) === seg || (it.aliases || []).includes(seg)) : null;

  const visibleOf = (it) => {
    const tpl = tplById[it.template];
    const vis = new Set((tpl?.fields || []).filter((f) => f.visible).map((f) => f.field));
    return it.values.filter((x) => vis.has(x.field));
  };
  const cols = [
    { key: "id", label: "ID", sort: (it) => it.id, render: (it) => it.id },
    { key: "title", label: t("vault.col_title"), hideable: false, sort: (it) => it.title,
      render: (it) => html`<a href=${"#vault/" + encodeURIComponent(it.id)} onClick=${(e) => e.stopPropagation()}><b>${it.title}</b></a>` },
    { key: "template", label: t("vault.col_template"), sort: (it) => it.template_label || "", render: (it) => it.template_label ? html`<${Badge}>${it.template_label}<//>` : "—" },
    { key: "visible", label: t("vault.col_visible_fields"), render: (it) => html`${visibleOf(it).map((x) => html`<span class="vault-kv" key=${x.field}>
        <span class="muted">${x.field}:</span> ${x.kind === "text" ? x.value : MASK + (unlocked ? "" : " 🔒")}</span>`)}` },
    { key: "secrets", label: t("vault.col_secrets"), sort: (it) => it.values.filter((x) => x.kind === "secret").length,
      render: (it) => { const n = it.values.filter((x) => x.kind === "secret").length; return n ? `🔒 ${n}` : "—"; } },
    { key: "updated_at", label: t("vault.col_updated_at"), sort: (it) => it.updated_at || "", render: (it) => (it.updated_at || "").replace("T", " ").slice(0, 16) },
    { key: "updated_by", label: t("vault.col_updated_by"), sort: (it) => it.updated_by || "", render: (it) => it.updated_by || "—" },
  ];
  return html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("vault.search_placeholder")}
      selects=${[{ key: "tpl", label: t("vault.col_template"), value: tplLabel, options: tplOptions }]} count=${items.length} total=${all.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">${t("vault.item_not_found", { id: seg })} <a href="#vault">${t("vault.back_to_vault")}</a></div>`}
    <${DataTable} tableId="vault-items" urlSort columns=${cols} rows=${items.map((it) => ({ ...it, _key: it.id }))}
      onRowClick=${(it) => r.open(it.id)}
      actions=${(it) => html`
        <button class="sm" onClick=${() => r.open(it.id)}>${t("common.open")}</button>
        <button class="sm needs-vault-edit" onClick=${() => r.open([it.id, "edit"])}>${t("common.edit")}</button>
        <button class="sm danger needs-vault-edit" onClick=${() => setConfirm(it)}>${t("common.delete")}</button>`}
      empty=${t("vault.items_empty")} />
    ${found && sub !== "edit" && html`<${ItemView} key=${found.id} item=${found} tpl=${tplById[found.template]} unlocked=${unlocked}
        onEdit=${() => r.open([found.id, "edit"])} onClose=${() => r.close()} />`}
    ${(seg === "new" || (found && sub === "edit")) && html`<${ItemForm} key=${seg + (sub || "")} item=${found}
        data=${data} unlocked=${unlocked} onClose=${() => (found ? r.open(found.id) : r.close())}
        onSaved=${(saved) => { reload(); r.open(saved.id); }} />`}
    ${confirm && html`<${ConfirmDialog} title=${t("vault.delete_item_title")} danger=${true}
        message=${t("vault.delete_item_confirm", { title: confirm.title, id: confirm.id })} onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/vault/items/${encodeURIComponent(confirm.id)}`, rev); toast.ok(t("vault.item_removed")); if (found && found.id === confirm.id) r.close(); reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function ItemView({ item, tpl, unlocked, onEdit, onClose }) {
  const [shown, setShown] = useState({});           // campo -> valor revelado (só nesta janela)
  const mayReveal = can("vault.reveal");
  const order = (tpl?.fields || []).map((f) => f.field);
  const vals = [...item.values].sort((a, b) => {
    const ia = order.indexOf(a.field), ib = order.indexOf(b.field);
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
  });
  async function reveal(field) {
    if (shown[field] != null) return shown[field];
    const res = await api.post(`/vault/items/${encodeURIComponent(item.id)}/reveal`, { field });
    const value = res.values[field] ?? Object.values(res.values)[0] ?? "";
    setShown((s) => ({ ...s, [field]: value }));
    return value;
  }
  const toggle = async (field) => {
    if (shown[field] != null) { setShown((s) => { const n = { ...s }; delete n[field]; return n; }); return; }
    try { await reveal(field); } catch (e) { handleError(e); }
  };
  const copyField = async (x) => {
    try {
      const value = x.kind === "text" ? x.value : (shown[x.field] ?? (await api.post(`/vault/items/${encodeURIComponent(item.id)}/reveal`, { field: x.field })).values[x.field]);
      if (await copy(value)) toast.ok(t("vault.field_copied", { field: x.field })); else toast.err(t("vault.copy_failed"));
    } catch (e) { handleError(e); }
  };
  const secretBtns = (x) => !unlocked ? html`<span class="muted">${t("vault.unlock_to_reveal")}</span>`
    : !mayReveal ? html`<span class="muted">${t("vault.no_reveal_permission")}</span>`
    : html`<button class="sm" onClick=${() => toggle(x.field)}>${shown[x.field] != null ? t("vault.hide") : t("vault.reveal")}</button>
        <button class="sm" onClick=${() => copyField(x)}>${t("vault.copy_btn")}</button>`;
  return html`<${Modal} title=${`${item.title} (ID ${item.id})`} onClose=${onClose} wide=${true}>
    <div class="help">${item.template_label ? html`${t("vault.template_prefix")} <${Badge}>${item.template_label}<//> · ` : ""}
      ${t("vault.updated_by", { when: (item.updated_at || "").replace("T", " ").slice(0, 16), who: item.updated_by || "—" })}</div>
    <div class="vault-fields">
      ${vals.length === 0 && html`<div class="muted">${t("vault.no_fields")}</div>`}
      ${vals.map((x) => html`<div class="vault-row" key=${x.field}>
        <div class="vault-row-label">${x.field}${x.kind === "secret" ? " 🔒" : ""}</div>
        <div class="vault-row-value"><code>${x.kind === "text" ? x.value : (shown[x.field] ?? MASK)}</code>
          <div class="vault-ref" title=${t("vault.ref_title")}>
            <code>${vaultRef(item.id, x.field)}</code>
            <button class="sm link-btn" onClick=${async () => { if (await copy(vaultRef(item.id, x.field))) toast.ok(t("vault.ref_copied")); }}>${t("vault.copy_ref")}</button></div></div>
        <div class="vault-row-actions">${x.kind === "text"
          ? html`<button class="sm" onClick=${() => copyField(x)}>${t("vault.copy_btn")}</button>` : secretBtns(x)}</div>
      </div>`)}
    </div>
    <div class="help">${t("vault.usage_1")} <code>.env</code> ${t("vault.usage_2")}
      (${t("vault.usage_eg")} <code>API_KEY=${vaultRef(item.id, vals.find((v) => v.kind === "secret")?.field || t("vault.usage_default_field"))}</code>) ${t("vault.usage_3")}
      <code>nvault run -- &lt;${t("vault.usage_command")}&gt;</code> ${t("vault.usage_4")}</div>
    ${item.notes && html`<${Field} label=${t("vault.notes")}><div class="vault-notes">${item.notes}</div><//>`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.close")}</button>
      <button class="primary needs-vault-edit" onClick=${onEdit}>${t("common.edit")}</button></div>
  <//>`;
}

function ItemForm({ item, data, unlocked, onClose, onSaved }) {
  const isNew = !item;
  const { templates, fields, rev } = data;
  const kindOf = (name) => fields.find((f) => f.name === name)?.kind || "secret";
  const tplById = Object.fromEntries(templates.map((tp) => [tp.id, tp]));
  const existing = Object.fromEntries((item?.values || []).map((x) => [x.field, x]));
  const rowsFor = (tid, keep = []) => {
    const tf = (tplById[tid]?.fields || []).map((f) => f.field);
    const extra = keep.filter((n) => !tf.includes(n));
    return [...tf, ...extra];
  };
  const [title, setTitle] = useState(item?.title || "");
  const [template, setTemplate] = useState(item ? (item.template || "") : (templates[0]?.id || ""));
  const [notes, setNotes] = useState(item?.notes || "");
  const [names, setNames] = useState(() => rowsFor(item ? item.template : templates[0]?.id, Object.keys(existing)));
  const [vals, setVals] = useState(() => Object.fromEntries(Object.entries(existing)
    .filter(([, x]) => x.kind === "text").map(([k, x]) => [k, x.value])));
  const [addName, setAddName] = useState("");
  const [busy, setBusy] = useState(false);
  const req = new Set((tplById[template]?.fields || []).filter((f) => f.required).map((f) => f.field));
  const inTpl = new Set((tplById[template]?.fields || []).map((f) => f.field));

  const changeTemplate = (tid) => {
    setTemplate(tid);
    // Troca de template: entram os campos do novo; ficam os avulsos que já têm valor.
    setNames(rowsFor(tid, names.filter((n) => vals[n] || existing[n])));
  };
  const addField = () => {
    const real = fields.find((f) => f.name.toLowerCase() === addName.trim().toLowerCase());
    if (!real) { toast.err(t("vault.field_unknown")); return; }
    if (!names.includes(real.name)) setNames([...names, real.name]);
    setAddName("");
  };
  const missing = [...req].filter((n) => !(vals[n] || (existing[n]?.kind === "secret" && existing[n].set && vals[n] === undefined)));
  const needsUnlock = names.some((n) => kindOf(n) === "secret" && vals[n]);

  async function save() {
    if (!title.trim()) { toast.err(t("vault.title_required")); return; }
    if (missing.length) { toast.err(t("vault.required_empty", { list: missing.join(", ") })); return; }
    if (needsUnlock && !unlocked) { toast.err(t("vault.unlock_to_save")); return; }
    const values = names.map((n) => {
      if (kindOf(n) === "secret") return { field: n, value: vals[n] ? vals[n] : (existing[n]?.set ? null : "") };
      return { field: n, value: vals[n] || "" };
    });
    setBusy(true);
    try {
      const body = { title, template: template || null, notes, values };
      const saved = isNew ? await api.post("/vault/items", body, rev)
        : await api.put(`/vault/items/${encodeURIComponent(item.id)}`, body, rev);
      toast.ok(isNew ? t("vault.item_created") : t("vault.item_updated")); onSaved(saved);
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }
  return html`<${Modal} title=${isNew ? t("vault.new_item_title") : t("vault.edit_item_title", { title: item.title, id: item.id })} onClose=${onClose} wide=${true}>
    <${Field} label=${t("vault.field_title")}><input value=${title} onInput=${(e) => setTitle(e.target.value)} placeholder=${t("vault.title_placeholder")} /><//>
    <${Field} label=${t("vault.col_template")} hint=${t("vault.template_hint")}>
      <select value=${template} onChange=${(e) => changeTemplate(e.target.value)}>
        <option value="">${t("vault.no_template")}</option>
        ${templates.map((tp) => html`<option key=${tp.id} value=${tp.id}>${tp.label}</option>`)}
      </select><//>
    ${!unlocked && html`<div class="vault-banner locked">${t("vault.locked_banner")}</div>`}
    ${names.map((n) => {
      const secret = kindOf(n) === "secret";
      const label = `${n}${req.has(n) ? " *" : ""}${secret ? " 🔒" : ""}`;
      const keep = secret && existing[n]?.set;
      return html`<div class="vault-form-row" key=${n}>
        <${Field} label=${label} hint=${keep ? t("vault.secret_keep_hint") : null}>
          ${secret
            ? html`<${PasswordInput} autocomplete="new-password" disabled=${!unlocked} value=${vals[n] || ""}
                placeholder=${keep ? t("vault.secret_kept") : ""} onInput=${(e) => setVals({ ...vals, [n]: e.target.value })} />`
            : html`<input value=${vals[n] || ""} onInput=${(e) => setVals({ ...vals, [n]: e.target.value })} />`}
        <//>
        ${!inTpl.has(n) && html`<button class="sm" title=${t("vault.remove_field_title")} onClick=${() => {
          setNames(names.filter((x) => x !== n)); const nv = { ...vals }; delete nv[n]; setVals(nv); }}>✕</button>`}
      </div>`;
    })}
    <div class="vault-add">
      <input list="vault-fields-dl" placeholder=${t("vault.add_field_placeholder")} value=${addName}
        onInput=${(e) => setAddName(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); addField(); } }} />
      <datalist id="vault-fields-dl">${fields.filter((f) => !names.includes(f.name)).map((f) => html`<option key=${f.name} value=${f.name} />`)}</datalist>
      <button class="sm" onClick=${addField} disabled=${!addName.trim()}>${t("common.add")}</button>
    </div>
    <${Field} label=${t("vault.notes")}><textarea rows="3" value=${notes} onInput=${(e) => setNotes(e.target.value)} /><//>
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary" disabled=${busy} onClick=${save}>${isNew ? t("common.create") : t("common.save")}</button></div>
  <//>`;
}

/* ------------------------------- Templates ------------------------------- */
function TemplatesTab({ data, reload, r }) {
  const [confirm, setConfirm] = useState(null);
  const { templates, rev } = data;
  const [, tid] = r.segments;
  const found = tid && tid !== "new" ? templates.find((tp) => tp.id === tid) : null;
  const cols = [
    { key: "label", label: t("vault.col_template"), hideable: false, sort: (tp) => tp.label,
      render: (tp) => html`<a href=${"#vault/templates/" + encodeURIComponent(tp.id)} onClick=${(e) => e.stopPropagation()}><b>${tp.label}</b></a>` },
    { key: "description", label: t("common.description"), sort: (tp) => tp.description || "", render: (tp) => tp.description || "—" },
    { key: "fields", label: t("vault.tab_fields"), sort: (tp) => tp.fields.length,
      render: (tp) => tp.fields.map((f) => html`<span class="vault-chip" key=${f.field}>${f.field}${f.required ? "*" : ""}${f.kind === "secret" ? " 🔒" : ""}</span>`) },
    { key: "items", label: t("vault.tab_items"), sort: (tp) => tp.items, render: (tp) => tp.items },
  ];
  return html`<div>
    <p class="help vault-help">${t("vault.templates_help")}</p>
    ${tid && tid !== "new" && !found && html`<div class="card">${t("vault.template_not_found", { id: tid })} <a href="#vault/templates">${t("common.back")}</a></div>`}
    <${DataTable} tableId="vault-templates" urlSort columns=${cols} rows=${templates.map((tp) => ({ ...tp, _key: tp.id }))}
      onRowClick=${(tp) => r.open(["templates", tp.id])}
      actions=${(tp) => html`<button class="sm danger needs-vault-templates" onClick=${() => setConfirm(tp)}>${t("common.delete")}</button>`}
      empty=${t("vault.templates_empty")} />
    ${(tid === "new" || found) && html`<${TemplateForm} key=${tid} tpl=${found} data=${data}
        onClose=${() => r.open("templates")} onSaved=${() => { reload(); r.open("templates"); }} />`}
    ${confirm && html`<${ConfirmDialog} title=${t("vault.delete_template_title")} danger=${true}
        message=${t("vault.delete_template_confirm", { name: confirm.label, items: confirm.items ? t("vault.delete_template_items", { count: confirm.items }) : "" })}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/vault/templates/${encodeURIComponent(confirm.id)}`, rev); toast.ok(t("vault.template_removed")); reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function TemplateForm({ tpl, data, onClose, onSaved }) {
  const isNew = !tpl;
  const { fields, rev } = data;
  const kindOf = (name) => fields.find((f) => f.name.toLowerCase() === String(name).trim().toLowerCase())?.kind;
  const [label, setLabel] = useState(tpl?.label || "");
  const [description, setDescription] = useState(tpl?.description || "");
  const [rows, setRows] = useState(() => (tpl?.fields || []).map((f) => ({ ...f })));
  const [busy, setBusy] = useState(false);
  const set = (i, patch) => setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const move = (i, d) => { const n = [...rows]; const j = i + d; if (j < 0 || j >= n.length) return; [n[i], n[j]] = [n[j], n[i]]; setRows(n); };
  const onName = (i, name) => {
    const k = kindOf(name);
    set(i, { field: name, kind: k || rows[i].kind || "secret", known: !!k });
  };
  async function save() {
    if (!label.trim()) { toast.err(t("vault.template_name_required")); return; }
    if (rows.some((x) => !String(x.field || "").trim())) { toast.err(t("vault.field_without_name")); return; }
    const changed = rows.filter((x) => { const k = kindOf(x.field); return k && x.kind && k !== x.kind; });
    if (changed.length && !confirm(t("vault.kind_change_confirm", { list: changed.map((x) => x.field).join(", ") }))) return;
    setBusy(true);
    try {
      const body = { label, description, fields: rows.map((x) => ({ field: x.field.trim(), kind: x.kind || null, required: !!x.required, visible: !!x.visible })) };
      if (isNew) await api.post("/vault/templates", body, rev);
      else await api.put(`/vault/templates/${encodeURIComponent(tpl.id)}`, body, rev);
      toast.ok(isNew ? t("vault.template_created") : t("vault.template_saved")); onSaved();
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }
  return html`<${Modal} title=${isNew ? t("vault.new_template_title") : t("vault.template_title", { name: tpl.label })} onClose=${onClose} wide=${true}>
    <${Field} label=${t("vault.field_name_required")}><input value=${label} onInput=${(e) => setLabel(e.target.value)} placeholder=${t("vault.template_name_placeholder")} /><//>
    <${Field} label=${t("common.description")}><input value=${description} onInput=${(e) => setDescription(e.target.value)} /><//>
    <div class="vault-tpl-head"><span>${t("vault.tpl_head_field")}</span><span>${t("vault.col_kind")}</span><span>${t("vault.tpl_head_required")}</span><span>${t("vault.tpl_head_visible")}</span><span></span></div>
    <datalist id="vault-tpl-fields-dl">${fields.map((f) => html`<option key=${f.name} value=${f.name} />`)}</datalist>
    ${rows.map((x, i) => html`<div class="vault-tpl-row" key=${i}>
      <input list="vault-tpl-fields-dl" value=${x.field} placeholder=${t("vault.field_name_placeholder")} onInput=${(e) => onName(i, e.target.value)} />
      <select value=${x.kind || kindOf(x.field) || "secret"} onChange=${(e) => set(i, { kind: e.target.value })}
        title=${kindOf(x.field) ? t("vault.kind_shared_title") : t("vault.new_field_title")}>
        <option value="secret">${t("vault.kind_secret")}</option><option value="text">${t("vault.kind_plain_text")}</option></select>
      <label><input type="checkbox" checked=${!!x.required} onChange=${(e) => set(i, { required: e.target.checked })} /> ${t("vault.required_check")}</label>
      <label><input type="checkbox" checked=${!!x.visible} onChange=${(e) => set(i, { visible: e.target.checked })} /> ${t("vault.visible_check")}</label>
      <span class="vault-tpl-btns">
        <button class="sm" title=${t("vault.move_up")} onClick=${() => move(i, -1)}>↑</button>
        <button class="sm" title=${t("vault.move_down")} onClick=${() => move(i, 1)}>↓</button>
        <button class="sm danger" title=${t("vault.remove_from_template")} onClick=${() => setRows(rows.filter((_, j) => j !== i))}>✕</button>
        ${x.field && !kindOf(x.field) && html`<${Badge} kind="warn">${t("vault.new_badge")}<//>`}
      </span>
    </div>`)}
    <button class="sm" onClick=${() => setRows([...rows, { field: "", kind: "secret", required: false, visible: false }])}>${t("vault.add_field_btn")}</button>
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary needs-vault-templates" disabled=${busy} onClick=${save}>${isNew ? t("common.create") : t("common.save")}</button></div>
  <//>`;
}

/* -------------------------------- Campos --------------------------------- */
function FieldsTab({ data, reload, r }) {
  const [confirm, setConfirm] = useState(null);
  const { fields, rev } = data;
  const [, name] = r.segments;
  const found = name && name !== "new" ? fields.find((f) => f.name === name) : null;
  const cols = [
    { key: "name", label: t("vault.col_field"), hideable: false, sort: (f) => f.name,
      render: (f) => html`<a href=${"#vault/fields/" + encodeURIComponent(f.name)} onClick=${(e) => e.stopPropagation()}><b>${f.name}</b></a>` },
    { key: "kind", label: t("vault.col_kind"), sort: (f) => f.kind, render: (f) => kindLabel(f.kind) },
    { key: "templates", label: t("vault.tab_templates"), sort: (f) => f.templates, render: (f) => f.templates },
    { key: "items", label: t("vault.tab_items"), sort: (f) => f.items, render: (f) => f.items },
  ];
  return html`<div>
    <p class="help vault-help">${t("vault.fields_help")}</p>
    ${name && name !== "new" && !found && html`<div class="card">${t("vault.field_not_found", { name })} <a href="#vault/fields">${t("common.back")}</a></div>`}
    <${DataTable} tableId="vault-fields" urlSort columns=${cols} rows=${fields.map((f) => ({ ...f, _key: f.name }))}
      onRowClick=${(f) => r.open(["fields", f.name])}
      actions=${(f) => html`<button class="sm danger needs-vault-templates" disabled=${f.templates || f.items}
        title=${f.templates || f.items ? t("vault.field_in_use_title") : ""} onClick=${() => setConfirm(f)}>${t("common.delete")}</button>`}
      empty=${t("vault.fields_empty")} />
    ${(name === "new" || found) && html`<${FieldForm} key=${name} field=${found} rev=${rev}
        onClose=${() => r.open("fields")} onSaved=${() => { reload(); r.open("fields"); }} />`}
    ${confirm && html`<${ConfirmDialog} title=${t("vault.delete_field_title")} danger=${true} message=${t("vault.delete_field_confirm", { name: confirm.name })}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/vault/fields/${encodeURIComponent(confirm.name)}`, rev); toast.ok(t("vault.field_removed")); reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function FieldForm({ field, rev, onClose, onSaved }) {
  const isNew = !field;
  const [name, setName] = useState(field?.name || "");
  const [kind, setKind] = useState(field?.kind || "secret");
  async function save() {
    try {
      if (isNew) await api.post("/vault/fields", { name, kind }, rev);
      else {
        if (kind !== field.kind && field.items && !confirm(t("vault.convert_confirm", { count: field.items, kind: kindLabel(kind) }))) return;
        await api.patch(`/vault/fields/${encodeURIComponent(field.name)}`, { name: name !== field.name ? name : null, kind: kind !== field.kind ? kind : null }, rev);
      }
      toast.ok(t("vault.field_saved")); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? t("vault.new_field_modal_title") : t("vault.field_title_name", { name: field.name })} onClose=${onClose}>
    <${Field} label=${t("common.name")} hint=${isNew ? null : t("vault.rename_field_hint")}><input value=${name} onInput=${(e) => setName(e.target.value)} placeholder=${t("vault.field_name_placeholder")} /><//>
    <${Field} label=${t("vault.col_kind")}><select value=${kind} onChange=${(e) => setKind(e.target.value)}>
      <option value="secret">${t("vault.kind_secret_long")}</option>
      <option value="text">${t("vault.kind_text_long")}</option></select><//>
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary needs-vault-templates" disabled=${!name.trim()} onClick=${save}>${isNew ? t("common.create") : t("common.save")}</button></div>
  <//>`;
}
