// Regressão de controles e exclusão em todos os mapas; somente fixture isolada v2.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { mapActions } from './maps-actions.mjs';

const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8782';
const OUT = path.resolve(process.env.NETOPS_E2E_OUTPUT || 'runs/2026-11-11-map-controls-recovery/tester-cascade-browser');
const meta = await (await fetch(BASE + '/api/config/meta')).json();
if (!meta.isolated_data) throw Error('Teste recusa dados reais. Use instalação e dados fictícios separados.');
await fs.mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
try {
  for (const mode of ['desktop', 'mobile']) {
    const context = await browser.newContext(mode === 'mobile' ? { ...devices['iPhone 13'] } : { viewport: { width: 1440, height: 1050 } });
    const page = await context.newPage(), errors = [], checks = [];
    page.setDefaultTimeout(12000);
    page.on('pageerror', error => errors.push(error.message));
    const actions = mapActions(page, mode);
    const click = async locator => { await locator.scrollIntoViewIfNeeded(); if (mode === 'mobile') await locator.tap(); else await locator.click(); };
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
    const saveMap = async value => {
      const state = await snapshot();
      delete value.host_ids;
      const response = await context.request.put(BASE + '/api/maps/' + value.id, {
        headers: { 'If-Match': state.rev }, data: { map: value, hosts_rev: state.hosts_rev, topology_rev: state.topology.rev },
      });
      assert.equal(response.status(), 200, await response.text());
    };
    try {
      const stamp = `${mode}-${Date.now()}`, site = 'Cascade ' + stamp, ids = [];
      for (let index = 0; index < 4; index++) {
        const state = await snapshot();
        const response = await context.request.post(BASE + '/api/hosts', {
          headers: { 'If-Match': state.hosts_rev },
          data: { hostname: `Cascade ${index} ${stamp}`, mgmt_ip: '192.0.2.' + (110 + index), group: 'linux-servers', site },
        });
        assert.equal(response.status(), 201, await response.text());
        ids.push((await response.json()).id);
      }
      const [other, victim, third, fourth] = ids;
      for (const [source, target] of [[other, victim], [victim, other], [third, victim], [third, fourth]]) {
        const state = await snapshot();
        const response = await context.request.post(BASE + '/api/topology/links', {
          headers: { 'If-Match': state.topology.rev }, data: { a: { host: source }, b: { host: target } },
        });
        assert.equal(response.status(), 200, await response.text());
      }
      let state = await snapshot();
      assert.equal(state.read_only, false);
      assert.equal(state.migration_required, false);
      const automatic = state.maps.find(value => value.site === site), mapIds = ['all', automatic.id, 'cascade-a-' + stamp, 'cascade-b-' + stamp];
      const affected = state.topology.links.filter(link => link.a.host === victim || link.b.host === victim).map(link => link.id);
      assert.equal(affected.length, 3);
      const keptLink = state.topology.links.find(link => link.a.host === third && link.b.host === fourth);
      for (const mapId of mapIds) {
        state = await snapshot();
        const existing = state.maps.find(value => value.id === mapId);
        const value = existing ? structuredClone(existing) : { id: mapId, name: mapId, kind: 'custom', members: ids };
        value.positions = ids.map((host_id, index) => ({ host_id, x: index % 2 ? 500 : 40, y: index > 1 ? 480 : 40 }));
        value.objects = ['first', 'second'].map((id, index) => ({ id, type: 'shape', label: '', width: 160, height: 100, position: { x: index ? 500 : 40, y: 260 } }));
        value.visual_links = [
          { id: 'host-source', source: { kind: 'host', host_id: victim }, target: { kind: 'object', object_id: 'first' } },
          { id: 'host-target', source: { kind: 'object', object_id: 'second' }, target: { kind: 'host', host_id: victim } },
          { id: 'keep-host', source: { kind: 'host', host_id: other }, target: { kind: 'object', object_id: 'first' } },
          { id: 'keep-shapes', source: { kind: 'object', object_id: 'first' }, target: { kind: 'object', object_id: 'second' } },
        ];
        value.edges = Object.fromEntries([...affected, keptLink.id].map(id => [id, { route: { axis: 'x', tracks: [180] } }]));
        await saveMap(value);
      }
      await page.goto(BASE + '/#maps');
      await page.locator('#map-select').selectOption(automatic.id);
      await node(victim).waitFor();
      await actions.background();
      for (const name of ['Adicionar host', 'Host existente', 'Ligar hosts', 'Adicionar forma']) {
        assert.equal(await page.getByRole('menuitem', { name, exact: true }).count(), 1);
      }
      checks.push('menus gerais oferecem cadastro de host, host existente, ligação e forma');
      await page.keyboard.press('Escape');
      if (mode === 'desktop') await node(victim).dblclick();
      else await actions.on(node(victim), 'Editar');
      await page.locator('.modal').waitFor();
      const hostName = page.locator('.modal .field').filter({ has: page.locator('label').filter({ hasText: 'Nome do host' }) }).locator('input');
      assert.equal(await hostName.inputValue(), `Cascade 1 ${stamp}`);
      await hostName.fill('Host editado ' + stamp);
      await click(page.locator('.modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.locator('.modal').waitFor({ state: 'detached' });
      await wait(value => value.hosts.some(host => host.id === victim && host.hostname === 'Host editado ' + stamp));
      checks.push(mode === 'desktop' ? 'duplo clique abre detalhes e salva nome sem trocar ID' : 'menu por toque abre detalhes e salva nome sem trocar ID');

      const before = await snapshot();
      if (mode === 'desktop') {
        await click(node(victim));
        await page.keyboard.press('Delete');
      } else await actions.on(node(victim), 'Excluir host');
      const confirm = page.locator('.modal');
      await confirm.waitFor();
      assert.ok((await confirm.innerText()).includes('todos os mapas'));
      assert.ok((await confirm.innerText()).includes('Host editado ' + stamp));
      await page.screenshot({ path: path.join(OUT, mode + '-confirmation.png') });
      await click(confirm.getByRole('button', { name: 'Confirmar', exact: true }));
      await confirm.waitFor({ state: 'detached' });
      const after = await wait(value => !value.hosts.some(host => host.id === victim));
      assert.ok(after.topology.links.every(link => link.a.host !== victim && link.b.host !== victim));
      const canonical = link => Object.fromEntries(Object.entries(link).filter(([key]) => key !== 'index'));
      assert.deepEqual(canonical(after.topology.links.find(link => link.id === keptLink.id)), canonical(keptLink));
      for (const mapId of mapIds) {
        const previous = before.maps.find(value => value.id === mapId), current = after.maps.find(value => value.id === mapId);
        assert.ok(!current.host_ids.includes(victim) && !current.members.includes(victim));
        assert.ok(current.positions.every(position => position.host_id !== victim));
        assert.ok(affected.every(id => !Object.hasOwn(current.edges, id)));
        assert.deepEqual(current.edges[keptLink.id], previous.edges[keptLink.id]);
        assert.deepEqual(current.visual_links, previous.visual_links.filter(link => link.id.startsWith('keep-')));
        assert.deepEqual(current.objects, previous.objects);
      }
      checks.push('exclusão confirmada remove host e três enlaces A/B, inclusive paralelo inverso');
      checks.push('quatro mapas sem host, posição, rota física ou ligação visual órfã nas duas pontas');
      checks.push('hosts, formas, ligação física, rotas e ligações visuais não afetados são preservados');
      await page.reload();
      await page.locator('.netops-maps').waitFor();
      assert.equal(await node(victim).count(), 0);
      assert.deepEqual(errors, []);
      checks.push('recarregar mantém exclusão e não gera exceção JavaScript');
      await fs.writeFile(path.join(OUT, mode + '-state.json'), JSON.stringify({ victim, mapIds, affected, keptLink: keptLink.id, before, after }, null, 2));
      await page.screenshot({ path: path.join(OUT, mode + '-after.png') });
      results.push({ mode, status: 'PASS', checks });
    } catch (error) {
      await page.screenshot({ path: path.join(OUT, mode + '-failure.png') }).catch(() => {});
      results.push({ mode, status: 'FAIL', checks, error: error.stack, errors });
    } finally { await context.close(); }
  }
} finally {
  await browser.close();
  await fs.writeFile(path.join(OUT, 'result.json'), JSON.stringify(results, null, 2));
}
console.log(JSON.stringify(results, null, 2));
if (results.some(result => result.status !== 'PASS')) process.exitCode = 1;
