// Minha conta (#account): quem sou, meus grupos e permissões, trocar a própria senha.
// Senha provisória (must_change_password): o shell só mostra esta tela até a troca.
import { html, useState, api, toast, handleError, useMe, refreshMe, Badge } from "../ui.js";
import { Field, PasswordInput } from "../components.js";

const fmtTs = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
const NET = { read: "Ler e diagnosticar", create: "Criar", edit: "Editar", delete: "Apagar" };

export function AccountPage({ forced = false }) {
  const me = useMe();
  const [cur, setCur] = useState(""); const [v1, setV1] = useState(""); const [v2, setV2] = useState("");
  const [busy, setBusy] = useState(false);
  if (!me) return html`<div class="card">Carregando…</div>`;
  const mismatch = v2 && v1 !== v2;
  const short = v1 && v1.length < 8;
  async function save(e) {
    e && e.preventDefault && e.preventDefault();
    if (!cur || !v1 || mismatch || short || busy) return;
    setBusy(true);
    try {
      const r = await api.post("/auth/password", { current_password: cur, new_password: v1 });
      setCur(""); setV1(""); setV2("");
      toast.ok(r.vault_slot ? "Senha trocada (sua chave do cofre foi refeita)" : "Senha trocada");
      await refreshMe();
      if (forced) location.hash = "#";
    } catch (err) { handleError(err); if (err.status === 401) toast.err("Senha atual incorreta."); }
    finally { setBusy(false); }
  }
  const perms = (me.catalog || []).filter((p) => me.is_admin || (me.permissions || []).includes(p.key));
  return html`<div>
    <div class="page-title"><h1>Minha conta</h1></div>
    ${forced && html`<div class="card"><b>Senha provisória.</b> Defina sua senha para continuar usando o console.</div>`}
    <div class="card">
      <dl class="account-grid">
        <dt>Usuário</dt><dd><b>${me.username}</b>${me.display_name && me.display_name !== me.username ? ` — ${me.display_name}` : ""}</dd>
        <dt>Grupos</dt><dd>${(me.groups || []).map((g) => html`<${Badge} kind=${g === "admin" ? "warn" : ""}>${g}<//> `)}</dd>
        <dt>Equipamentos (aba Claude)</dt><dd>${(me.net_perms || []).map((p) => NET[p] || p).join(", ") || "nada"}</dd>
        ${me.multiuser && !me.legacy && html`<dt>Último login</dt><dd>${fmtTs(me.last_login)}</dd>
          <dt>Senha trocada em</dt><dd>${fmtTs(me.password_changed_at)}</dd>
          <dt>Cofre</dt><dd>${me.vault_slot ? "seu login destranca o cofre" : "sem chave (ganha no próximo login com o cofre destrancado)"}</dd>`}
      </dl>
    </div>
    ${me.multiuser && !me.legacy ? html`<form class="card" onSubmit=${save} style="max-width:460px">
      <h3>Trocar senha</h3>
      <${Field} label="Senha atual"><${PasswordInput} autocomplete="current-password" value=${cur} onInput=${(e) => setCur(e.target.value)} /><//>
      <${Field} label="Nova senha" error=${short ? "Mínimo de 8 caracteres" : null}>
        <${PasswordInput} autocomplete="new-password" value=${v1} onInput=${(e) => setV1(e.target.value)} /><//>
      <${Field} label="Confirme a nova senha" error=${mismatch ? "As senhas não conferem" : null}>
        <${PasswordInput} autocomplete="new-password" value=${v2} onInput=${(e) => setV2(e.target.value)} /><//>
      <div class="help">Trocar a senha encerra suas outras sessões (esta continua).</div>
      <div class="modal-actions"><button type="submit" class="primary" disabled=${busy || !cur || !v1 || mismatch || short}>Trocar senha</button></div>
    </form>` : html`<div class="card">Modo senha-mestra: ainda não há usuários. ${me.is_admin
      ? html`Crie o primeiro administrador em <a href="#users/new">Sistema → Usuários</a>.` : ""}</div>`}
    ${!me.is_admin && html`<div class="card"><h3>O que você pode fazer</h3>
      <ul>${perms.map((p) => html`<li key=${p.key}>${p.label}</li>`)}</ul></div>`}
  </div>`;
}
