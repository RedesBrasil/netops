import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reconcileNodes } from './node-state.js';

const host = () => ({ id: 'host:a', type: 'device', position: { x: 10, y: 20 }, data: { label: 'A' } });
const measured = () => ({ ...host(), measured: { width: 198, height: 91 }, selected: true, dragging: false });

test('snapshot equivalente preserva nós, medidas e seleção', () => {
  const nodes = [measured()];
  assert.equal(reconcileNodes(nodes, [host()]), nodes);
  assert.equal(reconcileNodes(nodes, [host()])[0].measured, nodes[0].measured);
});
test('mudar posição mantém as dimensões e os dados estáveis', () => {
  const old = measured();
  const next = reconcileNodes([old], [{ ...host(), position: { x: 50, y: 60 } }])[0];
  assert.deepEqual(next.position, { x: 50, y: 60 });
  assert.equal(next.measured, old.measured);
  assert.equal(next.data, old.data);
  assert.equal(next.selected, true);
});
test('atualizar cadastro não recria metadados de medição', () => {
  const old = measured();
  const next = reconcileNodes([old], [{ ...host(), data: { label: 'Renomeado' } }])[0];
  assert.equal(next.data.label, 'Renomeado');
  assert.equal(next.measured, old.measured);
  assert.equal(next.position, old.position);
});
test('formas refletem dimensões novas sem perder a medida observada', () => {
  const old = { ...measured(), id: 'object:area', type: 'shape', style: { width: 240, height: 180 }, width: 240, height: 180 };
  // O servidor não fornece measured, como o makeNodes do editor.
  const desired = { id: old.id, type: old.type, data: old.data, position: old.position, style: { width: 300, height: 220 } };
  const merged = reconcileNodes([old], [desired])[0];
  assert.equal(merged.measured, old.measured);
  assert.equal(merged.width, 300);
  assert.equal(merged.height, 220);
});
test('adição, remoção e mudança de tipo respeitam o snapshot', () => {
  const old = measured();
  const desired = { ...host(), type: 'note' };
  assert.equal(reconcileNodes([old], [desired])[0], desired);
  assert.deepEqual(reconcileNodes([old], []), []);
  const added = { ...host(), id: 'host:b' };
  const next = reconcileNodes([old], [host(), added]);
  assert.equal(next[0], old);
  assert.equal(next[1], added);
});
