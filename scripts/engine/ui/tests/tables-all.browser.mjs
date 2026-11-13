// Smoke: toda tela com tabela usa o DataTable (layout fixo + ⚙ Colunas), e o menu oculta/reexibe coluna.
// Uso: tests/e2e-env.sh up && PLAYWRIGHT_MODULE=... CHROMIUM_EXECUTABLE=... node tests/tables-all.browser.mjs
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
if (!(await (await fetch(BASE + '/api/config/meta')).json()).isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT.');
// [hash, tableId]: telas sem dados no ambiente isolado só exibem o vazio (aceito, informado no log)
const PAGES = [['#hosts', 'hosts'], ['#groups', 'groups'], ['#credentials', 'credentials'], ['#practices', 'best-practices'],
  ['#configs', 'config-examples'], ['#workflows', 'workflows'], ['#agents', 'agents'], ['#reports', 'reports'], ['#runs', 'runs'],
  ['#memory/notas', 'memory-notes'], ['#scripts', 'skills'], ['#scripts?tab=scripts', 'scripts'],
  ['#schedules/runs', 'schedule-runs'], ['#backups/storage', 'backup-storage']];
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
let failed = 0;
try {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  for (const [hash, id] of PAGES) {
    try {
      await page.goto(BASE + '/' + hash);
      const table = page.locator(`table.rt[data-table="${id}"]`), empty = page.locator('.empty, .bk-empty');
      await Promise.race([table.waitFor({ timeout: 15000 }), empty.first().waitFor({ timeout: 15000 })]);
      if (!(await table.count())) { console.log(`--   ${hash} (sem dados no ambiente isolado)`); continue; }
      await page.locator(`table.rt-fixed[data-table="${id}"]`).waitFor();
      const heads = () => table.locator('thead th.rt-th:not(.rt-pinned)').count();
      const n0 = await heads();
      await table.locator('.rt-cols-btn').click();
      const free = page.locator('.rt-menu .rt-menu-row input:not([disabled])');
      if (await free.count()) {
        await free.first().click(); assert.equal(await heads(), n0 - 1, 'ocultar coluna');
        await free.first().click(); assert.equal(await heads(), n0, 'reexibir coluna');
      }
      await page.keyboard.press('Escape');
      await page.evaluate((k) => localStorage.removeItem('netops.table.' + k), id);
      console.log(`OK   ${hash} (${n0} colunas)`);
    } catch (e) { failed++; console.log(`FAIL ${hash} - ${e.message.split('\n')[0]}`); }
  }
  assert.deepEqual(errors, [], 'sem erros de página');
} finally { await browser.close(); }
if (failed) process.exit(1);
