// UI servida pelo launcher em instalação temporária. Releases da UI são fixtures interceptadas.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL;
const root = process.env.NETOPS_UPDATE_TEST_ROOT;
if (!BASE || !root || !root.startsWith('/tmp/') || path.basename(root) !== 'installation') throw Error('Teste exige cópia completa em /tmp.');
await fs.access(path.join(root, '.netops-update/installed.json'));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
try {
  for (const mobile of [false, true]) {
    const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1366, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const result = { current_version: '1.0.0', managed: true, read_only: false, job: {}, can_apply: true,
      releases: [2, 1].map(i => ({ id: i, tag: `v1.${i}.0`, version: `1.${i}.0`, published_at: '2026-11-10T12:00:00Z',
        changelog: `Novidades da versão ${i}\n<script>window.NOTES_XSS = true</script>`, url: `https://github.com/RedesBrasil/netops/releases/tag/v1.${i}.0`, installable: true })) };
    await page.route('**/api/updates/check', r => r.fulfill({ json: result }));
    await page.goto(BASE + '/#settings');
    await page.getByRole('button', { name: 'Verificar atualizações', exact: true }).click();
    await page.getByRole('region', { name: 'Atualizações' }).waitFor();
    assert.equal(await page.locator('.update-release').count(), 2);
    assert.equal(await page.locator('.update-release script').count(), 0);
    assert.equal(await page.evaluate(() => window.NOTES_XSS), undefined);
    await page.getByRole('button', { name: 'Atualizar para v1.2.0', exact: true }).click();
    await page.getByRole('button', { name: 'Criar backup e atualizar', exact: true }).waitFor();
    // Exercita confirmação e retomada sem tocar na API real de aplicação.
    const job = { id: 'fixture-browser-job', phase: 'queued', version: '1.2.0' };
    let applied = 0;
    await page.route('**/api/updates/apply', async r => {
      assert.deepEqual(r.request().postDataJSON(), { release_id: 2, confirm: true });
      applied++;
      await r.fulfill({ status: 202, json: job });
    });
    await page.route('**/api/updates/status', r => r.fulfill({ json: { ...result, job } }));
    await page.getByRole('button', { name: 'Criar backup e atualizar', exact: true }).click();
    await page.getByText('Atualização confirmada', { exact: true }).waitFor();
    assert.equal(applied, 1);
    await page.reload();
    await page.getByRole('region', { name: 'Atualizações' }).waitFor();
    job.phase = 'completed'; job.detail = 'Fixture concluída';
    await page.getByRole('button', { name: 'Recarregar interface atualizada' }).waitFor();
    assert.equal(await page.evaluate(() => sessionStorage.getItem('netops_update_job')), null);
    await page.screenshot({ path: `/tmp/netops-updates-${mobile ? 'mobile' : 'desktop'}.png` });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log('PASS: changelogs intermediários, escape de HTML, confirmação, retomada, conclusão e layout desktop/celular.');
} finally { await browser.close(); }
