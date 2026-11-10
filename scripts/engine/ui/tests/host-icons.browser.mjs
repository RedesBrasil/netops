import { mapActions } from "./maps-actions.mjs";
// Cadastro e edição reais com biblioteca local. Nunca executar contra dados de produção.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
if (!(await (await fetch(BASE + '/api/config/meta')).json()).isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT.');
const catalog = (await (await fetch(BASE + '/api/meta/icons')).json()).icons;
assert.equal(catalog.length, 10);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
try {
  for (const [mode, options] of [['desktop', { viewport: { width: 1440, height: 950 } }], ['mobile', { ...devices['iPhone 13'] }]]) {
    const context = await browser.newContext(options), page = await context.newPage(), errors = [], external = [], passed = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (!r.url().startsWith(BASE) && !r.url().startsWith('data:')) external.push(r.url()); });
    const click = async locator => { await locator.scrollIntoViewIfNeeded(); if (mode === 'mobile') await locator.tap(); else await locator.click(); };
    const actions = mapActions(page, mode);
    const modal = () => page.locator('.modal');
    const field = label => modal().locator('.field').filter({ has: page.locator('label').filter({ hasText: label }) });
    const node = id => page.locator(`.react-flow__node[data-id="host:${id}"]`);
    const maps = async () => { await click(page.locator('.sidebar a[href="#maps"]')); await page.locator('.netops-maps').waitFor(); };
    async function fillHost(id) {
      await field('ID (identificador').locator('input').fill(id);
      await field('Hostname').locator('input').fill(id.toUpperCase());
      await field('IP de gerência').locator('input').fill('192.0.2.70');
      await field('Grupo (herança').locator('select').selectOption('linux-servers');
    }
    async function expectIcon(id, file) {
      const image = node(id).locator('img.device-icon-image');
      await image.waitFor();
      assert.ok((await image.getAttribute('src')).endsWith('/' + file + '.png'));
      await page.waitForFunction(id => { const img = document.querySelector(`.react-flow__node[data-id="host:${id}"] img`); return img?.complete && img.naturalWidth > 0; }, id);
    }
    try {
      await page.goto(BASE + '/#maps');
      await page.locator('.netops-maps').waitFor();
      await actions.pane('Adicionar host');
      await page.getByRole('group', { name: 'Escolher ícone do host', exact: true }).waitFor();
      const picker = page.locator('.host-icon-picker');
      await picker.getByRole('button', { name: 'Ícone VMware', exact: true }).waitFor();
      assert.equal(await picker.locator('.host-icon-option').count(), 11);
      for (const icon of catalog) {
        const option = picker.getByRole('button', { name: 'Ícone ' + icon.name, exact: true });
        await click(option);
        assert.equal(await option.getAttribute('aria-pressed'), 'true');
        const image = option.locator('img');
        await page.waitForFunction(url => [...document.querySelectorAll('.host-icon-option img')].some(img => img.src === location.origin + url && img.complete && img.naturalWidth > 0), icon.url);
      }
      await click(picker.getByRole('button', { name: 'Ícone Roteador', exact: true }));
      await picker.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `/tmp/netops-host-icons-picker-${mode}.png` });
      passed.push('10 miniaturas locais selecionáveis, com rótulo e estado acessíveis');
      const fromMap = `icon-map-${mode}-${Date.now()}`;
      await fillHost(fromMap);
      await click(modal().getByRole('button', { name: 'Criar', exact: true }));
      await modal().waitFor({ state: 'detached' });
      await expectIcon(fromMap, 'router');
      const created = await (await context.request.get(BASE + '/api/hosts/' + fromMap)).json();
      assert.equal(created.explicit.icon, 'router');
      passed.push('cadastro pelo mapa grava o ícone no host e exibe a imagem');
      await page.waitForTimeout(300);
      const before = (await (await context.request.get(BASE + '/api/maps')).json()).maps.find(m => m.id === 'all').positions[fromMap];
      const box = await node(fromMap).boundingBox(), x = box.x + box.width / 2, y = box.y + box.height / 2;
      if (mode === 'mobile') {
        const touch = await context.newCDPSession(page);
        await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 0 }] });
        for (let i = 1; i <= 14; i++) {
          await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x + 32 * i / 14, y: y + 32 * i / 14, id: 0 }] });
          await page.waitForTimeout(20);
        }
        await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        await touch.detach();
      } else {
        await page.mouse.move(x, y); await page.mouse.down();
        await page.mouse.move(x + 32, y + 32, { steps: 14 }); await page.mouse.up();
      }
      await page.waitForTimeout(250);
      const moved = (await (await context.request.get(BASE + '/api/maps')).json()).maps.find(m => m.id === 'all').positions[fromMap];
      assert.notDeepEqual(moved, before);
      await expectIcon(fromMap, 'router');
      assert.equal(await node(fromMap).evaluate(el => getComputedStyle(el).visibility), 'visible');
      passed.push('host com imagem continua arrastável e visível após autosave');

      await click(page.locator('.sidebar a[href="#hosts"]'));
      await click(page.getByRole('cell', { name: fromMap, exact: true }));
      await picker.getByRole('button', { name: 'Ícone Roteador', exact: true }).waitFor();
      assert.equal(await picker.getByRole('button', { name: 'Ícone Roteador', exact: true }).getAttribute('aria-pressed'), 'true');
      await click(picker.getByRole('button', { name: 'Ícone OLT', exact: true }));
      await click(modal().getByRole('button', { name: 'Salvar', exact: true }));
      await modal().waitFor({ state: 'detached' });
      await maps(); await expectIcon(fromMap, 'olt');
      await page.reload(); await page.locator('.netops-maps').waitFor(); await expectIcon(fromMap, 'olt');
      passed.push('edição pela lista atualiza o mapa e permanece ao recarregar');
      await click(page.locator('.topbar button').filter({ hasText: 'escuro' }));
      await expectIcon(fromMap, 'olt');
      await node(fromMap).scrollIntoViewIfNeeded();
      await page.screenshot({ path: `/tmp/netops-host-icons-map-${mode}-dark.png` });
      passed.push('ícone retangular mantém proporção no tema escuro');
      await click(page.locator('.sidebar a[href="#hosts"]'));
      await click(page.getByRole('cell', { name: fromMap, exact: true }));
      await click(picker.getByRole('button', { name: 'Padrão', exact: true }));
      await click(modal().getByRole('button', { name: 'Salvar', exact: true }));
      await modal().waitFor({ state: 'detached' }); await maps();
      assert.equal(await node(fromMap).locator('img.device-icon-image').count(), 0);
      assert.equal(await node(fromMap).locator('.device-icon').count(), 1);
      assert.ok(!('icon' in (await (await context.request.get(BASE + '/api/hosts/' + fromMap)).json()).explicit));
      passed.push('Padrão remove a escolha e restaura símbolo anterior');
      await click(page.locator('.sidebar a[href="#hosts"]'));
      await click(page.getByRole('button', { name: '+ Novo host', exact: true }));
      const fromList = `icon-list-${mode}-${Date.now()}`;
      await fillHost(fromList);
      await click(picker.getByRole('button', { name: 'Ícone Servidor Windows', exact: true }));
      await click(modal().getByRole('button', { name: 'Criar', exact: true }));
      await modal().waitFor({ state: 'detached' }); await maps(); await expectIcon(fromList, 'windows-server');
      passed.push('cadastro pela lista também leva o ícone ao mapa');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.deepEqual(errors, []); assert.deepEqual(external, []);
      results.push({ mode, status: 'PASS', passed, errors, external });
    } catch (e) {
      await page.screenshot({ path: `/tmp/netops-host-icons-${mode}-failed.png` });
      results.push({ mode, status: 'FAIL', passed, errors, external, failure: e.stack });
    }
    await context.close();
  }
} finally { await browser.close(); }
await fs.writeFile('/tmp/netops-host-icons-browser-results.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
if (results.some(r => r.status === 'FAIL')) process.exitCode = 1;
