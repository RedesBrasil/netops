// Clique de atualização REAL em instalação legada fictícia; nenhuma API interceptada.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { mapActions } from './maps-actions.mjs';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL, root = process.env.NETOPS_UPDATE_TEST_ROOT;
if (!BASE || !root || !root.startsWith('/tmp/') || path.basename(root) !== 'installation' || new URL(BASE).hostname !== '127.0.0.1') {
  throw Error('Teste exige instalação completa fictícia em /tmp e loopback.');
}
const old = JSON.parse(await fs.readFile(path.join(root, '.netops-update/installed.json'), 'utf8'));
assert.ok(['1.3.0', '1.2.1'].includes(old.version));
const before = await (await fetch(BASE + '/api/config/meta')).json();
assert.equal(before.isolated_data, true);
const output = process.env.NETOPS_E2E_OUTPUT || path.join(root, '..', 'browser');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
process.once('SIGTERM', async () => { await browser.close(); process.exit(143); });
const result = { from: before.version, to: '2.0.0', status: 'RUNNING', checks: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } }), errors = [], applies = [];
  page.setDefaultTimeout(30000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/updates/apply') applies.push(request.postDataJSON());
  });
  const login = async () => {
    await page.locator('.login-screen').waitFor();
    await page.locator('input[type=password]').fill('fixture-migration-update-master');
    await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    await page.locator('.shell').waitFor();
  };
  await page.goto(BASE + '/#maps');
  await login();
  await page.getByRole('button', { name: 'Verificar atualizações', exact: true }).click();
  await page.getByRole('region', { name: 'Atualizações' }).waitFor();
  await page.getByRole('button', { name: 'Atualizar para v2.0.0', exact: true }).click();
  const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/updates/apply' && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Criar backup e atualizar', exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 202, await response.text());
  assert.deepEqual(applies, [{ release_id: 202000, confirm: true }]);
  result.checks.push('botões Verificar, Atualizar e confirmação chamam API real sem interceptação');
  await page.screenshot({ path: path.join(output, 'update-requested.png') });
  let updated;
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    try {
      const meta = await (await fetch(BASE + '/api/config/meta')).json();
      if (meta.version === '2.0.0' && meta.boot_id !== before.boot_id && meta.host_migration?.blocking === false) { updated = meta; break; }
    } catch {}
    await page.waitForTimeout(100);
  }
  assert.ok(updated, 'A versão candidata precisa iniciar na mesma URL automaticamente.');
  result.checks.push('supervisor reinicia automaticamente na mesma URL com versão e boot novos');
  await page.reload();
  await login();
  await page.locator('.netops-maps').waitFor();
  // O painel de progresso é reaberto pela sessão do atualizador após recarregar.
  const updates = page.getByRole('region', { name: 'Atualizações' });
  if (await updates.isVisible()) await updates.getByRole('button', { name: 'Fechar', exact: true }).click();
  const host = page.locator('.react-flow__node[data-id="host:1"]');
  await host.waitFor();
  const actions = mapActions(page, 'desktop');
  await actions.background();
  for (const label of ['Adicionar host', 'Host existente', 'Ligar hosts', 'Adicionar forma']) {
    assert.equal(await page.getByRole('menuitem', { name: label, exact: true }).count(), 1);
  }
  await page.screenshot({ path: path.join(output, 'updated-menus.png') });
  result.checks.push('migração libera menus de cadastro, ligação e formas no pacote instalado');
  await page.keyboard.press('Escape');
  await host.dblclick();
  await page.locator('.modal').waitFor();
  const name = page.locator('.modal .field').filter({ has: page.locator('label').filter({ hasText: 'Nome do host' }) }).locator('input');
  assert.equal(await name.inputValue(), 'Host A fixture');
  await page.screenshot({ path: path.join(output, 'updated-host-details.png') });
  result.checks.push('duplo clique abre detalhes reais do host convertido para ID inteiro');
  assert.deepEqual(errors, []);
  result.status = 'PASS';
} catch (error) {
  result.status = 'FAIL'; result.error = error.stack;
  throw error;
} finally {
  await browser.close();
  await fs.writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
}
console.log(JSON.stringify(result, null, 2));
