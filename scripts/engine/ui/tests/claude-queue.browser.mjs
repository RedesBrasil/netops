// Envio durante a execução (agora x fila). Console temporário em loopback; APIs e WebSocket
// simulados — o mock imita o servidor: turno ocupado, fila, despacho no fim e restauração.
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL;
if (!BASE || !/^(127\.0\.0\.1|localhost)$/.test(new URL(BASE).hostname)) {
  throw Error('Use NETOPS_E2E_URL de um console temporário em loopback.');
}
const SID = '55555555-5555-4555-8555-555555555555';

async function fixture(browser, mobile) {
  const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1366, height: 900 } });
  const errors = [];
  context.on('page', p => p.on('pageerror', e => errors.push(e.message)));
  await context.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/status') return route.fulfill({ json: { auth_required: false, authenticated: true } });
    if (path === '/api/config/meta') return route.fulfill({ json: { network_name: 'Fixture', version: '1.0.0', claude_enabled: true, terminal_enabled: false, read_only: false } });
    if (path === '/api/vault/status') return route.fulfill({ json: { state: 'cache' } });
    if (path === '/api/updates/status') return route.fulfill({ json: { current_version: '1.0.0', managed: false, read_only: false, job: {} } });
    if (path === '/api/claude/auth/status') return route.fulfill({ json: { available: true, loggedIn: true } });
    if (path === '/api/claude/models') return route.fulfill({ json: { models: [{ id: 'm', name: 'Modelo' }], default: 'm' } });
    if (path === '/api/claude/attach-ticket') return route.fulfill({ status: 204 });
    if (path === '/api/claude/sessions') return route.fulfill({ json: { sessions: [] } });
    if (path.startsWith('/api/claude/sessions/')) return route.fulfill({ json: path.endsWith('/messages') ? { items: [] } : { id: SID } });
    return route.fulfill({ json: { hosts: [], groups: [], rev: 'x' } });
  });
  const page = await context.newPage();
  await page.addInitScript(sid => {
    const mock = window.__mock = { sockets: [] };
    class WS extends EventTarget {
      constructor(url) {
        super(); this.url = url; this.readyState = 0; this.sent = []; this.busy = false; this.queue = []; this.seq = 0;
        mock.sockets.push(this); mock.ws = this;
        setTimeout(() => { this.readyState = 1; this.onopen?.({});
          this.emit({ type: 'system', subtype: 'init', data: { session_id: sid, model: 'm', permissionMode: 'default', slash_commands: [] } }); }, 0);
      }
      emit(p) { this.onmessage?.({ data: JSON.stringify(p) }); }
      send(raw) {
        const m = JSON.parse(raw); this.sent.push(m);
        if (m.type === 'prompt') {
          if (m.queue && this.busy) { this.queue.push({ id: 'q' + (++this.seq), text: m.text }); this.emit({ type: 'queue', items: this.queue }); }
          else this.busy = true;
        } else if (m.type === 'queue_remove' || m.type === 'queue_send_now') {
          const it = this.queue.find(q => q.id === m.id); this.queue = this.queue.filter(q => q.id !== m.id);
          this.emit({ type: 'queue', items: this.queue });
          if (m.type === 'queue_send_now' && it) this.emit({ type: 'queue_dispatched', ...it });
        } else if (m.type === 'interrupt') this.interrupted = true;
      }
      // fim do turno no "servidor": result + despacho/restauração da fila
      finish() {
        this.emit({ type: 'text_delta', text: 'ok' });
        this.emit({ type: 'result', session_id: sid, cost_usd: 0, usage: {}, is_error: !!this.interrupted });
        this.busy = false;
        if (!this.queue.length) { this.interrupted = false; return; }
        if (this.interrupted) { this.interrupted = false; const items = this.queue; this.queue = [];
          this.emit({ type: 'queue_restored', items }); this.emit({ type: 'queue', items: [] }); return; }
        const it = this.queue.shift(); this.emit({ type: 'queue', items: this.queue });
        this.emit({ type: 'queue_dispatched', ...it }); this.busy = true;
      }
      close() { this.readyState = 3; }
    }
    window.WebSocket = WS;
  }, SID);
  return { context, page, errors };
}

const prompts = page => page.evaluate(() => window.__mock.ws.sent.filter(m => m.type === 'prompt'));
const bubbles = page => page.locator('.cc-msg.user .cc-usertext').allTextContents();
async function type(page, text) {
  const ta = page.locator('.cc-composer textarea').first();
  await ta.fill(text); await ta.press('Enter');
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
try {
  for (const mobile of [false, true]) {
    const { context, page, errors } = await fixture(browser, mobile);
    await page.goto(BASE + '/#claude/' + SID);
    await page.waitForFunction(() => window.__mock.ws?.readyState === 1);
    const choice = page.locator('.cc-sendchoice');

    // 1) ocioso: Enter envia direto, sem perguntar
    await type(page, 'tarefa longa');
    assert.equal(await choice.count(), 0, 'ocioso não pergunta');
    assert.deepEqual(await prompts(page), [{ type: 'prompt', text: 'tarefa longa', queue: false }]);
    await page.locator('.cc-send.stop').waitFor();

    // 2) ocupado: Enter pergunta; "Enviar agora" manda já (queue:false) e mostra a bolha marcada
    await type(page, 'ajuste imediato');
    await choice.waitFor();
    assert.match(await choice.textContent(), /ajuste imediato/);
    await choice.getByRole('button', { name: /Enviar agora/ }).click();
    assert.equal(await choice.count(), 0);
    assert.deepEqual((await prompts(page)).at(-1), { type: 'prompt', text: 'ajuste imediato', queue: false });
    await page.getByText('durante a execução').first().waitFor();
    assert.equal(await page.locator('.cc-composer textarea').first().inputValue(), '');

    // 3) ocupado: "Colocar na fila" (atalho F) -> painel da fila, sem bolha ainda
    await type(page, 'depois 1');
    await choice.waitFor(); await page.keyboard.press('f');
    await type(page, 'depois 2');
    await choice.waitFor(); await choice.getByRole('button', { name: /Colocar na fila/ }).click();
    const q = page.locator('.cc-queue');
    await q.waitFor();
    assert.deepEqual(await q.locator('.cc-queue-text').allTextContents(), ['depois 1', 'depois 2']);
    assert.ok(!(await bubbles(page)).includes('depois 1'), 'item da fila não vira bolha antes de rodar');
    assert.deepEqual((await prompts(page)).slice(-2).map(p => p.queue), [true, true]);

    // 4) Esc na escolha cancela e mantém o texto para editar; NÃO interrompe o agente
    await type(page, 'rascunho');
    await choice.waitFor(); await page.keyboard.press('Escape');
    assert.equal(await choice.count(), 0);
    assert.equal(await page.locator('.cc-composer textarea').first().inputValue(), 'rascunho');
    assert.ok(!(await page.evaluate(() => window.__mock.ws.sent.some(m => m.type === 'interrupt'))));
    await page.locator('.cc-composer textarea').first().fill('');

    // 5) fim do turno: o 1º da fila vira turno (bolha "da fila"), o painel encolhe
    await page.evaluate(() => window.__mock.ws.finish());
    await page.getByText('da fila').first().waitFor();
    assert.ok((await bubbles(page)).includes('depois 1'));
    assert.deepEqual(await q.locator('.cc-queue-text').allTextContents(), ['depois 2']);
    await page.locator('.cc-send.stop').waitFor();

    // 6) remover da fila (×)
    await q.getByTitle('Tirar da fila').click();
    await page.waitForFunction(() => !document.querySelector('.cc-queue'));

    // 7) interromper com fila -> textos voltam para a caixa e a fila não roda
    await type(page, 'nao roda');
    await choice.waitFor(); await page.keyboard.press('f');
    await q.waitFor();
    await page.locator('.cc-send.stop').click();
    await page.evaluate(() => window.__mock.ws.finish());
    await page.waitForFunction(() => !document.querySelector('.cc-queue'));
    assert.equal(await page.locator('.cc-composer textarea').first().inputValue(), 'nao roda');
    assert.ok(!(await bubbles(page)).includes('nao roda'));

    // 8) "⚡ Enviar agora" num item da fila
    await page.locator('.cc-composer textarea').first().fill('');
    await type(page, 'novo turno');                 // ocioso: direto
    await type(page, 'promover');
    await choice.waitFor(); await page.keyboard.press('f');
    await q.getByTitle(/Enviar agora/).click();
    await page.waitForFunction(() => !document.querySelector('.cc-queue'));
    assert.ok((await bubbles(page)).includes('promover'));

    if (mobile) {   // a fila e a escolha cabem na largura do celular
      await type(page, 'texto de teste bem comprido para a fila, com várias palavras para quebrar');
      await choice.waitFor(); await page.keyboard.press('f');
      await type(page, 'outra mensagem');
      await choice.waitFor();
      const over = await page.evaluate(() => [...document.querySelectorAll('.cc-sendchoice, .cc-sendchoice *, .cc-queue, .cc-queue *, .cc-composer')]
        .filter(el => el.getBoundingClientRect().right > innerWidth + 1).map(el => el.className + ':' + Math.round(el.getBoundingClientRect().right)));
      assert.deepEqual(over, [], 'fila/escolha sem overflow no celular');
    }
    await context.close();
    assert.deepEqual(errors, [], 'Nenhuma exceção no navegador');
    console.log('OK claude-queue ' + (mobile ? 'celular' : 'desktop'));
  }
} finally {
  await browser.close();
}
