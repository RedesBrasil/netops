import { mapActions } from "./maps-actions.mjs";
// Executar apenas com NETOPS_UI_DATA_ROOT e fixtures, nunca na rede real.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
const meta = await (await fetch(BASE + '/api/config/meta')).json();
if (!meta.isolated_data) throw Error('Teste recusa dados reais. Inicie com NETOPS_UI_DATA_ROOT.');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
try {
  for (const [mode, options] of [['desktop', { viewport: { width: 1440, height: 950 } }], ['mobile', { ...devices['iPhone 13'] }]]) {
    const context = await browser.newContext(options), page = await context.newPage(), requests = [], errors = [], passed = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/api/topology/links')) requests.push(r.postDataJSON()); });
    const click = async locator => { await locator.scrollIntoViewIfNeeded(); if (mode === 'mobile') await locator.tap(); else await locator.click(); };
    const actions = mapActions(page, mode);
    const description = 'Validação de portas ' + mode + ' ' + Date.now();
    const modal = () => page.locator('.modal');
    const save = () => modal().getByRole('button', { name: 'Salvar', exact: true });
    async function openFromMap() {
      await page.goto(BASE + '/#maps');
      await page.locator('.netops-maps').waitFor();
      await page.waitForTimeout(250);
      await actions.pane('Ligar hosts');
      await click(page.locator('.react-flow__node[data-id="host:rt-core-01"]'));
      await click(page.locator('.react-flow__node[data-id="host:rt-dist-01"]'));
      await modal().waitFor();
    }
    try {
      await openFromMap();
      await page.getByLabel('Velocidade', { exact: true }).fill('10G');
      await page.getByLabel('Descrição', { exact: true }).fill(description);
      assert.equal(await page.locator('#link-ap').getAttribute('required'), null);
      assert.equal(await page.locator('#link-bp').getAttribute('required'), null);
      const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/api/topology/links'));
      await click(save());
      assert.equal((await response).status(), 200);
      await modal().waitFor({ state: 'detached' });
      assert.deepEqual(requests[0].a, { host: 'rt-core-01' });
      assert.deepEqual(requests[0].b, { host: 'rt-dist-01' });
      passed.push('mapa: enlace salva com ambas as interfaces em branco');
      await page.reload();
      await page.locator('.netops-maps').waitFor();
      const snap = await (await context.request.get(BASE + '/api/maps')).json();
      const line = snap.topology.links.find(l => l.desc === description);
      assert.ok(line);
      await page.locator(`[data-line-id="${line.id}"][data-line-part="line"]`).waitFor();
      passed.push('enlace sem interfaces continua visível ao recarregar o mapa');
      await page.screenshot({ path: `/tmp/netops-optional-interfaces-${mode}.png` });

      assert.equal(await page.locator('.sidebar a[href="#topology"]').count(), 0);
      const editExisting = async () => {
        await actions.on(page.locator(`[data-line-id="${line.id}"][data-line-part="line"]`), 'Editar');
        await modal().waitFor();
      };
      await editExisting();
      await page.locator('#link-ap').fill(' ether2 ');
      await page.locator('#link-bp').fill('   ');
      let updated = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().includes('/api/topology/link/'));
      await click(save());
      assert.equal((await updated).status(), 200);
      await modal().waitFor({ state: 'detached' });
      let saved = (await (await context.request.get(BASE + '/api/topology')).json()).links.find(l => l.id === line.id);
      assert.equal(saved.a.port, 'ether2');
      assert.equal(saved.b.port, undefined);
      passed.push('edição aceita interface somente na ponta A e ignora espaços em branco');
      await editExisting();
      await page.locator('#link-ap').fill('');
      updated = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().includes('/api/topology/link/'));
      await page.locator('#link-ap').press('Enter');
      assert.equal((await updated).status(), 200);
      await modal().waitFor({ state: 'detached' });
      saved = (await (await context.request.get(BASE + '/api/topology')).json()).links.find(l => l.id === line.id);
      assert.equal(saved.a.port, undefined);
      assert.equal(saved.b.port, undefined);
      passed.push('edição permite apagar interfaces informadas anteriormente');

      await openFromMap();
      await page.locator('#link-ah').selectOption('');
      await page.locator('#link-bh').selectOption('');
      await click(save());
      assert.equal(await modal().locator('.err').count(), 2);
      assert.equal(await page.locator('#link-ap-error').count(), 0);
      assert.equal(await page.locator('#link-bp-error').count(), 0);
      assert.equal(requests.length, 1);
      await page.getByLabel('Host A *', { exact: true }).selectOption('rt-core-01');
      await page.getByLabel('Host B *', { exact: true }).selectOption('rt-dist-01');
      await page.getByLabel('Descrição', { exact: true }).fill(description + ' mapa');
      const entered = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/api/topology/links'));
      await page.getByLabel('Porta B (opcional)', { exact: true }).press('Enter');
      assert.equal((await entered).status(), 200);
      await modal().waitFor({ state: 'detached' });
      assert.equal(requests.length, 2);
      assert.deepEqual(requests[1].a, { host: 'rt-core-01' });
      assert.deepEqual(requests[1].b, { host: 'rt-dist-01' });
      passed.push('mapa: somente os hosts são obrigatórios, envio sem interfaces com Enter');

      await openFromMap();
      await page.locator('#link-ah').selectOption('rt-core-01');
      await page.locator('#link-bh').selectOption('rt-dist-01');
      await page.locator('#link-ap').fill('ether3');
      await page.locator('#link-bp').fill('ether4');
      const url = '**/api/topology/links';
      await page.route(url, async route => {
        if (route.request().method() !== 'POST') return route.continue();
        await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: [{ loc: ['body', 'a', 'port'], type: 'value_error', msg: 'Interface de teste inválida', input: 'não deve ir para o erro exibido' }] }) });
      });
      await click(save());
      await page.locator('#link-ap-error').getByText('Interface de teste inválida', { exact: true }).waitFor();
      assert.equal(await page.locator('#link-ap').inputValue(), 'ether3');
      assert.ok(!(await modal().innerText()).includes('não deve ir para o erro exibido'));
      await page.unroute(url);
      await click(modal().getByRole('button', { name: 'Cancelar', exact: true }));
      passed.push('rejeição 422 do servidor indica o campo sem perder dados ou exibir input interno');
      assert.deepEqual(errors, []);
      results.push({ mode, status: 'PASS', passed, errors });
    } catch (e) {
      await page.screenshot({ path: `/tmp/netops-link-validation-${mode}-failed.png` });
      results.push({ mode, status: 'FAIL', passed, errors, failure: e.stack });
    }
    await context.close();
  }
} finally { await browser.close(); }
await fs.writeFile('/tmp/netops-link-validation-results.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
if (results.some(r => r.status === 'FAIL')) process.exitCode = 1;
