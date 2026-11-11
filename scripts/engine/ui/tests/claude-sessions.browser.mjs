// Console temporário em loopback; APIs e WebSockets simulados, sem executar o Claude.
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL;
if (!BASE || !/^(127\.0\.0\.1|localhost)$/.test(new URL(BASE).hostname)) {
  throw Error('Use NETOPS_E2E_URL de um console temporário em loopback.');
}
const LAST_KEY = 'netops_claude_last_session';
const IDS = {
  A: '11111111-1111-4111-8111-111111111111',
  B: '22222222-2222-4222-8222-222222222222',
  C: '33333333-3333-4333-8333-333333333333',
  D: '44444444-4444-4444-8444-444444444444',
  missing: '99999999-9999-4999-8999-999999999999',
};
const LABELS = Object.fromEntries(Object.entries(IDS).map(([label, id]) => [id, label]));

function deferred() {
  let release;
  const promise = new Promise(resolve => { release = resolve; });
  return { promise, release, reached: false };
}

async function until(predicate, description) {
  const deadline = Date.now() + 10000;
  while (!await predicate()) {
    if (Date.now() >= deadline) throw Error('Timeout: ' + description);
    await new Promise(resolve => setTimeout(resolve, 25));
  }
}

async function fixture(browser, mobile = false) {
  const context = await browser.newContext({
    viewport: mobile ? { width: 390, height: 844 } : { width: 1366, height: 900 },
  });
  const errors = [];
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  const controls = { ticket: null, histories: new Map(), requests: [], gates: [], sessionIds: [IDS.B, IDS.A] };
  await context.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    controls.requests.push(path);
    if (path === '/api/auth/status') return route.fulfill({ json: { auth_required: false, authenticated: true } });
    if (path === '/api/config/meta') return route.fulfill({ json: {
      network_name: 'Fixture Claude', version: '1.0.0', claude_enabled: true,
      terminal_enabled: false, isolated_data: true, read_only: false,
    } });
    if (path === '/api/vault/status') return route.fulfill({ json: { state: 'cache' } });
    if (path === '/api/updates/status') return route.fulfill({ json: {
      current_version: '1.0.0', managed: false, read_only: false, job: {},
    } });
    if (path === '/api/claude/auth/status') return route.fulfill({ json: { available: true, loggedIn: true, email: 'fixture@example.test' } });
    if (path === '/api/claude/models') return route.fulfill({ json: {
      models: [{ id: 'fixture-model', name: 'Modelo de teste' }], default: 'fixture-model',
    } });
    if (path === '/api/claude/attach-ticket') {
      const gate = controls.ticket;
      controls.ticket = null;
      if (gate) { gate.reached = true; await gate.promise; }
      return route.fulfill({ status: 204 });
    }
    if (path === '/api/claude/sessions' || path === '/api/claude/sessions/search') {
      return route.fulfill({ json: { sessions: controls.sessionIds.map((id, index) => ({
        id, title: 'Sessão ' + LABELS[id], preview: 'Conversa fictícia ' + LABELS[id],
        mtime: 1800000000000 - index * 1000,
      })) } });
    }
    const match = /^\/api\/claude\/sessions\/([^/]+)(\/messages)?$/.exec(path);
    if (match) {
      const id = decodeURIComponent(match[1]);
      if (!LABELS[id] || id === IDS.missing) {
        return route.fulfill({ status: 404, json: { error: 'session_not_found', detail: 'Sessão não encontrada.' } });
      }
      if (!match[2]) return route.fulfill({ json: { id } });
      const gate = controls.histories.get(id);
      controls.histories.delete(id);
      if (gate) { gate.reached = true; await gate.promise; }
      return route.fulfill({ json: { items: [{ type: 'user', text: 'Histórico da sessão ' + LABELS[id] }] } });
    }
    return route.fulfill({ json: { hosts: [], groups: [], rev: 'fixture' } });
  });

  async function page(options = {}) {
    const current = await context.newPage();
    await current.addInitScript(({ ids, key, seed, blockStorage }) => {
      if (seed) localStorage.setItem(key, seed);
      if (blockStorage) {
        for (const method of ['getItem', 'setItem', 'removeItem']) {
          const original = Storage.prototype[method];
          Storage.prototype[method] = function (name, ...args) {
            if (name === key) throw new DOMException('Fixture: storage indisponível', 'SecurityError');
            return original.call(this, name, ...args);
          };
        }
      }
      const mock = window.__claudeMock = { connections: [], clipboard: [], nextIds: [ids.C, ids.D] };
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        writeText: async value => { mock.clipboard.push(value); },
      } });
      class MockWebSocket extends EventTarget {
        static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
        CONNECTING = 0; OPEN = 1; CLOSING = 2; CLOSED = 3;
        constructor(url) {
          super();
          this.url = String(url);
          this.readyState = 0;
          this.sent = [];
          this.sid = new URL(this.url).searchParams.get('resume') || mock.nextIds.shift() || ids.D;
          mock.connections.push(this);
          setTimeout(() => {
            if (this.readyState !== 0) return;
            this.readyState = 1;
            this.onopen?.(new Event('open'));
            this.emit({ type: 'system', subtype: 'init', data: {
              session_id: this.sid, model: 'fixture-model', permissionMode: 'default', slash_commands: [],
            } });
          }, 0);
        }
        emit(payload) { this.onmessage?.({ data: JSON.stringify(payload) }); }
        send(raw) {
          const message = JSON.parse(raw);
          this.sent.push(message);
          if (message.type === 'prompt') setTimeout(() => {
            if (this.readyState !== 1) return;
            this.emit({ type: 'text_delta', text: 'Resposta simulada' });
            this.emit({ type: 'result', session_id: this.sid, cost_usd: 0, usage: {}, is_error: false });
          }, 0);
        }
        close(code = 1000, reason = '') {
          if (this.readyState === 3) return;
          this.readyState = 3;
          setTimeout(() => this.onclose?.({ code, reason, wasClean: true }), 0);
        }
      }
      window.WebSocket = MockWebSocket;
    }, { ids: IDS, key: LAST_KEY, seed: options.seed || '', blockStorage: !!options.blockStorage });
    return current;
  }
  return {
    context, controls, errors, page,
    holdTicket() { const gate = deferred(); controls.ticket = gate; controls.gates.push(gate); return gate; },
    holdHistory(id) { const gate = deferred(); controls.histories.set(id, gate); controls.gates.push(gate); return gate; },
    async close() {
      for (const gate of controls.gates) gate.release();
      await context.close();
      assert.deepEqual(errors, [], 'Nenhuma exceção no navegador');
    },
  };
}

async function waitSession(page, id, history = true) {
  await page.waitForFunction(sid => location.hash === '#claude/' + sid
    && window.__claudeMock.connections.some(socket => socket.sid === sid && socket.readyState === 1), id);
  if (history) await page.getByText('Histórico da sessão ' + LABELS[id], { exact: true }).waitFor();
}

async function activeIds(page) {
  return page.evaluate(() => window.__claudeMock.connections.filter(socket => socket.readyState === 1).map(socket => socket.sid));
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
try {
  for (const mobile of [false, true]) {
    const f = await fixture(browser, mobile);
    try {
      const page = await f.page({ seed: IDS.B });
      await page.goto(BASE + '/#claude/' + IDS.A);
      await waitSession(page, IDS.A);
      if (mobile) {
        const layout = await page.evaluate(() => {
          const page = document.querySelector('.claude-page'), title = page.querySelector('.page-title');
          return { viewport: innerWidth, document: document.documentElement.scrollWidth,
            page: page.clientWidth, pageScroll: page.scrollWidth, title: title.clientWidth, titleScroll: title.scrollWidth };
        });
        console.log('LAYOUT celular: ' + JSON.stringify(layout));
        assert.ok(layout.pageScroll <= layout.page && layout.titleScroll <= layout.title,
          'Cabeçalho Claude não pode causar overflow horizontal: ' + JSON.stringify(layout));
      }
      assert.equal(await page.locator('.sidebar a.active').textContent(), 'Claude Code');
      assert.equal(await page.evaluate(key => localStorage.getItem(key), LAST_KEY), IDS.A);
      await page.getByRole('button', { name: 'Copiar link', exact: true }).click();
      await page.waitForFunction(() => window.__claudeMock.clipboard.length > 0);
      assert.equal(await page.evaluate(() => window.__claudeMock.clipboard.at(-1)), BASE.replace(/\/$/, '') + '/#claude/' + IDS.A);
      await page.reload();
      await waitSession(page, IDS.A);

      await page.evaluate(id => { location.hash = '#claude/' + id; }, IDS.B);
      await waitSession(page, IDS.B);
      await page.goBack();
      await waitSession(page, IDS.A);
      await page.goForward();
      await waitSession(page, IDS.B);
      assert.deepEqual(await activeIds(page), [IDS.B]);

      await page.getByRole('button', { name: 'Sessões', exact: true }).click();
      const sessionLink = page.getByRole('link', { name: 'Sessão A', exact: true });
      await sessionLink.waitFor();
      assert.equal(await sessionLink.getAttribute('href'), '#claude/' + IDS.A);
      assert.ok(await page.getByTitle('Copiar link da sessão', { exact: true }).count() >= 2);
      await page.locator('.cc-sess').filter({ has: sessionLink }).getByTitle('Copiar link da sessão', { exact: true }).click();
      await page.waitForFunction(() => window.__claudeMock.clipboard.length > 0);
      assert.equal(await page.evaluate(() => window.__claudeMock.clipboard.at(-1)), BASE.replace(/\/$/, '') + '/#claude/' + IDS.A);
      assert.equal(new URL(page.url()).hash, '#claude/' + IDS.B, 'Copiar link não troca a conversa');
      await sessionLink.click();
      await waitSession(page, IDS.A);

      await page.evaluate(() => { location.hash = '#hosts'; });
      await page.locator('.chat-dock').waitFor();
      assert.deepEqual(await activeIds(page), [IDS.A], 'Hosts mantém o mesmo socket no dock');
      await page.locator('.chat-dock a[title="Abrir em tela cheia"]').click();
      await waitSession(page, IDS.A);
      await page.getByRole('button', { name: 'Nova sessão', exact: true }).click();
      await waitSession(page, IDS.C, false);
      assert.deepEqual(await activeIds(page), [IDS.C]);
      assert.equal(await page.evaluate(key => localStorage.getItem(key), LAST_KEY), IDS.C);
      await page.locator('.cc-composer textarea').fill('Mensagem de teste');
      await page.getByRole('button', { name: 'Enviar', exact: true }).click();
      await page.getByText('Resposta simulada', { exact: true }).waitFor();
      assert.equal(new URL(page.url()).hash, '#claude/' + IDS.C);
      console.log(`PASS: link direto, copiar, reload, histórico, Sessões, dock e nova (${mobile ? 'celular' : 'desktop'}).`);
    } finally { await f.close(); }
  }

  for (const options of [{ seed: IDS.A }, {}, { blockStorage: true }, { seed: IDS.missing }]) {
    const f = await fixture(browser);
    try {
      const page = await f.page(options);
      await page.goto(BASE + '/#claude');
      await waitSession(page, options.seed && options.seed !== IDS.missing ? options.seed : IDS.B);
      assert.equal((await activeIds(page)).length, 1);
      console.log('PASS: restauração padrão ' + (options.seed === IDS.missing ? 'com preferência removida do servidor'
        : options.seed ? 'da última sessão local' : options.blockStorage ? 'com storage indisponível' : 'da sessão mais recente'));
    } finally { await f.close(); }
  }

  for (const explicitNew of [false, true]) {
    const f = await fixture(browser);
    try {
      f.controls.sessionIds = [];
      const page = await f.page(explicitNew ? { seed: IDS.B } : {});
      await page.goto(BASE + (explicitNew ? '/#claude/new' : '/#claude'));
      await waitSession(page, IDS.C, false);
      assert.deepEqual(await activeIds(page), [IDS.C]);
      assert.equal(await page.evaluate(key => localStorage.getItem(key), LAST_KEY), IDS.C);
      console.log('PASS: nova sessão ' + (explicitNew ? 'por link explícito apesar da preferência salva.' : 'quando não há histórico.'));
    } finally { await f.close(); }
  }

  {
    const f = await fixture(browser);
    try {
      const first = await f.page(), second = await f.page();
      await first.goto(BASE + '/#claude/' + IDS.A);
      await waitSession(first, IDS.A);
      await second.goto(BASE + '/#claude/' + IDS.B);
      await waitSession(second, IDS.B);
      assert.equal(await first.evaluate(key => localStorage.getItem(key), LAST_KEY), IDS.B);
      assert.equal(new URL(first.url()).hash, '#claude/' + IDS.A);
      assert.deepEqual(await activeIds(first), [IDS.A]);
      assert.deepEqual(await activeIds(second), [IDS.B]);
      await second.reload();
      await waitSession(second, IDS.B);
      assert.deepEqual(await activeIds(first), [IDS.A]);
      console.log('PASS: abas A/B mantêm URLs, sockets e conversas independentes.');
    } finally { await f.close(); }
  }

  for (const fragment of ['#claude/%ZZ', '#claude/../secrets', '#claude/' + IDS.missing]) {
    const f = await fixture(browser);
    try {
      const page = await f.page({ seed: IDS.A });
      await page.goto(BASE + '/' + fragment);
      await page.locator('.claude-page').waitFor();
      await page.getByText(/sessão.*(inválid|encontrad|existe)|inválid.*sessão/i).first().waitFor();
      assert.deepEqual(await activeIds(page), []);
      assert.equal(await page.evaluate(() => window.__claudeMock.connections.length), 0);
      assert.ok(!f.controls.requests.some(path => path.includes('secrets')));
      console.log('PASS: link inválido/ausente não inicia agente: ' + fragment);
    } finally { await f.close(); }
  }

  {
    const f = await fixture(browser);
    try {
      const ticket = f.holdTicket(), page = await f.page();
      await page.goto(BASE + '/#claude/' + IDS.A);
      await until(() => ticket.reached, 'ticket A pendente');
      await page.evaluate(id => { location.hash = '#claude/' + id; }, IDS.B);
      await waitSession(page, IDS.B);
      ticket.release();
      await page.waitForTimeout(100);
      assert.deepEqual(await activeIds(page), [IDS.B]);
      assert.ok(!await page.evaluate(id => window.__claudeMock.connections.some(socket => socket.sid === id), IDS.A));
      console.log('PASS: ticket atrasado de A não abre socket após selecionar B.');
    } finally { await f.close(); }
  }

  {
    const f = await fixture(browser);
    try {
      const history = f.holdHistory(IDS.A), page = await f.page();
      await page.goto(BASE + '/#claude/' + IDS.A);
      await until(() => history.reached, 'histórico A pendente');
      await page.evaluate(id => { location.hash = '#claude/' + id; }, IDS.B);
      await waitSession(page, IDS.B);
      history.release();
      await page.waitForTimeout(100);
      assert.match(await page.locator('.cc-transcript').innerText(), /Histórico da sessão B/);
      assert.doesNotMatch(await page.locator('.cc-transcript').innerText(), /Histórico da sessão A/);
      // A implementação abre o socket só depois do histórico; conecta A sem atraso
      // para também exercitar callbacks de um socket efetivamente substituído.
      await page.evaluate(id => { location.hash = '#claude/' + id; }, IDS.A);
      await waitSession(page, IDS.A);
      await page.evaluate(id => { location.hash = '#claude/' + id; }, IDS.B);
      await waitSession(page, IDS.B);
      await page.evaluate(id => {
        const old = window.__claudeMock.connections.find(socket => socket.sid === id);
        old.emit({ type: 'system', subtype: 'init', data: { session_id: id } });
        old.emit({ type: 'text_delta', text: 'Evento antigo da sessão A' });
        old.emit({ type: 'result', session_id: id, usage: {} });
        old.onclose?.({ code: 1006, reason: 'Evento antigo', wasClean: false });
      }, IDS.A);
      await page.waitForTimeout(100);
      assert.equal(new URL(page.url()).hash, '#claude/' + IDS.B);
      assert.equal(await page.evaluate(key => localStorage.getItem(key), LAST_KEY), IDS.B);
      assert.deepEqual(await activeIds(page), [IDS.B]);
      assert.match(await page.locator('.cc-transcript').innerText(), /Histórico da sessão B/);
      assert.doesNotMatch(await page.locator('.cc-transcript').innerText(), /Histórico da sessão A|Evento antigo/);
      console.log('PASS: histórico e eventos WS antigos não alteram sessão B.');
    } finally { await f.close(); }
  }

  {
    const f = await fixture(browser);
    try {
      const pages = [];
      for (const [code, id] of [[4409, IDS.A], [4404, IDS.B]]) {
        const page = await f.page();
        await page.goto(BASE + '/#claude/' + id);
        await waitSession(page, id);
        await page.evaluate(closeCode => window.__claudeMock.connections.at(-1).close(closeCode), code);
        await page.getByText(code === 4409 ? /sessão foi aberta em outra aba/ : /Sessão não encontrada/).first().waitFor();
        pages.push(page);
      }
      await new Promise(resolve => setTimeout(resolve, 3250));
      for (const page of pages) {
        assert.deepEqual(await activeIds(page), []);
        assert.equal(await page.evaluate(() => window.__claudeMock.connections.length), 1);
      }
      console.log('PASS: takeover e sessão removida não causam reconexões repetidas.');
    } finally { await f.close(); }
  }
} finally { await browser.close(); }
