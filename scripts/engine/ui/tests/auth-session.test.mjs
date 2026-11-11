import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import { test } from 'node:test';

const source = (await fs.readFile(new URL('../static/js/api.js', import.meta.url), 'utf8'))
  .replaceAll(/^export /gm, '') + '\nthis.client = { api, authToken, setAuthToken, clearAuthToken, setOnAuthChange, setOnUnauthorized };';

function storage(values = new Map()) {
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
}
function tab(shared = storage(), legacy = storage()) {
  const listeners = {};
  const context = vm.createContext({
    localStorage: shared, sessionStorage: legacy,
    window: { addEventListener: (name, callback) => { listeners[name] = callback; }, dispatchEvent() {} },
    CustomEvent: class {},
  });
  vm.runInContext(source, context);
  return { ...context.client, context, changed: event => listeners.storage({ key: 'netops_auth', storageArea: shared, ...event }) };
}
const unauthorized = () => ({ ok: false, status: 401, headers: { get: () => 'application/json' }, json: async () => ({ error: 'auth_required' }) });

test('abas novas e existentes usam a mesma sessão, inclusive nos requests', async () => {
  const shared = storage();
  const first = tab(shared), second = tab(shared);
  first.setAuthToken('session-a');
  assert.equal(second.authToken(), 'session-a');
  assert.equal(tab(shared).authToken(), 'session-a');
  second.context.fetch = async (_url, options) => {
    assert.equal(options.headers['X-Netops-Session'], 'session-a');
    return { ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => ({ ok: true }) };
  };
  await second.api.get('/hosts');
  second.clearAuthToken();
  assert.equal(first.authToken(), '');
});

test('sessão antiga migra uma vez; sessão compartilhada tem prioridade', () => {
  const legacy = storage(new Map([['netops_auth', 'legacy']]));
  const shared = storage();
  assert.equal(tab(shared, legacy).authToken(), 'legacy');
  assert.equal(legacy.getItem('netops_auth'), null);
  assert.equal(shared.getItem('netops_auth'), 'legacy');
  assert.equal(tab(shared, storage(new Map([['netops_auth', 'stale']]))).authToken(), 'legacy');
});

test('eventos sincronizam login, logout e limpeza, sem usar valores atrasados', () => {
  const shared = storage(), current = tab(shared);
  let changes = 0;
  current.setOnAuthChange(() => changes++);
  shared.setItem('netops_auth', 'new');
  current.changed({ newValue: 'old' });
  assert.equal(current.authToken(), 'new');
  current.changed({ key: 'netops_theme' });
  current.changed({ storageArea: storage() });
  assert.equal(changes, 1);
  shared.removeItem('netops_auth');
  current.changed({ key: null });
  assert.equal(current.authToken(), '');
  assert.equal(changes, 2);
});

test('logout impede que uma aba legada restaure outra sessão ao recarregar', () => {
  const shared = storage();
  const first = tab(shared, storage(new Map([['netops_auth', 'session-a']])));
  first.clearAuthToken();
  const legacy = storage(new Map([['netops_auth', 'session-b']]));
  assert.equal(tab(shared, legacy).authToken(), '');
  assert.equal(legacy.getItem('netops_auth'), null);
  assert.equal(shared.getItem('netops_auth'), '');
});

test('401 atrasado não remove login novo realizado em outra aba', async () => {
  const shared = storage(), current = tab(shared), other = tab(shared);
  current.setAuthToken('old');
  let respond;
  current.context.fetch = () => new Promise(resolve => { respond = resolve; });
  let lost = false;
  current.setOnUnauthorized(() => { lost = true; });
  const pending = current.api.get('/hosts');
  other.setAuthToken('new');
  respond(unauthorized());
  await assert.rejects(pending);
  assert.equal(current.authToken(), 'new');
  assert.equal(lost, false);
});

test('401 da sessão atual limpa o login de todas as abas', async () => {
  const shared = storage(), current = tab(shared), other = tab(shared);
  current.setAuthToken('expired');
  current.context.fetch = async () => unauthorized();
  let lost = false;
  current.setOnUnauthorized(() => { lost = true; });
  await assert.rejects(current.api.get('/hosts'));
  assert.equal(other.authToken(), '');
  assert.equal(lost, true);
});

test('armazenamento indisponível mantém o login em memória sem quebrar a página', () => {
  const blocked = { getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }, removeItem() { throw Error('blocked'); } };
  const current = tab(blocked, blocked);
  current.setAuthToken('memory');
  assert.equal(current.authToken(), 'memory');
  current.clearAuthToken();
  assert.equal(current.authToken(), '');
});
