// Usuários e grupos de acesso (menu Sistema; só admin). Banco de acesso SQLite (lib/accessdb.py).
// URLs (core/rules/urls-navegacao.md):
//   #users[/<login>|/new|/<login>/password][?q=&group=&status=&sort=&dir=]
//   #access-groups[/<nome>|/new][?q=&sort=&dir=]
import { html, useState, api, useResource, Spinner, Badge, toast, handleError, useMe, refreshMe } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, Modal, ConfirmDialog, PasswordInput } from "../components.js";

const fmtTs = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");

function useCatalog() {
  const r = useResource("/access-catalog");
  return r.data || { permissions: [], net_perms: ["read", "create", "edit", "delete"], password_min: 8, multiuser: true };
}

const NET_LABELS = { read: "Ler e diagnosticar", create: "Criar", edit: "Editar", delete: "Apagar" };

/* ================================ Usuários ================================ */
export function UsersPage() {
  const res = useResource("/users");
  const me = useMe();
  const cat = useCatalog();
  const r = useMenuRoute("users");
  const q = r.params.q || "";
  const group = r.params.group || "";
  const status = r.params.status || "";
  const [confirm, setConfirm] = useState(null);
  if (res.loading && !res.data) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { users: all, groups: groupNames, multiuser } = res.data;
  const [seg, sub] = r.segments;
  const found = seg && seg !== "new" ? all.find((u) => u.username === seg) : null;
  const resetting = found && sub === "password" ? found : null;
  const editing = seg === "new" ? { __new: true } : found && !resetting ? found : null;
  const users = all.filter((u) => matchText(q, u.username, u.display_name, u.email)
    && (!group || u.groups.includes(group))
    && (!status || (status === "ativo" ? !u.disabled : u.disabled)));

  const cols = [
    { key: "email", label: "E-mail (login)", hideable: false, sort: (u) => u.email || u.username,
      render: (u) => html`<a href=${"#users/" + encodeURIComponent(u.username)} onClick=${(e) => e.stopPropagation()}><b>${u.email || u.username}</b></a>
        ${me && me.username === u.username ? html` <${Badge}>você<//>` : ""}${!u.email ? html` <${Badge} kind="warn">sem e-mail<//>` : ""}` },
    { key: "display_name", label: "Nome", sort: true, render: (u) => u.display_name || "—" },
    { key: "username", label: "ID", sort: true, hidden: true, render: (u) => html`<code>${u.username}</code>` },
    { key: "groups", label: "Grupos", sort: (u) => u.groups.join(","), render: (u) => u.groups.length
        ? u.groups.map((g) => html`<${Badge} kind=${g === "admin" ? "warn" : ""}>${g}<//> `) : html`<span class="help">sem grupo</span>` },
    { key: "status", label: "Situação", sort: (u) => (u.disabled ? 2 : u.must_change_password ? 1 : 0),
      render: (u) => u.disabled ? html`<${Badge} kind="danger">desativado<//>`
        : u.must_change_password ? html`<${Badge} kind="warn">senha provisória<//>` : html`<${Badge} kind="ok">ativo<//>` },
    { key: "last_login", label: "Último login", sort: (u) => u.last_login || 0, render: (u) => fmtTs(u.last_login) },
    { key: "sessions", label: "Sessões", sort: true, render: (u) => String(u.sessions) },
    { key: "vault_slot", label: "Cofre", sort: (u) => (u.vault_slot ? 1 : 0),
      render: (u) => (u.vault_slot ? html`<${Badge} kind="ok">🔑 destranca<//>` : html`<span class="help" title="O login cria a chave quando o cofre estiver destrancado">—</span>`) },
    { key: "last_ip", label: "Último IP", sort: true, hidden: true, render: (u) => u.last_ip || "—" },
    { key: "created_at", label: "Criado em", sort: (u) => u.created_at || 0, hidden: true, render: (u) => `${fmtTs(u.created_at)} (${u.created_by || "—"})` },
  ];

  return html`<div>
    <div class="page-title"><h1>Usuários</h1><span class="spacer"></span>
      <a class="btn" href="#access-groups">Grupos de acesso</a>
      <button class="primary" onClick=${() => r.open("new")}>+ Novo usuário</button></div>
    ${!multiuser && html`<div class="card"><b>Modo senha-mestra.</b> Ainda não há usuários: crie o primeiro
      administrador (grupo <code>admin</code>). Depois disso o login passa a ser por usuário e senha.</div>`}
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar e-mail ou nome"
      selects=${[{ key: "group", label: "Grupo", value: group, options: groupNames },
                 { key: "status", label: "Situação", value: status, options: ["ativo", "desativado"] }]}
      count=${users.length} total=${all.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">Usuário '${seg}' não encontrado. <a href="#users">Voltar aos usuários</a></div>`}
    <${DataTable} tableId="users" urlSort columns=${cols} rows=${users.map((u) => ({ ...u, _key: u.username }))}
      onRowClick=${(u) => r.open(u.username)}
      actions=${(u) => html`
        <button class="sm" onClick=${() => r.open([u.username, "password"])}>Senha…</button>
        <button class="sm" disabled=${!u.sessions} onClick=${() => setConfirm({ kind: "logout", u })}>Encerrar sessões</button>
        <button class="sm danger" disabled=${me && me.username === u.username} onClick=${() => setConfirm({ kind: "delete", u })}>Excluir</button>`}
      empty="Nenhum usuário." />

    ${editing && html`<${UserForm} key=${editing.username || "new"} user=${editing} groups=${groupNames} cat=${cat}
        first=${!multiuser} self=${me && me.username === editing.username}
        onClose=${() => r.close()} onSaved=${(u) => { res.reload(); u ? r.open(u.username) : r.close(); }} />`}
    ${resetting && html`<${ResetPasswordModal} user=${resetting} cat=${cat} onClose=${() => r.close()}
        onSaved=${() => { r.close(); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} danger=${confirm.kind === "delete"}
        title=${confirm.kind === "delete" ? "Excluir usuário" : "Encerrar sessões"}
        message=${confirm.kind === "delete" ? `Apagar o usuário ${confirm.u.email || confirm.u.username}? As sessões dele caem na hora.`
          : `Derrubar as ${confirm.u.sessions} sessão(ões) abertas de ${confirm.u.email || confirm.u.username}?`}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try {
            if (confirm.kind === "delete") { await api.del(`/users/${encodeURIComponent(confirm.u.username)}`); toast.ok("Usuário apagado"); }
            else { await api.del(`/users/${encodeURIComponent(confirm.u.username)}/sessions`); toast.ok("Sessões encerradas"); }
            res.reload();
          } catch (e) { handleError(e); } }} />`}
  </div>`;
}

function GroupChecks({ value, options, onChange, disabled }) {
  return html`<div class="perm-checks">${options.map((g) => html`<label key=${g} class="perm-check">
    <input type="checkbox" disabled=${disabled} checked=${value.includes(g)}
      onChange=${(e) => onChange(e.target.checked ? [...value, g] : value.filter((x) => x !== g))} /> ${g}</label>`)}</div>`;
}

function UserForm({ user, groups, cat, first, self, onClose, onSaved }) {
  const isNew = !!user.__new;
  const [form, setForm] = useState({
    display_name: user.display_name || "", email: user.email || "",
    groups: isNew ? (first ? ["admin"] : []) : user.groups, disabled: !!user.disabled,
    must_change_password: isNew ? !first : !!user.must_change_password, password: "", password2: "",
  });
  const [errs, setErrs] = useState({});
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const mismatch = form.password2 && form.password !== form.password2;
  async function save() {
    setErrs({});
    try {
      if (isNew) {
        if (form.password.length < cat.password_min) { setErrs({ password: `Mínimo de ${cat.password_min} caracteres` }); return; }
        if (form.password !== form.password2) return;
        const u = await api.post("/users", {
          email: form.email.trim().toLowerCase(), password: form.password, display_name: form.display_name,
          groups: form.groups, must_change_password: form.must_change_password });
        toast.ok(`Usuário ${u.email} criado`);
        if (first) await refreshMe();
        onSaved(u);
      } else {
        const u = await api.patch(`/users/${encodeURIComponent(user.username)}`, {
          display_name: form.display_name, email: form.email.trim().toLowerCase() || undefined, groups: form.groups, disabled: form.disabled,
          must_change_password: form.must_change_password }, user.rev);
        toast.ok("Usuário atualizado");
        if (self) await refreshMe();
        onSaved(u);
      }
    } catch (e) { handleError(e); }
  }
  const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim());
  return html`<${Modal} title=${isNew ? (first ? "Primeiro administrador" : "Novo usuário") : `Usuário ${user.email || user.username}`} onClose=${onClose}>
    <${Field} label="E-mail" hint=${isNew ? "É o login do usuário." : html`É o login. ID interno: <code>${user.username}</code> (não muda)`}
        error=${form.email && !emailOk ? "E-mail inválido" : null}>
      <input type="email" autocapitalize="none" spellcheck="false" value=${form.email} onInput=${(e) => set("email", e.target.value)} /><//>
    <${Field} label="Nome"><input value=${form.display_name} onInput=${(e) => set("display_name", e.target.value)} /><//>
    <${Field} label="Grupos de acesso" hint=${first ? "O primeiro usuário precisa ser admin." : html`Permissões efetivas = soma dos grupos. <a href="#access-groups">Ver grupos</a>`}>
      <${GroupChecks} value=${form.groups} options=${groups} disabled=${first} onChange=${(v) => set("groups", v)} /><//>
    ${isNew && html`
      <${Field} label="Senha" error=${errs.password}><${PasswordInput} autocomplete="new-password" value=${form.password} onInput=${(e) => set("password", e.target.value)} /><//>
      <${Field} label="Confirme a senha" error=${mismatch ? "As senhas não conferem" : null}>
        <${PasswordInput} autocomplete="new-password" value=${form.password2} onInput=${(e) => set("password2", e.target.value)} /><//>`}
    ${!first && html`<${Field}><label><input type="checkbox" checked=${form.must_change_password}
      onChange=${(e) => set("must_change_password", e.target.checked)} /> Senha provisória (troca obrigatória no próximo login)</label><//>`}
    ${!isNew && html`<${Field}><label><input type="checkbox" disabled=${self} checked=${form.disabled}
      onChange=${(e) => set("disabled", e.target.checked)} /> Desativado (não entra; sessões caem na hora)</label><//>`}
    ${!isNew && html`<div class="help">Criado em ${fmtTs(user.created_at)} por ${user.created_by || "—"} · último login ${fmtTs(user.last_login)}${user.last_ip ? " de " + user.last_ip : ""} · senha trocada em ${fmtTs(user.password_changed_at)}</div>`}
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary" disabled=${(isNew && (!form.password || mismatch)) || (form.email && !emailOk) || (isNew && !emailOk)} onClick=${save}>${isNew ? "Criar" : "Salvar"}</button></div>
  <//>`;
}

function ResetPasswordModal({ user, cat, onClose, onSaved }) {
  const [v1, setV1] = useState(""); const [v2, setV2] = useState("");
  const [temp, setTemp] = useState(true);
  const mismatch = v1 && v2 && v1 !== v2;
  const short = v1 && v1.length < cat.password_min;
  async function save() {
    if (!v1 || mismatch || short) return;
    try {
      await api.put(`/users/${encodeURIComponent(user.username)}/password`, { password: v1, must_change_password: temp });
      toast.ok("Senha definida; as sessões do usuário foram encerradas"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${`Definir senha — ${user.email || user.username}`} onClose=${onClose}>
    <${Field} label="Nova senha" error=${short ? `Mínimo de ${cat.password_min} caracteres` : null}>
      <${PasswordInput} autocomplete="new-password" value=${v1} onInput=${(e) => setV1(e.target.value)} /><//>
    <${Field} label="Confirme" error=${mismatch ? "As senhas não conferem" : null}>
      <${PasswordInput} autocomplete="new-password" value=${v2} onInput=${(e) => setV2(e.target.value)} /><//>
    <${Field}><label><input type="checkbox" checked=${temp} onChange=${(e) => setTemp(e.target.checked)} /> Provisória (o usuário troca no próximo login)</label><//>
    <div class="help">Se o cofre estiver destrancado agora, a chave do cofre do usuário é refeita junto; senão ele a ganha no próximo login com o cofre aberto.</div>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary" disabled=${!v1 || mismatch || short} onClick=${save}>Definir senha</button></div>
  <//>`;
}

/* ============================ Grupos de acesso ============================ */
export function AccessGroupsPage() {
  const res = useResource("/access-groups");
  const cat = useCatalog();
  const r = useMenuRoute("access-groups");
  const q = r.params.q || "";
  const [confirm, setConfirm] = useState(null);
  if (res.loading && !res.data) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { groups: all, users } = res.data;
  const [seg] = r.segments;
  const found = seg && seg !== "new" ? all.find((g) => g.name === seg) : null;
  const editing = seg === "new" ? { __new: true, permissions: [], net_perms: ["read"], members: [] } : found;
  const groups = all.filter((g) => matchText(q, g.name, g.description, g.members.join(" ")));
  const permCount = (g) => (g.permissions.includes("*") ? "todas" : String(g.permissions.length));

  const cols = [
    { key: "name", label: "Grupo", hideable: false, sort: true,
      render: (g) => html`<a href=${"#access-groups/" + encodeURIComponent(g.name)} onClick=${(e) => e.stopPropagation()}><b>${g.name}</b></a>${g.builtin ? html` <${Badge} kind="warn">fixo<//>` : ""}` },
    { key: "description", label: "Descrição", sort: true, render: (g) => g.description || "—" },
    { key: "permissions", label: "Permissões", sort: (g) => (g.permissions.includes("*") ? 999 : g.permissions.length), render: permCount },
    { key: "net_perms", label: "Rede (aba Claude)", sort: (g) => g.net_perms.length,
      render: (g) => g.net_perms.length === 4 ? html`<${Badge} kind="warn">Full<//>` : g.net_perms.map((p) => html`<${Badge}>${NET_LABELS[p] || p}<//> `) },
    { key: "members", label: "Membros", sort: (g) => g.members.length, render: (g) => g.members.join(", ") || "—" },
  ];

  return html`<div>
    <div class="page-title"><h1>Grupos de acesso</h1><span class="spacer"></span>
      <a class="btn" href="#users">Usuários</a>
      <button class="primary" onClick=${() => r.open("new")}>+ Novo grupo</button></div>
    <p class="help">O grupo define o que o usuário vê e faz no console. Quem tem acesso a hosts vê todos os
      hosts. Terminal e arquivos do servidor, configuração, atualização, usuários, auditoria, scripts e tarefas
      agendadas ficam só com o grupo <b>admin</b>, porque esses recursos rodam como root no servidor.</p>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder="Buscar grupo ou membro" count=${groups.length} total=${all.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">Grupo '${seg}' não encontrado. <a href="#access-groups">Voltar aos grupos</a></div>`}
    <${DataTable} tableId="access-groups" urlSort columns=${cols} rows=${groups.map((g) => ({ ...g, _key: g.name }))}
      onRowClick=${(g) => r.open(g.name)}
      actions=${(g) => html`<button class="sm danger" disabled=${g.builtin} onClick=${() => setConfirm(g)}>Excluir</button>`}
      empty="Nenhum grupo." />
    ${editing && html`<${GroupForm} key=${editing.name || "new"} group=${editing} cat=${cat} users=${users}
        onClose=${() => r.close()} onSaved=${(g) => { res.reload(); g ? r.open(g.name) : r.close(); }} />`}
    ${confirm && html`<${ConfirmDialog} danger=${true} title="Excluir grupo"
        message=${`Apagar o grupo '${confirm.name}'? ${confirm.members.length ? `Os membros (${confirm.members.join(", ")}) perdem as permissões dele.` : ""}`}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/access-groups/${encodeURIComponent(confirm.name)}`); toast.ok("Grupo apagado"); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function GroupForm({ group, cat, users, onClose, onSaved }) {
  const isNew = !!group.__new;
  const fixed = !!group.builtin;
  const [form, setForm] = useState({ name: isNew ? "" : group.name, description: group.description || "",
    permissions: group.permissions || [], net_perms: group.net_perms || [], members: group.members || [] });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const grantable = cat.permissions.filter((p) => !p.admin_only);
  const areas = [...new Set(grantable.map((p) => p.area))];
  const togglePerm = (key, on) => set("permissions", on ? [...form.permissions, key] : form.permissions.filter((x) => x !== key));
  async function save() {
    try {
      let g;
      if (isNew) {
        g = await api.post("/access-groups", { name: form.name.trim().toLowerCase(), description: form.description,
          permissions: form.permissions, net_perms: form.net_perms });
        if (form.members.length) g = await api.patch(`/access-groups/${encodeURIComponent(g.name)}`, { members: form.members }, g.rev);
        toast.ok(`Grupo ${g.name} criado`);
      } else {
        const body = { description: form.description, members: form.members };
        if (!fixed) { body.permissions = form.permissions; body.net_perms = form.net_perms; }
        g = await api.patch(`/access-groups/${encodeURIComponent(group.name)}`, body, group.rev);
        toast.ok("Grupo atualizado");
      }
      onSaved(g);
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} wide=${true} title=${isNew ? "Novo grupo de acesso" : `Grupo ${group.name}`} onClose=${onClose}>
    ${isNew && html`<${Field} label="Nome" hint="2 a 40 caracteres: minúsculas, números, ponto, hífen ou _">
      <input autocapitalize="none" spellcheck="false" value=${form.name} onInput=${(e) => set("name", e.target.value)} /><//>`}
    <${Field} label="Descrição"><input value=${form.description} onInput=${(e) => set("description", e.target.value)} /><//>
    ${fixed ? html`<div class="card">O grupo <b>admin</b> tem <b>todas</b> as permissões, inclusive as de administração,
        e <b>Full</b> nos equipamentos. Só os membros podem mudar.</div>`
      : html`
      <${Field} label="Permissões no console">
        ${areas.map((a) => html`<fieldset key=${a} class="perm-area"><legend>${a}</legend>
          ${grantable.filter((p) => p.area === a).map((p) => html`<label key=${p.key} class="perm-check" title=${p.key}>
            <input type="checkbox" checked=${form.permissions.includes(p.key)} onChange=${(e) => togglePerm(p.key, e.target.checked)} /> ${p.label}</label>`)}
        </fieldset>`)}
      <//>
      <${Field} label="Teto nos equipamentos (aba Claude)" hint="A aba Claude deste grupo nunca passa disto, nem com aprovação na tela. Terminal de host não é limitado por aqui: libere só a quem pode operar o equipamento.">
        <div class="perm-checks">${cat.net_perms.map((p) => html`<label key=${p} class="perm-check">
          <input type="checkbox" checked=${form.net_perms.includes(p)}
            onChange=${(e) => set("net_perms", e.target.checked ? [...form.net_perms, p] : form.net_perms.filter((x) => x !== p))} /> ${NET_LABELS[p] || p}</label>`)}</div>
      <//>`}
    <${Field} label="Membros">
      <${GroupChecks} value=${form.members} options=${users} onChange=${(v) => set("members", v)} /><//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button>
      <button class="primary" disabled=${isNew && !form.name} onClick=${save}>${isNew ? "Criar" : "Salvar"}</button></div>
  <//>`;
}
