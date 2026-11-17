import assert from "node:assert/strict";
import test from "node:test";
const { findLinks, registerTermLinks } = await import("../static/js/term-links.js");
const urls = (s) => findLinks(s).map((l) => l.url);

test("URLs completas, sem pontuação colada", () => {
  assert.deepEqual(urls("veja https://example.com/a?b=1&c=2). ok"), ["https://example.com/a?b=1&c=2"]);
  assert.deepEqual(urls("(http://x.org/p_(1))"), ["http://x.org/p_(1)"]);
  assert.deepEqual(urls("www.redesbrasil.com.br, e ftp://h/f"), ["https://www.redesbrasil.com.br", "ftp://h/f"]);
});

test("ip:porta -> http, ou https nas portas seguras", () => {
  assert.deepEqual(urls("Listen 10.8.200.3:8006 e 10.0.0.1:8080/admin"), ["https://10.8.200.3:8006", "http://10.0.0.1:8080/admin"]);
  assert.deepEqual(urls("[2001:db8::1]:443"), ["https://[2001:db8::1]:443"]);
  assert.equal(findLinks("10.8.200.3:8006")[0].text, "10.8.200.3:8006");
});

test("não linka o que não é ip:porta útil", () => {
  assert.deepEqual(urls("10.0.0.1 port 22; 10.0.0.1/24; 999.1.1.1:80; 1.2.3.4:99999; 1.2.3.4.5:80"), []);
  assert.deepEqual(urls("0.0.0.0:22 127.0.0.1:8080 [::1]:80"), []);
  assert.deepEqual(urls("ip 10.0.0.1:22: erro"), ["http://10.0.0.1:22"]);
});

test("URL com ip:porta não duplica", () => {
  assert.equal(findLinks("http://10.0.0.5:3000/x").length, 1);
});

// Buffer falso do xterm: duas linhas "quebradas" (wrap) e uma célula larga.
function fakeTerm(rows) {
  const lines = rows.map(({ s, wrapped }) => ({
    isWrapped: !!wrapped, length: s.length,
    getCell: (x) => ({ getWidth: () => 1, getChars: () => s[x] ?? "" }),
  }));
  let provider;
  return { buffer: { active: { getLine: (i) => lines[i] } }, registerLinkProvider: (p) => { provider = p; }, get p() { return provider; } };
}
test("provider acha link que atravessa linhas quebradas", () => {
  const t = fakeTerm([{ s: "ver http://exa" }, { s: "mple.com/x ok", wrapped: true }]);
  registerTermLinks(t, () => {});
  for (const y of [1, 2]) {
    let got; t.p.provideLinks(y, (l) => { got = l; });
    assert.equal(got.length, 1);
    assert.deepEqual(got[0].range, { start: { x: 5, y: 1 }, end: { x: 10, y: 2 } });
    assert.equal(got[0].text, "http://example.com/x");
  }
});
