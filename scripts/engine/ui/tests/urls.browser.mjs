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
  maps: { custom: async (page, BASE, { assert, settle, hash }) => {
    await page.goto(`${BASE}/#maps`); await page.locator("section.netops-maps").waitFor(); await settle();
    assert.match(hash(), /^#maps\/all/, `maps: #maps normaliza p/ #maps/<id> (${hash()})`);
    await page.goto(`${BASE}/#maps/mapa-inexistente`); await page.locator("section.netops-maps").waitFor(); await settle();
    assert.match(hash(), /^#maps\/all/, `maps: id inexistente cai em all (${hash()})`);
    await page.goto(`${BASE}/#maps/all?host=1`); await page.locator(".modal").first().waitFor();
    assert.ok((await page.locator(".modal").innerText()).includes("RT-CORE-01"), "maps: deep link do host");
    await page.reload(); await page.locator(".modal").first().waitFor();
    await page.goBack(); await settle(); assert.equal(await page.locator(".modal").count(), 0, "maps: Voltar fecha o host");
    await page.goto(`${BASE}/#maps/all?host=9999`); await settle();
    assert.equal(await page.locator(".modal").count(), 0, "maps: host inexistente não abre modal");
  } },
  backups: { row: ".bk-svc a[href^='#backups/services/']", open: ".modal", q: "Servico B", qRows: -1, extra: [
    ["#backups/storage", "a[href^='#backups/storage/']"], ["#backups/storage/1", ".modal:has-text('Backups')"],
    ["#backups/storage/1?file=by-id%2F1%2Fa.rsc", ".modal pre"], ["#backups/services/new", ".modal"]] },
  smoke: { custom: async (page, BASE, { assert, settle, hash }) => {   // todo menu abre sem erro, com URL e item ativo na sidebar
    await page.goto(`${BASE}/#hosts`); await page.locator(".sidebar a").first().waitFor();
    const hrefs = await page.locator(".sidebar a").evaluateAll((a) => a.map((x) => x.getAttribute("href")));
    assert.ok(hrefs.length >= 12, `smoke: ${hrefs.length} menus`);
    for (const h of hrefs) {
      await page.goto(`${BASE}/${h}`); await settle();
      assert.ok(hash().startsWith(h), `smoke: ${h} → ${hash()}`);
      assert.equal(await page.locator(`.sidebar a[href="${h}"].active`).count(), 1, `smoke: ${h} ativo`);
      await page.goto(`${BASE}/${h}/item-inexistente-xyz`); await settle();
      assert.equal(await page.locator(`.sidebar a[href="${h}"].active`).count(), 1, `smoke: ${h}/x ativo`);
    }
  } },
  settings: { custom: async (page, BASE, { assert, settle, hash }) => {
    await page.goto(`${BASE}/#settings`); await page.getByRole("button", { name: /Verificar atualizações/ }).click(); await settle();
    assert.equal(hash(), "#settings/updates"); await page.locator(".modal").first().waitFor();
    await page.reload(); await page.locator(".modal").first().waitFor();
    assert.equal(hash(), "#settings/updates", "settings: F5 mantém painel");
    await page.goBack(); await settle();
    assert.equal(await page.locator(".modal").count(), 0, "settings: Voltar fecha painel");
  } },
  scripts: { row: "table a[href^='#scripts/']", open: ".modal", q: "ssh", qRows: -1, deep: ["#scripts?sort=location&dir=desc", "th:has-text('Pasta'):has-text('▼')"] },
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
    if (c.custom) { await c.custom(page, BASE, { assert, settle, hash }); assert.equal(errors.length, 0, `${menu}: erros JS ${errors}`); console.log("OK  ", menu); await ctx.close(); continue; }
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
    for (const [h, sel] of c.extra || []) { await page.goto(`${BASE}/${h}`); await page.locator(sel).first().waitFor({ timeout: 8000 }).catch(() => { throw Error(`deep link ${h} não abriu ${sel}`); }); }
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
