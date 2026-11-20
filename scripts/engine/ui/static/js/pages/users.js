// Usuários e grupos de acesso (menu Sistema; só admin). Banco de acesso SQLite (lib/accessdb.py).
// URLs (core/rules/urls-navegacao.md):
//   #users[/<login>|/new|/<login>/password][?q=&group=&status=&sort=&dir=]
//   #access-groups[/<nome>|/new][?q=&sort=&dir=]
import { html, useState, api, useResource, Spinner, Badge, toast, handleError, useMe, refreshMe, t, fmtDateTime } from "../ui.js";
import { useMenuRoute, matchText } from "../route.js";
import { FilterBar, DataTable, Field, Modal, ConfirmDialog, PasswordInput } from "../components.js";

const fmtTs = (ts) => (ts ? fmtDateTime(ts * 1000, { dateStyle: "short", timeStyle: "short" }) : "—");

function useCatalog() {
  const r = useResource("/access-catalog");
  return r.data || { permissions: [], net_perms: ["read", "create", "edit", "delete"], password_min: 8, multiuser: true };
}

const NET_LABELS = { read: "users.net_read", create: "users.net_create", edit: "users.net_edit", delete: "users.net_delete" };
const netLabel = (p) => (NET_LABELS[p] ? t(NET_LABELS[p]) : p);

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
  if (res.error) return html`<div class="card">${t("users.error", { message: res.error.message })}</div>`;
  const { users: all, groups: groupNames, multiuser } = res.data;
  const [seg, sub] = r.segments;
  const found = seg && seg !== "new" ? all.find((u) => u.username === seg) : null;
  const resetting = found && sub === "password" ? found : null;
  const editing = seg === "new" ? { __new: true } : found && !resetting ? found : null;
  const users = all.filter((u) => matchText(q, u.username, u.display_name, u.email)
    && (!group || u.groups.includes(group))
    && (!status || (status === "ativo" ? !u.disabled : u.disabled)));

  const cols = [
    { key: "email", label: t("users.col_email"), hideable: false, sort: (u) => u.email || u.username,
      render: (u) => html`<a href=${"#users/" + encodeURIComponent(u.username)} onClick=${(e) => e.stopPropagation()}><b>${u.email || u.username}</b></a>
        ${me && me.username === u.username ? html` <${Badge}>${t("users.you")}<//>` : ""}${!u.email ? html` <${Badge} kind="warn">${t("users.no_email")}<//>` : ""}` },
    { key: "display_name", label: t("common.name"), sort: true, render: (u) => u.display_name || "—" },
    { key: "username", label: "ID", sort: true, hidden: true, render: (u) => html`<code>${u.username}</code>` },
    { key: "groups", label: t("users.col_groups"), sort: (u) => u.groups.join(","), render: (u) => u.groups.length
        ? u.groups.map((g) => html`<${Badge} kind=${g === "admin" ? "warn" : ""}>${g}<//> `) : html`<span class="help">${t("users.no_group")}</span>` },
    { key: "status", label: t("users.col_status"), sort: (u) => (u.disabled ? 2 : u.must_change_password ? 1 : 0),
      render: (u) => u.disabled ? html`<${Badge} kind="danger">${t("users.status_disabled")}<//>`
        : u.must_change_password ? html`<${Badge} kind="warn">${t("users.status_temp_password")}<//>` : html`<${Badge} kind="ok">${t("users.status_active")}<//>` },
    { key: "last_login", label: t("users.col_last_login"), sort: (u) => u.last_login || 0, render: (u) => fmtTs(u.last_login) },
    { key: "sessions", label: t("users.col_sessions"), sort: true, render: (u) => String(u.sessions) },
    { key: "vault_slot", label: t("users.col_vault"), sort: (u) => (u.vault_slot ? 1 : 0),
      render: (u) => (u.vault_slot ? html`<${Badge} kind="ok">${t("users.vault_unlocks")}<//>` : html`<span class="help" title=${t("users.vault_slot_hint")}>—</span>`) },
    { key: "last_ip", label: t("users.col_last_ip"), sort: true, hidden: true, render: (u) => u.last_ip || "—" },
    { key: "created_at", label: t("users.col_created"), sort: (u) => u.created_at || 0, hidden: true, render: (u) => `${fmtTs(u.created_at)} (${u.created_by || "—"})` },
  ];

  return html`<div>
    <div class="page-title"><h1>${t("users.title")}</h1><span class="spacer"></span>
      <a class="btn" href="#access-groups">${t("users.access_groups")}</a>
      <button class="primary" onClick=${() => r.open("new")}>${t("users.new_user_btn")}</button></div>
    ${!multiuser && html`<div class="card"><b>${t("users.master_mode_strong")}</b> ${t("users.master_mode_text")} <code>admin</code>${t("users.master_mode_end")}</div>`}
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("users.search_users")}
      selects=${[{ key: "group", label: t("users.group"), value: group, options: groupNames },
                 { key: "status", label: t("users.col_status"), value: status,
                   options: [{ value: "ativo", label: t("users.status_active") }, { value: "desativado", label: t("users.status_disabled") }] }]}
      count=${users.length} total=${all.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">${t("users.user_not_found", { name: seg })} <a href="#users">${t("users.back_users")}</a></div>`}
    <${DataTable} tableId="users" urlSort columns=${cols} rows=${users.map((u) => ({ ...u, _key: u.username }))}
      onRowClick=${(u) => r.open(u.username)}
      actions=${(u) => html`
        <button class="sm" onClick=${() => r.open([u.username, "password"])}>${t("users.password_btn")}</button>
        <button class="sm" disabled=${!u.sessions} onClick=${() => setConfirm({ kind: "logout", u })}>${t("users.end_sessions")}</button>
        <button class="sm danger" disabled=${me && me.username === u.username} onClick=${() => setConfirm({ kind: "delete", u })}>${t("common.delete")}</button>`}
      empty=${t("users.no_users")} />

    ${editing && html`<${UserForm} key=${editing.username || "new"} user=${editing} groups=${groupNames} cat=${cat}
        first=${!multiuser} self=${me && me.username === editing.username}
        onClose=${() => r.close()} onSaved=${(u) => { res.reload(); u ? r.open(u.username) : r.close(); }} />`}
    ${resetting && html`<${ResetPasswordModal} user=${resetting} cat=${cat} onClose=${() => r.close()}
        onSaved=${() => { r.close(); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} danger=${confirm.kind === "delete"}
        title=${confirm.kind === "delete" ? t("users.delete_user") : t("users.end_sessions")}
        message=${confirm.kind === "delete" ? t("users.delete_user_confirm", { name: confirm.u.email || confirm.u.username })
          : t("users.logout_confirm", { count: confirm.u.sessions, name: confirm.u.email || confirm.u.username })}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try {
            if (confirm.kind === "delete") { await api.del(`/users/${encodeURIComponent(confirm.u.username)}`); toast.ok(t("users.user_deleted")); }
            else { await api.del(`/users/${encodeURIComponent(confirm.u.username)}/sessions`); toast.ok(t("users.sessions_ended")); }
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
        if (form.password.length < cat.password_min) { setErrs({ password: t("users.password_min", { n: cat.password_min }) }); return; }
        if (form.password !== form.password2) return;
        const u = await api.post("/users", {
          email: form.email.trim().toLowerCase(), password: form.password, display_name: form.display_name,
          groups: form.groups, must_change_password: form.must_change_password });
        toast.ok(t("users.user_created", { email: u.email }));
        if (first) await refreshMe();
        onSaved(u);
      } else {
        const u = await api.patch(`/users/${encodeURIComponent(user.username)}`, {
          display_name: form.display_name, email: form.email.trim().toLowerCase() || undefined, groups: form.groups, disabled: form.disabled,
          must_change_password: form.must_change_password }, user.rev);
        toast.ok(t("users.user_updated"));
        if (self) await refreshMe();
        onSaved(u);
      }
    } catch (e) { handleError(e); }
  }
  const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim());
  return html`<${Modal} title=${isNew ? (first ? t("users.first_admin") : t("users.new_user")) : t("users.user_title", { name: user.email || user.username })} onClose=${onClose}>
    <${Field} label=${t("common.email")} hint=${isNew ? t("users.email_hint_new") : html`${t("users.email_hint_edit")} <code>${user.username}</code> ${t("users.email_hint_edit_end")}`}
        error=${form.email && !emailOk ? t("users.email_invalid") : null}>
      <input type="email" autocapitalize="none" spellcheck="false" value=${form.email} onInput=${(e) => set("email", e.target.value)} /><//>
    <${Field} label=${t("common.name")}><input value=${form.display_name} onInput=${(e) => set("display_name", e.target.value)} /><//>
    <${Field} label=${t("users.access_groups")} hint=${first ? t("users.groups_hint_first") : html`${t("users.groups_hint")} <a href="#access-groups">${t("users.see_groups")}</a>`}>
      <${GroupChecks} value=${form.groups} options=${groups} disabled=${first} onChange=${(v) => set("groups", v)} /><//>
    ${isNew && html`
      <${Field} label=${t("common.password")} error=${errs.password}><${PasswordInput} autocomplete="new-password" value=${form.password} onInput=${(e) => set("password", e.target.value)} /><//>
      <${Field} label=${t("users.confirm_password")} error=${mismatch ? t("users.password_mismatch") : null}>
        <${PasswordInput} autocomplete="new-password" value=${form.password2} onInput=${(e) => set("password2", e.target.value)} /><//>`}
    ${!first && html`<${Field}><label><input type="checkbox" checked=${form.must_change_password}
      onChange=${(e) => set("must_change_password", e.target.checked)} /> ${t("users.must_change")}</label><//>`}
    ${!isNew && html`<${Field}><label><input type="checkbox" disabled=${self} checked=${form.disabled}
      onChange=${(e) => set("disabled", e.target.checked)} /> ${t("users.disabled_check")}</label><//>`}
    ${!isNew && html`<div class="help">${t("users.user_meta", { created: fmtTs(user.created_at), by: user.created_by || "—", last: fmtTs(user.last_login), ip: user.last_ip ? t("users.from_ip", { ip: user.last_ip }) : "", changed: fmtTs(user.password_changed_at) })}</div>`}
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary" disabled=${(isNew && (!form.password || mismatch)) || (form.email && !emailOk) || (isNew && !emailOk)} onClick=${save}>${isNew ? t("common.create") : t("common.save")}</button></div>
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
      toast.ok(t("users.password_set")); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${t("users.set_password_title", { name: user.email || user.username })} onClose=${onClose}>
    <${Field} label=${t("users.new_password")} error=${short ? t("users.password_min", { n: cat.password_min }) : null}>
      <${PasswordInput} autocomplete="new-password" value=${v1} onInput=${(e) => setV1(e.target.value)} /><//>
    <${Field} label=${t("users.confirm")} error=${mismatch ? t("users.password_mismatch") : null}>
      <${PasswordInput} autocomplete="new-password" value=${v2} onInput=${(e) => setV2(e.target.value)} /><//>
    <${Field}><label><input type="checkbox" checked=${temp} onChange=${(e) => setTemp(e.target.checked)} /> ${t("users.temporary")}</label><//>
    <div class="help">${t("users.reset_help")}</div>
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary" disabled=${!v1 || mismatch || short} onClick=${save}>${t("users.set_password")}</button></div>
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
  if (res.error) return html`<div class="card">${t("users.error", { message: res.error.message })}</div>`;
  const { groups: all, users } = res.data;
  const [seg] = r.segments;
  const found = seg && seg !== "new" ? all.find((g) => g.name === seg) : null;
  const editing = seg === "new" ? { __new: true, permissions: [], net_perms: ["read"], members: [] } : found;
  const groups = all.filter((g) => matchText(q, g.name, g.description, g.members.join(" ")));
  const permCount = (g) => (g.permissions.includes("*") ? t("users.perm_all") : String(g.permissions.length));

  const cols = [
    { key: "name", label: t("users.group"), hideable: false, sort: true,
      render: (g) => html`<a href=${"#access-groups/" + encodeURIComponent(g.name)} onClick=${(e) => e.stopPropagation()}><b>${g.name}</b></a>${g.builtin ? html` <${Badge} kind="warn">${t("users.builtin")}<//>` : ""}` },
    { key: "description", label: t("common.description"), sort: true, render: (g) => g.description || "—" },
    { key: "permissions", label: t("users.col_permissions"), sort: (g) => (g.permissions.includes("*") ? 999 : g.permissions.length), render: permCount },
    { key: "net_perms", label: t("users.col_network"), sort: (g) => g.net_perms.length,
      render: (g) => g.net_perms.length === 4 ? html`<${Badge} kind="warn">Full<//>` : g.net_perms.map((p) => html`<${Badge}>${netLabel(p)}<//> `) },
    { key: "members", label: t("users.col_members"), sort: (g) => g.members.length, render: (g) => g.members.join(", ") || "—" },
  ];

  return html`<div>
    <div class="page-title"><h1>${t("users.access_groups")}</h1><span class="spacer"></span>
      <a class="btn" href="#users">${t("users.users")}</a>
      <button class="primary" onClick=${() => r.open("new")}>${t("users.new_group_btn")}</button></div>
    <p class="help">${t("users.groups_help_1")} <b>admin</b>${t("users.groups_help_2")} <b>server.admin</b> ${t("users.groups_help_3")}</p>
    <${FilterBar} q=${q} onChange=${r.setParams} placeholder=${t("users.search_groups")} count=${groups.length} total=${all.length} />
    ${seg && seg !== "new" && !found && html`<div class="card">${t("users.group_not_found", { name: seg })} <a href="#access-groups">${t("users.back_groups")}</a></div>`}
    <${DataTable} tableId="access-groups" urlSort columns=${cols} rows=${groups.map((g) => ({ ...g, _key: g.name }))}
      onRowClick=${(g) => r.open(g.name)}
      actions=${(g) => html`<button class="sm danger" disabled=${g.builtin} onClick=${() => setConfirm(g)}>${t("common.delete")}</button>`}
      empty=${t("users.no_groups")} />
    ${editing && html`<${GroupForm} key=${editing.name || "new"} group=${editing} cat=${cat} users=${users}
        onClose=${() => r.close()} onSaved=${(g) => { res.reload(); g ? r.open(g.name) : r.close(); }} />`}
    ${confirm && html`<${ConfirmDialog} danger=${true} title=${t("users.delete_group")}
        message=${t("users.delete_group_confirm", { name: confirm.name, members: confirm.members.length ? t("users.delete_group_members", { members: confirm.members.join(", ") }) : "" })}
        onClose=${() => setConfirm(null)}
        onConfirm=${async () => {
          try { await api.del(`/access-groups/${encodeURIComponent(confirm.name)}`); toast.ok(t("users.group_deleted")); res.reload(); }
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
        toast.ok(t("users.group_created", { name: g.name }));
      } else {
        const body = { description: form.description, members: form.members };
        if (!fixed) { body.permissions = form.permissions; body.net_perms = form.net_perms; }
        g = await api.patch(`/access-groups/${encodeURIComponent(group.name)}`, body, group.rev);
        toast.ok(t("users.group_updated"));
      }
      onSaved(g);
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} wide=${true} title=${isNew ? t("users.new_group") : t("users.group_title", { name: group.name })} onClose=${onClose}>
    ${isNew && html`<${Field} label=${t("common.name")} hint=${t("users.group_name_hint")}>
      <input autocapitalize="none" spellcheck="false" value=${form.name} onInput=${(e) => set("name", e.target.value)} /><//>`}
    <${Field} label=${t("common.description")}><input value=${form.description} onInput=${(e) => set("description", e.target.value)} /><//>
    ${fixed ? html`<div class="card">${t("users.admin_fixed_1")} <b>admin</b> ${t("users.admin_fixed_2")} <b>${t("users.admin_fixed_all")}</b> ${t("users.admin_fixed_3")} <b>Full</b> ${t("users.admin_fixed_4")}</div>`
      : html`
      <${Field} label=${t("users.console_perms")}>
        ${areas.map((a) => html`<fieldset key=${a} class="perm-area"><legend>${a}</legend>
          ${grantable.filter((p) => p.area === a).map((p) => html`<label key=${p.key} class="perm-check" title=${p.key}>
            <input type="checkbox" checked=${form.permissions.includes(p.key)} onChange=${(e) => togglePerm(p.key, e.target.checked)} /> ${p.label}</label>`)}
        </fieldset>`)}
      <//>
      <${Field} label=${t("users.net_ceiling")} hint=${t("users.net_ceiling_hint")}>
        <div class="perm-checks">${cat.net_perms.map((p) => html`<label key=${p} class="perm-check">
          <input type="checkbox" checked=${form.net_perms.includes(p)}
            onChange=${(e) => set("net_perms", e.target.checked ? [...form.net_perms, p] : form.net_perms.filter((x) => x !== p))} /> ${netLabel(p)}</label>`)}</div>
      <//>`}
    <${Field} label=${t("users.col_members")}>
      <${GroupChecks} value=${form.members} options=${users} onChange=${(v) => set("members", v)} /><//>
    <div class="modal-actions"><button onClick=${onClose}>${t("common.cancel")}</button>
      <button class="primary" disabled=${isNew && !form.name} onClick=${save}>${isNew ? t("common.create") : t("common.save")}</button></div>
  <//>`;
}
