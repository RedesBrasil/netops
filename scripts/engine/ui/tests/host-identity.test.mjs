import test from 'node:test';
import assert from 'node:assert/strict';
import { parseHostId, nodeHostId, mapToWire, snapshotToView } from '../static/js/host-identity.js';

test('UI selection and graph IDs resolve strictly to integer identity', () => {
  assert.equal(parseHostId('42'), 42);
  assert.equal(nodeHostId('host:42'), 42);
  for (const value of ['042', '4.2', '42x', ' 42', '0', '', true, null, -1, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => parseHostId(value));
  }
});

test('wire roundtrip preserves integer references, positions and mixed visual layers', () => {
  const map = { id: 'all', name: 'Rede geral', kind: 'all', members: [42], host_ids: [42],
    positions: [{ host_id: 42, x: 12, y: 34, z_index: 3 }], objects: [{ id: 'shape', type: 'shape', position: { x: 90, y: 90 } }],
    edges: {}, visual_links: [{ id: 'v', source: { kind: 'host', host_id: 42 }, target: { kind: 'object', object_id: 'shape' }, label: '', route: { axis: 'x', tracks: [50] } }] };
  const snapshot = { hosts: [{ id: 42, hostname: 'Roteador' }], maps: [map] };
  const view = snapshotToView(snapshot);
  assert.equal(view.hosts[42].id, 42);
  assert.deepEqual(view.maps[0].positions[42], { x: 12, y: 34, z_index: 3 });
  assert.equal(view.maps[0].visual_links[0].source, 'host:42');
  const { host_ids, ...wireMap } = map;
  assert.deepEqual(mapToWire(view.maps[0]), { ...wireMap, excluded: [] });
  assert.deepEqual(snapshot, { hosts: [{ id: 42, hostname: 'Roteador' }], maps: [map] });
});

test('invalid graph host identity cannot escape into persisted map', () => {
  const map = { members: [], positions: {}, visual_links: [{ source: 'host:router', target: 'object:shape' }] };
  assert.throws(() => mapToWire(map));
});
