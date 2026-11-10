// Formas conectáveis, ícones e alinhamento, somente em fixtures isoladas.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { mapActions } from './maps-actions.mjs';
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
if (!(await (await fetch(BASE + '/api/config/meta')).json()).isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT.');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
try {
  for (const [mode, options] of [['desktop', { viewport: { width: 1600, height: 1050 } }], ['mobile', { ...devices['iPhone 13'] }]]) {
    const ctx = await browser.newContext(options), page = await ctx.newPage(), errors = [], passed = [];
    page.on('pageerror', e => errors.push(e.message));
    const actions = mapActions(page, mode);
    const click = async l => {
      await l.scrollIntoViewIfNeeded();
      const position = await l.evaluate(el => {
        if (!el.classList.contains('react-flow__node')) return undefined;
        const r = el.getBoundingClientRect();
        for (const [x, y] of [[.2, .2], [.8, .2], [.2, .7], [.8, .7], [.5, .5]]) {
          const top = document.elementFromPoint(r.x + r.width * x, r.y + r.height * y);
          if (top?.closest('.react-flow__node') === el) return { x: r.width * x, y: r.height * y };
        }
        throw Error('Nó totalmente coberto por outro elemento');
      });
      if (mode === 'mobile') await l.tap({ position }); else await l.click({ position });
    };
    const get = async () => (await ctx.request.get(BASE + '/api/maps')).json();
    const node = id => page.locator(`.react-flow__node[data-id="${id}"]`);
    const ids = ['host:rt-core-01', 'host:rt-dist-01', 'host:sw-access-01', 'host:srv-web-01'];
    const currentMap = async () => (await get()).maps.find(m => m.id === 'all');
    async function waitSaved(predicate) {
      for (let i = 0; i < 100; i++) { const s = await get(); if (predicate(s.maps.find(m => m.id === 'all'), s)) return s; await page.waitForTimeout(60); }
      throw Error('Persistência não observada');
    }
    async function reset() {
      const s = await get(), map = structuredClone(s.maps.find(m => m.id === 'all')); delete map.host_ids;
      map.positions = { 'rt-core-01': { x: 70, y: 70 }, 'rt-dist-01': { x: 420, y: 130 }, 'sw-access-01': { x: 70, y: 350 }, 'srv-web-01': { x: 420, y: 410 } };
      map.objects = []; map.visual_links = []; map.edges = {};
      const r = await ctx.request.put(BASE + '/api/maps/all', { headers: { 'If-Match': s.rev }, data: { map, hosts_rev: s.hosts_rev, topology_rev: s.topology.rev } });
      assert.equal(r.status(), 200, await r.text());
      await page.goto(BASE + '/#maps'); await node(ids[0]).waitFor(); await page.waitForTimeout(350);
      return r.json();
    }
    async function createShape(label, icon) {
      await actions.pane('Adicionar forma');
      await page.locator('.map-modal textarea').fill(label);
      await click(page.locator('.map-modal').getByRole('button', { name: 'Ícone ' + icon, exact: true }));
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      const s = await waitSaved(m => m.objects.some(o => o.label === label));
      const shape = s.maps[0].objects.find(o => o.label === label);
      await node('object:' + shape.id).waitFor();
      return shape;
    }
    async function connect(source, target, fromItem = false) {
      const count = (await currentMap()).visual_links.length;
      if (fromItem) await actions.on(node(source), 'Ligar a outro dispositivo');
      else { await actions.pane('Ligar hosts'); await click(node(source)); }
      await click(node(target));
      await waitSaved(m => m.visual_links.length === count + 1);
      await page.waitForTimeout(300);
      assert.equal(await page.locator('.modal').count(), 0, 'forma não exige cadastro de host/porta');
      return (await currentMap()).visual_links.at(-1);
    }
    async function selectMany(selectedIds) {
      if (mode === 'mobile') {
        await actions.pane('Selecionar vários');
        for (const id of selectedIds) await click(node(id));
      } else {
        await actions.background(); await page.keyboard.press('Escape');
        // Clique sem modificador inicia uma seleção nova; Ctrl adiciona os demais.
        await click(node(selectedIds[0]));
        await page.waitForTimeout(70);
        await page.keyboard.down('Control');
        for (const id of selectedIds.slice(1)) await click(node(id));
        await page.keyboard.up('Control');
      }
      await page.waitForFunction(ids => ids.every(id => document.querySelector(`.react-flow__node[data-id="${id}"]`)?.classList.contains('selected')), selectedIds);
      assert.deepEqual((await page.locator('.react-flow__node.selected').evaluateAll(ns => ns.map(n => n.dataset.id))).filter(id => selectedIds.includes(id)).sort(), [...selectedIds].sort());
    }
    async function groupMenu(id = ids[0]) {
      if (mode === 'mobile') await click(page.getByRole('button', { name: 'Ações do mapa', exact: true }));
      else await node(id).click({ button: 'right' });
      await page.getByRole('menuitem', { name: 'Alinhar horizontalmente', exact: true }).waitFor();
    }
    async function rects(selectedIds) {
      return page.locator('.react-flow__node').evaluateAll((ns, selectedIds) => {
        const zoom = new DOMMatrix(document.querySelector('.react-flow__viewport').style.transform).a;
        return ns.filter(n => selectedIds.includes(n.dataset.id)).map(n => {
          const r = n.getBoundingClientRect(), t = new DOMMatrix(n.style.transform);
          return { id: n.dataset.id, x: t.m41, y: t.m42, width: r.width / zoom, height: r.height / zoom };
        });
      }, selectedIds);
    }
    function checkAlignment(values, direction) {
      const axis = direction === 'horizontal' ? 'x' : 'y', cross = axis === 'x' ? 'y' : 'x';
      const size = axis === 'x' ? 'width' : 'height', other = axis === 'x' ? 'height' : 'width';
      const rows = values.sort((a, b) => a[axis] - b[axis]);
      for (let i = 1; i < rows.length; i++) {
        assert.ok(Math.abs(rows[i][axis] - rows[i - 1][axis] - rows[i - 1][size] - 24) < .15, 'espaços livres iguais');
        assert.ok(Math.abs(rows[i][cross] + rows[i][other] / 2 - rows[0][cross] - rows[0][other] / 2) < .15, 'centros alinhados');
      }
    }
    try {
      const initial = await reset(), initialHosts = initial.hosts, initialLinks = initial.topology.links;
      const cloud = await createShape('Nuvem ' + mode, 'Cloud');
      assert.equal(cloud.icon, 'cloud');
      await page.waitForFunction(id => { const i = document.querySelector(`[data-id="object:${id}"] img`); return i?.complete && i.naturalWidth > 0; }, cloud.id);
      // Reposiciona só a fixture para garantir área livre de interação para todos os gestos.
      let s = await get(), m = structuredClone(s.maps[0]); delete m.host_ids;
      m.objects.find(o => o.id === cloud.id).position = { x: 740, y: 230 };
      m.objects.find(o => o.id === cloud.id).width = 220; m.objects.find(o => o.id === cloud.id).height = 140;
      assert.equal((await ctx.request.put(BASE + '/api/maps/all', { headers: { 'If-Match': s.rev }, data: { map: m, hosts_rev: s.hosts_rev, topology_rev: s.topology.rev } })).status(), 200);
      await page.reload(); await node('object:' + cloud.id).waitFor(); await page.waitForTimeout(300);
      const first = await connect(ids[0], 'object:' + cloud.id);
      await connect('object:' + cloud.id, ids[1], true);
      await connect('object:' + cloud.id, ids[2]);
      assert.equal(await page.locator('.react-flow__edge-path').count(), initialLinks.length + 3);
      const now = await get(); assert.deepEqual(now.hosts, initialHosts); assert.deepEqual(now.topology.links, initialLinks);
      passed.push('mesmo Ligar hosts conecta host-forma e forma-host sem IP nem cadastro de host fictício');
      const edge = page.locator(`[data-line-id="visual:${first.id}"][data-line-part="line"]`);
      await actions.on(edge, '+ Dobra');
      await waitSaved(m => m.visual_links.find(l => l.id === first.id).route);
      passed.push('ligação com forma tem dobras e controles de enlace existentes');
      await actions.on(node('object:' + cloud.id), 'Editar');
      await click(page.locator('.map-modal').getByRole('button', { name: 'Ícone Switch', exact: true }));
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await waitSaved(m => m.objects.find(o => o.id === cloud.id).icon === 'switch');
      await page.reload(); await node('object:' + cloud.id).waitFor();
      assert.ok((await node('object:' + cloud.id).locator('img').getAttribute('src')).endsWith('/switch.png'));
      passed.push('ícone de forma editável e persistido no YAML');
      // O grupo nativo não pode se desfazer ao abrir o menu sobre um de seus membros.
      await selectMany(ids);
      const oldRoutes = structuredClone((await currentMap()).visual_links);
      let writes = 0; const track = r => { if (r.method() === 'PUT' && r.url().endsWith('/api/maps/all')) writes++; };
      page.on('request', track);
      await groupMenu(); await actions.choose('Alinhar horizontalmente');
      await waitSaved(m => ids.every(id => m.positions[id.slice(5)]));
      await page.waitForTimeout(200);
      checkAlignment(await rects(ids), 'horizontal');
      assert.equal(writes, 1, 'alinhamento faz uma gravação');
      assert.deepEqual((await currentMap()).visual_links, oldRoutes);
      passed.push('quatro hosts alinhados na horizontal com intervalos iguais em uma gravação');
      await groupMenu(); await actions.choose('Alinhar verticalmente'); await page.waitForTimeout(200);
      checkAlignment(await rects(ids), 'vertical');
      assert.equal(writes, 2);
      page.off('request', track);
      await page.screenshot({ path: `/tmp/netops-aligned-${mode}.png` });
      const finalPositions = structuredClone((await currentMap()).positions);
      await page.reload(); await node(ids[0]).waitFor(); await page.waitForTimeout(250);
      assert.deepEqual((await currentMap()).positions, finalPositions);
      checkAlignment(await rects(ids), 'vertical');
      passed.push('coluna vertical compacta com espaços iguais, preservada ao recarregar');
      if (mode === 'desktop') {
        // Retângulo com Shift seleciona o grupo sem mudar o pan normal do mapa.
        const boxes = await Promise.all(ids.map(id => node(id).boundingBox()));
        const x = Math.min(...boxes.map(r => r.x)) - 12, y = Math.min(...boxes.map(r => r.y)) - 12;
        const right = Math.max(...boxes.map(r => r.x + r.width)) + 12, bottom = Math.max(...boxes.map(r => r.y + r.height)) + 12;
        await page.keyboard.down('Shift'); await page.mouse.move(x, y); await page.mouse.down();
        await page.mouse.move(right, bottom, { steps: 18 }); await page.mouse.up(); await page.keyboard.up('Shift');
        await page.waitForTimeout(100);
        assert.equal(await page.locator('.react-flow__node-device.selected').count(), 4);
        await page.locator('.react-flow__nodesselection-rect').click({ button: 'right' });
        await page.getByRole('menuitem', { name: 'Alinhar horizontalmente', exact: true }).waitFor(); await page.keyboard.press('Escape');
        passed.push('Shift e retângulo selecionam quatro hosts e abrem menu de grupo');
      }
      await actions.background(); await page.keyboard.press('Escape');
      const switchShape = await createShape('Switch sem IP ' + mode, 'Switch');
      s = await get(); m = structuredClone(s.maps[0]); delete m.host_ids;
      m.objects.find(o => o.id === switchShape.id).position = { x: 90, y: 80 };
      m.objects.find(o => o.id === switchShape.id).width = 180;
      m.objects.find(o => o.id === switchShape.id).height = 110;
      assert.equal((await ctx.request.put(BASE + '/api/maps/all', { headers: { 'If-Match': s.rev }, data: { map: m, hosts_rev: s.hosts_rev, topology_rev: s.topology.rev } })).status(), 200);
      await page.reload(); await node('object:' + switchShape.id).waitFor(); await page.waitForTimeout(300);
      await connect('object:' + switchShape.id, 'object:' + cloud.id, true);
      passed.push('forma-forma usa a mesma ligação visual sem novo menu');
      const unselected = structuredClone((await currentMap()).positions['srv-web-01']);
      const mixed = [ids[0], ids[1], 'object:' + cloud.id, 'object:' + switchShape.id];
      await selectMany(mixed); await groupMenu(); await actions.choose('Alinhar horizontalmente');
      await page.waitForTimeout(250); checkAlignment(await rects(mixed), 'horizontal');
      assert.deepEqual((await currentMap()).positions['srv-web-01'], unselected);
      passed.push('alinhamento misto respeita dimensões distintas e não move host fora da seleção');
      await groupMenu(); await actions.choose('Limpar seleção');
      await actions.on(node('object:' + switchShape.id), 'Editar');
      await page.locator('.map-modal select[name="form"]').selectOption('ellipse');
      await click(page.locator('.map-modal').getByRole('button', { name: 'Sem ícone', exact: true }));
      await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true }));
      await waitSaved(m => !m.objects.find(o => o.id === switchShape.id).icon);
      assert.equal(await node('object:' + switchShape.id).locator('img').count(), 0);
      const linked = (await currentMap()).visual_links;
      await actions.on(node('object:' + switchShape.id), 'Remover do mapa');
      await waitSaved(m => !m.objects.some(o => o.id === switchShape.id));
      const afterRemove = await get();
      assert.ok(afterRemove.maps[0].visual_links.every(l => l.source !== 'object:' + switchShape.id && l.target !== 'object:' + switchShape.id));
      assert.equal(afterRemove.maps[0].visual_links.length, linked.filter(l => l.source !== 'object:' + switchShape.id && l.target !== 'object:' + switchShape.id).length);
      assert.deepEqual(afterRemove.hosts, initialHosts);
      assert.deepEqual(afterRemove.topology.links, initialLinks);
      passed.push('limpar ícone e remover forma preservam hosts e limpam somente suas conexões');
      await actions.pane('Selecionar vários'); await click(node(ids[0])); await click(node(ids[1]));
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('.react-flow__node.selected').count(), 0);
      await click(page.locator('.topbar button').filter({ hasText: 'escuro' }));
      await page.screenshot({ path: `/tmp/netops-shapes-aligned-${mode}-dark.png` });
      passed.push('cancelamento da seleção e tema escuro funcionam');
      assert.equal(await page.locator('.react-flow__handle:visible').count(), 0);
      assert.deepEqual(errors, []);
      results.push({ mode, status: 'PASS', passed, errors });
    } catch (e) {
      await page.screenshot({ path: `/tmp/netops-shapes-align-${mode}-failed.png` });
      results.push({ mode, status: 'FAIL', passed, errors, failure: e.stack });
    }
    await ctx.close();
  }
} finally { await browser.close(); }
await fs.writeFile('/tmp/netops-shapes-align-results.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
if (results.some(r => r.status === 'FAIL')) process.exitCode = 1;
