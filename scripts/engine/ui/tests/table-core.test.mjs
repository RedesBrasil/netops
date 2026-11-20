// Padrão de tabelas do console (core/rules/console-tables.md) + núcleo puro do DataTable.
// Uso: node --test scripts/engine/ui/tests/table-core.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveColumns, moveColumn, sortRows } from '../static/js/table-core.js';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '../static/js');
const sources = () => {
  const files = [...fs.readdirSync(JS).map((f) => path.join(JS, f)), ...fs.readdirSync(path.join(JS, 'pages')).map((f) => path.join(JS, 'pages', f))];
  return files.filter((f) => f.endsWith('.js')).map((f) => ({ f: path.relative(JS, f), s: fs.readFileSync(f, 'utf8') }));
};
// Tabela que não é de dados (ex.: modelo inserido no editor de Markdown) fica nesta lista, com justificativa.
const RAW_TABLE_OK = new Set(['table.js', 'wysiwyg.js']);

test('telas não usam <table> cru: toda tabela de dados é DataTable', () => {
  const bad = sources().filter(({ f, s }) => !RAW_TABLE_OK.has(f) && /<table[\s>]/.test(s)).map(({ f }) => f);
  assert.deepEqual(bad, [], `use DataTable (js/table.js) em vez de <table> em: ${bad.join(', ')}`);
});

test('todo DataTable tem tableId, e os ids fixos são únicos', () => {
  const ids = [], missing = [];
  for (const { f, s } of sources().filter(({ f }) => f !== 'table.js')) {   // table.js só tem o exemplo no comentário
    for (const m of s.matchAll(/<\$\{(?:DataTable|ResourceTable)\}([\s\S]*?)\/>/g)) {
      const id = m[1].match(/tableId=(?:"([^"]+)"|\$\{)/);
      if (!id) missing.push(f); else if (id[1]) ids.push(id[1]);
    }
  }
  assert.deepEqual(missing, [], `DataTable sem tableId em: ${missing.join(', ')}`);
  assert.deepEqual(ids.filter((x, i) => ids.indexOf(x) !== i), [], 'tableId repetido');
  assert.ok(ids.length >= 10, 'esperava as tabelas do console migradas');
});

const COLS = [{ key: 'chk', pinned: true }, { key: 'a', hideable: false }, { key: 'b' }, { key: 'c', hidden: true }, { key: 'd' }];
test('resolveColumns: padrão, ordem salva, visibilidade e coluna nova', () => {
  const keys = (l) => resolveColumns(COLS, l).visible.map((c) => c.key);
  assert.deepEqual(keys({}), ['chk', 'a', 'b', 'd']);
  assert.deepEqual(keys({ order: ['d', 'b', 'a'], vis: { c: true, b: false, a: false } }), ['chk', 'd', 'a', 'c']);
  assert.deepEqual(keys({ order: ['zz', 'd'] }), ['chk', 'd', 'a', 'b']);         // chave sumida é ignorada
  assert.deepEqual(resolveColumns(COLS, {}).ordered.map((c) => c.key), ['a', 'b', 'c', 'd']); // pinned fora do menu
});

test('moveColumn antes/depois e alvo inexistente', () => {
  assert.deepEqual(moveColumn(['a', 'b', 'c'], 'c', 'a', 'before'), ['c', 'a', 'b']);
  assert.deepEqual(moveColumn(['a', 'b', 'c'], 'a', 'c', 'after'), ['b', 'c', 'a']);
  assert.deepEqual(moveColumn(['a', 'b'], 'a', 'x', 'after'), ['a', 'b']);
});

test('sortRows: número, texto natural, desc, sort:true e coluna sem sort', () => {
  const rows = [{ n: 10, s: 'x10' }, { n: 2, s: 'x2' }, { n: 33, s: 'X1' }];
  const cols = [{ key: 'n', sort: true }, { key: 's', sort: (r) => r.s }, { key: 'z' }];
  assert.deepEqual(sortRows(rows, cols, { key: 'n', dir: 'asc' }).map((r) => r.n), [2, 10, 33]);
  assert.deepEqual(sortRows(rows, cols, { key: 's', dir: 'desc' }).map((r) => r.s), ['x10', 'x2', 'X1']);
  assert.equal(sortRows(rows, cols, { key: 'z', dir: 'asc' }), rows);
});
