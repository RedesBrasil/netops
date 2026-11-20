// Primeiro acesso (#setup?token=...): idioma + conta do admin + cofre, depois a etapa root.
// O instalador não pergunta nada: imprime o link com token de uso único. Sem o token o assistente
// não conclui (services/setup_svc.py). A senha vira a senha-mestra do cofre E a senha do admin.
import { html, useState, useEffect, api, CopyButton, refreshVault } from "../ui.js";
import { setAuthToken } from "../api.js";
import { PasswordInput } from "../components.js";

export function setupTokenFromHash(hash = location.hash) {
  const m = /^#setup\?(.*)$/.exec(hash || "");
  if (!m) return "";
  return new URLSearchParams(m[1]).get("token") || "";
}

const LANG_LABEL = { en: "English", "pt-BR": "Português" };

export function SetupScreen({ onDone }) {
  const [info, setInfo] = useState(null);
  const [token, setToken] = useState(setupTokenFromHash());
  const [lang, setLang] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [finish, setFinish] = useState(null);   // depois de concluir: estado da etapa root

  useEffect(() => { api.get("/setup/status").then(setInfo).catch(() => setInfo({})); }, []);
  useEffect(() => {
    const h = () => { const t = setupTokenFromHash(); if (t) setToken(t); };
    addEventListener("hashchange", h);
    return () => removeEventListener("hashchange", h);
  }, []);

  // Etapa root: acompanha até concluir (a unidade root costuma terminar em 1-3 s).
  useEffect(() => {
    if (!finish || !["pending"].includes(finish.state)) return;
    let n = 0;
    const t = setInterval(async () => {
      n += 1;
      try { const s = await api.get("/setup/finish"); setFinish(s); if (s.state !== "pending") clearInterval(t); }
      catch { /* segue tentando */ }
      if (n > 30) { clearInterval(t); setFinish((f) => ({ ...f, state: "failed", detail: f?.detail || "sem resposta da etapa root" })); }
    }, 2000);
    return () => clearInterval(t);
  }, [finish && finish.state]);

  const min = info?.password_min || 8;
  const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  const pwOk = pw.length >= min && pw === pw2;
  const ready = !!token && !!lang && emailOk && pwOk && !busy;

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true); setErr("");
    try {
      const r = await api.post("/setup/complete", { token: token.trim(), language: lang, name: name.trim(),
        email: email.trim().toLowerCase(), password: pw });
      setPw(""); setPw2("");
      setAuthToken(r.auth_token);
      history.replaceState(null, "", location.pathname + location.search);   // tira o token da URL
      await refreshVault();
      const f = r.finish || { state: "not_applicable" };
      if (f.state === "not_applicable" || f.state === "done") { onDone && onDone(); return; }
      setFinish(f);
    } catch (e2) {
      setErr(e2.payload?.detail || e2.message || "Falha ao concluir.");
    } finally { setBusy(false); }
  }

  async function retry() {
    try { setFinish(await api.post("/setup/finish")); } catch (e2) { setErr(e2.payload?.detail || e2.message); }
  }

  if (finish) {
    const ok = finish.state === "done" || finish.state === "not_applicable";
    return html`<div class="login-screen"><div class="login-card setup-card">
      <div class="login-brand">🔧 NetOps — finalizando</div>
      ${finish.state === "pending" && html`<p class="help">Ativando o sudo pelo cofre e o host Local (etapa de root)…</p>`}
      ${ok && html`<p class="help">✓ Pronto: sudo pelo cofre e host Local configurados.</p>`}
      ${finish.state === "failed" && html`<div>
        <p class="err">A etapa de root não terminou: ${finish.detail || "motivo desconhecido"}.</p>
        <p class="help">O console já funciona. Para ativar o sudo pelo cofre e o host Local, rode uma vez no servidor:</p>
        <p class="setup-cmd"><code>${finish.command}</code><${CopyButton} text=${finish.command} /></p>
        <button type="button" onClick=${retry}>Tentar de novo</button>
      </div>`}
      <button type="button" class="primary" disabled=${finish.state === "pending"} onClick=${() => onDone && onDone()}>
        Abrir o console</button>
    </div></div>`;
  }

  return html`<div class="login-screen">
    <form class="login-card setup-card" onSubmit=${submit}>
      <div class="login-brand">🔧 NetOps — primeiro acesso</div>
      ${!token && html`<div class="field">
        <p class="help">Abra o link que o instalador mostrou (ele traz o código). Perdeu? Gere outro no servidor:</p>
        <p class="setup-cmd"><code>sudo -u netops python3 /opt/netops/scripts/engine/users/cli.py setup-link</code></p>
        <label>Código do link</label>
        <input value=${token} onInput=${(e) => setToken(e.target.value)} autocomplete="off" spellcheck="false" />
      </div>`}
      ${info?.token === "expired" && !token && html`<p class="err">O link anterior expirou: gere outro.</p>`}
      <div class="field">
        <label>Language / Idioma</label>
        <div class="setup-langs" role="radiogroup">
          ${(info?.languages || [{ code: "en" }, { code: "pt-BR" }]).map((l) => html`
            <button type="button" role="radio" aria-checked=${lang === l.code} class=${lang === l.code ? "primary" : ""}
              onClick=${() => setLang(l.code)}>${l.name || LANG_LABEL[l.code] || l.code}</button>`)}
        </div>
      </div>
      <div class="field"><label>Nome</label>
        <input value=${name} onInput=${(e) => setName(e.target.value)} autocomplete="name" maxlength="80" /></div>
      <div class="field"><label>E-mail do administrador (seu login)</label>
        <input type="email" value=${email} onInput=${(e) => setEmail(e.target.value)} autocomplete="username"
          autocapitalize="none" spellcheck="false" /></div>
      <div class="field"><label>Senha (mínimo ${min} caracteres)</label>
        <${PasswordInput} autocomplete="new-password" value=${pw} onInput=${(e) => setPw(e.target.value)} /></div>
      <div class="field"><label>Confirme a senha</label>
        <${PasswordInput} autocomplete="new-password" value=${pw2} onInput=${(e) => setPw2(e.target.value)} />
        ${pw2 && pw !== pw2 && html`<div class="err">As senhas não conferem.</div>`}</div>
      <p class="help">Essa senha é o seu login e também a senha-mestra do cofre (protege as senhas dos
        equipamentos). Guarde bem: não há como recuperá-la.</p>
      ${err && html`<div class="err">${err}</div>`}
      <button type="submit" class="primary" disabled=${!ready}>${busy ? "Configurando…" : "Concluir"}</button>
    </form>
  </div>`;
}
