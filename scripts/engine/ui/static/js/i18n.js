// Translations for the console (no build step). Catalog = /api/i18n/<lang> (core/locales/<lang>/*.json merged over
// English on the server; see scripts/engine/lib/i18n.py and core/rules/i18n.md).
//
//   t("hosts.delete_confirm", { name })   -> translated text; "{name}" placeholders; missing key -> the key itself
//   t("hosts.count", { count: n })         -> picks "hosts.count_one" / "hosts.count_other" (Intl.PluralRules)
//   fmtDateTime(ts) / fmtDate / fmtTime / fmtNumber -> Intl in the active language
//
// No imports here (node tests load it directly); useLocale() lives in ui.js. Modules that tests load as plain
// source (api.js, claude-errors.js, mentions.js, route.js...) use globalThis.netopsT(key, vars) with a fallback.
//
// Rules: never call t() at module top level (the catalog loads after import) — keep keys in constants and
// translate at render time. Language order: user's choice (Minha conta) > instance language > this browser.
const STORE_KEY = "netops_lang";
let _lang = "";
let _msgs = {};
const _subs = new Set();
const _warned = new Set();

export function lang() { return _lang || "pt-BR"; }
export function catalogLoaded() { return !!_lang; }

export function setCatalog(code, messages) {        // also used by the node tests
  _lang = code; _msgs = messages || {};
  try { globalThis.netopsLang = code; globalThis.netopsT = t; } catch (e) {}
  try { if (typeof document !== "undefined") document.documentElement.lang = code; } catch (e) {}
  _subs.forEach((f) => { try { f(code); } catch (e) {} });
}

export function has(key) { return Object.prototype.hasOwnProperty.call(_msgs, key); }

function pluralKey(key, count) {
  let cat = "other";
  try { cat = new Intl.PluralRules(lang()).select(Number(count)); } catch (e) {}
  if (has(`${key}_${cat}`)) return `${key}_${cat}`;
  if (has(`${key}_other`)) return `${key}_other`;
  return key;
}

export function t(key, vars) {
  const k = vars && vars.count !== undefined ? pluralKey(key, vars.count) : key;
  let msg = _msgs[k];
  if (msg === undefined) {
    if (_lang && !_warned.has(k)) { _warned.add(k); try { console.warn("[i18n] missing key:", k); } catch (e) {} }
    return key;
  }
  if (vars) msg = msg.replace(/\{(\w+)\}/g, (m, name) => (vars[name] !== undefined && vars[name] !== null ? String(vars[name]) : m));
  return msg;
}

// Translate an API error: payload.error = stable code -> "errors.<code>" when the catalog has it.
export function errorText(payload, fallback = "") {
  const code = payload && typeof payload.error === "string" ? payload.error : "";
  if (code && has(`errors.${code}`)) return t(`errors.${code}`, payload.params || payload);
  if (payload && typeof payload.detail === "string" && payload.detail) return payload.detail;
  return fallback || (code ? code : t("common.error"));
}

/* ------------------------------ formatting ------------------------------ */
const toDate = (v) => (v instanceof Date ? v : new Date(typeof v === "number" && v < 1e12 ? v * 1000 : v));
export function fmtDateTime(v, opts) {
  if (v === null || v === undefined || v === "") return "";
  const d = toDate(v); if (isNaN(d)) return String(v);
  return d.toLocaleString(lang(), opts);
}
export function fmtDate(v, opts) {
  if (v === null || v === undefined || v === "") return "";
  const d = toDate(v); if (isNaN(d)) return String(v);
  return d.toLocaleDateString(lang(), opts);
}
export function fmtTime(v, opts) {
  if (v === null || v === undefined || v === "") return "";
  const d = toDate(v); if (isNaN(d)) return String(v);
  return d.toLocaleTimeString(lang(), opts);
}
export function fmtNumber(n, opts) {
  if (n === null || n === undefined || n === "") return "";
  try { return Number(n).toLocaleString(lang(), opts); } catch (e) { return String(n); }
}

/* ------------------------------- loading -------------------------------- */
let _index = null;
export async function loadIndex() {
  if (_index) return _index;
  try { const r = await fetch("/api/i18n"); if (r.ok) _index = await r.json(); } catch (e) {}
  return _index || { languages: [{ code: "en", name: "English" }, { code: "pt-BR", name: "Português" }], instance: null, default: "pt-BR" };
}
export function languages() { return (_index && _index.languages) || []; }

export function supported(code, langs = languages()) {
  if (!code) return "";
  const raw = String(code).replace("_", "-").toLowerCase();
  const list = langs.map((l) => l.code);
  return list.find((c) => c.toLowerCase() === raw) || list.find((c) => c.split("-")[0].toLowerCase() === raw.split("-")[0]) || "";
}

export function browserLang(langs = languages()) {
  const cands = (typeof navigator !== "undefined" && (navigator.languages || [navigator.language])) || [];
  for (const c of cands) { const s = supported(c, langs); if (s) return s; }
  return "en";
}

export function storedLang() { try { return localStorage.getItem(STORE_KEY) || ""; } catch (e) { return ""; } }

export async function loadLocale(code, { remember = true } = {}) {
  const idx = await loadIndex();
  const target = supported(code, idx.languages) || idx.instance || idx.default || "en";
  if (target === _lang && Object.keys(_msgs).length) return target;
  try {
    const r = await fetch("/api/i18n/" + encodeURIComponent(target));
    if (r.ok) { const d = await r.json(); setCatalog(d.lang, d.messages); }
  } catch (e) {}
  if (remember) { try { localStorage.setItem(STORE_KEY, target); } catch (e) {} }
  return target;
}

// Boot: before login we only know this browser's last choice and the instance language.
export async function initI18n({ setup = false } = {}) {
  const idx = await loadIndex();
  const pick = supported(storedLang(), idx.languages) || idx.instance || (setup ? browserLang(idx.languages) : idx.default);
  return loadLocale(pick, { remember: false });
}

// After /auth/me: the user's own language wins, else the instance language.
export async function applyUserLocale(me) {
  const idx = await loadIndex();
  const want = supported(me && me.locale, idx.languages) || (me && me.instance_language) || idx.instance || idx.default;
  if (want && want !== _lang) await loadLocale(want);
  else if (want) { try { localStorage.setItem(STORE_KEY, want); } catch (e) {} }
}

export function onLocaleChange(fn) { _subs.add(fn); return () => _subs.delete(fn); }
