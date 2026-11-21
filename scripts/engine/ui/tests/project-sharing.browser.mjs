// Project sharing end to end in the browser: private by default, Share page (users + groups, levels),
// view-only member, level change, deep links. Needs a NEW isolated console with login and the Claude tab on:
//   NETOPS_E2E_DIR=/var/tmp/netops-x/e2e NETOPS_E2E_PORT=8773 NETOPS_E2E_VAULT=e2e-senha-mestra tests/e2e-env.sh up
//   (then restart that instance with --enable-claude)
//   NETOPS_E2E_URL=http://127.0.0.1:8773 NETOPS_E2E_VAULT=e2e-senha-mestra PLAYWRIGHT_MODULE=... node tests/project-sharing.browser.mjs
import assert from "node:assert/strict";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const BASE = process.env.NETOPS_E2E_URL || "http://127.0.0.1:8773";
const MASTER = process.env.NETOPS_E2E_VAULT;
if (!MASTER) throw Error("NETOPS_E2E_VAULT is required.");
if (!new URL(BASE).hostname.match(/^(127\.0\.0\.1|localhost)$/)) throw Error("Use a temporary loopback console.");
const meta = await (await fetch(BASE + "/api/config/meta")).json();
if (!meta.isolated_data) throw Error("Refusing real data.");
if (!meta.claude_enabled) throw Error("Start the instance with --enable-claude.");
const SHOTS = process.env.NETOPS_E2E_SHOTS || "";

async function call(token, method, path, body) {
  const r = await fetch(BASE + "/api" + path, { method, headers: { "Content-Type": "application/json", ...(token ? { "X-Netops-Session": token } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const txt = await r.text();
  let data = null; try { data = JSON.parse(txt); } catch (_) { data = txt; }
  return { status: r.status, data };
}
const login = async (body) => { const r = await call("", "POST", "/auth/login", body); assert.equal(r.status, 200, JSON.stringify(r.data)); return r.data.auth_token; };

const admin = await login({ master_password: MASTER });
assert.equal((await call(admin, "POST", "/access-groups", { name: "dev", permissions: ["claude.use", "projects.files", "projects.create"] })).status, 201);
for (const u of ["ana", "bia"]) {
  const r = await call(admin, "POST", "/users", { email: `${u}@empresa.com.br`, username: u, display_name: u === "ana" ? "Ana Souza" : "Bia Lima",
    password: "senha-forte-1", groups: ["dev"], must_change_password: false });
  assert.equal(r.status, 201, JSON.stringify(r.data));
}
const ana = await login({ email: "ana@empresa.com.br", password: "senha-forte-1" });
const bia = await login({ email: "bia@empresa.com.br", password: "senha-forte-1" });
const base = (await call(admin, "GET", "/projects")).data.default_base;
const created = await call(admin, "POST", "/projects", { name: "Site Teste", path: base, new_folder: "site-teste" });
assert.equal(created.status, 200, JSON.stringify(created.data));
const PID = created.data.id;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
const errors = [];
async function as(token) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  await ctx.addInitScript((tk) => { try { localStorage.setItem("netops_auth", tk); } catch (_) {} }, token);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  return { ctx, page };
}
const settle = (page) => page.waitForTimeout(500);
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); };

try {
  // 1) private by default: Ana does not see it (list, sidebar, deep link)
  let A = await as(ana);
  await A.page.goto(BASE + "/#projects"); await settle(A.page);
  assert.ok(!(await A.page.locator(".pj-row").count()), "ana sees no project");
  await A.page.goto(BASE + "/#projects/" + PID); await settle(A.page);
  assert.ok((await A.page.locator(".card").first().innerText()).length > 0);
  assert.ok(!(await A.page.getByRole("button", { name: /Entrar como administrador/ }).count()), "non-admin has no override");

  // 2) owner opens the project and the Share page (deep link + button)
  const O = await as(admin);
  await O.page.goto(BASE + "/#projects/" + PID); await settle(O.page);
  assert.ok((await O.page.locator(".pj-share-line").innerText()).includes("Privado"), "private badge");
  await O.page.getByRole("link", { name: /Compartilhar/ }).first().click(); await settle(O.page);
  assert.ok(O.page.url().endsWith("#projects/" + PID + "/share"), "share URL: " + O.page.url());
  await shot(O.page, "01-share-empty");
  // add Ana (user) and the dev group, both as View
  const search = O.page.getByPlaceholder("Digite nome, usuário ou grupo…");
  await search.click(); await search.fill("ana"); await O.page.waitForTimeout(500);
  await O.page.locator(".pj-share-opt", { hasText: "Ana Souza" }).click();
  await search.fill("dev"); await O.page.waitForTimeout(500);
  await O.page.locator(".pj-share-opt", { hasText: "dev" }).click();
  await O.page.locator(".pj-share-add select").selectOption("view");
  await O.page.getByRole("button", { name: "Adicionar", exact: true }).click(); await settle(O.page);
  assert.equal(await O.page.locator(".pj-share tbody tr").count(), 2, "two rows (user + group)");
  assert.ok(await O.page.getByText("Alterações não salvas").first().isVisible(), "dirty marker");
  await shot(O.page, "02-share-draft");
  await O.page.getByRole("button", { name: "Salvar alterações" }).click(); await settle(O.page);
  const sh = (await call(admin, "GET", `/projects/${PID}/shares`)).data;
  assert.deepEqual(sh.users.map((u) => [u.username, u.level]), [["ana", "view"]]);
  assert.deepEqual(sh.groups.map((g) => [g.name, g.level]), [["dev", "view"]]);
  // effective tab (URL param)
  await O.page.getByRole("tab", { name: /Quem tem acesso/ }).click(); await settle(O.page);
  assert.ok(O.page.url().includes("tab=effective"), "effective tab in the URL");
  const eff = await O.page.locator(".pj-share tbody").innerText();
  assert.ok(eff.includes("Ana Souza") && eff.includes("Bia Lima") && eff.includes("grupo dev"), "effective list: " + eff);
  await shot(O.page, "03-share-effective");

  // 3) Ana (view) sees it, cannot start a conversation nor share
  await A.page.goto(BASE + "/#projects"); await settle(A.page);
  assert.equal(await A.page.locator(".pj-row").count(), 1, "ana sees the shared project");
  assert.ok((await A.page.locator(".pj-row").innerText()).includes("Ver"), "level badge");
  await A.page.goto(BASE + "/#projects/" + PID); await settle(A.page);
  assert.ok(await A.page.getByRole("button", { name: "Nova sessão" }).or(A.page.getByRole("button", { name: /Nova/ })).first().isDisabled(), "new session disabled");
  assert.equal(await A.page.getByRole("link", { name: /Compartilhar/ }).count(), 0, "no share button for view");
  await shot(A.page, "04-ana-view");
  assert.equal((await A.page.request.get(BASE + `/api/projects/${PID}/shares`, { headers: { "X-Netops-Session": ana } })).status(), 403);

  // 4) owner raises Ana to Participate on the table; Ana can start a conversation
  await O.page.getByRole("tab", { name: /Membros/ }).click(); await settle(O.page);
  await O.page.getByLabel("Nível de Ana Souza").selectOption("participate");
  await O.page.getByRole("button", { name: "Salvar alterações" }).click(); await settle(O.page);
  await A.page.reload(); await settle(A.page);
  assert.ok(await A.page.getByRole("link", { name: /Nova/ }).first().isVisible(), "new session link for participate");
  // Bia only through the group = view
  const B = await as(bia);
  await B.page.goto(BASE + "/#projects"); await settle(B.page);
  assert.ok((await B.page.locator(".pj-row").innerText()).includes("Ver"));

  // 5) removing the group: Bia loses it, Ana keeps it
  await O.page.locator(".pj-share tbody tr", { hasText: "dev" }).getByRole("button").click();
  await O.page.getByRole("button", { name: "Salvar alterações" }).click(); await settle(O.page);
  await B.page.reload(); await settle(B.page);
  assert.equal(await B.page.locator(".pj-row").count(), 0, "bia lost access");
  await shot(O.page, "05-share-final");

  // 6) filters in the URL
  await A.page.goto(BASE + "/#projects?filter=mine"); await settle(A.page);
  assert.equal(await A.page.locator(".pj-row").count(), 0, "ana owns nothing");
  await A.page.goto(BASE + "/#projects?filter=shared"); await settle(A.page);
  assert.equal(await A.page.locator(".pj-row").count(), 1);

  assert.deepEqual(errors, [], "page errors: " + errors.join(" | "));
  console.log("project-sharing.browser: OK");
} finally {
  await browser.close();
}
