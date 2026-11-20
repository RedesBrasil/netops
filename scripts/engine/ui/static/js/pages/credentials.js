// Credenciais (network/credentials.yaml). Senhas sempre mascaradas; encrypt-on-write.
import { html, useState, api, useResource, Spinner, Badge, toast, handleError, useStore, vaultStore, t } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, Modal, ConfirmDialog, RenameCascadeHint } from "../components.js";
import { vaultWritable, PasswordInput } from "../components.js";

// URL: #credentials[/<nome>|/new|/<nome>/password|/<nome>/secret][?q=]  (core/rules/urls-navegacao.md)
export function CredentialsPage() {
  const res = useResource("/credentials");
  const v = useStore(vaultStore);
  const r = useMenuRoute("credentials");
  const q = r.params.q || "";
  const [confirm, setConfirm] = useState(null);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">${t("credentials.load_error", { message: res.error.message })}</div>`;
  const { credentials: allCreds, rev, vault_initialized } = res.data;
  const [seg, sub] = r.segments;
  const found = seg && seg !== "new" ? allCreds.find((c) => c.name === seg) : null;
  const rotating = found && (sub === "password" || sub === "secret") ? { name: seg, field: sub } : null;
  const editing = seg === "new" ? { __new: true } : found && !rotating ? found : null;
  const setEditing = (c) => (c ? r.open(c.__new ? "new" : c.name) : r.close());
  const setRotating = (target) => (target ? r.open([target.name, target.field]) : r.close());
  const credentials = allCreds.filter((c) => matchText(q, c.name, c.username));
  const writable = v.state === "cache" || v.state === "env";

  const secretBadge = (s) => !s ? html`<${Badge}>${t("credentials.secret_unset")}<//>`
    : s.encrypted ? html`<${Badge} kind="ok">${t("credentials.secret_encrypted")}<//>` : html`<${Badge} kind="warn">${t("credentials.secret_plain")}<//>`;

  const cols = [
    { key: "name", label: t("credentials.col_credential"), hideable: false, sort: true, render: (r) => html`<a href=${"#credentials/" + encodeURIComponent(r.name)} onClick=${(e) => e.stopPropagation()}><b>${r.name}</b></a>${r.system === "local_admin" ? html` <${Badge} kind="accent" title=${t("credentials.local_admin_title")}>${t("credentials.local_admin")}<//>` : ""}` },
    { key: "username", label: t("credentials.col_username"), sort: true, render: (r) => r.username || "—" },
    { key: "password", label: t("common.password"), sort: (r) => !r.password ? 0 : r.password.encrypted ? 2 : 1, render: (r) => secretBadge(r.password) },
    { key: "secret", label: "Secret", sort: (r) => !r.secret ? 0 : r.secret.encrypted ? 2 : 1, render: (r) => r.secret ? secretBadge(r.secret) : "—" },
    { key: "extra", label: t("credentials.col_other"), render: (r) => html`${r.key_file ? html`<${Badge}>key_file<//> ` : ""}${r.api_ssl != null ? html`<${Badge}>api_ssl=${String(r.api_ssl)}<//>` : ""}` },
  ];

  return html`<div>
    <div class="page-title"><h1>${t("credentials.title")}</h1><span class="spacer"></span>
      <button class="primary needs-credentials-edit" onClick=${() => setEditing({ __new: true })}>${t("credentials.new_btn")}</button></div>
    ${!vault_initialized && html`<div class="card"><b>${t("credentials.vault_not_initialized")}</b> ${t("credentials.vault_init_1")}
      <code>python3 scripts/engine/vault/cli.py init</code> ${t("credentials.vault_init_2")} <code>encrypt</code>.</div>`}
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("credentials.search_placeholder")} count=${credentials.length} total=${allCreds.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">${t("credentials.not_found", { name: seg })} <a href="#credentials">${t("credentials.back_to_list")}</a></div>`}
    <${DataTable} tableId="credentials" urlSort columns=${cols} rows=${credentials.map((c) => ({ ...c, _key: c.name }))}
      onRowClick=${(r) => setEditing(r)}
      actions=${(r) => r.system === "local_admin" ? html`<span class="muted" title=${t("credentials.system_managed_title")}>${t("credentials.system_managed")}</span>` : html`
        <button class="sm" disabled=${!writable} title=${writable ? "" : t("credentials.unlock_in_terminal")}
          onClick=${() => setRotating({ name: r.name, field: "password" })}>${t("credentials.set_password_btn")}</button>
        <button class="sm" disabled=${!writable}
          onClick=${() => setRotating({ name: r.name, field: "secret" })}>Secret…</button>
        <button class="sm danger needs-credentials-edit" onClick=${() => setConfirm(r.name)}>${t("common.delete")}</button>`}
      empty=${t("credentials.empty")} />

    ${editing && html`<${CredentialForm} key=${editing.name || "new"} cred=${editing} rev=${rev} onClose=${() => setEditing(null)}
        onSaved=${() => { setEditing(null); res.reload(); }} />`}
    ${rotating && html`<${RotateModal} target=${rotating} writable=${writable}
        onClose=${() => setRotating(null)} onSaved=${() => { setRotating(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title=${t("credentials.delete_title")} danger=true
        message=${t("credentials.delete_confirm", { name: confirm })} onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/credentials/${confirm}`, rev); toast.ok(t("credentials.removed")); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function CredentialForm({ cred, rev, onClose, onSaved }) {
  const isNew = !!cred.__new;
  const [form, setForm] = useState({
    name: isNew ? "" : cred.name, username: cred.username || "",
    key_file: cred.key_file || "", api_ssl: !!cred.api_ssl,
  });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  async function save() {
    try {
      if (isNew) {
        const body = { name: form.name, username: form.username || null };
        if (form.key_file) body.key_file = form.key_file;
        if (form.api_ssl) body.api_ssl = true;
        await api.post("/credentials", body, rev);
        toast.ok(t("credentials.created"));
      } else {
        let curRev = rev;
        if (form.name !== cred.name) {                      // renomeia primeiro (cascade em hosts/grupos)
          curRev = (await api.post(`/credentials/${cred.name}/rename`, { to: form.name }, curRev)).rev;
        }
        await api.patch(`/credentials/${form.name}`, {
          username: form.username || null, key_file: form.key_file || null,
          api_ssl: form.api_ssl ? true : null,
        }, curRev);
        toast.ok(t("credentials.updated"));
      }
      onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? t("credentials.new_title") : t("credentials.edit_title", { name: cred.name })} onClose=${onClose}>
    <${Field} label=${isNew ? t("credentials.field_name_new") : t("credentials.field_name_rename")}>
      <input value=${form.name} onInput=${(e) => set("name", e.target.value)} /><//>
    ${!isNew && html`<${RenameCascadeHint} refsPath=${`/credentials/${cred.name}/references`} changed=${form.name !== cred.name} />`}
    <${Field} label=${t("credentials.col_username")}><input value=${form.username} onInput=${(e) => set("username", e.target.value)} /><//>
    <${Field} label=${t("credentials.field_key_file")} hint=${t("credentials.key_file_hint")}>
      <input value=${form.key_file} onInput=${(e) => set("key_file", e.target.value)} /><//>
    <${Field}><label><input type="checkbox" checked=${form.api_ssl} onChange=${(e) => set("api_ssl", e.target.checked)} /> ${t("credentials.api_ssl")}</label><//>
    ${isNew && html`<div class="help">${t("credentials.password_later_help")}</div>`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary needs-credentials-edit" onClick=${save}>${isNew ? t("common.create") : t("common.save")}</button></div>
  <//>`;
}

function RotateModal({ target, writable, onClose, onSaved }) {
  const [v1, setV1] = useState(""); const [v2, setV2] = useState("");
  const mismatch = v1 && v2 && v1 !== v2;
  async function save() {
    if (!v1 || mismatch) return;
    try {
      await api.put(`/credentials/${target.name}/password`, { value: v1, field: target.field });
      toast.ok(t("credentials.secret_saved", { field: target.field })); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${t("credentials.rotate_title", { field: target.field, name: target.name })} onClose=${onClose}>
    ${!writable
      ? html`<div class="vault-banner locked">${t("credentials.locked_banner")}</div>`
      : html`<div>
          <${Field} label=${t("credentials.new_value")}><${PasswordInput} autocomplete="new-password" value=${v1} onInput=${(e) => setV1(e.target.value)} /><//>
          <${Field} label=${t("credentials.confirm_value")} error=${mismatch ? t("credentials.mismatch") : null}>
            <${PasswordInput} autocomplete="new-password" value=${v2} onInput=${(e) => setV2(e.target.value)} /><//>
        </div>`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary" disabled=${!writable || !v1 || mismatch} onClick=${save}>${t("credentials.encrypt_save")}</button></div>
  <//>`;
}
