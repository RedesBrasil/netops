// Edição livre dos mapas. Recusa inventário real e usa somente mapas de fixture.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { mapActions } from './maps-actions.mjs';

const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8782';
const OUT = path.resolve(process.env.NETOPS_E2E_OUTPUT || 'runs/2026-11-11-map-editing');
const meta = await (await fetch(BASE + '/api/config/meta')).json();
if (!meta.isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT fictício.');
await fs.mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const results = [];
const hostIds = ['rt-core-01', 'rt-dist-01', 'sw-access-01', 'srv-web-01'];
let serial = 0;

function fixture(id, mode) {
  return { id, name: 'Edição ' + mode, kind: 'custom', members: [...hostIds],
    positions: { 'rt-core-01': { x: 80, y: 70, z_index: 2 }, 'rt-dist-01': { x: 520, y: 70, z_index: 3 },
      'sw-access-01': { x: 80, y: 520, z_index: 4 }, 'srv-web-01': { x: 520, y: 520, z_index: 5 } },
    objects: [
      { id: 'first-shape', type: 'shape', label: 'Forma um', form: 'rect', position: { x: 80, y: 270 }, width: 200, height: 120, z_index: 0 },
      { id: 'second-shape', type: 'shape', label: 'Forma dois', form: 'ellipse', position: { x: 520, y: 270 }, width: 200, height: 120, z_index: 1 }
    ], visual_links: [], edges: {} };
}
const layerOrder = map => [
  ...map.host_ids.map(id => ({ id: 'host:' + id, z: map.positions[id].z_index })),
  ...map.objects.map(o => ({ id: 'object:' + o.id, z: o.z_index }))
].sort((a, b) => a.z - b.z).map(o => o.id);

async function scenario(mode, name, fn) {
  if (process.env.NETOPS_E2E_FILTER && !`${mode}/${name}`.includes(process.env.NETOPS_E2E_FILTER)) return;
  const mobile = mode === 'mobile';
  const context = await browser.newContext(mobile ? { ...devices['iPhone 13'] } : { viewport: { width: 1600, height: 1050 } });
  context.setDefaultTimeout(9000);
  const page = await context.newPage(), errors = [], id = `editing-${mode}-${++serial}`;
  const actions = mapActions(page, mode);
  page.on('pageerror', error => errors.push(error.message));
  const node = value => page.locator(`.react-flow__node[data-id="${value}"]`);
  const click = async locator => { await locator.scrollIntoViewIfNeeded(); if (mobile) await locator.tap(); else await locator.click(); };
  const snapshot = async () => {
    const response = await context.request.get(BASE + '/api/maps');
    assert.equal(response.status(), 200, await response.text());
    return response.json();
  };
  const currentMap = async () => (await snapshot()).maps.find(m => m.id === id);
  const saved = async predicate => {
    for (let i = 0; i < 100; i++) {
      const s = await snapshot(), m = s.maps.find(m => m.id === id);
      if (predicate(m, s)) { await page.waitForTimeout(100); return s; }
      await page.waitForTimeout(60);
    }
    throw Error('Persistência não observada: ' + predicate.toString());
  };
  const putMap = async map => {
    const s = await snapshot(); delete map.host_ids;
    const response = await context.request.put(BASE + '/api/maps/' + map.id, {
      headers: { 'If-Match': s.rev }, data: { map, hosts_rev: s.hosts_rev, topology_rev: s.topology.rev }
    });
    assert.equal(response.status(), 200, await response.text());
    return response.json();
  };
  const reload = async () => { await page.reload(); await node('host:rt-core-01').waitFor(); await page.waitForTimeout(230); };
  const saveDialog = async () => { await click(page.locator('.map-modal').getByRole('button', { name: 'Salvar', exact: true })); await page.locator('.map-modal').waitFor({ state: 'detached' }); };
  const selectMany = async ids => {
    if (mobile) {
      await actions.pane('Selecionar vários');
      for (const selected of ids) await click(node(selected));
    } else {
      await click(node(ids[0]));
      await page.keyboard.down('Control');
      for (const selected of ids.slice(1)) await click(node(selected));
      await page.keyboard.up('Control');
    }
    await page.waitForFunction(ids => ids.every(id => document.querySelector(`[data-id="${id}"]`)?.classList.contains('selected')), ids);
  };
  const clearSelection = async () => {
    await page.keyboard.press('Escape');
    await page.locator('.netops-maps').focus();
  };
  const edge = value => page.locator(`[data-line-id="${value}"][data-line-part="line"]`);
  const assertBlankEdge = async value => {
    const text = await page.locator(`.line-label[data-line-id="${value}"]`).allTextContents();
    assert.ok(text.every(t => t.replaceAll('↔', '').trim() === ''), 'ligação sem texto não recebe rótulo/velocidade/número automático: ' + text);
  };
  let baseline;
  const stamp = `${String(serial).padStart(2, '0')}-${mode}-${name}`;
  try {
    baseline = await putMap(fixture(id, mode));
    await page.goto(BASE + '/#maps'); await page.locator('#map-select').selectOption(id);
    await node('host:rt-core-01').waitFor(); await page.waitForTimeout(300);
    await fn({ page, context, actions, node, edge, click, currentMap, snapshot, saved, putMap, reload, saveDialog, selectMany, clearSelection, assertBlankEdge, baseline, id });
    assert.deepEqual(errors, [], 'sem exceções JavaScript');
    const final = await snapshot();
    await fs.writeFile(path.join(OUT, stamp + '.json'), JSON.stringify({ map: final.maps.find(m => m.id === id), hosts: final.hosts, topology: final.topology.links }, null, 2));
    await page.screenshot({ path: path.join(OUT, stamp + '.png'), fullPage: true });
    results.push({ mode, name, status: 'PASS', errors, evidence: stamp + '.json', screenshot: stamp + '.png' });
  } catch (error) {
    await page.screenshot({ path: path.join(OUT, stamp + '-failed.png'), fullPage: true }).catch(() => {});
    results.push({ mode, name, status: 'FAIL', errors, failure: error.stack, screenshot: stamp + '-failed.png' });
  } finally { await context.close(); }
  console.log(JSON.stringify(results.at(-1)));
  await fs.writeFile(path.join(OUT, 'browser-results.json'), JSON.stringify(results, null, 2));
}

try {
  for (const mode of ['desktop', 'mobile']) {
    await scenario(mode, 'shape-empty-and-optional-text', async ({ page, actions, node, saved, reload, saveDialog, currentMap }) => {
      await actions.pane('Adicionar forma');
      assert.equal(await page.locator('.map-modal textarea').inputValue(), '');
      assert.equal(await page.locator('.map-modal textarea').evaluate(e => e.required), false);
      await saveDialog();
      await saved(m => m.objects.length === 3);
      const created = (await currentMap()).objects.find(o => !['first-shape', 'second-shape'].includes(o.id));
      assert.equal(created.label || '', '');
      await reload(); assert.equal(await node('object:' + created.id).locator('.map-shape').innerText(), '');
      await actions.on(node('object:' + created.id), 'Editar');
      await page.locator('.map-modal textarea').fill('Texto colocado depois'); await saveDialog();
      await saved(m => m.objects.find(o => o.id === created.id).label === 'Texto colocado depois');
      await actions.on(node('object:' + created.id), 'Editar');
      await page.locator('.map-modal textarea').fill(''); await saveDialog();
      await saved(m => (m.objects.find(o => o.id === created.id).label || '') === '');
    });

    await scenario(mode, 'physical-link-empty-and-manual-text', async ({ page, actions, node, edge, click, saved, snapshot, reload, assertBlankEdge }) => {
      await actions.on(node('host:rt-core-01'), 'Ligar a outro dispositivo'); await click(node('host:rt-dist-01'));
      await page.locator('#link-desc').waitFor();
      assert.equal(await page.locator('#link-desc').inputValue(), '');
      await click(page.locator('.modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.locator('.modal').waitFor({ state: 'detached' });
      let s = await saved((m, s) => s.topology.links.some(l => l.a.host === 'rt-core-01' && l.b.host === 'rt-dist-01'));
      const link = s.topology.links.filter(l => l.a.host === 'rt-core-01' && l.b.host === 'rt-dist-01').at(-1);
      assert.equal(link.desc || '', ''); await assertBlankEdge(link.id);
      await reload(); await assertBlankEdge(link.id);
      await actions.on(edge(link.id), 'Editar');
      await page.locator('#link-desc').fill('Fibra escolhida pelo usuário');
      await click(page.locator('.modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.locator('.modal').waitFor({ state: 'detached' });
      await saved((m, s) => s.topology.links.find(l => l.id === link.id)?.desc === 'Fibra escolhida pelo usuário');
      assert.ok((await page.locator(`.line-label[data-line-id="${link.id}"]`).innerText()).includes('Fibra escolhida pelo usuário'));
      await actions.on(edge(link.id), 'Editar'); await page.locator('#link-desc').fill('');
      await click(page.locator('.modal').getByRole('button', { name: 'Salvar', exact: true }));
      await page.locator('.modal').waitFor({ state: 'detached' });
      await saved((m, s) => !(s.topology.links.find(l => l.id === link.id)?.desc)); await assertBlankEdge(link.id);
      assert.ok(Object.keys((await snapshot()).hosts).length === 4);
    });

    await scenario(mode, 'visual-link-empty-and-manual-text', async ({ page, actions, node, edge, click, saved, currentMap, reload, saveDialog, assertBlankEdge, baseline, snapshot }) => {
      await actions.on(node('object:first-shape'), 'Ligar a outro dispositivo'); await click(node('host:rt-dist-01'));
      await saved(m => m.visual_links.length === 1);
      const link = (await currentMap()).visual_links[0]; assert.equal(link.label || '', '');
      assert.equal(await page.locator('.modal, .map-modal').count(), 0); await assertBlankEdge('visual:' + link.id);
      await reload(); await assertBlankEdge('visual:' + link.id);
      await actions.on(edge('visual:' + link.id), 'Editar');
      assert.equal(await page.locator('.map-modal input[name="label"]').inputValue(), '');
      await page.locator('.map-modal input[name="label"]').fill('Ligação opcional'); await saveDialog();
      await saved(m => m.visual_links[0].label === 'Ligação opcional');
      assert.ok((await page.locator(`.line-label[data-line-id="visual:${link.id}"]`).innerText()).includes('Ligação opcional'));
      await actions.on(edge('visual:' + link.id), 'Editar');
      await page.locator('.map-modal input[name="label"]').fill(''); await saveDialog();
      await saved(m => !m.visual_links[0].label); await assertBlankEdge('visual:' + link.id);
      const after = await snapshot(); assert.deepEqual(after.hosts, baseline.hosts); assert.deepEqual(after.topology.links, baseline.topology.links);
    });

    await scenario(mode, 'mixed-layers-one-step-and-persistence', async ({ actions, node, currentMap, saved, reload, page }) => {
      let expected = layerOrder(await currentMap());
      async function step(id, direction) {
        const before = [...expected], index = before.indexOf(id), destination = index + (direction === 'frente' ? 1 : -1);
        [expected[index], expected[destination]] = [expected[destination], expected[index]];
        await actions.on(node(id), 'Enviar para ' + direction);
        await saved(m => JSON.stringify(layerOrder(m)) === JSON.stringify(expected));
        assert.deepEqual(layerOrder(await currentMap()), expected, 'um clique troca apenas uma camada');
        const actual = await node(id).evaluate(el => Number(getComputedStyle(el).zIndex));
        assert.equal(actual, expected.indexOf(id), 'camada persistida é a camada renderizada, inclusive na seleção');
      }
      await step('object:first-shape', 'frente'); await step('object:first-shape', 'frente');
      await step('object:first-shape', 'trás'); await step('host:rt-core-01', 'trás');
      await step('host:rt-core-01', 'trás'); await step('host:rt-core-01', 'frente');
      await reload(); assert.deepEqual(layerOrder(await currentMap()), expected);
      const domOrder = await page.locator('.react-flow__node').evaluateAll(nodes => nodes.map(n => ({ id: n.dataset.id, z: Number(getComputedStyle(n).zIndex) })).sort((a, b) => a.z - b.z).map(n => n.id));
      assert.deepEqual(domOrder, expected);
    });

    await scenario(mode, 'free-fill-stroke-hex-copy-and-persistence', async ({ page, context, actions, node, click, saveDialog, saved, currentMap, reload }) => {
      await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
      await actions.on(node('object:first-shape'), 'Editar');
      const fill = page.getByLabel('Selecionar cor de preenchimento', { exact: true });
      const stroke = page.getByLabel('Selecionar cor do contorno', { exact: true });
      assert.equal(await fill.getAttribute('type'), 'color'); assert.equal(await stroke.getAttribute('type'), 'color');
      for (const [picker, value] of [[fill, '#1a2b3c'], [stroke, '#d4e5f6']]) {
        await picker.evaluate((el, value) => { el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }, value);
      }
      assert.equal(await page.locator('input[name="color"]').inputValue(), '#1a2b3c');
      assert.equal(await page.locator('input[name="stroke"]').inputValue(), '#d4e5f6');
      await click(page.getByRole('button', { name: 'Copiar cor de preenchimento', exact: true }));
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), '#1a2b3c');
      await click(page.getByRole('button', { name: 'Copiar cor do contorno', exact: true }));
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), '#d4e5f6');
      await saveDialog(); await saved(m => m.objects[0].color === '#1a2b3c' && m.objects[0].stroke === '#d4e5f6');
      await reload();
      assert.deepEqual(await node('object:first-shape').locator('.map-shape').evaluate(el => ({ fill: getComputedStyle(el).backgroundColor, stroke: getComputedStyle(el).borderTopColor })), { fill: 'rgb(26, 43, 60)', stroke: 'rgb(212, 229, 246)' });
      await actions.on(node('object:second-shape'), 'Editar');
      await page.locator('input[name="color"]').fill('#1a2b3c');
      await page.locator('input[name="stroke"]').fill('#d4e5f6');
      await page.locator('input[name="stroke"]').blur();
      assert.equal(await page.getByLabel('Selecionar cor de preenchimento', { exact: true }).inputValue(), '#1a2b3c');
      assert.equal(await page.getByLabel('Selecionar cor do contorno', { exact: true }).inputValue(), '#d4e5f6');
      await saveDialog(); await saved(m => m.objects[1].color === '#1a2b3c' && m.objects[1].stroke === '#d4e5f6');
      assert.equal((await currentMap()).objects[0].color, (await currentMap()).objects[1].color);
    });

    await scenario(mode, 'duplicate-preserves-style-and-is-independent', async ({ page, actions, node, currentMap, saved, saveDialog, reload }) => {
      await actions.on(node('object:first-shape'), 'Editar');
      await page.locator('.map-modal textarea').fill('');
      await page.locator('.map-modal select[name="form"]').selectOption('ellipse');
      await page.locator('input[name="color"]').fill('#2a6b8c'); await page.locator('input[name="stroke"]').fill('#ca8b1d');
      await page.locator('.map-modal').getByRole('button', { name: 'Ícone Cloud', exact: true }).click();
      await saveDialog(); await saved(m => m.objects[0].icon === 'cloud');
      const original = structuredClone((await currentMap()).objects[0]);
      await actions.on(node('object:first-shape'), 'Duplicar'); await saved(m => m.objects.length === 3);
      const clone = (await currentMap()).objects.find(o => !['first-shape', 'second-shape'].includes(o.id));
      for (const key of ['type', 'label', 'form', 'width', 'height', 'icon', 'color', 'stroke']) assert.equal(clone[key], original[key], key);
      assert.notEqual(clone.id, original.id); assert.notDeepEqual(clone.position, original.position);
      // A cópia selecionada abre a edição pelo teclado mesmo quando cobre a forma original.
      await node('object:' + clone.id).focus(); await page.keyboard.press('Shift+F10'); await actions.choose('Editar');
      await page.locator('.map-modal textarea').fill('Só a cópia'); await page.locator('input[name="color"]').fill('#f1e2d3');
      await saveDialog(); await saved(m => m.objects.find(o => o.id === clone.id).label === 'Só a cópia');
      assert.deepEqual((await currentMap()).objects.find(o => o.id === original.id), original);
      await reload(); assert.equal((await currentMap()).objects.find(o => o.id === clone.id).color, '#f1e2d3');
      await actions.on(node('object:' + clone.id), 'Duplicar'); await saved(m => m.objects.length === 4);
      const immediateCopy = (await currentMap()).objects.find(o => !['first-shape', 'second-shape', clone.id].includes(o.id));
      await page.keyboard.press('Delete');
      await saved(m => !m.objects.some(o => o.id === immediateCopy.id));
      assert.equal((await currentMap()).objects.length, 3, 'Delete logo após duplicar remove a nova cópia');
    });

    await scenario(mode, 'delete-shape-and-protect-text-editing', async ({ page, actions, node, click, saved, currentMap, baseline, snapshot }) => {
      await actions.on(node('object:first-shape'), 'Editar');
      const before = structuredClone(await currentMap());
      await page.locator('.map-modal textarea').fill('Texto seguro'); await page.locator('.map-modal textarea').focus();
      await page.keyboard.press('Home'); await page.keyboard.press('Delete');
      assert.equal((await currentMap()).objects.length, before.objects.length);
      assert.equal(await node('object:first-shape').count(), 1);
      await click(page.locator('.map-modal').getByRole('button', { name: 'Cancelar', exact: true }));
      await click(node('object:first-shape')); await node('object:first-shape').focus(); await page.keyboard.press('Delete');
      await saved(m => !m.objects.some(o => o.id === 'first-shape'));
      assert.equal(await node('object:first-shape').count(), 0);
      const after = await snapshot(); assert.deepEqual(after.hosts, baseline.hosts); assert.deepEqual(after.topology.links, baseline.topology.links);
    });

    await scenario(mode, 'group-delete-does-not-delete-inventory', async ({ page, actions, node, click, selectMany, saved, snapshot, currentMap, baseline }) => {
      await actions.on(node('object:first-shape'), 'Ligar a outro dispositivo'); await click(node('host:rt-core-01'));
      await saved(m => m.visual_links.length === 1);
      await selectMany(['host:rt-core-01', 'object:first-shape']);
      if (mode === 'mobile') {
        await click(page.getByRole('button', { name: 'Ações do mapa', exact: true }));
        await actions.choose('Remover seleção do mapa');
      } else { await node('host:rt-core-01').focus(); await page.keyboard.press('Delete'); }
      await saved(m => !m.members.includes('rt-core-01') && !m.objects.some(o => o.id === 'first-shape'));
      assert.equal((await currentMap()).visual_links.length, 0);
      const after = await snapshot(); assert.deepEqual(after.hosts, baseline.hosts); assert.deepEqual(after.topology.links, baseline.topology.links);
      assert.ok(after.maps.find(m => m.id === 'all').host_ids.includes('rt-core-01'));
    });
  }

  await scenario('desktop', 'plain-marquee-mixed-move-and-delete', async ({ page, node, currentMap, saved, snapshot, baseline }) => {
    const selected = ['host:rt-core-01', 'object:first-shape'];
    const boxes = await Promise.all(selected.map(id => node(id).boundingBox()));
    const start = { x: Math.min(...boxes.map(b => b.x)) - 14, y: Math.min(...boxes.map(b => b.y)) - 14 };
    const end = { x: Math.max(...boxes.map(b => b.x + b.width)) + 14, y: Math.max(...boxes.map(b => b.y + b.height)) + 14 };
    const beforeTransform = await page.locator('.react-flow__viewport').getAttribute('style');
    await page.mouse.move(start.x, start.y); await page.mouse.down();
    await page.mouse.move(end.x, end.y, { steps: 20 }); await page.mouse.up();
    await page.waitForFunction(ids => ids.every(id => document.querySelector(`[data-id="${id}"]`)?.classList.contains('selected')), selected);
    assert.deepEqual((await page.locator('.react-flow__node.selected').evaluateAll(ns => ns.map(n => n.dataset.id))).sort(), [...selected].sort());
    assert.equal(await page.locator('.react-flow__viewport').getAttribute('style'), beforeTransform, 'arraste simples seleciona sem mover o fundo');
    const before = structuredClone(await currentMap()), group = page.locator('.react-flow__nodesselection-rect'), r = await group.boundingBox();
    const zoom = await page.locator('.react-flow__viewport').evaluate(el => new DOMMatrix(el.style.transform).a);
    await page.mouse.move(r.x + r.width / 2, r.y + r.height / 2); await page.mouse.down();
    await page.mouse.move(r.x + r.width / 2 + 65, r.y + r.height / 2 + 36, { steps: 16 }); await page.mouse.up();
    await saved(m => Math.abs(m.positions['rt-core-01'].x - before.positions['rt-core-01'].x) > 20);
    const after = await currentMap();
    const hostDelta = { x: after.positions['rt-core-01'].x - before.positions['rt-core-01'].x, y: after.positions['rt-core-01'].y - before.positions['rt-core-01'].y };
    const shapeDelta = { x: after.objects[0].position.x - before.objects[0].position.x, y: after.objects[0].position.y - before.objects[0].position.y };
    assert.ok(Math.abs(hostDelta.x - 65 / zoom) < 1 && Math.abs(hostDelta.y - 36 / zoom) < 1);
    assert.ok(Math.abs(hostDelta.x - shapeDelta.x) < .1 && Math.abs(hostDelta.y - shapeDelta.y) < .1);
    assert.deepEqual(after.positions['rt-dist-01'], before.positions['rt-dist-01']); assert.deepEqual(after.objects[1], before.objects[1]);
    await node('host:rt-core-01').focus(); await page.keyboard.press('Delete');
    await saved(m => !m.members.includes('rt-core-01') && !m.objects.some(o => o.id === 'first-shape'));
    const final = await snapshot(); assert.deepEqual(final.hosts, baseline.hosts); assert.deepEqual(final.topology.links, baseline.topology.links);
  });

  await scenario('desktop', 'read-only-and-automatic-map-host-protection', async ({ page, actions, node, click, snapshot, currentMap, baseline }) => {
    await page.locator('#map-select').selectOption('all'); await node('host:rt-core-01').focus(); await page.keyboard.press('Delete');
    await page.waitForTimeout(200);
    assert.ok((await snapshot()).maps.find(m => m.id === 'all').host_ids.includes('rt-core-01'));
    await page.route('**/api/maps', async route => { const response = await route.fetch(); const data = await response.json(); await route.fulfill({ response, json: { ...data, read_only: true } }); });
    await page.reload(); await node('host:rt-core-01').waitFor();
    await actions.item(node('host:rt-core-01'));
    for (const label of ['Editar', 'Enviar para frente', 'Enviar para trás', 'Duplicar', 'Remover do mapa']) assert.equal(await page.getByRole('menuitem', { name: label, exact: true }).count(), 0);
    await page.keyboard.press('Escape'); await node('host:rt-core-01').focus(); await page.keyboard.press('Delete');
    const after = await snapshot(); assert.deepEqual(after.hosts, baseline.hosts); assert.deepEqual(after.topology.links, baseline.topology.links);
    assert.equal((await currentMap()).objects.length, 2);
  });

  await scenario('desktop', 'automatic-map-partial-delete-reconciles-real-state', async ({ page, context, node, click, snapshot, putMap, selectMany }) => {
    const unique = Date.now(), first = `partial-first-${unique}`, second = `partial-second-${unique}`;
    for (const [id, ip] of [[first, '192.0.2.101'], [second, '192.0.2.102']]) {
      const s = await snapshot();
      const response = await context.request.post(BASE + '/api/hosts', { headers: { 'If-Match': s.hosts_rev },
        data: { id, hostname: id, mgmt_ip: ip, vendor: 'linux', role: 'other', site: 'fixture' } });
      assert.equal(response.status(), 201, await response.text());
    }
    const all = structuredClone((await snapshot()).maps.find(m => m.id === 'all'));
    all.positions = { ...fixture('unused', 'desktop').positions, [first]: { x: 80, y: 730 }, [second]: { x: 520, y: 730 } };
    all.objects = [{ id: 'partial-delete-shape', type: 'shape', label: 'Preservada após falha', form: 'rect', position: { x: 300, y: 270 }, width: 200, height: 120 }];
    all.visual_links = [];
    await putMap(all);
    await page.reload(); await page.locator('#map-select').selectOption('all'); await node('host:' + first).waitFor();
    await selectMany(['host:' + first, 'host:' + second, 'object:partial-delete-shape']);
    const calls = [];
    page.on('request', request => { if (request.method() === 'DELETE' && request.url().includes('/api/hosts/')) calls.push(request.url().split('/').at(-1)); });
    await page.route('**/api/hosts/' + second, route => route.request().method() === 'DELETE'
      ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Falha de teste no segundo host' }) })
      : route.continue());
    await node('host:' + first).focus(); await page.keyboard.press('Delete');
    await click(page.locator('.modal').getByRole('button', { name: 'Confirmar', exact: true }));
    await page.getByText('1 host(s) já removido(s). A exclusão parou; confira a seleção restante antes de tentar novamente.', { exact: true }).waitFor();
    const after = await snapshot();
    assert.equal(after.hosts[first], undefined); assert.ok(after.hosts[second]);
    assert.deepEqual(calls, [first, second], 'segunda revisão encadeada antes da falha simulada');
    assert.ok(after.maps.find(m => m.id === 'all').objects.some(o => o.id === 'partial-delete-shape'));
    await node('host:' + first).waitFor({ state: 'detached' }); await node('host:' + second).waitFor();
    await node('object:partial-delete-shape').waitFor();
    await page.unroute('**/api/hosts/' + second);
    const cleanup = await context.request.delete(BASE + '/api/hosts/' + second, { headers: { 'If-Match': after.hosts_rev } });
    assert.equal(cleanup.status(), 200, await cleanup.text());
  });

  // Último cenário: exclui dois hosts fictícios do inventário da fixture.
  await scenario('desktop', 'automatic-map-delete-cancel-and-confirm', async ({ page, node, click, snapshot, putMap, selectMany, baseline }) => {
    const all = structuredClone((await snapshot()).maps.find(m => m.id === 'all'));
    all.positions = fixture('unused', 'desktop').positions;
    all.objects = [{ id: 'delete-with-host', type: 'shape', label: '', form: 'rect', position: { x: 80, y: 270 }, width: 200, height: 120 }];
    all.visual_links = [{ id: 'delete-with-host-link', source: 'host:rt-core-01', target: 'object:delete-with-host', label: '' }];
    await putMap(all);
    await page.reload(); await page.locator('#map-select').selectOption('all'); await node('object:delete-with-host').waitFor();
    await selectMany(['host:rt-core-01', 'host:rt-dist-01', 'object:delete-with-host']);
    await node('host:rt-core-01').focus(); await page.keyboard.press('Delete');
    await page.locator('.modal').getByRole('heading', { name: 'Confirmar exclusão', exact: true }).waitFor();
    const untouched = await snapshot(); assert.deepEqual(untouched.hosts, baseline.hosts);
    assert.ok(untouched.maps.find(m => m.id === 'all').objects.some(o => o.id === 'delete-with-host'));
    await click(page.locator('.modal').getByRole('button', { name: 'Cancelar', exact: true }));
    assert.deepEqual((await snapshot()).hosts, baseline.hosts);
    await node('host:rt-core-01').focus(); await page.keyboard.press('Delete');
    await click(page.locator('.modal').getByRole('button', { name: 'Confirmar', exact: true }));
    await page.locator('.modal').waitFor({ state: 'detached' });
    let final;
    for (let i = 0; i < 100; i++) {
      final = await snapshot();
      if (!final.hosts['rt-core-01'] && !final.maps.find(m => m.id === 'all').objects.some(o => o.id === 'delete-with-host')) break;
      await page.waitForTimeout(60);
    }
    assert.equal(final.hosts['rt-core-01'], undefined); assert.equal(final.hosts['rt-dist-01'], undefined);
    assert.deepEqual(Object.keys(final.hosts).sort(), Object.keys(baseline.hosts).filter(id => !['rt-core-01', 'rt-dist-01'].includes(id)).sort());
    assert.ok(final.topology.links.every(l => !['rt-core-01', 'rt-dist-01'].includes(l.a.host) && !['rt-core-01', 'rt-dist-01'].includes(l.b.host)));
    assert.ok(final.maps.every(m => !m.host_ids.some(id => ['rt-core-01', 'rt-dist-01'].includes(id)) && !m.visual_links.some(l => ['host:rt-core-01', 'host:rt-dist-01'].includes(l.source) || ['host:rt-core-01', 'host:rt-dist-01'].includes(l.target))));
    assert.equal(final.maps.find(m => m.id === 'all').objects.length, 0);
  });
} finally { await browser.close(); }

console.log(JSON.stringify({ passed: results.filter(r => r.status === 'PASS').length, failed: results.filter(r => r.status === 'FAIL').length, output: OUT }));
if (results.some(r => r.status === 'FAIL')) process.exitCode = 1;
