// Menus contextuais e tela compacta. Dados de teste isolados são obrigatórios.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { mapActions } from './maps-actions.mjs';
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
if (!(await (await fetch(BASE + '/api/config/meta')).json()).isolated_data) throw Error('Use NETOPS_UI_DATA_ROOT com dados fictícios.');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
try {
  for (const [mode, options] of [['desktop', { viewport: { width: 1440, height: 950 } }], ['mobile', { ...devices['iPhone 13'] }]]) {
    const context = await browser.newContext(options), page = await context.newPage(), errors = [], passed = [];
    page.on('pageerror', e => errors.push(e.message));
    const actions = mapActions(page, mode);
    const click = async l => { await l.scrollIntoViewIfNeeded(); if (mode === 'mobile') await l.tap(); else await l.click(); };
    const snapshot = async () => (await context.request.get(BASE + '/api/maps')).json();
    const saved = async predicate => {
      for (let i = 0; i < 100; i++) { const s = await snapshot(); if (predicate(s)) return s; await page.waitForTimeout(50); }
      throw Error('Salvamento não observado');
    };
    const node = id => page.locator(`.react-flow__node[data-id="${id}"]`);
    try {
      const s = await snapshot(), id = 'context-' + mode;
      const fixture = { id, name: 'Contexto ' + mode, kind: 'custom', members: ['rt-core-01', 'rt-dist-01'],
        positions: { 'rt-core-01': { x: 60, y: 300 }, 'rt-dist-01': { x: 450, y: 60 } }, objects: [], edges: {}, visual_links: [] };
      const response = await context.request.put(BASE + '/api/maps/' + id, { headers: { 'If-Match': s.rev }, data: { map: fixture, hosts_rev: s.hosts_rev, topology_rev: s.topology.rev } });
      assert.equal(response.status(), 200, await response.text());
      await page.goto(BASE + '/#maps'); await page.locator('.netops-maps').waitFor();
      await page.locator('#map-select').selectOption(id); await node('host:rt-core-01').waitFor(); await page.waitForTimeout(300);
      assert.equal(await page.locator('.maps-page > .page-title, .map-footer, .selection-bar').count(), 0);
      assert.equal(await page.getByText('Cadastro integrado a Hosts', { exact: true }).count(), 0);
      const toolbarButtons = await page.locator('.map-toolbar button:visible').allTextContents();
      assert.deepEqual(toolbarButtons, mode === 'mobile' ? ['+', 'Exportar JSON', '⋯'] : ['+', 'Exportar JSON']);
      const row = await page.locator('.map-toolbar').evaluate(el => [...el.querySelectorAll('select, button')].filter(e => e.getBoundingClientRect().width).map(e => { const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; }));
      assert.ok(Math.max(...row.map(r => r.top)) - Math.min(...row.map(r => r.top)) < 8);
      assert.ok((await page.locator('.map-toolbar').boundingBox()).height < 62);
      passed.push('cabeçalho, rodapé e botões circulados removidos; opções restantes em uma linha');
      await page.screenshot({ path: `/tmp/netops-compact-map-${mode}.png` });
      await actions.background();
      for (const label of ['Adicionar host', 'Host existente', 'Ligar hosts', 'Adicionar texto', 'Adicionar forma', 'Referenciar mapa', 'Nome do mapa', 'Excluir mapa', 'Enquadrar mapa']) {
        assert.equal(await page.getByRole('menu').getByRole('menuitem', { name: label, exact: true }).count(), 1, label);
      }
      for (const removed of ['Hosts deste mapa', 'Exportar JSON', 'Legenda e ajuda', 'Novo mapa']) {
        assert.equal(await page.getByRole('menu').getByRole('menuitem', { name: removed, exact: true }).count(), 0, removed);
      }
      assert.equal(await page.getByLabel('Velocidade do novo enlace', { exact: true }).count(), 0);
      assert.equal(await page.getByRole('menu').count(), 1);
      const menuBox = await page.getByRole('menu').boundingBox();
      const screen = page.viewportSize();
      assert.ok(menuBox.x >= 0 && menuBox.y >= 0 && menuBox.x + menuBox.width <= screen.width + 1 && menuBox.y + menuBox.height <= screen.height + 1);
      await page.screenshot({ path: `/tmp/netops-compact-menu-${mode}.png` });
      await page.keyboard.press('Escape'); await page.getByRole('menu').waitFor({ state: 'detached' });
      passed.push('menu de fundo enxuto, sem as cinco opções removidas e dentro da tela');
      if (mode === 'desktop') {
        await node('host:rt-core-01').focus(); await page.keyboard.press('Shift+F10');
        await page.getByRole('menu', { name: 'Ações do item', exact: true }).waitFor();
        await page.getByRole('menuitem', { name: 'Editar', exact: true }).waitFor();
        await page.keyboard.press('ArrowDown');
        assert.ok(await page.getByRole('menu').evaluate(el => el.contains(document.activeElement)));
        await page.keyboard.press('Escape');
        passed.push('menu acessível por Shift+F10, setas e Escape');
      }
      await actions.on(node('host:rt-core-01'), 'Editar');
      await page.locator('.modal').getByRole('heading', { name: 'Editar rt-core-01', exact: true }).waitFor();
      await click(page.locator('.modal').getByRole('button', { name: 'Cancelar', exact: true }));
      passed.push('botão direito no host abre edição do cadastro');
      await actions.on(node('host:rt-core-01'), 'Ligar a outro dispositivo');
      await click(node('host:rt-dist-01'));
      await page.locator('.modal').waitFor();
      assert.equal(await page.locator('#link-ah').inputValue(), 'rt-core-01');
      assert.equal(await page.locator('#link-bh').inputValue(), 'rt-dist-01');
      assert.equal(await page.locator('#link-speed').inputValue(), '10G');
      const desc = `Contexto ${mode} ${Date.now()}`;
      await page.locator('#link-desc').fill(desc);
      await click(page.locator('.modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.locator('.modal').waitFor({ state: 'detached' });
      const withLink = await saved(s => s.topology.links.some(l => l.desc === desc));
      const link = withLink.topology.links.find(l => l.desc === desc);
      const label = page.locator(`[data-line-id="${link.id}"][data-line-part="line"]`);
      await actions.on(label, '+ Dobra');
      await saved(s => s.maps.find(m => m.id === id).edges[link.id]?.route?.tracks.length === 0);
      await actions.on(label, '+ Dobra');
      await saved(s => s.maps.find(m => m.id === id).edges[link.id]?.route?.tracks.length === 1);
      await actions.on(label, 'Remover dobra');
      await saved(s => s.maps.find(m => m.id === id).edges[link.id]?.route?.tracks.length === 0);
      await actions.on(label, 'Linha reta');
      await saved(s => !s.maps.find(m => m.id === id).edges[link.id]?.route);
      passed.push('ligação a partir do host e dobras unitárias operadas pelo menu do enlace');
      if (mode === 'desktop') {
        await page.locator(`.react-flow__edge[data-id="${link.id}"] .react-flow__edge-interaction`).click({ button: 'right' });
        await page.getByRole('menu', { name: 'Ações do item', exact: true }).waitFor();
        await page.keyboard.press('Escape');
        passed.push('menu também abre diretamente sobre o traço do enlace');
      }
      await actions.on(label, 'Editar');
      await page.locator('#link-speed').fill('1G');
      await click(page.locator('.modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.locator('.modal').waitFor({ state: 'detached' });
      await saved(s => s.topology.links.find(l => l.id === link.id)?.speed === '1G');
      await actions.pane('Adicionar texto');
      await page.locator('.map-modal textarea').fill('Nota pelo menu');
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      let current = await saved(s => s.maps.find(m => m.id === id).objects.some(o => o.label === 'Nota pelo menu'));
      const note = current.maps.find(m => m.id === id).objects.find(o => o.label === 'Nota pelo menu');
      await actions.on(node('object:' + note.id), 'Editar');
      await page.locator('.map-modal textarea').fill('Nota editada');
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await saved(s => s.maps.find(m => m.id === id).objects.some(o => o.label === 'Nota editada'));
      await actions.on(node('object:' + note.id), 'Remover do mapa');
      await saved(s => !s.maps.find(m => m.id === id).objects.some(o => o.id === note.id));
      passed.push('texto criado, editado e removido pelo menu contextual');
      await actions.pane('Nome do mapa'); await page.locator('.map-modal input[name="name"]').fill('Mapa renomeado ' + mode);
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await saved(s => s.maps.find(m => m.id === id).name === 'Mapa renomeado ' + mode);
      passed.push('renomear mapa permanece disponível; velocidade continua editável no cadastro do enlace');
      const download = page.waitForEvent('download');
      await click(page.locator('.map-toolbar').getByRole('button', { name: 'Exportar JSON', exact: true }));
      assert.ok((await download).suggestedFilename().endsWith('.json'));
      // Um conflito continua acionável, mesmo sem rodapé de status.
      const before = await snapshot(), other = structuredClone(before.maps.find(m => m.id === id)); delete other.host_ids;
      await actions.pane('Adicionar texto');
      other.name = 'Alterado por outro operador ' + mode;
      assert.equal((await context.request.put(BASE + '/api/maps/' + id, { headers: { 'If-Match': before.rev }, data: { map: other, hosts_rev: before.hosts_rev, topology_rev: before.topology.rev } })).status(), 200);
      await page.locator('.map-modal textarea').fill('Não sobrescrever');
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.getByRole('alert').filter({ hasText: 'Conflito de versão' }).waitFor();
      await click(page.getByRole('button', { name: 'Recarregar', exact: true }));
      await click(page.getByRole('button', { name: 'Confirmar', exact: true }));
      await page.locator('.map-save-error').waitFor({ state: 'detached' });
      assert.equal((await snapshot()).maps.find(m => m.id === id).name, other.name);
      passed.push('exportação preservada e aviso de conflito aparece somente quando necessário');
      const failedWrite = '**/api/maps/' + id;
      await page.route(failedWrite, async route => {
        if (route.request().method() !== 'PUT') return route.continue();
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Falha de teste temporária' }) });
      });
      await actions.pane('Adicionar texto'); await page.locator('.map-modal textarea').fill('Recuperado após falha');
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.getByRole('alert').filter({ hasText: 'Falha ao salvar' }).waitFor();
      await page.unroute(failedWrite);
      await click(page.getByRole('button', { name: 'Tentar novamente', exact: true }));
      await page.locator('.map-save-error').waitFor({ state: 'detached' });
      await saved(s => s.maps.find(m => m.id === id).objects.some(o => o.label === 'Recuperado após falha'));
      passed.push('falha de salvamento mantém rascunho e permite tentar novamente sem rodapé');

      await click(page.locator('.topbar button').filter({ hasText: 'escuro' }));
      await page.screenshot({ path: `/tmp/netops-compact-map-${mode}-dark.png` });
      await page.route('**/api/maps', async route => {
        const response = await route.fetch(), data = await response.json();
        await route.fulfill({ response, json: { ...data, read_only: true } });
      });
      await page.reload(); await page.locator('.netops-maps').waitFor();
      await actions.background();
      assert.equal(await page.getByRole('menuitem', { name: 'Adicionar host', exact: true }).count(), 0);
      assert.equal(await page.getByRole('menuitem', { name: 'Ligar hosts', exact: true }).count(), 0);
      await page.getByRole('menuitem', { name: 'Enquadrar mapa', exact: true }).waitFor();
      await page.keyboard.press('Escape');
      await actions.item(node('host:rt-core-01'));
      assert.equal(await page.getByRole('menuitem', { name: 'Editar', exact: true }).count(), 0);
      assert.equal(await page.getByRole('menuitem', { name: 'Remover do mapa', exact: true }).count(), 0);
      await page.keyboard.press('Escape');
      passed.push('modo somente leitura não oferece ações de escrita nos menus');

      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.deepEqual(errors, []);
      results.push({ mode, status: 'PASS', passed, errors });
    } catch (e) {
      await page.screenshot({ path: `/tmp/netops-compact-menu-${mode}-failed.png` });
      results.push({ mode, status: 'FAIL', passed, errors, failure: e.stack });
    }
    await context.close();
  }
} finally { await browser.close(); }
await fs.writeFile('/tmp/netops-compact-context-results.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
if (results.some(r => r.status === 'FAIL')) process.exitCode = 1;
