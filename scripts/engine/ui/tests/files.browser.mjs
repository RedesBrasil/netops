// Gerenciador de arquivos (#files): navegar, criar pasta, enviar, renomear, editar, baixar, apagar — fluxo real no navegador.
// Uso: tests/e2e-env.sh up && PLAYWRIGHT_MODULE=... CHROMIUM_EXECUTABLE=... node tests/files.browser.mjs
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
if (!(await (await fetch(BASE + '/api/config/meta')).json()).isolated_data) throw Error('Teste recusa dados reais. Use NETOPS_UI_DATA_ROOT.');
const ROOT = `/tmp/netops-e2e/fb-${Date.now()}`;
const post = (p, b) => fetch(BASE + '/api' + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
assert.equal((await post('/files/mkdir', { path: ROOT })).status, 200);
await post('/files/mkdir', { path: ROOT + '/pasta' });
await fetch(BASE + `/api/files/upload?path=${encodeURIComponent(ROOT + '/pasta/a.txt')}&uid=seed00000001&final=1`, { method: 'PUT', body: 'alfa\n' });

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
try {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 860 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => d.accept());
  const row = (name) => page.locator('.fm-row', { has: page.locator('.fm-name', { hasText: new RegExp(`^${name.replace(/[.()]/g, '\\$&')}$`) }) });

  await page.goto(`${BASE}/#files?path=${encodeURIComponent(ROOT)}`);
  await row('pasta').waitFor();
  assert.ok(await page.locator('nav.sidebar a[href="#files"]').count(), 'menu Arquivos');
  assert.equal(await page.locator('.fm table, .files-page table').count(), 0, 'lista sem <table>');

  // duplo clique entra na pasta e a URL muda (Voltar volta)
  await row('pasta').dblclick();
  await row('a.txt').waitFor();
  assert.match(decodeURIComponent(page.url()), new RegExp(`path=${ROOT}/pasta`));
  await page.goBack();
  await row('pasta').waitFor();

  // nova pasta
  await page.getByRole('button', { name: 'Nova pasta' }).click();
  await page.locator('.modal input').fill('criada');
  await page.locator('.modal button[type=submit]').click();
  await row('criada').waitFor();

  // enviar arquivos (input)
  await page.locator('.fm input[type=file]').first().setInputFiles([{ name: 'up.conf', mimeType: 'text/plain', buffer: Buffer.from('k=v\n') }]);
  await row('up.conf').waitFor();

  // renomear (F2)
  await row('up.conf').click();
  await page.keyboard.press('F2');
  await page.locator('.modal input').fill('renomeado.conf');
  await page.locator('.modal button[type=submit]').click();
  await row('renomeado.conf').waitFor();

  // abrir no editor (URL ganha open=), editar e salvar com Ctrl+S
  await row('renomeado.conf').dblclick();
  await page.locator('.fm-editor-modal textarea').waitFor();
  assert.match(decodeURIComponent(page.url()), /open=.*renomeado\.conf/);
  await page.locator('.fm-editor-modal textarea').fill('k=editado\n');
  await page.keyboard.press('Control+s');
  await page.locator('.toast.ok', { hasText: 'Salvo' }).waitFor();
  const read = await (await fetch(`${BASE}/api/files/read?path=${encodeURIComponent(ROOT + '/renomeado.conf')}`)).json();
  assert.equal(read.content, 'k=editado\n');
  await page.locator('.fm-editor-modal').getByRole('button', { name: 'Fechar' }).click();

  // baixar seleção múltipla = .zip
  await row('pasta').click();
  await row('renomeado.conf').click({ modifiers: ['Control'] });
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Baixar' }).click()]);
  assert.match(dl.suggestedFilename(), /\.zip$/);

  // copiar/colar na mesma pasta = "(cópia)"; menu de contexto
  await row('renomeado.conf').click();
  await page.keyboard.press('Control+c');
  await page.keyboard.press('Control+v');
  await row('renomeado (cópia).conf').waitFor();
  await row('criada').click({ button: 'right' });
  await page.locator('.fm-menu').waitFor();
  await page.keyboard.press('Escape');
  await page.mouse.click(5, 5);

  // apagar exige digitar o nome
  await row('criada').click();
  await page.keyboard.press('Delete');
  const del = page.locator('.modal button.danger');
  assert.ok(await del.isDisabled());
  await page.locator('.modal input').fill('criada');
  await del.click();
  await row('criada').waitFor({ state: 'detached' });

  await page.screenshot({ path: process.env.FILES_SHOT || '/tmp/netops-files.png' });
  assert.deepEqual(errors, [], 'sem erros de página');
  console.log('OK files.browser');
} finally {
  await browser.close();
  await post('/files/delete', { paths: [ROOT] });
}
