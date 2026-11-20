// Guard for translations (core/rules/i18n.md): catalogs in parity with English, placeholders preserved,
// every literal t("ns.key") used in the console exists in core/locales/en. Hard-coded Portuguese text = warning.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../../../..");
const LOCALES = path.join(REPO, "core", "locales");
const STATIC = path.resolve(HERE, "../static/js");

function flatten(prefix, obj, out) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object") flatten(key, v, out); else if (typeof v === "string") out[key] = v;
  }
  return out;
}
function load(lang) {
  const dir = path.join(LOCALES, lang), out = {};
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith(".json")).sort())
    flatten(f.replace(/\.json$/, ""), JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")), out);
  return out;
}
function languages() {
  const txt = fs.readFileSync(path.join(LOCALES, "_languages.yaml"), "utf8");
  const out = []; let cur = null;
  for (const line of txt.split("\n")) {
    let m = /^\s*-\s*code:\s*(\S+)/.exec(line); if (m) { cur = { code: m[1], status: "partial" }; out.push(cur); continue; }
    m = /^\s*status:\s*(\S+)/.exec(line); if (m && cur) cur.status = m[1];
  }
  return out;
}
const placeholders = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
const EN = load("en");

test("every complete language has exactly the English keys and placeholders", () => {
  for (const l of languages().filter((x) => x.code !== "en")) {
    const cat = load(l.code);
    const missing = Object.keys(EN).filter((k) => !(k in cat));
    const extra = Object.keys(cat).filter((k) => !(k in EN));
    if (l.status === "complete") {
      assert.deepEqual(missing, [], `${l.code}: keys missing (present in en)`);
    } else if (missing.length) console.warn(`[i18n] ${l.code} (partial): ${missing.length} keys fall back to English`);
    assert.deepEqual(extra, [], `${l.code}: keys that do not exist in en`);
    const bad = Object.keys(cat).filter((k) => k in EN && placeholders(cat[k]) !== placeholders(EN[k]));
    assert.deepEqual(bad, [], `${l.code}: placeholders differ from en`);
  }
});

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === "vendor") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out); else if (/\.(js|jsx|mjs)$/.test(e.name) && !/\.test\.mjs$|\.browser\.mjs$|bundle/.test(e.name)) out.push(p);
  }
  return out;
}
const SOURCES = [...walk(STATIC), ...walk(path.resolve(HERE, "../maps")).filter((f) => /editor\.jsx$|\/maps\/[^/]+\.js$/.test(f))];
const exists = (k) => k in EN || `${k}_one` in EN || `${k}_other` in EN;

test("every literal t(key) used in the console exists in core/locales/en", () => {
  const missing = [];
  // complete literal argument only: t("a.b") / t("a.b", vars). Concatenated keys ("nav.group_" + g) are skipped.
  const re = /\b(?:t|netopsT|tr)\(\s*["'`]([a-z][a-z0-9_]*(?:\.[a-z0-9_-]+)+)["'`]\s*[,)]/g;
  for (const f of SOURCES.filter((x) => !x.endsWith("i18n.js"))) {
    const src = fs.readFileSync(f, "utf8");
    for (const m of src.matchAll(re)) if (!exists(m[1])) missing.push(`${path.relative(STATIC, f)}: ${m[1]}`);
  }
  assert.deepEqual(missing, []);
});

// AI-context text (sent to the agent, not shown): the mention/quote notes are matched by text and stay as they are.
const AI_CONTEXT_FILES = new Set(["mentions.js"]);

test("no hard-coded Portuguese text in the console (use t(); exceptions marked // i18n-ok)", () => {
  const accent = /["'`>][^"'`<]*[áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ][^"'`<]*["'`<]/;
  const hits = [];
  for (const f of SOURCES.filter((x) => !AI_CONTEXT_FILES.has(path.basename(x)))) {
    fs.readFileSync(f, "utf8").split("\n").forEach((line, i) => {
      if (line.includes("i18n-ok")) return;
      const code = line.replace(/\/\/.*$/, "").replace(/\/\*.*?\*\//g, "");
      if (/^\s*\*/.test(line) || !accent.test(code)) return;
      if (/\b(?:t|netopsT|tr)\(/.test(code) && !/html`[^`]*[áéíóúâêôãõç]/.test(code)) return;
      hits.push(`${path.relative(STATIC, f)}:${i + 1}`);
    });
  }
  assert.deepEqual(hits, [], "visible text must go through t() (core/rules/i18n.md)");
});
