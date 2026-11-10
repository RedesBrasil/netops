// Estabilidade visual e concorrência no arraste. Somente dados fictícios isolados.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
if (!(await (await fetch(BASE + '/api/config/meta')).json()).isolated_data) throw Error('Teste recusa inventário real. Use NETOPS_UI_DATA_ROOT.');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const timeout = (promise, label) => Promise.race([promise, new Promise((_, reject) => { const t = setTimeout(() => reject(Error('Timeout: ' + label)), 8000); t.unref(); })]);
const results = [];
try {
  for (const [mode, options] of [['desktop', { viewport: { width: 1440, height: 950 } }], ['mobile', { ...devices['iPhone 13'] }]]) {
    const context = await browser.newContext(options), page = await context.newPage(), errors = [], passed = [];
    page.on('pageerror', e => errors.push(e.message));
    const get = async () => (await context.request.get(BASE + '/api/maps')).json();
    const node = id => page.locator(`.react-flow__node[data-id="${id}"]`);
    const position = id => node(id).evaluate(el => { const m = new DOMMatrix(el.style.transform); return { x: m.m41, y: m.m42 }; });
    const close = (a, b) => Math.abs(a.x - b.x) < .02 && Math.abs(a.y - b.y) < .02;
    const releases = [];
    let touch;
    async function startDrag(id, dx, dy) {
      if (mode === 'mobile') { dx *= 2.5; dy *= 2.5; }
      const box = await node(id).boundingBox();
      assert.ok(box);
      const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
      if (mode === 'mobile') {
        touch = await context.newCDPSession(page);
        await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...from, id: 0 }] });
        for (let i = 1; i <= 12; i++) {
          await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: from.x + dx * i / 12, y: from.y + dy * i / 12, id: 0 }] });
          await page.waitForTimeout(18);
        }
      } else {
        await page.mouse.move(from.x, from.y); await page.mouse.down();
        await page.mouse.move(from.x + dx, from.y + dy, { steps: 12 });
      }
      return { x: from.x + dx, y: from.y + dy };
    }
    async function endDrag() {
      if (touch) { await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); await touch.detach(); touch = null; }
      else await page.mouse.up();
    }
    async function drag(id, dx, dy) {
      const before = await position(id);
      await startDrag(id, dx, dy);
      await endDrag();
      assert.ok(!close(await position(id), before), 'gesto deve realmente mover ' + id);
    }
    async function savedPosition(id, expected) {
      for (let i = 0; i < 100; i++) {
        const data = await get();
        if (close(data.maps.find(m => m.id === 'all').positions[id.slice(5)] || {}, expected)) return;
        await page.waitForTimeout(40);
      }
      throw Error('Última posição não foi salva para ' + id);
    }
    function hold(method, responseAfterRequest = true) {
      let release, enter;
      const gate = new Promise(resolve => { release = resolve; });
      const entered = new Promise(resolve => { enter = resolve; });
      releases.push(() => release());
      let handled = false;
      const handler = async route => {
        if (handled || route.request().method() !== method) return route.continue();
        handled = true;
        let response;
        if (responseAfterRequest) response = await route.fetch();
        enter(); await gate;
        if (!response) response = await route.fetch();
        await route.fulfill({ response });
      };
      return { handler, entered, release: () => release() };
    }
    try {
      let s = await get(), map = structuredClone(s.maps.find(m => m.id === 'all'));
      delete map.host_ids;
      map.positions = { 'rt-core-01': { x: 60, y: 60 }, 'rt-dist-01': { x: 410, y: 100 }, 'sw-access-01': { x: 60, y: 340 }, 'srv-web-01': { x: 410, y: 390 } };
      map.objects = [{ id: 'area', type: 'shape', label: 'Área de teste', position: { x: 730, y: 280 }, width: 240, height: 180 }];
      map.visual_links = [];
      const reset = await context.request.put(BASE + '/api/maps/all', { headers: { 'If-Match': s.rev }, data: { map, hosts_rev: s.hosts_rev, topology_rev: s.topology.rev } });
      assert.equal(reset.status(), 200);
      await page.goto(BASE + '/#maps');
      await page.locator('.netops-maps').waitFor();
      await node('host:rt-core-01').waitFor();
      await node('host:rt-dist-01').waitFor();
      await page.waitForTimeout(450);
      // Registra também visibilidade transitória, não apenas o estado após o gesto.
      await page.evaluate(() => {
        window.dragVisibility = [];
        const root = document.querySelector('.react-flow__nodes');
        const check = (el, reason) => { if (el.style.visibility === 'hidden') window.dragVisibility.push({ id: el.dataset.id, reason }); };
        const observer = new MutationObserver(records => {
          for (const r of records) if (r.type === 'attributes' && r.target.matches('.react-flow__node')) {
            if (r.oldValue?.includes('visibility: hidden')) window.dragVisibility.push({ id: r.target.dataset.id, reason: 'style-before' });
            check(r.target, 'style-after');
          }
        });
        observer.observe(root, { subtree: true, attributes: true, attributeOldValue: true, attributeFilter: ['style'] });
        const frame = () => { for (const el of root.children) check(el, 'frame'); window.dragFrame = requestAnimationFrame(frame); };
        frame();
      });
      const a = 'host:rt-core-01', b = 'host:rt-dist-01';
      for (let i = 0; i < 6; i++) {
        const sign = Math.floor(i / 2) % 2 ? -1 : 1;
        await drag(i % 2 ? b : a, (i % 2 ? -8 : 8) * sign, 7 * sign);
        await savedPosition(i % 2 ? b : a, await position(i % 2 ? b : a));
      }
      passed.push('arrastes repetidos mantêm hosts e enlaces visíveis em todos os frames');
      assert.deepEqual(await page.evaluate(() => window.dragVisibility), []);
      // Um GET obtido antes do gesto não pode voltar o host à posição anterior.
      const read = hold('GET');
      await page.route('**/api/maps', read.handler);
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      await timeout(read.entered, mode + ' GET interceptado');
      await drag(a, 12, 9);
      const latest = await position(a);
      await savedPosition(a, latest);
      read.release();
      await page.waitForTimeout(150);
      assert.ok(close(await position(a), latest), 'resposta GET antiga não pode desfazer arraste');
      await page.unroute('**/api/maps', read.handler);
      passed.push('resposta atrasada do polling não sobrescreve o último movimento');
      // A confirmação de um PUT anterior chega no meio de outro gesto.
      const write = hold('PUT');
      await page.route('**/api/maps/all', write.handler);
      await drag(a, -8, 8);
      await timeout(write.entered, mode + ' PUT interceptado');
      await startDrag(b, 10, 10);
      const inGesture = await position(b);
      write.release();
      await page.waitForTimeout(130);
      assert.ok(close(await position(b), inGesture), 'ack antigo não pode interromper o gesto atual');
      await endDrag();
      await page.unroute('**/api/maps/all', write.handler);
      await savedPosition(b, await position(b));
      passed.push('autosave lento de outro host não interrompe o arraste em andamento');
      // Coalescer dois movimentos antes de a primeira gravação retornar.
      const queued = hold('PUT', false);
      await page.route('**/api/maps/all', queued.handler);
      await drag(a, 8, 6); await timeout(queued.entered, mode + ' PUT em fila');
      await drag(a, 9, -7); await drag(b, -9, -8);
      const finalA = await position(a), finalB = await position(b);
      queued.release();
      await savedPosition(a, finalA); await savedPosition(b, finalB);
      await page.unroute('**/api/maps/all', queued.handler);
      passed.push('fila de salvamento preserva a última posição de ambos os hosts');
      // Poll sem mudanças não reconstrói os nós nem dispara outro PUT.
      let writes = 0;
      const track = r => { if (r.method() === 'PUT' && r.url().includes('/api/maps/')) writes++; };
      page.on('request', track);
      for (let i = 0; i < 3; i++) {
        const got = page.waitForResponse(r => r.request().method() === 'GET' && r.url().endsWith('/api/maps'));
        await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await timeout(got, mode + ' focus polling');
        await page.waitForTimeout(70);
      }
      assert.equal(writes, 0); page.off('request', track);
      assert.ok(close(await position(a), finalA)); assert.ok(close(await position(b), finalB));
      assert.deepEqual(await page.evaluate(() => window.dragVisibility), []);
      await page.screenshot({ path: `/tmp/netops-drag-stability-${mode}.png` });
      passed.push('atualização sem mudanças mantém visibilidade, posição e não grava novamente');
      await page.reload(); await node(a).waitFor(); await page.waitForTimeout(200);
      assert.ok(close(await position(a), finalA)); assert.ok(close(await position(b), finalB));
      passed.push('recarregar confirma a persistência das posições mais recentes');
      assert.deepEqual(errors, []);
      results.push({ mode, status: 'PASS', passed, errors });
    } catch (e) {
      await page.screenshot({ path: `/tmp/netops-drag-stability-${mode}-failed.png` });
      results.push({ mode, status: 'FAIL', passed, errors, failure: e.stack });
    }
    for (const release of releases) release();
    await context.close();
  }
} finally { await browser.close(); }
await fs.writeFile('/tmp/netops-drag-stability-results.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
if (results.some(r => r.status === 'FAIL')) process.exitCode = 1;
