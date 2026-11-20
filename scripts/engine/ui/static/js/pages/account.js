// Minha conta (#account): quem sou, meus grupos e permissões, trocar a própria senha.
// #account/github: conectar a PRÓPRIA conta do GitHub (vale nas conversas da aba Claude/Projetos).
// Senha provisória (must_change_password): o shell só mostra esta tela até a troca.
import { html, useState, useEffect, useRef, api, toast, handleError, useMe, refreshMe, Badge, Tabs, CopyButton, t, fmtDateTime } from "../ui.js";
import { Field, PasswordInput } from "../components.js";
import { authToken } from "../api.js";
import { useMenuRoute } from "../route.js";
import { MyLanguageCard } from "../language.js";

const fmtTs = (ts) => (ts ? fmtDateTime(ts * 1000, { dateStyle: "short", timeStyle: "short" }) : "—");
const NET = { read: "account.net_read", create: "account.net_create", edit: "account.net_edit", delete: "account.net_delete" };

export function AccountPage({ forced = false }) {
  const me = useMe();
  const r = useMenuRoute("account");
  const tab = !forced && r.segments[0] === "github" ? "github" : "conta";
  const [cur, setCur] = useState(""); const [v1, setV1] = useState(""); const [v2, setV2] = useState("");
  const [busy, setBusy] = useState(false);
  if (!me) return html`<div class="card">${t("common.loading")}</div>`;
  const mismatch = v2 && v1 !== v2;
  const short = v1 && v1.length < 8;
  async function save(e) {
    e && e.preventDefault && e.preventDefault();
    if (!cur || !v1 || mismatch || short || busy) return;
    setBusy(true);
    try {
      const r = await api.post("/auth/password", { current_password: cur, new_password: v1 });
      setCur(""); setV1(""); setV2("");
      toast.ok(r.vault_slot ? t("account.password_changed_vault") : t("account.password_changed"));
      await refreshMe();
      if (forced) location.hash = "#";
    } catch (err) { handleError(err); if (err.status === 401) toast.err(t("account.current_password_wrong")); }
    finally { setBusy(false); }
  }
  const perms = (me.catalog || []).filter((p) => me.is_admin || (me.permissions || []).includes(p.key));
  return html`<div>
    <div class="page-title"><h1>${t("common.my_account")}</h1></div>
    ${!forced && html`<${Tabs} tabs=${[{ key: "conta", label: t("account.tab_account") }, { key: "github", label: "GitHub" }]}
      active=${tab} onChange=${(k) => r.open(k === "github" ? ["github"] : [])} />`}
    ${tab === "github" ? html`<${GitHubCard} me=${me} />` : html`<div>
    ${forced && html`<div class="card"><b>${t("account.temp_password_strong")}</b> ${t("account.temp_password_text")}</div>`}
    <div class="card">
      <dl class="account-grid">
        <dt>${t("account.email_login")}</dt><dd><b>${me.email || me.username}</b>${me.display_name && me.display_name !== me.username ? ` — ${me.display_name}` : ""}</dd>
        <dt>${t("account.groups")}</dt><dd>${(me.groups || []).map((g) => html`<${Badge} kind=${g === "admin" ? "warn" : ""}>${g}<//> `)}</dd>
        <dt>${t("account.devices")}</dt><dd>${(me.net_perms || []).map((p) => (NET[p] ? t(NET[p]) : p)).join(", ") || t("account.nothing")}</dd>
        ${me.multiuser && !me.legacy && html`<dt>${t("account.last_login")}</dt><dd>${fmtTs(me.last_login)}</dd>
          <dt>${t("account.password_changed_at")}</dt><dd>${fmtTs(me.password_changed_at)}</dd>
          <dt>${t("account.vault")}</dt><dd>${me.vault_slot ? t("account.vault_slot_yes") : t("account.vault_slot_no")}</dd>`}
      </dl>
    </div>
    ${!forced && html`<${MyLanguageCard} me=${me} />`}
    ${me.multiuser && !me.legacy ? html`<form class="card" onSubmit=${save} style="max-width:460px">
      <h3>${t("account.change_password")}</h3>
      <${Field} label=${t("account.current_password")}><${PasswordInput} autocomplete="current-password" value=${cur} onInput=${(e) => setCur(e.target.value)} /><//>
      <${Field} label=${t("account.new_password")} error=${short ? t("account.password_min8") : null}>
        <${PasswordInput} autocomplete="new-password" value=${v1} onInput=${(e) => setV1(e.target.value)} /><//>
      <${Field} label=${t("account.confirm_new_password")} error=${mismatch ? t("account.password_mismatch") : null}>
        <${PasswordInput} autocomplete="new-password" value=${v2} onInput=${(e) => setV2(e.target.value)} /><//>
      <div class="help">${t("account.change_password_help")}</div>
      <div class="modal-actions"><button type="submit" class="primary" disabled=${busy || !cur || !v1 || mismatch || short}>${t("account.change_password")}</button></div>
    </form>` : html`<div class="card">${t("account.master_mode")} ${me.is_admin
      ? html`${t("account.create_first_admin")} <a href="#users/new">${t("account.system_users")}</a>.` : ""}</div>`}
    ${!me.is_admin && html`<div class="card"><h3>${t("account.what_you_can_do")}</h3>
      <ul>${perms.map((p) => html`<li key=${p.key}>${p.label}</li>`)}</ul></div>`}
    </div>`}
  </div>`;
}

// ------------------------------------------------------------------ GitHub
// Login por dispositivo do GitHub CLI conduzido pelo servidor (WS /api/account/github/login): mostra o
// código + link; você autoriza no SEU navegador. Ver services/github_auth.py e lib/github_identity.py.
function GitHubCard({ me }) {
  const [st, setSt] = useState(null);
  const [phase, setPhase] = useState("idle");      // idle|starting|device|done|error
  const [device, setDevice] = useState(null);
  const [log, setLog] = useState([]);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const wsRef = useRef(null);
  const alive = useRef(true);

  const load = () => api.get("/account/github").then((d) => alive.current && setSt(d)).catch(handleError);
  useEffect(() => { load(); return () => { alive.current = false; try { wsRef.current && wsRef.current.close(); } catch (_) {} }; }, []);

  function start() {
    setPhase("starting"); setDevice(null); setLog([]);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/account/github/login?auth=${encodeURIComponent(authToken())}`);
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "start" }));
    ws.onclose = () => { if (alive.current) setPhase((p) => (p === "done" ? p : p === "idle" ? p : "error")); };
    ws.onmessage = (e) => {
      if (!alive.current) return;
      let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
      if (ev.type === "device") { setDevice(ev); setPhase("device"); }
      else if (ev.type === "log") setLog((l) => [...l, ev.text].slice(-6));
      else if (ev.type === "error") { setLog((l) => [...l, ev.detail]); setPhase("error"); }
      else if (ev.type === "done") {
        setSt({ ...(st || {}), ...ev.status, multiuser: true }); setPhase("done");
        if (ev.ok) { toast.ok(t("account.gh_connected_as", { login: ev.status.login })); refreshMe(); } else toast.err(t("account.gh_login_incomplete"));
        try { ws.close(); } catch (_) {}
      }
    };
  }
  function cancel() {
    try { wsRef.current && wsRef.current.send(JSON.stringify({ type: "cancel" })); } catch (_) {}
    setPhase("idle"); setDevice(null);
  }
  async function act(fn, okMsg) {
    setBusy(true);
    try { const d = await fn(); setSt(d); if (okMsg) toast.ok(okMsg); refreshMe(); }
    catch (err) { handleError(err); } finally { setBusy(false); }
  }
  const saveToken = () => act(async () => { const d = await api.post("/account/github/token", { token: token.trim() }); setToken(""); setTokenOpen(false); return d; }, t("account.gh_connected"));
  const disconnect = () => act(() => api.del("/account/github"), t("account.gh_disconnected"));
  const setEmail = (email) => act(() => api.put("/account/github/email", { email }), t("account.gh_email_updated"));

  if (!st) return html`<div class="card">${t("common.loading")}</div>`;
  if (!st.multiuser) return html`<div class="card">${t("account.gh_multiuser_only")}</div>`;
  if (!st.gh_available) return html`<div class="card">${t("account.gh_cli_missing_1")}<code>gh</code>${t("account.gh_cli_missing_2")}</div>`;
  const flow = phase === "starting" || phase === "device";
  return html`<div>
    <div class="card">
      <h3>${t("account.gh_title")}</h3>
      <p class="help">${t("account.gh_help_1")} <b>${t("account.gh_help_you")}</b> ${t("account.gh_help_2")} <code>gh</code>${t("account.gh_help_3")} <code>gh</code> ${t("account.gh_help_4")} <b>${t("account.gh_help_new")}</b>.</p>
      ${st.connected ? html`<dl class="account-grid">
          <dt>${t("account.gh_account")}</dt><dd>${st.avatar_url && html`<img src=${st.avatar_url + "&s=40"} alt="" width="20" height="20" style="vertical-align:middle;border-radius:50%;margin-right:6px" />`}
            <a href=${"https://github.com/" + st.login} target="_blank" rel="noopener"><b>@${st.login}</b></a>${st.name && st.name !== st.login ? ` — ${st.name}` : ""}</dd>
          <dt>${t("account.gh_commit_email")}</dt><dd>
            <select value=${st.email} disabled=${busy} onChange=${(e) => setEmail(e.target.value)}>
              ${(st.emails || [st.email]).map((m) => html`<option key=${m} value=${m}>${m}${/noreply/.test(m) ? t("account.gh_private") : ""}</option>`)}
            </select></dd>
          <dt>${t("account.gh_permissions")}</dt><dd>${(st.scopes || []).join(", ") || "—"}</dd>
          <dt>${t("account.gh_connected_at")}</dt><dd>${fmtTs(st.connected_at)} · ${st.method === "token" ? t("account.gh_method_token") : t("account.gh_method_browser")}</dd>
        </dl>` : html`<p><${Badge} kind="warn">${t("account.gh_not_connected")}<//></p>`}
      <div class="modal-actions">
        ${!flow && html`<button class="primary" disabled=${busy} onClick=${start}>${st.connected ? t("account.gh_switch") : t("account.gh_connect")}</button>`}
        ${!flow && html`<button disabled=${busy} onClick=${() => setTokenOpen(!tokenOpen)}>${t("account.gh_use_token")}</button>`}
        ${st.connected && !flow && html`<button class="danger" disabled=${busy} onClick=${disconnect}>${t("account.gh_disconnect")}</button>`}
      </div>
    </div>
    ${flow && html`<div class="card">
      ${phase === "starting" && html`<p>${t("account.gh_requesting")}</p>`}
      ${device && html`<div>
        <p>${t("account.gh_step1")} <b style="font-size:1.4em;letter-spacing:2px">${device.code}</b> <${CopyButton} text=${device.code} /></p>
        <p>${t("account.gh_step2_open")} <a href=${device.url} target="_blank" rel="noopener">${device.url}</a> ${t("account.gh_step2_text")} <b>${t("account.gh_step2_yours")}</b> ${t("account.gh_step2_end")}</p>
        <p class="help">${t("account.gh_auto_refresh")}</p>
      </div>`}
      ${log.length > 0 && html`<pre class="help">${log.join("\n")}</pre>`}
      <div class="modal-actions"><button onClick=${cancel}>${t("common.cancel")}</button></div>
    </div>`}
    ${phase === "error" && log.length > 0 && html`<div class="card"><pre class="help">${log.join("\n")}</pre></div>`}
    ${tokenOpen && !flow && html`<div class="card" style="max-width:560px">
      <h3>${t("account.gh_token_title")}</h3>
      <p class="help">${t("account.gh_token_help")}</p>
      <${Field} label=${t("account.gh_token")}><${PasswordInput} autocomplete="off" value=${token} onInput=${(e) => setToken(e.target.value)} /><//>
      <div class="modal-actions"><button class="primary" disabled=${busy || token.trim().length < 10} onClick=${saveToken}>${t("account.gh_connect_token")}</button></div>
    </div>`}
  </div>`;
}
