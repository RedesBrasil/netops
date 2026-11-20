// Language pickers: Minha conta -> Idioma (only for this user) and Configuração -> Idioma da instalação (admin).
// Order: user's choice > instance language. See static/js/i18n.js and core/rules/i18n.md.
import { html, useState, useEffect, api, toast, handleError, refreshMe, t, useLocale } from "./ui.js";
import { loadIndex, loadLocale, languages } from "./i18n.js";

function useLanguages() {
  const [list, setList] = useState(languages());
  const [index, setIndex] = useState(null);
  useEffect(() => { loadIndex().then((idx) => { setIndex(idx); setList(idx.languages || []); }); }, []);
  return { list, index };
}

export function MyLanguageCard({ me }) {
  useLocale();
  const { list, index } = useLanguages();
  const [busy, setBusy] = useState(false);
  const current = (me && me.locale) || "";
  const inst = (me && me.instance_language) || (index && index.instance) || "";
  const instName = (list.find((l) => l.code === inst) || {}).name || inst || "—";
  async function choose(code) {
    if (busy) return;
    setBusy(true);
    try {
      const r = await api.put("/auth/locale", { locale: code });
      await loadLocale(r.effective);
      await refreshMe();
      toast.ok(t("account.language_saved"));
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }
  if (!me || !me.multiuser || me.legacy) return null;
  return html`<div class="card" data-testid="my-language">
    <h3>${t("account.language_title")}</h3>
    <p class="help">${t("account.language_help", { instance: instName })}</p>
    <div class="setup-langs" role="radiogroup" aria-label=${t("common.language")}>
      <button type="button" role="radio" aria-checked=${current === ""} class=${current === "" ? "primary" : ""}
        disabled=${busy} onClick=${() => choose("")}>${t("account.language_follow_instance", { instance: instName })}</button>
      ${list.map((l) => html`<button type="button" role="radio" key=${l.code} aria-checked=${current === l.code}
        class=${current === l.code ? "primary" : ""} disabled=${busy} onClick=${() => choose(l.code)}>${l.name}</button>`)}
    </div>
  </div>`;
}

export function InstanceLanguageCard() {
  useLocale();
  const { list, index } = useLanguages();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (index) setValue(index.instance || ""); }, [index]);
  async function save(code) {
    setBusy(true);
    try {
      await api.put("/config/language", { language: code });
      setValue(code);
      toast.ok(t("settings.language_saved"));
      const me = await refreshMe();
      if (!me || !me.locale) await loadLocale(code);
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }
  return html`<div class="card" data-testid="instance-language">
    <h3>${t("settings.language_title")}</h3>
    <p class="help">${t("settings.language_help")}</p>
    <div class="setup-langs" role="radiogroup" aria-label=${t("common.language")}>
      ${list.map((l) => html`<button type="button" role="radio" key=${l.code} aria-checked=${value === l.code}
        class=${value === l.code ? "primary" : ""} disabled=${busy} onClick=${() => save(l.code)}>${l.name}</button>`)}
    </div>
  </div>`;
}
