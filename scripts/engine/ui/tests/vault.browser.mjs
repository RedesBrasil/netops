// Cofre de senhas no navegador: criar item (template Login), revelar segredo, criar template com campo novo
// reutilizável, trancar o cofre (texto continua visível, segredo não abre).
// Uso: NETOPS_E2E_VAULT=<senha fictícia> tests/e2e-env.sh up && NETOPS_E2E_VAULT=... PLAYWRIGHT_MODULE=... \
//      CHROMIUM_EXECUTABLE=... node tests/vault.browser.mjs
import assert from "node:assert/strict";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const BASE = process.env.NETOPS_E2E_URL || "http://127.0.0.1:8771";
const MASTER = process.env.NETOPS_E2E_VAULT;
const SHOTS = process.env.NETOPS_E2E_SHOTS || "";
if (!MASTER) throw Error("Defina NETOPS_E2E_VAULT (mesma senha usada no e2e-env.sh up).");
if (!(await (await fetch(BASE + "/api/config/meta")).json()).isolated_data) throw Error("Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT.");

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
const errors = [];
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); };
const field = (scope, label) => scope.locator(".field", { has: scope.page().locator(`label:text-is("${label}")`) }).locator("input").first();
try {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });

  await page.goto(BASE + "/");
  await page.locator(".login-screen").waitFor();
  await page.locator(".login-card input[type=email]").fill("chefe@empresa.com.br");
  await page.locator(".login-card input[type=password]").fill(MASTER);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.locator(".shell").waitFor();

  await page.getByText("Inventário", { exact: false }).first().click();
  await page.locator('.sidebar a[href="#vault"]').waitFor({ timeout: 8000 });
  const links = await page.locator(".sidebar a").evaluateAll((a) => a.map((x) => [x.getAttribute("href"), x.textContent.trim()]));
  assert.ok(links.some(([h, t]) => h === "#vault" && t.includes("Cofre de senhas")), "menu Cofre de senhas: " + JSON.stringify(links));
  assert.ok(links.some(([h, t]) => h === "#credentials" && t.includes("Credenciais de hosts")), "menu Credenciais de hosts");

  // 1) novo item pelo template Login (padrão)
  await page.goto(BASE + "/#vault/new");
  const modal = page.locator(".modal");
  await modal.waitFor();
  await field(modal, "Título *").fill("Portal Claro");
  await field(modal, "URL").fill("https://claro.example");
  await field(modal, "Usuário *").fill("fulano");
  await field(modal, "Senha * 🔒").fill("s3gr3d0-e2e");
  await shot(page, "01-novo-item");
  await modal.getByRole("button", { name: "Criar", exact: true }).click();
  await page.waitForFunction(() => location.hash === "#vault/portal-claro");
  await page.locator(".modal .vault-row").first().waitFor();
  const view = page.locator(".modal");
  assert.ok((await view.innerText()).includes("fulano"));
  assert.ok(!(await view.innerText()).includes("s3gr3d0-e2e"), "segredo mascarado antes de revelar");
  assert.ok((await view.innerText()).includes("nvault://portal-claro/senha"), "referência para .env/nvault");
  await view.getByRole("button", { name: "👁 Revelar" }).click();
  await page.locator(".modal code", { hasText: "s3gr3d0-e2e" }).waitFor();
  await shot(page, "02-item-revelado");
  await view.getByRole("button", { name: "Fechar", exact: true }).click();
  await page.waitForFunction(() => location.hash === "#vault");
  const row = page.locator("table tbody tr", { hasText: "Portal Claro" });
  assert.ok((await row.innerText()).includes("https://claro.example"), "campo visível na lista");
  assert.ok(!(await row.innerText()).includes("s3gr3d0-e2e"));
  await shot(page, "03-lista");

  // 2) template novo com campo novo (texto) + campo existente (API key)
  await page.goto(BASE + "/#vault/templates/new");
  await modal.waitFor();
  await field(modal, "Nome *").fill("Cloudflare");
  for (const name of ["Zone ID", "API key"]) {
    await modal.getByRole("button", { name: "+ Adicionar campo" }).click();
    await modal.locator(".vault-tpl-row input[list]").last().fill(name);
  }
  const zone = modal.locator(".vault-tpl-row").nth(0);
  await zone.locator("select").selectOption("text");
  await zone.locator("label", { hasText: "visível" }).locator("input").check();
  await modal.locator(".vault-tpl-row").nth(1).locator("label", { hasText: "obrigatório" }).locator("input").check();
  await shot(page, "04-template");
  await modal.getByRole("button", { name: "Criar", exact: true }).click();
  await page.waitForFunction(() => location.hash === "#vault/templates");
  await page.locator("table tbody tr", { hasText: "Cloudflare" }).waitFor();
  await page.goto(BASE + "/#vault/fields");
  const zr = page.locator("table tbody tr", { hasText: "Zone ID" });
  await zr.waitFor();
  assert.ok((await zr.innerText()).includes("Texto"), "campo novo criado como texto e reutilizável");

  // 3) tranca o cofre: texto aparece, segredo não abre
  await page.goto(BASE + "/#vault");
  await page.locator(".vault-page .vault-icon.ok").click();
  await page.locator(".vault-page .vault-icon.locked").waitFor();
  await page.goto(BASE + "/#vault/portal-claro");
  await page.locator(".modal .muted", { hasText: "destranque o cofre" }).waitFor();
  assert.ok((await page.locator(".modal").innerText()).includes("fulano"));
  assert.equal(await page.locator(".modal").getByRole("button", { name: "👁 Revelar" }).count(), 0);
  await shot(page, "05-trancado");

  assert.deepEqual(errors, [], "sem erro de JS no console");
  console.log("OK — Cofre de senhas no navegador");
} finally {
  await browser.close();
}
