import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const src = readFileSync(new URL("../static/js/route.js", import.meta.url), "utf8")
  .replace(/^import .*$/m, "const useState=()=>{},useEffect=()=>{};");
const r = await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"));

test("parse: menu, item e filtros", () => {
  assert.deepEqual(r.parseRoute("#hosts/rt%20core?vendor=mikrotik&q=a"),
    { menu: "hosts", segments: ["rt core"], params: { vendor: "mikrotik", q: "a" } });
  assert.deepEqual(r.parseRoute(""), { menu: "", segments: [], params: {} });
  assert.equal(r.parseRoute("#hosts/%ZZ").segments[0], "%ZZ");
});
test("build: omite vazios e é ida-e-volta; itens diferentes => URLs diferentes", () => {
  assert.equal(r.buildRoute({ menu: "hosts", params: { q: "", vendor: "" } }), "#hosts");
  const a = r.buildRoute({ menu: "hosts", segments: ["a"] }), b = r.buildRoute({ menu: "hosts", segments: ["b"] });
  assert.notEqual(a, b);
  const h = r.buildRoute({ menu: "hosts", segments: ["x y"], params: { q: "c&d" } });
  assert.deepEqual(r.parseRoute(h), { menu: "hosts", segments: ["x y"], params: { q: "c&d" } });
});
