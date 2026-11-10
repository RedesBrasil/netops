import { mapActions } from "./maps-actions.mjs";
// Requer fixture de uma localidade com layout e referência antiga, descrita em maps/SKILL.md.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
const meta = await (await fetch(BASE + '/api/config/meta')).json();
if (!meta.isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT.');
const initial = await (await fetch(BASE + '/api/maps')).json();
const oldId = Object.keys(initial.map_aliases).find(id => id.startsWith('site-'));
assert.ok(oldId);
const custom = initial.maps.find(m => m.kind === 'custom');
assert.ok(custom);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
try {
  for (const [mode, options] of [['desktop', { viewport: { width: 1440, height: 950 } }], ['mobile', { ...devices['iPhone 13'] }]]) {
    const context = await browser.newContext(options), page = await context.newPage(), errors = [], passed = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await context.addInitScript(id => sessionStorage.setItem('netops_map', id), oldId);
    const actions = mapActions(page, mode);
    const click = async l => { await l.scrollIntoViewIfNeeded(); if (mode === 'mobile') await l.tap(); else await l.click(); };
    try {
      await page.goto(BASE + '/#maps');
      await page.locator('.netops-maps').waitFor();
      await page.waitForFunction(() => document.querySelector('#map-select')?.value === 'all');
      assert.deepEqual(await page.locator('#map-select option').allTextContents(), ['Rede geral', custom.name]);
      assert.equal(await page.locator('.react-flow__node-device').count(), Object.keys(initial.hosts).length);
      await page.getByText('Anotação preservada da matriz', { exact: true }).waitFor();
      passed.push('somente Rede geral e mapa adicional no seletor, mesmo com seleção antiga de matriz');
      const before = await (await context.request.get(BASE + '/api/maps')).json();
      assert.deepEqual(before.maps[0].positions, initial.maps[0].positions);
      passed.push('posições e anotação dos mapas anteriores preservadas');
      await page.screenshot({ path: `/tmp/netops-single-map-${mode}.png` });
      await page.locator('#map-select').selectOption(custom.id);
      const ref = custom.objects.find(o => o.type === 'reference');
      await actions.on(page.locator(`.react-flow__node[data-id="object:${ref.id}"]`), 'Abrir mapa');
      await page.waitForFunction(() => document.querySelector('#map-select').value === 'all');
      passed.push('referência ao antigo mapa matriz abre Rede geral');
      await actions.pane('Adicionar texto');
      const note = `Unificado ${mode} ${Date.now()}`;
      await page.locator('.map-modal textarea').fill(note);
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.getByRole('status').filter({ hasText: 'Salvo no servidor' }).waitFor();
      await page.reload();
      await page.locator('.netops-maps').waitFor();
      const after = await (await context.request.get(BASE + '/api/maps')).json();
      assert.deepEqual(after.maps.map(m => m.id), ['all', custom.id]);
      assert.ok(after.maps[0].objects.some(o => o.label === note));
      assert.ok(after.maps[0].objects.some(o => o.label === 'Anotação preservada da matriz'));
      assert.deepEqual(after.maps[0].positions, initial.maps[0].positions);
      passed.push('salvamento e recarga mantêm uma única visão principal');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.deepEqual(errors, []);
      results.push({ mode, status: 'PASS', passed, errors });
    } catch (e) {
      await page.screenshot({ path: `/tmp/netops-single-map-${mode}-failed.png` });
      results.push({ mode, status: 'FAIL', passed, errors, failure: e.stack });
    }
    await context.close();
  }
} finally { await browser.close(); }
await fs.writeFile('/tmp/netops-single-map-results.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
if (results.some(r => r.status === 'FAIL')) process.exitCode = 1;
