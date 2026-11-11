// URLs de navegação (core/rules/urls-navegacao.md): item aberto e filtros têm URL; deep link e Voltar funcionam.
// Uso: tests/e2e-env.sh up && PLAYWRIGHT_MODULE=... CHROMIUM_EXECUTABLE=... node tests/urls.browser.mjs [menu ...]
import assert from "node:assert/strict";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const BASE = process.env.NETOPS_E2E_URL || "http://127.0.0.1:8771";
if (!(await (await fetch(BASE + "/api/config/meta")).json()).isolated_data) throw Error("Recusa dados reais.");

// openSel = elemento que prova "item aberto"; row = link que abre o item; q = termo de busca que filtra; filter = [selectLabel, valor]
const CASES = {
  hosts: { row: "table a[href^='#hosts/']", open: ".modal", q: "SW-ACESSO", qRows: 1, filter: ["Vendor", null] },
  groups: { row: "table a[href^='#groups/']", open: ".modal", q: "linux", qRows: 1 },
  practices: { row: "table a[href^='#practices/']", open: ".modal", q: "zzzz-sem-resultado", qRows: 0 },
  configs: { row: "table a[href^='#configs/']", open: ".modal", q: "zzzz-sem-resultado", qRows: 0 },
  workflows: { row: "table a[href^='#workflows/']", open: ".modal", q: "zzzz-sem-resultado", qRows: 0 },
  agents: { row: "table a[href^='#agents/']", open: ".modal", q: "zzzz-sem-resultado", qRows: 0 },
  credentials: { row: "table a[href^='#credentials/']", open: ".modal", q: "demo", qRows: 1, deep: ["#credentials/cred_demo/password", ".modal:has-text('Definir password')"] },
  reports: { row: "table a[href^='#reports/']", open: ".modal", q: "b.md", qRows: 1 },
  runs: { row: "table a[href^='#runs/']", open: ".modal", q: "run-b", qRows: 1 },
};
const want = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(CASES);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
let failed = 0;
for (const menu of want) {
  const c = CASES[menu]; if (!c) { console.log("sem caso:", menu); failed++; continue; }
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } }), page = await ctx.newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  const hash = () => new URL(page.url()).hash;
  const settle = () => page.waitForTimeout(300);
  try {
    await page.goto(`${BASE}/#${menu}`); await page.locator(c.row).first().waitFor();
    // 1) itens diferentes => URLs diferentes
    const hrefs = await page.locator(c.row).evaluateAll((a) => [...new Set(a.map((x) => x.getAttribute("href")))]);
    assert.ok(hrefs.length >= (menu === "hosts" ? 3 : 1), `${menu}: links de item (${hrefs.length})`);
    // 2) abrir item muda a URL
    await page.locator(c.row).first().click(); await settle();
    assert.equal(hash(), hrefs[0], `${menu}: URL do item`);
    await page.locator(c.open).first().waitFor();
    // 3) deep link: reload mantém o item aberto
    await page.reload(); await page.locator(c.open).first().waitFor();
    assert.equal(hash(), hrefs[0], `${menu}: URL após F5`);
    // 4) Voltar fecha o item
    await page.goBack(); await settle();
    assert.equal(hash(), `#${menu}`, `${menu}: Voltar`);
    assert.equal(await page.locator(c.open).count(), 0, `${menu}: modal fechou`);
    // 5) segundo item => URL diferente
    if (hrefs.length > 1) { await page.goto(`${BASE}/${hrefs[1]}`); await page.locator(c.open).first().waitFor(); assert.notEqual(hash(), hrefs[0]); }
    // 6) item inexistente não quebra a tela
    await page.goto(`${BASE}/#${menu}/nao-existe-xyz`); await settle();
    assert.equal(errors.length, 0, `${menu}: erros JS ${errors}`);
    if (c.deep) { await page.goto(`${BASE}/${c.deep[0]}`); await page.locator(c.deep[1]).first().waitFor(); }
    // 7) filtro na URL
    await page.goto(`${BASE}/#${menu}`); await page.locator(c.row).first().waitFor();
    await page.locator("input[type=search]").fill(c.q); await settle();
    assert.ok(hash().includes("q="), `${menu}: q na URL (${hash()})`);
    await page.reload(); await settle();
    assert.equal(await page.locator("input[type=search]").inputValue(), c.q, `${menu}: q restaurado`);
    if (c.qRows >= 1) assert.equal(await page.locator("table tbody tr").count(), c.qRows, `${menu}: linhas filtradas`);
    await page.getByRole("button", { name: "Limpar filtros" }).click(); await settle();
    assert.equal(hash(), `#${menu}`, `${menu}: limpar filtros limpa URL`);
    // 8) filtro select na URL (primeiro select com opções)
    const sel = page.locator(".filter-bar select, .toolbar select").first();
    if (await sel.count()) {
      const val = await sel.locator("option").nth(1).getAttribute("value");
      if (val) { await sel.selectOption(val); await settle(); assert.ok(/[?&][a-z]+=/.test(hash()), `${menu}: select na URL`); await page.reload(); await settle(); assert.equal(await sel.inputValue(), val); }
    }
    assert.equal(errors.length, 0, `${menu}: erros JS ${errors}`);
    console.log("OK  ", menu);
  } catch (e) { failed++; console.log("FAIL", menu, "-", e.message); }
  await ctx.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
