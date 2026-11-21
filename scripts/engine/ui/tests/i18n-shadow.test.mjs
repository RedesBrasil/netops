// Guard: a file that uses the console translator t() must never declare a parameter/variable named `t`.
// Shadowing turns every t("...") inside that scope into a call on the shadowing value: "t is not a function".
// Real bug (v2.6.1): ToastHost did `list.map((t) => ... t("common.close") ...)` and ANY toast broke the
// screen (e.g. right after creating a project on a fresh install).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.resolve(HERE, "../static/js");

function jsFiles(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== "vendor") out.push(...jsFiles(p)); }
    else if (e.name.endsWith(".js") || e.name.endsWith(".mjs")) out.push(p);
  }
  return out;
}

// Files where the translator `t` is in scope: import { ..., t, ... } from "...", or ui.js/i18n.js themselves.
const usesT = (src, file) => /import\s*\{[^}]*\bt\b[^}]*\}\s*from/.test(src)
  || ["ui.js", "i18n.js"].includes(path.basename(file));

// Declarations that would shadow it: (t) =>, t =>, (a, t) =>, function x(t), const/let/var t =, catch (t)
const SHADOW = [
  /\(\s*(?:[\w$]+\s*,\s*)*t\s*(?:=[^,)]*)?(?:,[^)]*)?\)\s*=>/g,
  /(?:^|[^\w$.])t\s*=>/g,
  /function\s*[\w$]*\s*\(\s*(?:[\w$]+\s*,\s*)*t\s*[,)=]/g,
  /\b(?:const|let|var)\s+t\s*=/g,
  /catch\s*\(\s*t\s*\)/g,
];

test("i18n: no `t` shadowing in files that use the translator t()", () => {
  const bad = [];
  for (const f of jsFiles(STATIC)) {
    const src = fs.readFileSync(f, "utf8");
    if (!usesT(src, f)) continue;
    src.split("\n").forEach((line, i) => {
      const code = line.replace(/\/\/.*$/, "");
      if (SHADOW.some((rx) => { rx.lastIndex = 0; return rx.test(code); }))
        bad.push(`${path.relative(STATIC, f)}:${i + 1}: ${line.trim().slice(0, 120)}`);
    });
  }
  assert.deepEqual(bad, [], "rename the parameter (e.g. `it`) — it shadows the translator t():\n" + bad.join("\n"));
});

test("i18n: the guard catches the original ToastHost bug", () => {
  const sample = 'list.map((t) => html`<button title=${t("common.close")}>`)';
  assert.ok(SHADOW.some((rx) => { rx.lastIndex = 0; return rx.test(sample); }));
});
