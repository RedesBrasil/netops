// Conserva as medidas e o estado transitório do React Flow ao atualizar o layout.
const same = (a, b) => a === b || JSON.stringify(a) === JSON.stringify(b);
export function reconcileNodes(previous, desired) {
  const byId = new Map(previous.map(node => [node.id, node]));
  const result = desired.map(node => {
    const old = byId.get(node.id);
    if (!old || old.type !== node.type) return node;
    const next = { ...old, ...node };
    for (const key of ['position', 'data', 'style']) {
      if (same(old[key], node[key])) next[key] = old[key];
    }
    if (node.type === 'shape') {
      next.width = node.style.width;
      next.height = node.style.height;
    }
    return Object.keys(next).every(key => next[key] === old[key]) ? old : next;
  });
  return result.length === previous.length && result.every((node, i) => node === previous[i]) ? previous : result;
}

// Espaçamento entre bordas, não entre centros: preserva a ordem visual do grupo.
export function alignNodes(nodes, direction, gap = 24) {
  if (!['horizontal', 'vertical'].includes(direction)) throw new Error('Alinhamento inválido');
  if (!Number.isFinite(gap) || gap < 0) throw new Error('Espaçamento inválido');
  if (nodes.length < 2) return {};
  const horizontal = direction === 'horizontal', axis = horizontal ? 'x' : 'y', cross = horizontal ? 'y' : 'x';
  const rectangles = nodes.map(node => {
    const width = node.measured?.width ?? node.width ?? node.style?.width ?? 198;
    const height = node.measured?.height ?? node.height ?? node.style?.height ?? 91;
    const rect = { id: node.id, x: node.position.x, y: node.position.y, width, height };
    if (![rect.x, rect.y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) throw new Error('Dimensões inválidas para alinhar');
    return rect;
  });
  const size = horizontal ? 'width' : 'height', crossSize = horizontal ? 'height' : 'width';
  rectangles.sort((a, b) => a[axis] - b[axis] || a[cross] - b[cross] || a.id.localeCompare(b.id));
  let position = Math.min(...rectangles.map(r => r[axis]));
  const center = (Math.min(...rectangles.map(r => r[cross])) + Math.max(...rectangles.map(r => r[cross] + r[crossSize]))) / 2;
  const result = {};
  for (const rect of rectangles) {
    const point = { [axis]: position, [cross]: center - rect[crossSize] / 2 };
    if (!Object.values(point).every(n => Number.isFinite(n) && Math.abs(n) <= 1000000)) throw new Error('O alinhamento excede os limites do mapa');
    result[rect.id] = point;
    position += rect[size] + gap;
  }
  return result;
}

// Hosts e objetos compartilham a mesma pilha; mapas antigos mantêm as formas no fundo.
export function orderedNodeIds(map) {
  return [...map.host_ids.map(id => ({ id: 'host:' + id, z: map.positions[id]?.z_index ?? 0 })),
    ...map.objects.map(o => ({ id: 'object:' + o.id, z: o.z_index ?? (o.type === 'shape' ? -1 : 0) }))]
    .sort((a, b) => a.z - b.z).map(n => n.id);
}
export function applyLayerOrder(map, order) {
  const layers = new Map(order.map((id, index) => [id, index]));
  return { ...map, positions: Object.fromEntries(map.host_ids.map((id, index) => [id,
    { ...(map.positions[id] || defaultHostPosition(index)), z_index: layers.get('host:' + id) }])),
    objects: map.objects.map(o => ({ ...o, z_index: layers.get('object:' + o.id) })) };
}
export const defaultHostPosition = index => ({ x: 70 + index % 3 * 300, y: 90 + Math.floor(index / 3) * 220 + index % 2 * 75 });
// Escolhe o texto com maior contraste sobre qualquer preenchimento HEX válido.
export function contrastingText(hex) {
  if (!/^#[0-9a-f]{6}$/i.test(hex || '')) return undefined;
  const channels = [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16) / 255)
    .map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
  const luminance = channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
  return luminance > .179 ? '#000000' : '#ffffff';
}
export function moveLayer(map, id, direction) {
  if (!['forward', 'backward'].includes(direction)) throw new Error('Direção de camada inválida');
  const order = orderedNodeIds(map), index = order.indexOf(id), next = index + (direction === 'forward' ? 1 : -1);
  if (index < 0 || next < 0 || next >= order.length) return map;
  [order[index], order[next]] = [order[next], order[index]];
  return applyLayerOrder(map, order);
}

// Remover do mapa nunca remove o cadastro canônico de um host.
export function removeMapNodes(map, ids) {
  const removable = new Set(ids.filter(id => id.startsWith('object:') || map.kind === 'custom' && id.startsWith('host:')));
  const positions = Object.fromEntries(Object.entries(map.positions).filter(([id]) => !removable.has('host:' + id)));
  return { ...map, positions, members: map.members.filter(id => !removable.has('host:' + id)),
    host_ids: map.host_ids.filter(id => !removable.has('host:' + id)),
    objects: map.objects.filter(o => !removable.has('object:' + o.id)),
    visual_links: map.visual_links.filter(l => !removable.has(l.source) && !removable.has(l.target)) };
}

export function duplicateShape(map, id, newId) {
  const source = map.objects.find(o => 'object:' + o.id === id && o.type === 'shape');
  if (!source) return map;
  const copy = { ...source, id: newId, position: { x: Math.min(1000000, source.position.x + 32), y: Math.min(1000000, source.position.y + 32) } };
  const order = orderedNodeIds(map); order.splice(order.indexOf(id) + 1, 0, 'object:' + newId);
  return applyLayerOrder({ ...map, objects: [...map.objects, copy] }, order);
}
