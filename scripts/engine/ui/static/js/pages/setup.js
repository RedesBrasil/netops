// Primeiro acesso (#setup?token=...): idioma + conta do admin + cofre, depois a etapa root.
// O instalador não pergunta nada: imprime o link com token de uso único. Sem o token o assistente
// não conclui (services/setup_svc.py). A senha vira a senha-mestra do cofre E a senha do admin.
import { html, useState, useEffect, api, CopyButton, refreshVault, t, useLocale } from "../ui.js";
import { loadLocale } from "../i18n.js";
import { setAuthToken } from "../api.js";
import { PasswordInput } from "../components.js";

export function setupTokenFromHash(hash = location.hash) {
  const m = /^#setup\?(.*)$/.exec(hash || "");
  if (!m) return "";
  return new URLSearchParams(m[1]).get("token") || "";
}

const LANG_LABEL = { en: "English", "pt-BR": "Português" };   // i18n-ok: native language names

export function SetupScreen({ onDone }) {
  useLocale();
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
      if (n > 30) { clearInterval(t); setFinish((f) => ({ ...f, state: "failed", detail: f?.detail || t("setup.root_no_answer") })); }
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
      setErr(e2.message || t("setup.failed"));
    } finally { setBusy(false); }
  }

  async function retry() {
    try { setFinish(await api.post("/setup/finish")); } catch (e2) { setErr(e2.message); }
  }

  if (finish) {
    const ok = finish.state === "done" || finish.state === "not_applicable";
    return html`<div class="login-screen"><div class="login-card setup-card">
      <div class="login-brand">🔧 NetOps — ${t("setup.finishing")}</div>
      ${finish.state === "pending" && html`<p class="help">${t("setup.root_running")}</p>`}
      ${ok && html`<p class="help">✓ ${t("setup.root_done")}</p>`}
      ${finish.state === "failed" && html`<div>
        <p class="err">${t("setup.root_failed", { detail: finish.detail || t("common.unknown") })}</p>
        <p class="help">${t("setup.root_manual")}</p>
        <p class="setup-cmd"><code>${finish.command}</code><${CopyButton} text=${finish.command} /></p>
        <button type="button" onClick=${retry}>${t("common.try_again")}</button>
      </div>`}
      <button type="button" class="primary" disabled=${finish.state === "pending"} onClick=${() => onDone && onDone()}>
        ${t("setup.open_console")}</button>
    </div></div>`;
  }

  return html`<div class="login-screen">
    <form class="login-card setup-card" onSubmit=${submit}>
      <div class="login-brand">🔧 NetOps — ${t("setup.title")}</div>
      ${!token && html`<div class="field">
        <p class="help">${t("setup.token_help")}</p>
        <p class="setup-cmd"><code>sudo -u netops python3 /opt/netops/scripts/engine/users/cli.py setup-link</code></p>
        <label>${t("setup.token_label")}</label>
        <input value=${token} onInput=${(e) => setToken(e.target.value)} autocomplete="off" spellcheck="false" />
      </div>`}
      ${info?.token === "expired" && !token && html`<p class="err">${t("setup.token_expired")}</p>`}
      <div class="field">
        <label>Language / Idioma</label>
        <div class="setup-langs" role="radiogroup">
          ${(info?.languages || [{ code: "en" }, { code: "pt-BR" }]).map((l) => html`
            <button type="button" role="radio" aria-checked=${lang === l.code} class=${lang === l.code ? "primary" : ""}
              onClick=${() => { setLang(l.code); loadLocale(l.code); }}>${l.name || LANG_LABEL[l.code] || l.code}</button>`)}
        </div>
      </div>
      <div class="field"><label>${t("common.name")}</label>
        <input value=${name} onInput=${(e) => setName(e.target.value)} autocomplete="name" maxlength="80" /></div>
      <div class="field"><label>${t("setup.email_label")}</label>
        <input type="email" value=${email} onInput=${(e) => setEmail(e.target.value)} autocomplete="username"
          autocapitalize="none" spellcheck="false" /></div>
      <div class="field"><label>${t("setup.password_label", { min })}</label>
        <${PasswordInput} autocomplete="new-password" value=${pw} onInput=${(e) => setPw(e.target.value)} /></div>
      <div class="field"><label>${t("setup.password_confirm")}</label>
        <${PasswordInput} autocomplete="new-password" value=${pw2} onInput=${(e) => setPw2(e.target.value)} />
        ${pw2 && pw !== pw2 && html`<div class="err">${t("setup.password_mismatch")}</div>`}</div>
      <p class="help">${t("setup.password_help")}</p>
      ${err && html`<div class="err">${err}</div>`}
      <button type="submit" class="primary" disabled=${!ready}>${busy ? t("setup.configuring") : t("setup.finish")}</button>
    </form>
  </div>`;
}
