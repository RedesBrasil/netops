import assert from "node:assert/strict";
import test from "node:test";
const { colorize, createHighlighter } = await import("../static/js/term-highlight.js");
const E = "\x1b";
const strip = (s) => s.replace(/\x1b\[[0-9;]*m/g, "");

test("pinta IP, MAC, erros, avisos e OK (estilo MobaXterm)", () => {
  const out = colorize("inet 10.0.0.11  netmask 255.255.255.0 ether bc:24:11:f6:ca:f9 RX errors 0 WARNING ok");
  assert.ok(out.includes(`${E}[95m10.0.0.11${E}[39m`));
  assert.ok(out.includes(`${E}[95mbc:24:11:f6:ca:f9${E}[39m`));
  assert.ok(out.includes(`${E}[91merrors${E}[39m`));
  assert.ok(out.includes(`${E}[93mWARNING${E}[39m`));
  assert.ok(out.includes(`${E}[92mok${E}[39m`));
  assert.ok(colorize("10.0.0.0/24").includes("10.0.0.0/24" + E));
  assert.equal(colorize("versão 1.2.3.4.5 e 999.1.1.1"), "versão 1.2.3.4.5 e 999.1.1.1");
  assert.equal(colorize("terror okay"), "terror okay");
});

test("não mexe em texto que já vem colorido nem em tela cheia", () => {
  const h = createHighlighter();
  const colored = `${E}[32m10.0.0.1 ok${E}[0m depois 10.0.0.2\n`;
  const out = h.feed(colored) + h.flush();
  assert.ok(out.startsWith(`${E}[32m10.0.0.1 ok${E}[0m`));
  assert.ok(out.includes(`${E}[95m10.0.0.2${E}[39m`));
  const alt = h.feed(`${E}[?1049h 10.0.0.3 ${E}[?1049l 10.0.0.4\n`);
  assert.ok(alt.includes(" 10.0.0.3 ") && alt.includes(`${E}[95m10.0.0.4`));
});

test("IP partido entre dois pacotes e escape partido", () => {
  const h = createHighlighter();
  let out = h.feed("inet 10.0.0");
  assert.equal(out, "inet ");
  out += h.feed(".11 netmask\n");
  assert.ok(out.includes(`${E}[95m10.0.0.11${E}[39m`));
  const h2 = createHighlighter();
  let o2 = h2.feed(`a${E}[3`); o2 += h2.feed(`2mverde${E}[0m 1.1.1.1\n`);
  assert.equal(strip(o2), "averde 1.1.1.1\n");
  assert.ok(o2.includes(`${E}[32mverde`));
  const h3 = createHighlighter();
  assert.equal(h3.feed("l") + h3.flush(), "l");       // eco de tecla sai no flush
});
