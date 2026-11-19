// Cofre de senhas (network/vault.yaml): segredos que NÃO são de host (portais, APIs, tokens).
// Texto puro aparece sempre; segredo só abre (revelar/copiar/gravar) com o cofre destrancado.
// URL (core/rules/urls-navegacao.md):
//   #vault[?q=&tpl=]  #vault/new  #vault/<id>  #vault/<id>/edit
//   #vault/templates  #vault/templates/new  #vault/templates/<id>
//   #vault/fields     #vault/fields/new     #vault/fields/<nome>
import { html, useState, api, useResource, useStore, vaultStore, Spinner, Badge, toast, handleError, can, Modal, ConfirmDialog } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, PasswordInput, VaultBanner } from "../components.js";

const KIND_LABEL = { secret: "🔒 Segredo", text: "Texto" };
const MASK = "••••••••";
// Mesmo slug de lib/pwvault.slugify: referência usada no .env (scripts/tools/secrets/run.py).
const slug = (t) => String(t || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
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
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const unlocked = v.state === "cache" || v.state === "env";
  const [seg] = r.segments;
  const tab = seg === "templates" || seg === "fields" ? seg : "items";
  const tabBtn = (key, label, go) => html`<button class=${tab === key ? "active" : ""} onClick=${go}>${label}</button>`;
  const ctx = { data: res.data, reload: res.reload, r, unlocked };
  return html`<div>
    <div class="page-title"><h1>Cofre de senhas</h1><span class="spacer"></span>
      ${tab === "items" && html`<button class="primary needs-vault-edit" onClick=${() => r.open("new")}>+ Novo item</button>`}
      ${tab === "templates" && html`<button class="primary needs-vault-templates" onClick=${() => r.open(["templates", "new"])}>+ Novo template</button>`}
      ${tab === "fields" && html`<button class="primary needs-vault-templates" onClick=${() => r.open(["fields", "new"])}>+ Novo campo</button>`}
    </div>
    <p class="help">Senhas, chaves de API e logins de sistemas e portais, para consulta das pessoas.
      O acesso a equipamentos continua em <a href="#credentials">Credenciais de hosts</a>.</p>
    <${VaultBanner} />
    ${!unlocked && html`<p class="help">Com o cofre trancado, os campos de texto aparecem; os segredos ficam ocultos até destrancar.</p>`}
    <div class="tabs">
      ${tabBtn("items", "Itens", () => r.close())}
      ${tabBtn("templates", "Templates", () => r.open("templates"))}
      ${tabBtn("fields", "Campos", () => r.open("fields"))}
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
  const tplById = Object.fromEntries(templates.map((t) => [t.id, t]));
  const q = r.params.q || "";
  const tplLabel = r.params.tpl || "";
  const textOf = (it) => it.values.filter((x) => x.kind === "text").map((x) => x.value);
  const items = all.filter((it) => (!tplLabel || (it.template_label || "—") === tplLabel)
    && matchText(q, it.title, it.template_label, it.notes, ...textOf(it)));
  const tplOptions = [...new Set(all.map((it) => it.template_label || "—"))].sort();
  const [seg, sub] = r.segments;
  const found = seg && seg !== "new" ? all.find((it) => it.id === seg) : null;

  const visibleOf = (it) => {
    const tpl = tplById[it.template];
    const vis = new Set((tpl?.fields || []).filter((f) => f.visible).map((f) => f.field));
    return it.values.filter((x) => vis.has(x.field));
  };
  const cols = [
    { key: "title", label: "Título", hideable: false, sort: (it) => it.title,
      render: (it) => html`<a href=${"#vault/" + encodeURIComponent(it.id)} onClick=${(e) => e.stopPropagation()}><b>${it.title}</b></a>` },
    { key: "template", label: "Template", sort: (it) => it.template_label || "", render: (it) => it.template_label ? html`<${Badge}>${it.template_label}<//>` : "—" },
    { key: "visible", label: "Campos visíveis", render: (it) => html`${visibleOf(it).map((x) => html`<span class="vault-kv" key=${x.field}>
        <span class="muted">${x.field}:</span> ${x.kind === "text" ? x.value : MASK + (unlocked ? "" : " 🔒")}</span>`)}` },
    { key: "secrets", label: "Segredos", sort: (it) => it.values.filter((x) => x.kind === "secret").length,
      render: (it) => { const n = it.values.filter((x) => x.kind === "secret").length; return n ? `🔒 ${n}` : "—"; } },
    { key: "updated_at", label: "Atualizado", sort: (it) => it.updated_at || "", render: (it) => (it.updated_at || "").replace("T", " ").slice(0, 16) },
    { key: "updated_by", label: "Por", sort: (it) => it.updated_by || "", render: (it) => it.updated_by || "—" },
  ];
  return html`<div>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar no cofre (título, notas, campos de texto)"
      selects=${[{ key: "tpl", label: "Template", value: tplLabel, options: tplOptions }]} count=${items.length} total=${all.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">Item '${seg}' não encontrado. <a href="#vault">Voltar ao cofre</a></div>`}
    <${DataTable} tableId="vault-items" urlSort columns=${cols} rows=${items.map((it) => ({ ...it, _key: it.id }))}
      onRowClick=${(it) => r.open(it.id)}
      actions=${(it) => html`
        <button class="sm" onClick=${() => r.open(it.id)}>Abrir</button>
        <button class="sm needs-vault-edit" onClick=${() => r.open([it.id, "edit"])}>Editar</button>
        <button class="sm danger needs-vault-edit" onClick=${() => setConfirm(it)}>Excluir</button>`}
      empty="Nenhum item no cofre. Clique em “+ Novo item”." />
    ${found && sub !== "edit" && html`<${ItemView} key=${found.id} item=${found} tpl=${tplById[found.template]} unlocked=${unlocked}
        onEdit=${() => r.open([found.id, "edit"])} onClose=${() => r.close()} />`}
    ${(seg === "new" || (found && sub === "edit")) && html`<${ItemForm} key=${seg + (sub || "")} item=${found}
        data=${data} unlocked=${unlocked} onClose=${() => (found ? r.open(found.id) : r.close())}
        onSaved=${(saved) => { reload(); r.open(saved.id); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir item" danger=${true}
        message=${`Remover '${confirm.title}' do cofre? Os valores são apagados.`} onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/vault/items/${encodeURIComponent(confirm.id)}`, rev); toast.ok("Item removido"); if (seg === confirm.id) r.close(); reload(); }
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
      if (await copy(value)) toast.ok(`${x.field} copiado`); else toast.err("Não consegui copiar");
    } catch (e) { handleError(e); }
  };
  const secretBtns = (x) => !unlocked ? html`<span class="muted">🔒 destranque o cofre</span>`
    : !mayReveal ? html`<span class="muted">sem permissão para revelar</span>`
    : html`<button class="sm" onClick=${() => toggle(x.field)}>${shown[x.field] != null ? "🙈 Ocultar" : "👁 Revelar"}</button>
        <button class="sm" onClick=${() => copyField(x)}>📋 Copiar</button>`;
  return html`<${Modal} title=${item.title} onClose=${onClose} wide=${true}>
    <div class="help">${item.template_label ? html`Template: <${Badge}>${item.template_label}<//> · ` : ""}
      Atualizado ${(item.updated_at || "").replace("T", " ").slice(0, 16)} por ${item.updated_by || "—"}</div>
    <div class="vault-fields">
      ${vals.length === 0 && html`<div class="muted">Sem campos preenchidos.</div>`}
      ${vals.map((x) => html`<div class="vault-row" key=${x.field}>
        <div class="vault-row-label">${x.field}${x.kind === "secret" ? " 🔒" : ""}</div>
        <div class="vault-row-value"><code>${x.kind === "text" ? x.value : (shown[x.field] ?? MASK)}</code>
          <div class="vault-ref" title="Use no .env ou em comandos: nvault run -- <comando>">
            <code>${vaultRef(item.id, x.field)}</code>
            <button class="sm link-btn" onClick=${async () => { if (await copy(vaultRef(item.id, x.field))) toast.ok("Referência copiada"); }}>copiar referência</button></div></div>
        <div class="vault-row-actions">${x.kind === "text"
          ? html`<button class="sm" onClick=${() => copyField(x)}>📋 Copiar</button>` : secretBtns(x)}</div>
      </div>`)}
    </div>
    <div class="help">Para usar em sistemas e na IA sem expor o valor: no <code>.env</code> coloque a referência
      (ex.: <code>API_KEY=${vaultRef(item.id, vals.find((v) => v.kind === "secret")?.field || "senha")}</code>) e rode
      <code>nvault run -- &lt;comando&gt;</code> com o cofre destrancado. O valor só entra no processo e sai mascarado.</div>
    ${item.notes && html`<${Field} label="Notas"><div class="vault-notes">${item.notes}</div><//>`}
    <div class="modal-actions"><button onClick=${onClose}>Fechar</button>
      <button class="primary needs-vault-edit" onClick=${onEdit}>Editar</button></div>
  <//>`;
}

function ItemForm({ item, data, unlocked, onClose, onSaved }) {
  const isNew = !item;
  const { templates, fields, rev } = data;
  const kindOf = (name) => fields.find((f) => f.name === name)?.kind || "secret";
  const tplById = Object.fromEntries(templates.map((t) => [t.id, t]));
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
    if (!real) { toast.err("Campo não existe. Crie em Templates ou na aba Campos."); return; }
    if (!names.includes(real.name)) setNames([...names, real.name]);
    setAddName("");
  };
  const missing = [...req].filter((n) => !(vals[n] || (existing[n]?.kind === "secret" && existing[n].set && vals[n] === undefined)));
  const needsUnlock = names.some((n) => kindOf(n) === "secret" && vals[n]);

  async function save() {
    if (!title.trim()) { toast.err("Informe o título"); return; }
    if (missing.length) { toast.err("Obrigatório(s) vazio(s): " + missing.join(", ")); return; }
    if (needsUnlock && !unlocked) { toast.err("Destranque o cofre para gravar segredos."); return; }
    const values = names.map((n) => {
      if (kindOf(n) === "secret") return { field: n, value: vals[n] ? vals[n] : (existing[n]?.set ? null : "") };
      return { field: n, value: vals[n] || "" };
    });
    setBusy(true);
    try {
      const body = { title, template: template || null, notes, values };
      const saved = isNew ? await api.post("/vault/items", body, rev)
        : await api.put(`/vault/items/${encodeURIComponent(item.id)}`, body, rev);
      toast.ok(isNew ? "Item criado" : "Item atualizado"); onSaved(saved);
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }
  return html`<${Modal} title=${isNew ? "Novo item do cofre" : `Editar ${item.title}`} onClose=${onClose} wide=${true}>
    <${Field} label="Título *"><input value=${title} onInput=${(e) => setTitle(e.target.value)} placeholder="ex.: Portal Claro empresas" /><//>
    <${Field} label="Template" hint="Define os campos do item. Trocar de template mantém os campos já preenchidos.">
      <select value=${template} onChange=${(e) => changeTemplate(e.target.value)}>
        <option value="">(sem template)</option>
        ${templates.map((t) => html`<option key=${t.id} value=${t.id}>${t.label}</option>`)}
      </select><//>
    ${!unlocked && html`<div class="vault-banner locked">🔒 Cofre trancado: dá para editar os campos de texto; segredos só com o cofre destrancado.</div>`}
    ${names.map((n) => {
      const secret = kindOf(n) === "secret";
      const label = `${n}${req.has(n) ? " *" : ""}${secret ? " 🔒" : ""}`;
      const keep = secret && existing[n]?.set;
      return html`<div class="vault-form-row" key=${n}>
        <${Field} label=${label} hint=${keep ? "Já definido. Deixe em branco para manter; digite para trocar." : null}>
          ${secret
            ? html`<${PasswordInput} autocomplete="new-password" disabled=${!unlocked} value=${vals[n] || ""}
                placeholder=${keep ? "(mantido)" : ""} onInput=${(e) => setVals({ ...vals, [n]: e.target.value })} />`
            : html`<input value=${vals[n] || ""} onInput=${(e) => setVals({ ...vals, [n]: e.target.value })} />`}
        <//>
        ${!inTpl.has(n) && html`<button class="sm" title="Remover este campo do item" onClick=${() => {
          setNames(names.filter((x) => x !== n)); const nv = { ...vals }; delete nv[n]; setVals(nv); }}>✕</button>`}
      </div>`;
    })}
    <div class="vault-add">
      <input list="vault-fields-dl" placeholder="+ adicionar campo do catálogo" value=${addName}
        onInput=${(e) => setAddName(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); addField(); } }} />
      <datalist id="vault-fields-dl">${fields.filter((f) => !names.includes(f.name)).map((f) => html`<option key=${f.name} value=${f.name} />`)}</datalist>
      <button class="sm" onClick=${addField} disabled=${!addName.trim()}>Adicionar</button>
    </div>
    <${Field} label="Notas"><textarea rows="3" value=${notes} onInput=${(e) => setNotes(e.target.value)} /><//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary" disabled=${busy} onClick=${save}>${isNew ? "Criar" : "Salvar"}</button></div>
  <//>`;
}

/* ------------------------------- Templates ------------------------------- */
function TemplatesTab({ data, reload, r }) {
  const [confirm, setConfirm] = useState(null);
  const { templates, rev } = data;
  const [, tid] = r.segments;
  const found = tid && tid !== "new" ? templates.find((t) => t.id === tid) : null;
  const cols = [
    { key: "label", label: "Template", hideable: false, sort: (t) => t.label,
      render: (t) => html`<a href=${"#vault/templates/" + encodeURIComponent(t.id)} onClick=${(e) => e.stopPropagation()}><b>${t.label}</b></a>` },
    { key: "description", label: "Descrição", sort: (t) => t.description || "", render: (t) => t.description || "—" },
    { key: "fields", label: "Campos", sort: (t) => t.fields.length,
      render: (t) => t.fields.map((f) => html`<span class="vault-chip" key=${f.field}>${f.field}${f.required ? "*" : ""}${f.kind === "secret" ? " 🔒" : ""}</span>`) },
    { key: "items", label: "Itens", sort: (t) => t.items, render: (t) => t.items },
  ];
  return html`<div>
    <p class="help">O template define quais campos um item tem e, em cada um, se é obrigatório e se aparece na lista do cofre.
      Um campo digitado aqui vira um campo do catálogo e fica disponível para os outros templates.</p>
    ${tid && tid !== "new" && !found && html`<div class="card">Template '${tid}' não encontrado. <a href="#vault/templates">Voltar</a></div>`}
    <${DataTable} tableId="vault-templates" urlSort columns=${cols} rows=${templates.map((t) => ({ ...t, _key: t.id }))}
      onRowClick=${(t) => r.open(["templates", t.id])}
      actions=${(t) => html`<button class="sm danger needs-vault-templates" onClick=${() => setConfirm(t)}>Excluir</button>`}
      empty="Nenhum template." />
    ${(tid === "new" || found) && html`<${TemplateForm} key=${tid} tpl=${found} data=${data}
        onClose=${() => r.open("templates")} onSaved=${() => { reload(); r.open("templates"); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir template" danger=${true}
        message=${`Remover o template '${confirm.label}'? ${confirm.items ? `Os ${confirm.items} item(ns) continuam no cofre, sem template.` : ""}`}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/vault/templates/${encodeURIComponent(confirm.id)}`, rev); toast.ok("Template removido"); reload(); }
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
    if (!label.trim()) { toast.err("Informe o nome do template"); return; }
    if (rows.some((x) => !String(x.field || "").trim())) { toast.err("Há campo sem nome"); return; }
    const changed = rows.filter((x) => { const k = kindOf(x.field); return k && x.kind && k !== x.kind; });
    if (changed.length && !confirm(`Mudar o tipo de ${changed.map((x) => x.field).join(", ")} vale para TODOS os templates e itens que usam o campo. Continuar?`)) return;
    setBusy(true);
    try {
      const body = { label, description, fields: rows.map((x) => ({ field: x.field.trim(), kind: x.kind || null, required: !!x.required, visible: !!x.visible })) };
      if (isNew) await api.post("/vault/templates", body, rev);
      else await api.put(`/vault/templates/${encodeURIComponent(tpl.id)}`, body, rev);
      toast.ok(isNew ? "Template criado" : "Template salvo"); onSaved();
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }
  return html`<${Modal} title=${isNew ? "Novo template" : `Template ${tpl.label}`} onClose=${onClose} wide=${true}>
    <${Field} label="Nome *"><input value=${label} onInput=${(e) => setLabel(e.target.value)} placeholder="ex.: Portal de operadora" /><//>
    <${Field} label="Descrição"><input value=${description} onInput=${(e) => setDescription(e.target.value)} /><//>
    <div class="vault-tpl-head"><span>Campo (escolha ou digite um novo)</span><span>Tipo</span><span>Obrigatório</span><span>Visível na lista</span><span></span></div>
    <datalist id="vault-tpl-fields-dl">${fields.map((f) => html`<option key=${f.name} value=${f.name} />`)}</datalist>
    ${rows.map((x, i) => html`<div class="vault-tpl-row" key=${i}>
      <input list="vault-tpl-fields-dl" value=${x.field} placeholder="ex.: API key" onInput=${(e) => onName(i, e.target.value)} />
      <select value=${x.kind || kindOf(x.field) || "secret"} onChange=${(e) => set(i, { kind: e.target.value })}
        title=${kindOf(x.field) ? "O tipo é do campo: mudar aqui vale para todos os templates/itens" : "Campo novo"}>
        <option value="secret">🔒 Segredo</option><option value="text">Texto puro</option></select>
      <label><input type="checkbox" checked=${!!x.required} onChange=${(e) => set(i, { required: e.target.checked })} /> obrigatório</label>
      <label><input type="checkbox" checked=${!!x.visible} onChange=${(e) => set(i, { visible: e.target.checked })} /> visível</label>
      <span class="vault-tpl-btns">
        <button class="sm" title="Subir" onClick=${() => move(i, -1)}>↑</button>
        <button class="sm" title="Descer" onClick=${() => move(i, 1)}>↓</button>
        <button class="sm danger" title="Tirar do template" onClick=${() => setRows(rows.filter((_, j) => j !== i))}>✕</button>
        ${x.field && !kindOf(x.field) && html`<${Badge} kind="warn">novo<//>`}
      </span>
    </div>`)}
    <button class="sm" onClick=${() => setRows([...rows, { field: "", kind: "secret", required: false, visible: false }])}>+ Adicionar campo</button>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary needs-vault-templates" disabled=${busy} onClick=${save}>${isNew ? "Criar" : "Salvar"}</button></div>
  <//>`;
}

/* -------------------------------- Campos --------------------------------- */
function FieldsTab({ data, reload, r }) {
  const [confirm, setConfirm] = useState(null);
  const { fields, rev } = data;
  const [, name] = r.segments;
  const found = name && name !== "new" ? fields.find((f) => f.name === name) : null;
  const cols = [
    { key: "name", label: "Campo", hideable: false, sort: (f) => f.name,
      render: (f) => html`<a href=${"#vault/fields/" + encodeURIComponent(f.name)} onClick=${(e) => e.stopPropagation()}><b>${f.name}</b></a>` },
    { key: "kind", label: "Tipo", sort: (f) => f.kind, render: (f) => KIND_LABEL[f.kind] || f.kind },
    { key: "templates", label: "Templates", sort: (f) => f.templates, render: (f) => f.templates },
    { key: "items", label: "Itens", sort: (f) => f.items, render: (f) => f.items },
  ];
  return html`<div>
    <p class="help">Catálogo de campos reutilizáveis. O tipo (segredo ou texto) é do campo; obrigatório e visível se escolhem em cada template.</p>
    ${name && name !== "new" && !found && html`<div class="card">Campo '${name}' não encontrado. <a href="#vault/fields">Voltar</a></div>`}
    <${DataTable} tableId="vault-fields" urlSort columns=${cols} rows=${fields.map((f) => ({ ...f, _key: f.name }))}
      onRowClick=${(f) => r.open(["fields", f.name])}
      actions=${(f) => html`<button class="sm danger needs-vault-templates" disabled=${f.templates || f.items}
        title=${f.templates || f.items ? "Em uso: tire dos templates/itens antes" : ""} onClick=${() => setConfirm(f)}>Excluir</button>`}
      empty="Nenhum campo." />
    ${(name === "new" || found) && html`<${FieldForm} key=${name} field=${found} rev=${rev}
        onClose=${() => r.open("fields")} onSaved=${() => { reload(); r.open("fields"); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir campo" danger=${true} message=${`Remover o campo '${confirm.name}' do catálogo?`}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/vault/fields/${encodeURIComponent(confirm.name)}`, rev); toast.ok("Campo removido"); reload(); }
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
        if (kind !== field.kind && field.items && !confirm(`Converter os valores de ${field.items} item(ns) para ${KIND_LABEL[kind]}? (exige o cofre destrancado)`)) return;
        await api.patch(`/vault/fields/${encodeURIComponent(field.name)}`, { name: name !== field.name ? name : null, kind: kind !== field.kind ? kind : null }, rev);
      }
      toast.ok("Campo salvo"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? "Novo campo" : `Campo ${field.name}`} onClose=${onClose}>
    <${Field} label="Nome" hint=${isNew ? null : "Renomear atualiza todos os templates e itens."}><input value=${name} onInput=${(e) => setName(e.target.value)} placeholder="ex.: API key" /><//>
    <${Field} label="Tipo"><select value=${kind} onChange=${(e) => setKind(e.target.value)}>
      <option value="secret">🔒 Segredo (cifrado; só abre com o cofre destrancado)</option>
      <option value="text">Texto puro (aparece sempre)</option></select><//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary needs-vault-templates" disabled=${!name.trim()} onClick=${save}>${isNew ? "Criar" : "Salvar"}</button></div>
  <//>`;
}
