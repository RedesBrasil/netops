// Minha conta (#account): quem sou, meus grupos e permissões, trocar a própria senha.
// #account/github: conectar a PRÓPRIA conta do GitHub (vale nas conversas da aba Claude/Projetos).
// Senha provisória (must_change_password): o shell só mostra esta tela até a troca.
import { html, useState, useEffect, useRef, api, toast, handleError, useMe, refreshMe, Badge, Tabs, CopyButton } from "../ui.js";
import { Field, PasswordInput } from "../components.js";
import { authToken } from "../api.js";
import { useMenuRoute } from "../route.js";

const fmtTs = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
const NET = { read: "Ler e diagnosticar", create: "Criar", edit: "Editar", delete: "Apagar" };

export function AccountPage({ forced = false }) {
  const me = useMe();
  const r = useMenuRoute("account");
  const tab = !forced && r.segments[0] === "github" ? "github" : "conta";
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
    ${!forced && html`<${Tabs} tabs=${[{ key: "conta", label: "Conta" }, { key: "github", label: "GitHub" }]}
      active=${tab} onChange=${(k) => r.open(k === "github" ? ["github"] : [])} />`}
    ${tab === "github" ? html`<${GitHubCard} me=${me} />` : html`<div>
    ${forced && html`<div class="card"><b>Senha provisória.</b> Defina sua senha para continuar usando o console.</div>`}
    <div class="card">
      <dl class="account-grid">
        <dt>E-mail (login)</dt><dd><b>${me.email || me.username}</b>${me.display_name && me.display_name !== me.username ? ` — ${me.display_name}` : ""}</dd>
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
        if (ev.ok) { toast.ok("GitHub conectado: @" + ev.status.login); refreshMe(); } else toast.err("Login no GitHub não concluído");
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
  const saveToken = () => act(async () => { const d = await api.post("/account/github/token", { token: token.trim() }); setToken(""); setTokenOpen(false); return d; }, "GitHub conectado");
  const disconnect = () => act(() => api.del("/account/github"), "GitHub desconectado");
  const setEmail = (email) => act(() => api.put("/account/github/email", { email }), "E-mail dos commits atualizado");

  if (!st) return html`<div class="card">Carregando…</div>`;
  if (!st.multiuser) return html`<div class="card">O GitHub por usuário vale no modo multiusuário. Sem usuários cadastrados,
    o agente usa a conta do GitHub configurada no servidor.</div>`;
  if (!st.gh_available) return html`<div class="card">O GitHub CLI (<code>gh</code>) não está instalado no servidor. Peça a um administrador.</div>`;
  const flow = phase === "starting" || phase === "device";
  return html`<div>
    <div class="card">
      <h3>Sua conta do GitHub</h3>
      <p class="help">O agente usa esta conta nas conversas que <b>você</b> abre na aba Claude Code e nos Projetos (push, PR, <code>gh</code>);
        os commits saem com o seu nome. Sem conta conectada, push e <code>gh</code> falham, e a conta do servidor nunca é usada.
        Conectar ou trocar a conta vale para <b>conversas novas ou reabertas</b>.</p>
      ${st.connected ? html`<dl class="account-grid">
          <dt>Conta</dt><dd>${st.avatar_url && html`<img src=${st.avatar_url + "&s=40"} alt="" width="20" height="20" style="vertical-align:middle;border-radius:50%;margin-right:6px" />`}
            <a href=${"https://github.com/" + st.login} target="_blank" rel="noopener"><b>@${st.login}</b></a>${st.name && st.name !== st.login ? ` — ${st.name}` : ""}</dd>
          <dt>E-mail dos commits</dt><dd>
            <select value=${st.email} disabled=${busy} onChange=${(e) => setEmail(e.target.value)}>
              ${(st.emails || [st.email]).map((m) => html`<option key=${m} value=${m}>${m}${/noreply/.test(m) ? " (privado)" : ""}</option>`)}
            </select></dd>
          <dt>Permissões</dt><dd>${(st.scopes || []).join(", ") || "—"}</dd>
          <dt>Conectado em</dt><dd>${fmtTs(st.connected_at)} · ${st.method === "token" ? "token pessoal" : "navegador"}</dd>
        </dl>` : html`<p><${Badge} kind="warn">não conectado<//></p>`}
      <div class="modal-actions">
        ${!flow && html`<button class="primary" disabled=${busy} onClick=${start}>${st.connected ? "Trocar de conta" : "Conectar GitHub"}</button>`}
        ${!flow && html`<button disabled=${busy} onClick=${() => setTokenOpen(!tokenOpen)}>Usar token pessoal</button>`}
        ${st.connected && !flow && html`<button class="danger" disabled=${busy} onClick=${disconnect}>Desconectar</button>`}
      </div>
    </div>
    ${flow && html`<div class="card">
      ${phase === "starting" && html`<p>Pedindo um código ao GitHub…</p>`}
      ${device && html`<div>
        <p>1. Copie o código: <b style="font-size:1.4em;letter-spacing:2px">${device.code}</b> <${CopyButton} text=${device.code} /></p>
        <p>2. Abra <a href=${device.url} target="_blank" rel="noopener">${device.url}</a> no seu navegador, entre na <b>sua</b> conta e cole o código.</p>
        <p class="help">Esta tela atualiza sozinha quando você autorizar (até 15 min).</p>
      </div>`}
      ${log.length > 0 && html`<pre class="help">${log.join("\n")}</pre>`}
      <div class="modal-actions"><button onClick=${cancel}>Cancelar</button></div>
    </div>`}
    ${phase === "error" && log.length > 0 && html`<div class="card"><pre class="help">${log.join("\n")}</pre></div>`}
    ${tokenOpen && !flow && html`<div class="card" style="max-width:560px">
      <h3>Token pessoal (alternativa)</h3>
      <p class="help">Use se a organização bloquear o login pelo navegador. Crie em GitHub → Settings → Developer settings →
        Personal access tokens, com acesso aos repositórios que você vai usar. O token fica só na sua pasta no servidor e não é exibido de novo.</p>
      <${Field} label="Token"><${PasswordInput} autocomplete="off" value=${token} onInput=${(e) => setToken(e.target.value)} /><//>
      <div class="modal-actions"><button class="primary" disabled=${busy || token.trim().length < 10} onClick=${saveToken}>Conectar com token</button></div>
    </div>`}
  </div>`;
}
