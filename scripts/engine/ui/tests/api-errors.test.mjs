import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { test } from 'node:test';
const source = await fs.readFile(new URL('../static/js/api.js', import.meta.url), 'utf8');
const { ApiError, ValidationError } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

test('erros de domínio preservam caminhos de campo', () => {
  const fields = [{ loc: 'a/port', msg: 'Informe a porta' }];
  assert.deepEqual(new ValidationError(422, { errors: fields }).fieldErrors, fields);
});
test('erros Pydantic são normalizados sem input ou contexto', () => {
  const e = new ValidationError(422, { detail: [{ loc: ['body', 'a', 'port'], type: 'string_too_short', msg: 'Porta inválida', input: 'não expor', ctx: { value: 'não expor' } }] });
  assert.deepEqual(e.fieldErrors, [{ loc: 'a/port', msg: 'Porta inválida' }]);
  assert.equal(e.message, 'HTTP 422');
});
test('campos ausentes usam mensagem legível e payloads desconhecidos não quebram', () => {
  assert.deepEqual(new ValidationError(422, { detail: [{ type: 'missing', loc: ['body', 'b', 'port'] }] }).fieldErrors, [{ loc: 'b/port', msg: 'Campo obrigatório' }]);
  assert.deepEqual(new ValidationError(422, { detail: 'Falha' }).fieldErrors, []);
  assert.equal(new ApiError(409, { detail: 'Arquivo mudou' }).message, 'Arquivo mudou');
});

test('ícone de forma rejeitado como campo extra indica backend incompatível', () => {
  for (const loc of [['body', 'map', 'objects', 0, 'icon'], ['map', 'objects', 2, 'icon']]) {
    const error = new ValidationError(422, { detail: [{ loc, type: 'extra_forbidden', msg: 'Extra inputs are not permitted', input: 'não expor' }] });
    assert.match(error.recoveryHint, /Atualize o NetOps e reinicie o console no servidor/);
    assert.match(error.recoveryHint, /ainda não foram salvos/);
    assert.ok(!error.recoveryHint.includes('não expor'));
    assert.equal(error.fieldErrors[0].loc, loc.filter(part => part !== 'body').join('/'));
  }
});

test('ícones inválidos e outros campos extras continuam como erros de validação', () => {
  const cases = [
    { loc: ['body', 'map', 'objects', 0, 'icon'], type: 'value_error' },
    { loc: ['body', 'map', 'objects', 0, 'icon'], type: 'string_pattern_mismatch' },
    { loc: ['body', 'map', 'objects', 0, 'unknown'], type: 'extra_forbidden' },
    { loc: ['body', 'icon'], type: 'extra_forbidden' },
    { loc: ['body', 'map', 'objects', 'icon'], type: 'extra_forbidden' },
    { loc: ['body', 'map', 'objects', '0', 'icon'], type: 'extra_forbidden' },
  ];
  for (const detail of cases) assert.equal(new ValidationError(422, { detail: [detail] }).recoveryHint, null);
  assert.equal(new ValidationError(422, { errors: [{ loc: 'map/objects/0/icon', msg: 'Ícone inválido' }] }).recoveryHint, null);
  assert.equal(new ValidationError(422, { detail: 'Falha' }).recoveryHint, null);
});
