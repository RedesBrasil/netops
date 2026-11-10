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
