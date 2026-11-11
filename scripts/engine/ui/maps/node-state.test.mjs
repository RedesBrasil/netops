import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reconcileNodes, orderedNodeIds, moveLayer, removeMapNodes, duplicateShape, contrastingText } from './node-state.js';

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

const { alignNodes } = await import('./node-state.js');
const group = () => [
  { id: 'host:a', position: { x: 50, y: 120 }, measured: { width: 198, height: 91 } },
  { id: 'host:b', position: { x: 400, y: -80 }, measured: { width: 240, height: 110 } },
  { id: 'object:shape', position: { x: -100, y: 350 }, measured: { width: 320, height: 200 } },
  { id: 'host:d', position: { x: 260, y: 230 }, measured: { width: 198, height: 91 } },
];
for (const direction of ['horizontal', 'vertical']) {
  test(`${direction}: centros alinhados e 24 unidades entre bordas de tamanhos diferentes`, () => {
    const nodes = group(), before = structuredClone(nodes), result = alignNodes(nodes, direction);
    assert.deepEqual(nodes, before);
    const axis = direction === 'horizontal' ? 'x' : 'y', cross = axis === 'x' ? 'y' : 'x';
    const size = axis === 'x' ? 'width' : 'height', other = axis === 'x' ? 'height' : 'width';
    const sorted = [...nodes].sort((a, b) => a.position[axis] - b.position[axis]);
    for (let i = 1; i < sorted.length; i++) {
      const a = sorted[i - 1], b = sorted[i];
      assert.equal(result[b.id][axis] - result[a.id][axis] - a.measured[size], 24);
      assert.equal(result[a.id][cross] + a.measured[other] / 2, result[b.id][cross] + b.measured[other] / 2);
    }
    assert.equal(result[sorted[0].id][axis], Math.min(...nodes.map(n => n.position[axis])));
    assert.deepEqual(Object.keys(result).sort(), nodes.map(n => n.id).sort());
    assert.deepEqual(alignNodes(nodes.slice(0, 1), direction), {});
    assert.equal(Object.keys(alignNodes(nodes.slice(0, 2), direction)).length, 2);
  });
}
test('alinhamento é determinístico nos empates e não inclui nós de fora da seleção', () => {
  const a = { id: 'a', position: { x: 0, y: 0 }, width: 100, height: 70 };
  const b = { ...a, id: 'b' };
  assert.deepEqual(alignNodes([a, b], 'horizontal'), alignNodes([b, a], 'horizontal'));
  assert.equal(alignNodes([a, b], 'horizontal').b.x, 124);
  assert.equal(alignNodes([a, b], 'horizontal').outside, undefined);
});
test('alinhamento rejeita dimensões/coordenadas inválidas sem resultado parcial', () => {
  assert.throws(() => alignNodes(group(), 'diagonal'));
  const nodes = group(); nodes.forEach((n, i) => { n.position.x = 999990 + i; });
  assert.throws(() => alignNodes(nodes, 'horizontal'));
  nodes[0].position.x = NaN;
  assert.throws(() => alignNodes(nodes, 'vertical'));
  nodes[0].position.x = 0; nodes[0].measured.width = 0;
  assert.throws(() => alignNodes(nodes, 'vertical'));
});

const stackedMap = () => ({ id: 'test', kind: 'custom', members: ['a', 'b'], host_ids: ['a', 'b'],
  positions: { a: { x: 1, y: 2 }, b: { x: 3, y: 4 } },
  objects: [{ id: 'area', type: 'shape', label: '', form: 'ellipse', position: { x: 10, y: 20 }, width: 320, height: 200, color: '#123456', stroke: '#abcdef', icon: 'router' },
    { id: 'note', type: 'note', position: { x: 30, y: 40 }, label: 'Nota' }],
  edges: { real: { route: { axis: 'x', tracks: [120] } } },
  visual_links: [{ id: 'visual', source: 'host:a', target: 'object:area' }, { id: 'other', source: 'host:b', target: 'object:note' }] });
test('texto da forma e prévia contrastam com cores claras/escuras em qualquer tema', () => {
  for (const hex of ['#ffffff', '#DBEAFE', '#00ff00', '#ffff00']) assert.equal(contrastingText(hex), '#000000');
  for (const hex of ['#000000', '#123456', '#0000ff']) assert.equal(contrastingText(hex), '#ffffff');
  for (const invalid of [null, undefined, '', 'red', '#abc', '#12345z']) assert.equal(contrastingText(invalid), undefined);
});
test('pilha legada conserva formas atrás de hosts e demais objetos', () => {
  assert.deepEqual(orderedNodeIds(stackedMap()), ['object:area', 'host:a', 'host:b', 'object:note']);
});
test('avançar/recuar troca exatamente uma camada mista e preserva posições/rotas', () => {
  const map = stackedMap(), before = structuredClone(map);
  let next = moveLayer(map, 'object:area', 'forward');
  assert.deepEqual(orderedNodeIds(next), ['host:a', 'object:area', 'host:b', 'object:note']);
  assert.equal(next.positions.a.z_index, 0); assert.equal(next.objects[0].z_index, 1);
  next = moveLayer(next, 'object:area', 'forward');
  assert.deepEqual(orderedNodeIds(next), ['host:a', 'host:b', 'object:area', 'object:note']);
  next = moveLayer(next, 'object:area', 'backward');
  assert.deepEqual(orderedNodeIds(next), ['host:a', 'object:area', 'host:b', 'object:note']);
  assert.deepEqual(next.edges, map.edges); assert.equal(next.positions.a.x, 1);
  assert.deepEqual(map, before); assert.deepEqual(orderedNodeIds(structuredClone(next)), orderedNodeIds(next));
});
test('pilha respeita limites e inicializa posições de hosts automáticos', () => {
  const map = stackedMap(); delete map.positions.b;
  assert.equal(moveLayer(map, 'object:area', 'backward'), map);
  assert.equal(moveLayer(map, 'object:note', 'forward'), map);
  assert.equal(moveLayer(map, 'missing', 'forward'), map);
  const next = moveLayer(map, 'object:area', 'forward');
  assert.deepEqual(next.positions.b, { x: 370, y: 165, z_index: 2 });
  assert.throws(() => moveLayer(map, 'host:a', 'invalid'));
});
test('duplicar forma preserva estilo/tamanho/ícone, desloca e insere uma camada acima', () => {
  const map = stackedMap(), next = duplicateShape(map, 'object:area', 'copy'), copy = next.objects.at(-1);
  assert.deepEqual(copy, { ...map.objects[0], id: 'copy', position: { x: 42, y: 52 }, z_index: 1 });
  assert.deepEqual(orderedNodeIds(next), ['object:area', 'object:copy', 'host:a', 'host:b', 'object:note']);
  assert.notEqual(copy.position, map.objects[0].position);
  assert.equal(next.visual_links, map.visual_links); assert.equal(map.objects.length, 2);
  assert.equal(duplicateShape(map, 'object:note', 'copy'), map);
});
test('remover grupo misto limpa somente membros/objetos/linhas visuais envolvidos', () => {
  const map = stackedMap(), next = removeMapNodes(map, ['host:a', 'object:area']);
  assert.deepEqual(next.host_ids, ['b']); assert.deepEqual(next.members, ['b']);
  assert.deepEqual(Object.keys(next.positions), ['b']); assert.deepEqual(next.objects.map(o => o.id), ['note']);
  assert.deepEqual(next.visual_links.map(l => l.id), ['other']); assert.equal(next.edges, map.edges);
  assert.equal(map.host_ids.length, 2);
});
test('mapa automático protege hosts enquanto permite excluir formas selecionadas', () => {
  const map = { ...stackedMap(), kind: 'all' }, next = removeMapNodes(map, ['host:a', 'object:area']);
  assert.deepEqual(next.host_ids, map.host_ids); assert.deepEqual(next.members, map.members);
  assert.deepEqual(next.positions, map.positions); assert.deepEqual(next.objects.map(o => o.id), ['note']);
});
