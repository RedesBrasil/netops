// Layout de colunas do ResourceTable (tableId) na tela de Hosts: redimensionar, auto-ajuste,
// mostrar/ocultar, reordenar (arrastar e ↑↓), persistência e "Restaurar padrão".
// Uso: tests/e2e-env.sh up && PLAYWRIGHT_MODULE=... CHROMIUM_EXECUTABLE=... node tests/table-columns.browser.mjs
import assert from 'node:assert/strict';
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
if (!(await (await fetch(BASE + '/api/config/meta')).json()).isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT.');
const SHOT = process.env.NETOPS_E2E_SHOTS;   // pasta opcional p/ screenshots
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
const DEFAULT = ['ID', 'NOME DO HOST', 'IP', 'VENDOR', 'ROLE', 'GRUPO', 'ACESSO'];
try {
  for (const [mode, options] of [['desktop', { viewport: { width: 1440, height: 900 } }], ['mobile', { ...devices['iPhone 13'] }]]) {
    const context = await browser.newContext(options), page = await context.newPage(), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const heads = async () => (await page.locator('table.rt thead th.rt-th .rt-th-label').allInnerTexts()).map((t) => t.replace(/[▲▼⇅]/g, '').trim().toUpperCase());
    const th = (label) => page.locator('table.rt thead th.rt-th').filter({ has: page.locator('.rt-th-label', { hasText: new RegExp('^' + label, 'i') }) });
    const width = async (label) => Math.round((await th(label).boundingBox()).width);
    const menu = () => page.locator('.rt-menu');
    const openMenu = async () => { if (!(await menu().count())) await page.locator('.rt-cols-btn').click(); await menu().waitFor(); };
    const row = (label) => menu().locator('.rt-menu-row').filter({ hasText: label });
    const load = async () => { await page.goto(BASE + '/#hosts'); await page.locator('table.rt.rt-fixed').waitFor(); };

    await load();
    assert.deepEqual(await heads(), DEFAULT, 'ordem padrão');

    if (mode === 'desktop') {
      // Redimensionar ao vivo + persistência
      const w0 = await width('IP');
      const h = await th('IP').locator('.rt-resize').boundingBox();
      await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2); await page.mouse.down();
      await page.mouse.move(h.x + 40, h.y + h.height / 2); await page.mouse.move(h.x + 90, h.y + h.height / 2);
      const live = await width('IP');
      await page.mouse.up();
      assert.ok(Math.abs(live - (w0 + 90)) <= 6, `largura ao vivo ${live} ≈ ${w0 + 90}`);
      assert.equal(page.url().includes('sort='), false, 'soltar o redimensionamento não ordena');
      await load();
      assert.ok(Math.abs((await width('IP')) - (w0 + 90)) <= 6, 'largura persiste após recarregar');

      // Duplo clique = ajusta ao conteúdo (encolhe a coluna larga)
      await th('IP').locator('.rt-resize').dblclick();
      assert.ok((await width('IP')) < w0 + 90, 'auto-ajuste encolheu');

      // Ordenar continua funcionando (URL)
      await th('IP').locator('.rt-th-label').click();
      await page.waitForFunction(() => location.hash.includes('sort=mgmt_ip'));

      // Arrastar GRUPO para antes de ID
      await th('Grupo').dragTo(th('ID'), { targetPosition: { x: 5, y: 10 } });
      assert.deepEqual((await heads()).slice(0, 2), ['GRUPO', 'ID'], 'arrastar reordena');
    }

    // Mostrar/ocultar pelo menu
    await openMenu();
    assert.ok(await row('Nome do host').locator('input').isDisabled(), 'coluna obrigatória não se oculta');
    await row('Role').locator('input').click();
    await row('Credencial').locator('input').click();
    assert.ok(!(await heads()).includes('ROLE') && (await heads()).includes('CREDENCIAL'), 'ocultar/mostrar');
    // ↑ move VENDOR para a esquerda (troca com IP no menu)
    const before = await heads();
    await row('Vendor').getByRole('button', { name: /esquerda/ }).click();
    const after = await heads();
    assert.ok(after.indexOf('VENDOR') < before.indexOf('VENDOR'), 'botão ↑ move a coluna');
    if (SHOT) await page.screenshot({ path: `${SHOT}/hosts-cols-${mode}.png` });
    await page.keyboard.press('Escape'); await menu().waitFor({ state: 'detached' });

    // Persistência do layout
    await load();
    assert.deepEqual(await heads(), after, 'layout persiste após recarregar');
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('netops.table.hosts')));
    assert.equal(stored.vis.role, false); assert.equal(stored.vis.credential, true);

    // Restaurar padrão
    await openMenu();
    await menu().getByRole('button', { name: 'Restaurar padrão' }).click();
    assert.deepEqual(await heads(), DEFAULT, 'restaurar volta ao padrão');
    assert.equal(await page.evaluate(() => localStorage.getItem('netops.table.hosts')), null);

    // Clique na linha ainda abre o host
    await page.keyboard.press('Escape');
    await page.locator('table.rt tbody tr').first().locator('td').nth(2).click();
    await page.waitForFunction(() => /^#hosts\/\d+/.test(location.hash));

    assert.deepEqual(errors, [], 'sem erros de página');
    console.log(`ok ${mode}`);
    await context.close();
  }
} finally { await browser.close(); }
