// Menções "#" na caixa da aba Claude: lista grupo + hosts, navega por teclado/mouse,
// insere #host:/#group: e o envio leva o bloco com os IDs (a bolha não o mostra).
// Console temporário em loopback; APIs e WebSocket simulados.
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.NETOPS_E2E_URL;
if (!BASE || !/^(127\.0\.0\.1|localhost)$/.test(new URL(BASE).hostname)) {
  throw Error('Use NETOPS_E2E_URL de um console temporário em loopback.');
}
const SID = '66666666-6666-4666-8666-666666666666';
const HOSTS = { rev: 'x', groups: ['MIKROTIK', 'LINUX'], hosts: [
  { id: 1, explicit: { hostname: '001 Mikrotik Test', group: 'MIKROTIK' }, effective: { mgmt_ip: '10.0.0.1' } },
  { id: 2, explicit: { hostname: 'RT-CORE-01', group: 'MIKROTIK' }, effective: { mgmt_ip: '10.0.0.2' } },
  { id: 3, explicit: { hostname: 'srv-mikrotik-backup', group: 'LINUX' }, effective: { mgmt_ip: '10.0.0.3' } },
  { id: 4, explicit: { hostname: 'ZABBIX', group: 'LINUX' }, effective: { mgmt_ip: '10.0.0.4' } },
] };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
try {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const errors = [];
  context.on('page', p => p.on('pageerror', e => errors.push(e.message)));
  await context.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/status') return route.fulfill({ json: { auth_required: false, authenticated: true } });
    if (path === '/api/auth/me') return route.fulfill({ json: { username: 'admin', is_admin: true, groups: ['admin'], permissions: [], net_perms: [], catalog: [] } });
    if (path === '/api/config/meta') return route.fulfill({ json: { network_name: 'Fixture', version: '1.0.0', claude_enabled: true, terminal_enabled: false, read_only: false } });
    if (path === '/api/vault/status') return route.fulfill({ json: { state: 'cache' } });
    if (path === '/api/updates/status') return route.fulfill({ json: { current_version: '1.0.0', managed: false, read_only: false, job: {} } });
    if (path === '/api/claude/auth/status') return route.fulfill({ json: { available: true, loggedIn: true } });
    if (path === '/api/claude/models') return route.fulfill({ json: { models: [{ id: 'm', name: 'Modelo' }], default: 'm' } });
    if (path === '/api/claude/attach-ticket') return route.fulfill({ status: 204 });
    if (path === '/api/claude/sessions') return route.fulfill({ json: { sessions: [] } });
    if (path.startsWith('/api/claude/sessions/')) return route.fulfill({ json: path.endsWith('/messages') ? { items: [] } : { id: SID } });
    if (path === '/api/hosts') return route.fulfill({ json: HOSTS });
    if (path === '/api/vault/items') return route.fulfill({ json: { items: [{ id: 'coolify-producao', title: 'Coolify produção', template_label: 'API',
      values: [{ field: 'URL', kind: 'text', value: 'https://c.example' }, { field: 'API key', kind: 'secret', set: true }] }] } });
    return route.fulfill({ json: {} });
  });
  const page = await context.newPage();
  await page.addInitScript(sid => {
    const mock = window.__mock = { sent: [] };
    class WS extends EventTarget {
      constructor() { super(); this.readyState = 0; mock.ws = this;
        setTimeout(() => { this.readyState = 1; this.onopen?.({});
          this.emit({ type: 'queue', items: [], fresh: true });
          this.emit({ type: 'system', subtype: 'init', data: { session_id: sid, model: 'm', permissionMode: 'default', slash_commands: [] } }); }, 0); }
      emit(p) { this.onmessage?.({ data: JSON.stringify(p) }); }
      send(raw) { mock.sent.push(JSON.parse(raw)); }
      close() { this.readyState = 3; }
    }
    window.WebSocket = WS;
  }, SID);
  await page.goto(BASE + '/#claude/' + SID);
  await page.waitForFunction(() => window.__mock.ws?.readyState === 1);

  const ta = page.locator('.cc-composer textarea').first();
  const menu = page.locator('.cc-mention-menu');
  const rows = () => menu.locator('.cc-mention').allTextContents();
  // A tela redesenha depois da tecla: espera a seleção chegar em vez de ler na hora.
  const selIs = async (re) => { await page.waitForFunction((src) => new RegExp(src).test(document.querySelector('.cc-mention.sel')?.textContent || ''), re.source, { timeout: 5000 }); };

  // 1) "#mikrotik" → grupo primeiro, depois os hosts que contêm o termo (inclusive no meio do nome)
  await ta.click(); await page.mouse.move(5, 5);   // ponteiro fora do menu: o hover não troca a seleção
  await ta.pressSequentially('acesse #mikrotik');
  await menu.waitFor();
  const r = await rows();
  assert.equal(r.length, 3, r.join(' | '));
  assert.match(r[0], /^groupMIKROTIK/);
  assert.match(r[1], /^host001 Mikrotik Test/);
  assert.match(r[2], /^hostsrv-mikrotik-backup/);

  // 2) ↓ muda a seleção; Esc fecha sem apagar; digitar de novo reabre
  await ta.press('ArrowDown');
  assert.equal(await menu.locator('.cc-mention.sel').count(), 1);
  await selIs(/001 Mikrotik Test/);
  await ta.press('Escape');
  assert.equal(await menu.count(), 0);
  assert.equal(await ta.inputValue(), 'acesse #mikrotik');
  await ta.press('Backspace'); await ta.pressSequentially('k');
  await menu.waitFor();
  await page.waitForTimeout(150);   // Preact agrupa os redesenhos: a seta não pode chegar antes do "k" ser desenhado

  // 3) Enter escolhe o item selecionado (não envia); troca só o token e mantém o resto
  await selIs(/^groupMIKROTIK/);   // busca mudou: seleção volta ao 1º (grupo)
  await ta.press('ArrowUp');                                         // wrap → último
  await selIs(/srv-mikrotik-backup/);
  await ta.press('ArrowDown');                                       // wrap → grupo
  await ta.press('Enter');
  assert.equal(await ta.inputValue(), 'acesse #group:MIKROTIK ');
  assert.equal((await page.evaluate(() => window.__mock.sent.filter(m => m.type === 'prompt'))).length, 0, 'Enter do menu não envia');
  assert.equal(await menu.count(), 0);

  // 4) clique do mouse escolhe host; menção no meio do texto
  await ta.pressSequentially('e #zab'); await menu.waitFor();
  await menu.locator('.cc-mention', { hasText: 'ZABBIX' }).click(); await page.mouse.move(5, 5);
  assert.equal(await ta.inputValue(), 'acesse #group:MIKROTIK e #host:ZABBIX ');

  // 5) enviar: o agente recebe o bloco com IDs do grupo; a bolha mostra só o que foi digitado
  await ta.pressSequentially('agora'); await ta.press('Enter');
  const sent = (await page.evaluate(() => window.__mock.sent.filter(m => m.type === 'prompt')))[0];
  assert.ok(sent.text.startsWith('acesse #group:MIKROTIK e #host:ZABBIX agora'), sent.text);
  assert.match(sent.text, /\[NetOps — menções\]/);
  assert.match(sent.text, /grupo do inventário com 2 host\(s\): host id 1 \(001 Mikrotik Test, 10\.0\.0\.1\); host id 2/);
  assert.match(sent.text, /#host:ZABBIX = host id 4/);
  const bubble = (await page.locator('.cc-msg.user .cc-usertext').allTextContents())[0];
  assert.equal(bubble, 'acesse #group:MIKROTIK e #host:ZABBIX agora');

  // 6) "#senha:" lista itens do Cofre de senhas; o envio leva só as referências nvault:// (nunca o valor)
  await ta.fill(''); await ta.pressSequentially('use #cool'); await menu.waitFor();
  assert.match((await rows())[0], /senhaCoolify produção/);
  await ta.press('Enter');
  assert.equal(await ta.inputValue(), 'use #senha:coolify-producao ');
  // o texto enviado (referências nvault://, sem valor) é coberto em tests/mentions.test.mjs
  await ta.fill('');

  // 7) "#" colado em palavra não abre menu
  await ta.pressSequentially('issue#12');
  assert.equal(await menu.count(), 0);

  assert.deepEqual(errors, []);
  console.log('mentions.browser: ok');
} finally { await browser.close(); }
