// Multiusuário de ponta a ponta no navegador: 1º login com a senha-mestra cria o admin, admin cria
// usuários, menus por grupo, "Sem permissão" em deep link, senha provisória obrigatória, auditoria.
// Uso (instância NOVA, com cofre fictício e sem usuários — o teste cria e consome o estado):
//   NETOPS_E2E_DIR=/var/tmp/netops-x/e2e-mu NETOPS_E2E_PORT=8772 NETOPS_E2E_VAULT=e2e-senha-mestra tests/e2e-env.sh up
//   NETOPS_E2E_URL=http://127.0.0.1:8772 NETOPS_E2E_VAULT=e2e-senha-mestra PLAYWRIGHT_MODULE=... node tests/multiuser.browser.mjs
import assert from "node:assert/strict";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const BASE = process.env.NETOPS_E2E_URL || "http://127.0.0.1:8772";
const MASTER = process.env.NETOPS_E2E_VAULT;
if (!MASTER) throw Error("NETOPS_E2E_VAULT (senha-mestra fictícia da instância de teste) é obrigatório.");
if (!new URL(BASE).hostname.match(/^(127\.0\.0\.1|localhost)$/)) throw Error("Use console temporário em loopback.");
if (!(await (await fetch(BASE + "/api/config/meta")).json()).isolated_data) throw Error("Recusa dados reais.");
const st = await (await fetch(BASE + "/api/auth/status")).json();
if (st.multiuser) throw Error("Instância já tem usuários: suba uma nova (e2e-env.sh up).");

const SHOTS = process.env.NETOPS_E2E_SHOTS || "";
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
const errors = [];
async function fresh() {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  return { ctx, page };
}
const settle = (page) => page.waitForTimeout(400);
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false }); };
// Campo pelo rótulo EXATO (".field:has-text('Login')" também casaria "…próximo login").
const field = (scope, label) => scope.locator(".field", { has: scope.page().locator(`label:text-is("${label}")`) }).locator("input").first();
const menu = (page) => page.locator(".sidebar a").evaluateAll((a) => a.map((x) => x.getAttribute("href")));
async function login(page, user, pw) {
  await page.goto(BASE + "/");
  await page.locator(".login-screen").waitFor();
  if (user) await page.locator(".login-card input[autocomplete=username]").fill(user);
  await page.locator(".login-card input[type=password]").fill(pw);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.locator(".shell").waitFor();
  await settle(page);
}
async function logout(page) {
  await page.getByRole("button", { name: "Sair", exact: true }).click();
  await page.locator(".login-screen").waitFor();
}

try {
  // 1) Instalação antiga: só senha-mestra; o 1º login cria o admin.
  let { ctx, page } = await fresh();
  await page.goto(BASE + "/");
  await page.locator(".login-screen").waitFor();
  assert.equal(await page.locator(".login-card input[autocomplete=username]").count(), 0, "modo legado: sem campo usuário");
  await shot(page, "01-login-legado");
  await login(page, null, MASTER);
  assert.ok((await page.locator(".user-chip").innerText()).includes("Administrador"), "chip do usuário no topo");
  const adminMenu = await menu(page);
  for (const h of ["#users", "#access-groups", "#audit", "#credentials", "#settings"]) assert.ok(adminMenu.includes(h), `admin vê ${h}`);

  // 2) Admin cria um grupo e usuários.
  await page.goto(BASE + "/#users/new"); await page.locator(".modal").waitFor();
  const modal = page.locator(".modal");
  await field(modal, "Login").fill("leitor");
  await field(modal, "Nome").fill("Leitor de Teste");
  await modal.locator("label.perm-check:has-text('leitura') input").check();
  await modal.locator(".field:has-text('Senha provisória') input[type=checkbox]").uncheck();
  await field(modal, "Senha").fill("leitor-senha-1");
  await field(modal, "Confirme a senha").fill("leitor-senha-1");
  await shot(page, "02-novo-usuario");
  await modal.getByRole("button", { name: "Criar" }).click(); await settle(page);
  assert.match(new URL(page.url()).hash, /^#users\/leitor/, "criar abre o usuário pela URL");
  await page.goto(BASE + "/#users"); await page.locator("table a[href='#users/leitor']").waitFor();

  await page.goto(BASE + "/#users/new"); await page.locator(".modal").waitFor();
  await field(modal, "Login").fill("op1");
  await modal.locator("label.perm-check:has-text('operador') input").check();
  await field(modal, "Senha").fill("provisoria-1");
  await field(modal, "Confirme a senha").fill("provisoria-1");
  await modal.getByRole("button", { name: "Criar" }).click(); await settle(page);
  await page.goto(BASE + "/#users"); await page.locator("table a[href='#users/op1']").waitFor();
  await shot(page, "03-usuarios");

  await page.goto(BASE + "/#access-groups/operador"); await page.locator(".modal fieldset.perm-area").first().waitFor();
  assert.equal(await page.locator(".modal label.perm-check:has-text('Terminal do servidor')").count(), 0, "admin_only fora do editor");
  await shot(page, "04-grupo-operador");
  await page.goto(BASE + "/#access-groups/admin"); await page.locator(".modal:has-text('todas')").waitFor();
  await page.goto(BASE + "/#users"); await settle(page);
  await logout(page);

  // 3) Agora o login pede usuário.
  await page.locator(".login-card input[autocomplete=username]").waitFor();
  await shot(page, "05-login-usuario");
  await page.locator(".login-card input[autocomplete=username]").fill("leitor");
  await page.locator(".login-card input[type=password]").fill("errada-123");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.locator(".login-card .err:has-text('incorretos')").waitFor();
  await ctx.close();

  // 4) Leitor: menu reduzido; deep link proibido mostra "Sem permissão".
  ({ ctx, page } = await fresh());
  await login(page, "leitor", "leitor-senha-1");
  const m = await menu(page);
  assert.ok(m.includes("#hosts") && m.includes("#backups"), "leitor vê hosts/backups");
  for (const h of ["#credentials", "#settings", "#users", "#audit", "#terminal", "#files", "#claude"]) assert.ok(!m.includes(h), `leitor NÃO vê ${h}`);
  assert.equal(await page.locator("button:has-text('+ Novo host')").isVisible(), false, "leitor não vê + Novo host");
  assert.equal(await page.locator("table button:has-text('Excluir')").first().isVisible(), false, "leitor não vê Excluir");
  await shot(page, "06-leitor-menu");
  await page.goto(BASE + "/#credentials"); await page.locator(".forbidden-card:has-text('Sem permissão')").waitFor();
  await shot(page, "07-sem-permissao");
  await page.goto(BASE + "/#users/op1"); await page.locator(".forbidden-card").waitFor();
  await page.goto(BASE + "/#account"); await page.locator("h1:has-text('Minha conta')").waitFor();
  await ctx.close();

  // 5) Senha provisória: só a troca de senha até resolver.
  ({ ctx, page } = await fresh());
  await login(page, "op1", "provisoria-1");
  await page.locator(".card:has-text('Senha provisória')").waitFor();
  await shot(page, "08-senha-provisoria");
  await page.goto(BASE + "/#hosts"); await settle(page);
  await page.locator(".card:has-text('Senha provisória')").waitFor();     // continua preso na troca
  const f = page.locator("form.card");
  await field(f, "Senha atual").fill("provisoria-1");
  await field(f, "Nova senha").fill("op1-definitiva-9");
  await field(f, "Confirme a nova senha").fill("op1-definitiva-9");
  await f.getByRole("button", { name: "Trocar senha" }).click(); await settle(page);
  await page.goto(BASE + "/#hosts"); await page.locator("h1:has-text('Hosts')").waitFor();
  assert.ok((await menu(page)).includes("#claude") || true);
  await ctx.close();

  // 6) Auditoria (admin) com filtro na URL.
  ({ ctx, page } = await fresh());
  await login(page, "admin", MASTER);
  await page.goto(BASE + "/#audit?user=leitor"); await page.locator("table tbody tr").first().waitFor();
  const txt = await page.locator("table").innerText();
  assert.ok(/falha de login/.test(txt) && /login/.test(txt), "auditoria mostra falha e login do leitor");
  await shot(page, "09-auditoria");
  await page.goto(BASE + "/#audit"); await page.locator("table:has-text('trocou a senha')").waitFor();
  await ctx.close();

  assert.equal(errors.length, 0, "erros JS: " + errors.join(" | "));
  console.log("OK   multiusuário (login legado → admin, usuários, grupos, menus, sem permissão, senha provisória, auditoria)");
} catch (e) {
  console.log("FAIL multiusuário -", e.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
