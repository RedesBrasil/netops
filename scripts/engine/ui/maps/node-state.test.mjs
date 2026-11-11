import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reconcileNodes, orderedNodeIds, moveLayer, removeMapNodes, duplicateShape, contrastingText, shapesOverlap, pushHistory, reconcileLayout } from './node-state.js';

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
test('pilha legada: formas no fundo, links logo abaixo dos dispositivos, hosts e notas acima', () => {
  assert.deepEqual(orderedNodeIds(stackedMap(), ['real']), ['object:area', 'edge:real', 'visual:visual', 'visual:other', 'host:a', 'host:b', 'object:note']);
  assert.deepEqual(orderedNodeIds(stackedMap()), ['object:area', 'visual:visual', 'visual:other', 'host:a', 'host:b', 'object:note']);
});
test('avançar/recuar troca exatamente uma camada da pilha mista e preserva posições/rotas', () => {
  const map = stackedMap(), before = structuredClone(map);
  let next = moveLayer(map, 'object:area', 'forward', ['real']);
  assert.deepEqual(orderedNodeIds(next, ['real']), ['edge:real', 'object:area', 'visual:visual', 'visual:other', 'host:a', 'host:b', 'object:note']);
  assert.equal(next.edges.real.z_index, 0); assert.equal(next.objects[0].z_index, 1);
  assert.deepEqual(next.edges.real.route, map.edges.real.route);
  next = moveLayer(next, 'object:area', 'backward', ['real']);
  assert.deepEqual(orderedNodeIds(next, ['real']), ['object:area', 'edge:real', 'visual:visual', 'visual:other', 'host:a', 'host:b', 'object:note']);
  assert.equal(next.positions.a.x, 1);
  assert.deepEqual(map, before); assert.deepEqual(orderedNodeIds(structuredClone(next), ['real']), orderedNodeIds(next, ['real']));
});
test('forma vai para cima de hosts e links; link vai para cima de forma e host', () => {
  let map = moveLayer(stackedMap(), 'object:area', 'front', ['real']);
  assert.equal(orderedNodeIds(map, ['real']).at(-1), 'object:area');
  map = moveLayer(map, 'edge:real', 'front', ['real']);
  assert.deepEqual(orderedNodeIds(map, ['real']).slice(-2), ['object:area', 'edge:real']);
  map = moveLayer(map, 'visual:other', 'front', ['real']);
  assert.equal(orderedNodeIds(map, ['real']).at(-1), 'visual:other');
  assert.equal(map.visual_links[1].z_index, 6);
  map = moveLayer(map, 'host:b', 'back', ['real']);
  assert.equal(orderedNodeIds(map, ['real'])[0], 'host:b');
  map = moveLayer(map, 'object:note', 'back', ['real']);
  assert.deepEqual(orderedNodeIds(map, ['real']).slice(0, 2), ['object:note', 'host:b']);
  // A ordem sobrevive à ida e volta pelo YAML (só z_index inteiros, sem empates).
  const z = [...Object.values(map.positions).map(p => p.z_index), ...map.objects.map(o => o.z_index),
    map.edges.real.z_index, ...map.visual_links.map(l => l.z_index)];
  assert.deepEqual([...z].sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6]);
});
test('pilha respeita limites e inicializa posições de hosts automáticos', () => {
  const map = stackedMap(); delete map.positions.b;
  assert.equal(moveLayer(map, 'object:area', 'backward'), map);
  assert.equal(moveLayer(map, 'object:area', 'back'), map);
  assert.equal(moveLayer(map, 'object:note', 'forward'), map);
  assert.equal(moveLayer(map, 'object:note', 'front'), map);
  assert.equal(moveLayer(map, 'missing', 'forward'), map);
  const next = moveLayer(map, 'object:area', 'forward');
  assert.deepEqual(next.positions.b, { x: 370, y: 165, z_index: 4 });
  assert.throws(() => moveLayer(map, 'host:a', 'invalid'));
});
test('mapa sem dispositivos põe links acima das formas', () => {
  const map = { host_ids: [], positions: {}, edges: {}, objects: [{ id: 's', type: 'shape', position: { x: 0, y: 0 } }],
    visual_links: [{ id: 'v', source: 'object:s', target: 'object:s' }] };
  assert.deepEqual(orderedNodeIds(map), ['object:s', 'visual:v']);
});
test('duplicar forma preserva estilo/tamanho/ícone, desloca e insere uma camada acima', () => {
  const map = stackedMap(), next = duplicateShape(map, 'object:area', 'copy'), copy = next.objects.at(-1);
  assert.deepEqual(copy, { ...map.objects[0], id: 'copy', position: { x: 42, y: 52 }, z_index: 1 });
  assert.deepEqual(orderedNodeIds(next), ['object:area', 'object:copy', 'visual:visual', 'visual:other', 'host:a', 'host:b', 'object:note']);
  assert.notEqual(copy.position, map.objects[0].position);
  assert.deepEqual(next.visual_links.map(({ z_index, ...l }) => l), map.visual_links); assert.equal(map.objects.length, 2);
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
test('frente/trás pulam até o próximo item sobreposto, ignorando links distantes', () => {
  // area (fundo) ... links distantes ... host:a sobreposto
  const map = stackedMap(), links = ['real'];
  const touching = new Set(['object:area|host:a', 'host:a|object:area']);
  const overlaps = (a, b) => touching.has(a + '|' + b);
  let next = moveLayer(map, 'object:area', 'forward', links, overlaps);
  const order = orderedNodeIds(next, links);
  assert.ok(order.indexOf('object:area') > order.indexOf('host:a'));
  assert.ok(order.indexOf('object:area') < order.indexOf('host:b'));
  next = moveLayer(next, 'object:area', 'backward', links, overlaps);
  const back = orderedNodeIds(next, links);
  assert.ok(back.indexOf('object:area') < back.indexOf('host:a'));
  // ninguém sobreposto: anda uma camada
  assert.deepEqual(orderedNodeIds(moveLayer(map, 'object:area', 'forward', links, () => false), links).slice(0, 2), ['edge:real', 'object:area']);
});
test('sobreposição geométrica: retângulos, segmento x retângulo e segmentos cruzados', () => {
  const r = (x, y, w, h) => ({ rect: { x, y, width: w, height: h } }), seg = (a, b, c, d) => ({ segment: [{ x: a, y: b }, { x: c, y: d }] });
  assert.ok(shapesOverlap(r(0, 0, 10, 10), r(5, 5, 10, 10)));
  assert.ok(!shapesOverlap(r(0, 0, 10, 10), r(20, 0, 5, 5)));
  assert.ok(shapesOverlap(seg(-5, 5, 15, 5), r(0, 0, 10, 10)));
  assert.ok(!shapesOverlap(seg(-5, 20, 15, 20), r(0, 0, 10, 10)));
  assert.ok(shapesOverlap(seg(0, 0, 10, 10), seg(0, 10, 10, 0)));
  assert.ok(!shapesOverlap(seg(0, 0, 10, 0), seg(0, 5, 10, 5)));
});
test('histórico guarda só as últimas 10 alterações', () => {
  let stack = [];
  for (let i = 0; i < 15; i++) stack = pushHistory(stack, i);
  assert.deepEqual(stack, [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]);
});
test('desfazer reconcilia com inventário/topologia atuais e restaura objeto apagado', () => {
  const before = stackedMap();
  const current = removeMapNodes(before, ['object:area', 'host:b']);
  // host b sumiu do inventário depois; o enlace "real" também
  const restored = reconcileLayout(before, current, ['a'], []);
  assert.deepEqual(restored.objects.map(o => o.id), ['area', 'note']);
  assert.deepEqual(restored.host_ids, ['a']); assert.deepEqual(restored.members, ['a']);
  assert.deepEqual(Object.keys(restored.positions), ['a']); assert.deepEqual(restored.edges, {});
  assert.deepEqual(restored.visual_links.map(l => l.id), ['visual']);
  // tudo ainda existe: volta exatamente ao estado anterior
  assert.deepEqual(reconcileLayout(before, current, ['a', 'b'], ['real']), before);
});
