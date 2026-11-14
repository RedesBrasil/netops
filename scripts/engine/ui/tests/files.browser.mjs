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

  // vários arquivos = downloads separados (sem zip)
  await page.locator('.fm input[type=file]').first().setInputFiles([{ name: 'b2.txt', mimeType: 'text/plain', buffer: Buffer.from('b2') }]);
  await row('b2.txt').waitFor();
  await row('renomeado.conf').click();
  await row('b2.txt').click({ modifiers: ['Control'] });
  const got = [];
  page.on('download', (d) => got.push(d.suggestedFilename()));
  await page.getByRole('button', { name: 'Baixar' }).click();
  for (let i = 0; i < 50 && got.length < 2; i++) await page.waitForTimeout(100);
  assert.deepEqual(got.sort(), ['b2.txt', 'renomeado.conf'], 'arquivos soltos, sem zip');

  // pasta = recriada na pasta escolhida no PC (seletor de pasta simulado em memória)
  await page.evaluate(() => {
    const mkDir = (name) => ({ kind: 'directory', name, children: {},
      async getDirectoryHandle(n, o = {}) { if (!this.children[n] && !o.create) throw new DOMException('x', 'NotFoundError');
        if (this.children[n] && this.children[n].kind !== 'directory') throw new DOMException('x', 'TypeMismatchError');
        return (this.children[n] ||= mkDir(n)); },
      async getFileHandle(n, o = {}) { if (!this.children[n] && !o.create) throw new DOMException('x', 'NotFoundError');
        if (this.children[n] && this.children[n].kind !== 'file') throw new DOMException('x', 'TypeMismatchError');
        const f = (this.children[n] ||= { kind: 'file', name: n, data: '' });
        return { async createWritable() { const parts = []; return { async write(v) { parts.push(v); },
          async close() { f.data = new TextDecoder().decode(new Uint8Array(parts.flatMap((p) => [...p]))); } }; } }; } });
    window.__pc = mkDir('Downloads');
    window.showDirectoryPicker = async () => window.__pc;
  });
  await row('pasta').click();
  await page.getByRole('button', { name: 'Baixar' }).click();
  await page.locator('.toast.ok', { hasText: 'Baixado' }).waitFor();
  const saved = await page.evaluate(() => window.__pc.children.pasta.children['a.txt'].data);
  assert.equal(saved, 'alfa\n', 'pasta recriada no PC com o conteúdo');
  // 2ª vez: pergunta de novo (abre o seletor) e não sobrescreve -> "pasta (2)"
  await page.evaluate(() => { window.__picks = 0; window.showDirectoryPicker = async () => { window.__picks++; return window.__pc; }; });
  await row('pasta').click();
  await page.getByRole('button', { name: 'Baixar' }).click();
  await page.locator('.toast.ok', { hasText: 'pasta (2)' }).waitFor();
  assert.equal(await page.evaluate(() => window.__picks), 1, 'perguntou onde salvar de novo');
  assert.equal(await page.evaluate(() => window.__pc.children['pasta (2)'].children['a.txt'].data), 'alfa\n');

  // arrastar para fora = download (DownloadURL pronto no dragstart): 1 arquivo direto; vários/pasta = .zip
  const dragData = async (selector) => page.evaluate((sel) => {
    const dt = new DataTransfer();
    document.querySelector(sel).dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
    return dt.getData('DownloadURL');
  }, selector);
  await page.mouse.click(5, 5);
  await row('b2.txt').click(); await page.waitForTimeout(600);
  const one = await dragData('.fm-row.sel');
  assert.match(one, /^application\/octet-stream:b2\.txt:http.*\/api\/files\/dl\//, one);
  const fetched = await page.evaluate(async (u) => (await fetch(u.split(':').slice(2).join(':'))).text(), one);
  assert.equal(fetched, 'b2');
  await row('pasta').click(); await page.waitForTimeout(600);
  assert.match(await dragData('.fm-row.sel'), /^application\/zip:pasta\.zip:/);

  // .zip continua disponível pelo menu de contexto
  await row('pasta').click({ button: 'right' });
  const [dl] = await Promise.all([page.waitForEvent('download'), page.locator('.fm-menu button', { hasText: 'Baixar como .zip' }).click()]);
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
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
  await page.locator('.modal .fm-copy').click();
  await page.locator('.modal .fm-copy', { hasText: 'copiado!' }).waitFor();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'criada');
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
