// Rodar contra console com dados fictícios isolados; auth é simulada, nenhuma escrita real.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL;
if (!BASE || !new URL(BASE).hostname.match(/^(127\.0\.0\.1|localhost)$/)) throw Error('Use console temporário em loopback.');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
try {
  for (const mobile of [false, true]) {
    const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1366, height: 900 } });
    const errors = [];
    context.on('page', page => page.on('pageerror', e => errors.push(e.message)));
    const sessions = new Set();
    let logins = 0;
    await context.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname;
      const sid = request.headers()['x-netops-session'];
      if (path === '/api/auth/login') {
        logins++;
        const token = 'fixture-session-' + logins;
        sessions.add(token);
        return route.fulfill({ json: { auth_token: token } });
      }
      if (path === '/api/auth/status') return route.fulfill({ json: { auth_required: true, authenticated: sessions.has(sid), vault_initialized: true } });
      if (path === '/api/auth/logout') {
        sessions.delete(sid);
        return route.fulfill({ json: { ok: true } });
      }
      if (path === '/api/config/meta') return route.fulfill({ json: { network_name: 'Fixture Auth', version: '1.0.0', terminal_enabled: false, claude_enabled: false } });
      if (!sessions.has(sid)) return route.fulfill({ status: 401, json: { error: 'auth_required' } });
      if (path === '/api/vault/status') return route.fulfill({ json: { state: 'cache' } });
      if (path === '/api/updates/status') return route.fulfill({ json: { current_version: '1.0.0', managed: false, read_only: false, job: {} } });
      return route.fulfill({ json: { hosts: [], groups: [], rev: 'fixture' } });
    });
    const first = await context.newPage(), waiting = await context.newPage();
    await first.goto(BASE + '/#hosts');
    await waiting.goto(BASE + '/#hosts');
    await waiting.locator('.login-screen').waitFor();
    await first.locator('input[type=password]').fill('fixture-only');
    await first.getByRole('button', { name: 'Entrar', exact: true }).click();
    await first.locator('.shell').waitFor();
    await waiting.locator('.shell').waitFor();
    const third = await context.newPage(); // Sem opener: reproduz nova aba digitando a URL.
    await third.goto(BASE + '/#hosts');
    await third.locator('.shell').waitFor();
    assert.equal(logins, 1);
    for (const page of [first, waiting, third]) {
      assert.equal(await page.evaluate(() => sessionStorage.getItem('netops_auth')), null);
      assert.equal(await page.evaluate(() => localStorage.getItem('netops_auth')), 'fixture-session-1');
    }
    await third.reload();
    await third.locator('.shell').waitFor();
    await waiting.getByRole('button', { name: 'Sair', exact: true }).click();
    for (const page of [first, waiting, third]) await page.locator('.login-screen').waitFor();
    await third.reload();
    await third.locator('.login-screen').waitFor();
    await first.locator('input[type=password]').fill('fixture-only');
    await first.getByRole('button', { name: 'Entrar', exact: true }).click();
    for (const page of [first, waiting, third]) await page.locator('.shell').waitFor();
    sessions.clear(); // Expiração/reinício do servidor continua exigindo autenticação.
    await first.evaluate(async () => { try { await (await import('/js/api.js')).api.get('/hosts'); } catch {} });
    for (const page of [first, waiting, third]) await page.locator('.login-screen').waitFor();
    assert.deepEqual(errors, []);
    await context.close();
    console.log(`PASS: três abas, login único, sincronização, reload, logout e expiração (${mobile ? 'celular' : 'desktop'}).`);
  }
} finally { await browser.close(); }
