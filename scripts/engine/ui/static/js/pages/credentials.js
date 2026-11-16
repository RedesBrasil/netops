// Credenciais (network/credentials.yaml). Senhas sempre mascaradas; encrypt-on-write.
import { html, useState, api, useResource, Spinner, Badge, toast, handleError, useStore, vaultStore } from "../ui.js";
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
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { credentials: allCreds, rev, vault_initialized } = res.data;
  const [seg, sub] = r.segments;
  const found = seg && seg !== "new" ? allCreds.find((c) => c.name === seg) : null;
  const rotating = found && (sub === "password" || sub === "secret") ? { name: seg, field: sub } : null;
  const editing = seg === "new" ? { __new: true } : found && !rotating ? found : null;
  const setEditing = (c) => (c ? r.open(c.__new ? "new" : c.name) : r.close());
  const setRotating = (t) => (t ? r.open([t.name, t.field]) : r.close());
  const credentials = allCreds.filter((c) => matchText(q, c.name, c.username));
  const writable = v.state === "cache" || v.state === "env";

  const secretBadge = (s) => !s ? html`<${Badge}>não def.<//>`
    : s.encrypted ? html`<${Badge} kind="ok">🔒 cifrado<//>` : html`<${Badge} kind="warn">⚠ texto puro<//>`;

  const cols = [
    { key: "name", label: "Credencial", hideable: false, sort: true, render: (r) => html`<a href=${"#credentials/" + encodeURIComponent(r.name)} onClick=${(e) => e.stopPropagation()}><b>${r.name}</b></a>` },
    { key: "username", label: "Usuário", sort: true, render: (r) => r.username || "—" },
    { key: "password", label: "Senha", sort: (r) => !r.password ? 0 : r.password.encrypted ? 2 : 1, render: (r) => secretBadge(r.password) },
    { key: "secret", label: "Secret", sort: (r) => !r.secret ? 0 : r.secret.encrypted ? 2 : 1, render: (r) => r.secret ? secretBadge(r.secret) : "—" },
    { key: "extra", label: "Outros", render: (r) => html`${r.key_file ? html`<${Badge}>key_file<//> ` : ""}${r.api_ssl != null ? html`<${Badge}>api_ssl=${String(r.api_ssl)}<//>` : ""}` },
  ];

  return html`<div>
    <div class="page-title"><h1>Credenciais</h1><span class="spacer"></span>
      <button class="primary needs-credentials-edit" onClick=${() => setEditing({ __new: true })}>+ Nova credencial</button></div>
    ${!vault_initialized && html`<div class="card"><b>Cofre não inicializado.</b> Para guardar senhas cifradas,
      rode no terminal: <code>python3 scripts/engine/vault/cli.py init</code> e depois <code>encrypt</code>.</div>`}
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar credencial" count=${credentials.length} total=${allCreds.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">Credencial '${seg}' não encontrada. <a href="#credentials">Voltar às credenciais</a></div>`}
    <${DataTable} tableId="credentials" urlSort columns=${cols} rows=${credentials.map((c) => ({ ...c, _key: c.name }))}
      onRowClick=${(r) => setEditing(r)}
      actions=${(r) => html`
        <button class="sm" disabled=${!writable} title=${writable ? "" : "Destranque o cofre na aba Terminal"}
          onClick=${() => setRotating({ name: r.name, field: "password" })}>Senha…</button>
        <button class="sm" disabled=${!writable}
          onClick=${() => setRotating({ name: r.name, field: "secret" })}>Secret…</button>
        <button class="sm danger needs-credentials-edit" onClick=${() => setConfirm(r.name)}>Excluir</button>`}
      empty="Nenhuma credencial. Crie uma e depois defina a senha." />

    ${editing && html`<${CredentialForm} key=${editing.name || "new"} cred=${editing} rev=${rev} onClose=${() => setEditing(null)}
        onSaved=${() => { setEditing(null); res.reload(); }} />`}
    ${rotating && html`<${RotateModal} target=${rotating} writable=${writable}
        onClose=${() => setRotating(null)} onSaved=${() => { setRotating(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir credencial" danger=true
        message=${`Remover a credencial '${confirm}'?`} onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/credentials/${confirm}`, rev); toast.ok("Credencial removida"); res.reload(); }
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
        toast.ok("Credencial criada. Agora defina a senha (cofre destrancado).");
      } else {
        let curRev = rev;
        if (form.name !== cred.name) {                      // renomeia primeiro (cascade em hosts/grupos)
          curRev = (await api.post(`/credentials/${cred.name}/rename`, { to: form.name }, curRev)).rev;
        }
        await api.patch(`/credentials/${form.name}`, {
          username: form.username || null, key_file: form.key_file || null,
          api_ssl: form.api_ssl ? true : null,
        }, curRev);
        toast.ok("Credencial atualizada");
      }
      onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? "Nova credencial" : `Editar ${cred.name}`} onClose=${onClose}>
    <${Field} label=${isNew ? "Nome (ex.: cred_mikrotik_admin)" : "Nome (alterar = renomear, atualiza hosts/grupos)"}>
      <input value=${form.name} onInput=${(e) => set("name", e.target.value)} /><//>
    ${!isNew && html`<${RenameCascadeHint} refsPath=${`/credentials/${cred.name}/references`} changed=${form.name !== cred.name} />`}
    <${Field} label="Usuário"><input value=${form.username} onInput=${(e) => set("username", e.target.value)} /><//>
    <${Field} label="Arquivo de chave SSH (opcional)" hint="ex.: ~/.ssh/id_ed25519">
      <input value=${form.key_file} onInput=${(e) => set("key_file", e.target.value)} /><//>
    <${Field}><label><input type="checkbox" checked=${form.api_ssl} onChange=${(e) => set("api_ssl", e.target.checked)} /> API com TLS (api_ssl)</label><//>
    ${isNew && html`<div class="help">A senha é definida depois, no botão "Senha…" (é cifrada no servidor; nunca trafega em texto puro de volta).</div>`}
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary needs-credentials-edit" onClick=${save}>${isNew ? "Criar" : "Salvar"}</button></div>
  <//>`;
}

function RotateModal({ target, writable, onClose, onSaved }) {
  const [v1, setV1] = useState(""); const [v2, setV2] = useState("");
  const mismatch = v1 && v2 && v1 !== v2;
  async function save() {
    if (!v1 || mismatch) return;
    try {
      await api.put(`/credentials/${target.name}/password`, { value: v1, field: target.field });
      toast.ok(`${target.field} cifrado e gravado`); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${`Definir ${target.field} — ${target.name}`} onClose=${onClose}>
    ${!writable
      ? html`<div class="vault-banner locked">🔒 Cofre trancado. Destranque na aba Terminal para definir a senha.</div>`
      : html`<div>
          <${Field} label="Novo valor"><${PasswordInput} autocomplete="new-password" value=${v1} onInput=${(e) => setV1(e.target.value)} /><//>
          <${Field} label="Confirme" error=${mismatch ? "Os valores não conferem" : null}>
            <${PasswordInput} autocomplete="new-password" value=${v2} onInput=${(e) => setV2(e.target.value)} /><//>
        </div>`}
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary" disabled=${!writable || !v1 || mismatch} onClick=${save}>Cifrar e gravar</button></div>
  <//>`;
}
