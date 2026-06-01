// Credenciais (network/credentials.yaml). Senhas sempre mascaradas; encrypt-on-write.
import { html, useState, api, useResource, Spinner, Badge, toast, handleError, useStore, vaultStore } from "../ui.js";
import { ResourceTable, Field, Modal, ConfirmDialog } from "../components.js";
import { vaultWritable } from "../components.js";

export function CredentialsPage() {
  const res = useResource("/credentials");
  const v = useStore(vaultStore);
  const [creating, setCreating] = useState(false);
  const [rotating, setRotating] = useState(null); // {name, field}
  const [confirm, setConfirm] = useState(null);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { credentials, rev, vault_initialized } = res.data;
  const writable = v.state === "cache" || v.state === "env";

  const secretBadge = (s) => !s ? html`<${Badge}>não def.<//>`
    : s.encrypted ? html`<${Badge} kind="ok">🔒 cifrado<//>` : html`<${Badge} kind="warn">⚠ texto puro<//>`;

  const cols = [
    { key: "name", label: "Credencial", render: (r) => html`<b>${r.name}</b>` },
    { key: "username", label: "Usuário", render: (r) => r.username || "—" },
    { key: "password", label: "Senha", render: (r) => secretBadge(r.password) },
    { key: "secret", label: "Secret", render: (r) => r.secret ? secretBadge(r.secret) : "—" },
    { key: "extra", label: "Outros", render: (r) => html`${r.key_file ? html`<${Badge}>key_file<//> ` : ""}${r.api_ssl != null ? html`<${Badge}>api_ssl=${String(r.api_ssl)}<//>` : ""}` },
  ];

  return html`<div>
    <div class="page-title"><h1>Credenciais</h1><span class="spacer"></span>
      <button class="primary" onClick=${() => setCreating(true)}>+ Nova credencial</button></div>
    ${!vault_initialized && html`<div class="card"><b>Cofre não inicializado.</b> Para guardar senhas cifradas,
      rode no terminal: <code>python scripts/vault/cli.py init</code> e depois <code>encrypt</code>.</div>`}
    <${ResourceTable} columns=${cols} rows=${credentials.map((c) => ({ ...c, _key: c.name }))}
      actions=${(r) => html`
        <button class="sm" disabled=${!writable} title=${writable ? "" : "Destranque o cofre"}
          onClick=${() => setRotating({ name: r.name, field: "password" })}>Senha…</button>
        <button class="sm" disabled=${!writable}
          onClick=${() => setRotating({ name: r.name, field: "secret" })}>Secret…</button>
        <button class="sm danger" onClick=${() => setConfirm(r.name)}>Excluir</button>`}
      empty="Nenhuma credencial. Crie uma e depois defina a senha." />

    ${creating && html`<${CredentialForm} rev=${rev} onClose=${() => setCreating(false)}
        onSaved=${() => { setCreating(false); res.reload(); }} />`}
    ${rotating && html`<${RotateModal} target=${rotating} writable=${writable}
        onClose=${() => setRotating(null)} onSaved=${() => { setRotating(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir credencial" danger=true
        message=${`Remover a credencial '${confirm}'?`} onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/credentials/${confirm}`, rev); toast.ok("Credencial removida"); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function CredentialForm({ rev, onClose, onSaved }) {
  const [form, setForm] = useState({ name: "", username: "", key_file: "", api_ssl: false });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  async function save() {
    try {
      const body = { name: form.name, username: form.username || null };
      if (form.key_file) body.key_file = form.key_file;
      if (form.api_ssl) body.api_ssl = true;
      await api.post("/credentials", body, rev);
      toast.ok("Credencial criada. Agora defina a senha (cofre destrancado).");
      onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title="Nova credencial" onClose=${onClose}>
    <${Field} label="Nome (ex.: cred_mikrotik_admin)"><input value=${form.name} onInput=${(e) => set("name", e.target.value)} /><//>
    <${Field} label="Usuário"><input value=${form.username} onInput=${(e) => set("username", e.target.value)} /><//>
    <${Field} label="Arquivo de chave SSH (opcional)" hint="ex.: ~/.ssh/id_ed25519">
      <input value=${form.key_file} onInput=${(e) => set("key_file", e.target.value)} /><//>
    <${Field}><label><input type="checkbox" checked=${form.api_ssl} onChange=${(e) => set("api_ssl", e.target.checked)} /> API com TLS (api_ssl)</label><//>
    <div class="help">A senha é definida depois, no botão "Senha…" (é cifrada no servidor; nunca trafega em texto puro de volta).</div>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Criar</button></div>
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
      ? html`<div class="vault-banner locked">🔒 Cofre trancado. Destranque no terminal e clique em "Re-verificar status" no topo.</div>`
      : html`<div>
          <${Field} label="Novo valor"><input type="password" autocomplete="new-password" value=${v1} onInput=${(e) => setV1(e.target.value)} /><//>
          <${Field} label="Confirme" error=${mismatch ? "Os valores não conferem" : null}>
            <input type="password" autocomplete="new-password" value=${v2} onInput=${(e) => setV2(e.target.value)} /><//>
        </div>`}
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary" disabled=${!writable || !v1 || mismatch} onClick=${save}>Cifrar e gravar</button></div>
  <//>`;
}
