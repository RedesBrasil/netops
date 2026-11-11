// Cadastro/mapas com IDs internos inteiros, em fixture isolada de desktop e toque.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { mapActions } from './maps-actions.mjs';

const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8794';
const OUT = path.resolve(process.env.NETOPS_E2E_OUTPUT || 'runs/2026-11-11-integer-hosts-browser');
const meta = await (await fetch(BASE + '/api/config/meta')).json();
if (!meta.isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT fictício.');
await fs.mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
try {
  for (const mode of ['desktop', 'mobile']) {
    const context = await browser.newContext(mode === 'mobile' ? { ...devices['iPhone 13'] } : { viewport: { width: 1440, height: 1050 } });
    const page = await context.newPage(), errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      const disabledClaude = !meta.claude_enabled && message.location().url.endsWith('/api/claude/models') && message.text().includes('403');
      if (message.type() === 'error' && !disabledClaude) errors.push(message.text());
    });
    page.on('request', request => {
      if (['POST', 'PUT', 'PATCH'].includes(request.method()) && new URL(request.url()).pathname.startsWith('/api/')) {
        writes.push({ route: new URL(request.url()).pathname, body: request.postDataJSON() });
      }
    });
    page.setDefaultTimeout(12000);
    const click = async locator => { await locator.scrollIntoViewIfNeeded(); if (mode === 'mobile') await locator.tap(); else await locator.click(); };
    const actions = mapActions(page, mode), modal = () => page.locator('.modal');
    const field = text => modal().locator('.field').filter({ has: page.locator('label').filter({ hasText: text }) });
    const node = id => page.locator(`.react-flow__node[data-id="${typeof id === 'number' ? 'host:' + id : id}"]`);
    const snapshot = async () => {
      const response = await context.request.get(BASE + '/api/maps');
      assert.equal(response.status(), 200, await response.text());
      return response.json();
    };
    const wait = async predicate => {
      for (let index = 0; index < 100; index++) {
        const state = await snapshot();
        if (predicate(state)) return state;
        await page.waitForTimeout(80);
      }
      throw Error('Persistência não observada: ' + predicate.toString());
    };
    async function createHost(name) {
      await modal().waitFor();
      assert.equal(await modal().getByText(/^ID(?:\s|$)/).count(), 0);
      assert.equal(await modal().locator('input[placeholder="ex.: rt-core-01"]').count(), 0);
      await field('Nome do host').locator('input').fill(name);
      await field('IP de gerência').locator('input').fill('192.0.2.88');
      await field('Grupo (herança').locator('select').selectOption('linux-servers');
      await click(modal().getByRole('button', { name: 'Ícone Roteador', exact: true }));
      const response = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/hosts');
      await click(modal().getByRole('button', { name: 'Criar', exact: true }));
      const created = await response;
      assert.equal(created.status(), 201, await created.text());
      assert.equal(Object.hasOwn(created.request().postDataJSON(), 'id'), false);
      const value = await created.json();
      assert.equal(typeof value.id, 'number');
      assert.ok(Number.isSafeInteger(value.id) && value.id > 0);
      await modal().waitFor({ state: 'detached' });
      return value.id;
    }
    try {
      const stamp = `${mode}-${Date.now()}`, listName = 'Cadastro lista ' + stamp, mapName = 'Cadastro mapa ' + stamp;
      await page.goto(BASE + '/#hosts');
      await page.getByRole('heading', { name: 'Hosts', exact: true }).waitFor();
      assert.equal(await page.getByRole('columnheader', { name: 'ID', exact: true }).count(), 0);
      await click(page.getByRole('button', { name: '+ Novo host', exact: true }));
      const listId = await createHost(listName);
      await page.getByRole('cell', { name: listName, exact: true }).waitFor();

      let state = await snapshot();
      const mapId = 'integer-' + stamp;
      const response = await context.request.put(BASE + '/api/maps/' + mapId, { headers: { 'If-Match': state.rev },
        data: { map: { id: mapId, name: 'IDs inteiros ' + mode, kind: 'custom', members: [listId],
          positions: [{ host_id: listId, x: 80, y: 80, z_index: 2 }], edges: {}, visual_links: [],
          objects: [{ id: 'shape', type: 'shape', label: 'Forma sem IP', position: { x: 500, y: 400 }, width: 180, height: 100 }] },
          hosts_rev: state.hosts_rev, topology_rev: state.topology.rev } });
      assert.equal(response.status(), 200, await response.text());
      await page.goto(BASE + '/#maps');
      await page.locator('#map-select').selectOption(mapId);
      await node(listId).waitFor();
      await actions.pane('Adicionar host');
      const mapHostId = await createHost(mapName);
      state = await wait(s => s.maps.find(m => m.id === mapId).host_ids.includes(mapHostId));
      assert.ok(state.maps.find(m => m.id === mapId).positions.some(p => p.host_id === mapHostId));
      assert.ok(state.hosts.find(h => h.id === mapHostId));

      await actions.pane('Host existente');
      const existing = page.locator('.map-modal select[name="host"]');
      const root = state.hosts.find(h => h.id === 1);
      assert.ok((await existing.locator('option[value="1"]').innerText()).includes(root.hostname));
      assert.ok((await existing.locator('option[value="1"]').innerText()).includes(root.mgmt_ip));
      assert.equal(await existing.locator(`option[value="${listId}"]`).count(), 0);
      await existing.selectOption('1');
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await wait(s => s.maps.find(m => m.id === mapId).members.includes(1));
      await actions.pane('Enquadrar mapa');
      await page.waitForTimeout(250);

      await actions.pane('Ligar hosts');
      await click(node(listId));
      await click(node(mapHostId));
      await modal().waitFor();
      assert.equal(await page.locator('#link-ah').inputValue(), String(listId));
      assert.equal(await page.locator('#link-bh').inputValue(), String(mapHostId));
      const option = await page.locator(`#link-ah option[value="${listId}"]`).innerText();
      assert.ok(option.includes(listName) && option.includes('192.0.2.88'));
      await click(modal().getByRole('button', { name: 'Salvar', exact: true }));
      await modal().waitFor({ state: 'detached' });
      state = await wait(s => s.topology.links.some(link => link.a.host === listId && link.b.host === mapHostId));
      const link = state.topology.links.find(link => link.a.host === listId && link.b.host === mapHostId);
      const placement = structuredClone(state.maps.find(m => m.id === mapId).positions.find(p => p.host_id === listId));

      await actions.on(node(listId), 'Editar');
      await field('Nome do host').locator('input').fill(listName + ' alterado');
      await click(modal().getByRole('button', { name: 'Salvar', exact: true }));
      await modal().waitFor({ state: 'detached' });
      state = await wait(s => s.hosts.some(h => h.id === listId && h.hostname === listName + ' alterado'));
      assert.equal(state.hosts.find(h => h.id === listId).icon, 'router');
      assert.deepEqual(state.maps.find(m => m.id === mapId).positions.find(p => p.host_id === listId), placement);
      assert.deepEqual(state.topology.links.find(value => value.id === link.id), link);

      await actions.pane('Ligar hosts');
      await click(node(listId));
      await click(node('object:shape'));
      state = await wait(s => s.maps.find(m => m.id === mapId).visual_links.some(link => link.source.kind === 'host' && link.source.host_id === listId && link.target.object_id === 'shape'));
      for (const write of writes) {
        if (write.route.startsWith('/api/maps/')) {
          assert.ok(Array.isArray(write.body.map.positions));
          assert.ok(write.body.map.positions.every(position => typeof position.host_id === 'number'));
          assert.ok(write.body.map.members.every(id => typeof id === 'number'));
          assert.ok(write.body.map.visual_links.every(link => typeof link.source === 'object' && typeof link.target === 'object'));
        }
        if (write.route === '/api/topology/links') {
          assert.equal(typeof write.body.a.host, 'number');
          assert.equal(typeof write.body.b.host, 'number');
        }
      }
      assert.ok(writes.some(write => write.route === '/api/topology/links'));
      assert.ok(writes.some(write => write.route.startsWith('/api/maps/')));
      await page.reload();
      await node(listId).waitFor();
      await node(listId).getByText(listName + ' alterado', { exact: true }).waitFor();
      assert.deepEqual(errors, []);
      await page.screenshot({ path: path.join(OUT, mode + '.png') });
      results.push({ mode, status: 'PASS', listId, mapHostId, checks: ['cadastro sem ID', 'ID inteiro retornado pelo servidor', 'host criado no mapa', 'seletor nome/IP', 'enlace inteiro', 'nome editável preserva ID/ícone/posição/enlace', 'ligação visual tipada', 'persistência após recarga'] });
    } catch (error) {
      await page.screenshot({ path: path.join(OUT, mode + '-failure.png') }).catch(() => {});
      throw error;
    } finally { await context.close(); }
  }
} finally {
  await browser.close();
  await fs.writeFile(path.join(OUT, 'result.json'), JSON.stringify(results, null, 2));
}
console.log(JSON.stringify(results, null, 2));
