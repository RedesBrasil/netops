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
// Pilha única de camadas: hosts, formas, notas, referências e links (físicos e
// visuais) disputam a mesma ordem. Sem z_index salvo, formas ficam no fundo e
// links logo abaixo do dispositivo mais baixo, para não sumirem sob uma área.
export const edgeLayerId = id => 'edge:' + id;
export function mapLinkIds(map, links = []) {
  const ids = new Set(map.host_ids);
  return links.filter(l => ids.has(l.a.host) && ids.has(l.b.host)).map(l => l.id);
}
export function orderedNodeIds(map, linkIds = []) {
  const nodes = [...map.host_ids.map(id => ({ id: 'host:' + id, z: map.positions[id]?.z_index ?? 0 })),
    ...map.objects.map(o => ({ id: 'object:' + o.id, z: o.z_index ?? (o.type === 'shape' ? -1 : 0), shape: o.type === 'shape' }))];
  const devices = nodes.filter(n => !n.shape).map(n => n.z);
  const linkZ = devices.length ? Math.min(...devices) - .5 : Math.max(-1, ...nodes.map(n => n.z)) + .5;
  const lines = [...linkIds.map(id => ({ id: edgeLayerId(id), z: map.edges?.[id]?.z_index ?? linkZ })),
    ...(map.visual_links || []).map(l => ({ id: 'visual:' + l.id, z: l.z_index ?? linkZ }))];
  return [...nodes, ...lines].sort((a, b) => a.z - b.z).map(n => n.id);
}
export function applyLayerOrder(map, order) {
  const layers = new Map(order.map((id, index) => [id, index]));
  const edges = { ...map.edges };
  for (const id of order) if (id.startsWith('edge:')) edges[id.slice(5)] = { ...edges[id.slice(5)], z_index: layers.get(id) };
  return { ...map, positions: Object.fromEntries(map.host_ids.map((id, index) => [id,
    { ...(map.positions[id] || defaultHostPosition(index)), z_index: layers.get('host:' + id) }])),
    objects: map.objects.map(o => ({ ...o, z_index: layers.get('object:' + o.id) })),
    ...(map.edges ? { edges } : {}),
    ...(map.visual_links ? { visual_links: map.visual_links.map(l => layers.has('visual:' + l.id) ? { ...l, z_index: layers.get('visual:' + l.id) } : l) } : {}) };
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
export const LAYER_DIRECTIONS = ['front', 'forward', 'backward', 'back'];
// Formas geométricas p/ sobreposição: { rect: {x,y,width,height} } ou { segment: [p, q] }.
const inside = (p, r) => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height;
const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
function segmentsCross([p1, p2], [q1, q2]) {
  const d1 = cross(q1, q2, p1), d2 = cross(q1, q2, p2), d3 = cross(p1, p2, q1), d4 = cross(p1, p2, q2);
  return (d1 > 0) !== (d2 > 0) && (d3 > 0) !== (d4 > 0);
}
function segmentHitsRect(seg, r) {
  if (inside(seg[0], r) || inside(seg[1], r)) return true;
  const c = [{ x: r.x, y: r.y }, { x: r.x + r.width, y: r.y }, { x: r.x + r.width, y: r.y + r.height }, { x: r.x, y: r.y + r.height }];
  return c.some((p, i) => segmentsCross(seg, [p, c[(i + 1) % 4]]));
}
export function shapesOverlap(a, b) {
  if (!a || !b) return false;
  if (a.rect && b.rect) return a.rect.x < b.rect.x + b.rect.width && b.rect.x < a.rect.x + a.rect.width
    && a.rect.y < b.rect.y + b.rect.height && b.rect.y < a.rect.y + a.rect.height;
  if (a.segment && b.segment) return segmentsCross(a.segment, b.segment);
  return a.segment ? segmentHitsRect(a.segment, b.rect) : segmentHitsRect(b.segment, a.rect);
}
// Avançar/recuar pula para além do próximo item que SOBREPÕE o alvo (como em editores
// de desenho): passar por um link distante que não cruza a forma não mudaria nada na tela.
// Sem `overlaps` (ou sem ninguém sobreposto na direção), anda uma camada.
export function moveLayer(map, id, direction, linkIds = [], overlaps = null) {
  if (!LAYER_DIRECTIONS.includes(direction)) throw new Error('Direção de camada inválida');
  const order = orderedNodeIds(map, linkIds), index = order.indexOf(id);
  if (index < 0) return map;
  const step = direction === 'forward' ? 1 : -1;
  let next = direction === 'front' ? order.length - 1 : direction === 'back' ? 0 : index + step;
  if ((direction === 'forward' || direction === 'backward') && overlaps) {
    for (let i = index + step; i >= 0 && i < order.length; i += step) if (overlaps(id, order[i])) { next = i; break; }
  }
  if (next < 0 || next >= order.length || next === index) return map;
  order.splice(index, 1); order.splice(next, 0, id);
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

export function duplicateShape(map, id, newId, linkIds = []) {
  const source = map.objects.find(o => 'object:' + o.id === id && o.type === 'shape');
  if (!source) return map;
  const copy = { ...source, id: newId, position: { x: Math.min(1000000, source.position.x + 32), y: Math.min(1000000, source.position.y + 32) } };
  const order = orderedNodeIds(map, linkIds); order.splice(order.indexOf(id) + 1, 0, 'object:' + newId);
  return applyLayerOrder({ ...map, objects: [...map.objects, copy] }, order);
}

// Histórico de desfazer (Ctrl+Z): só o layout do mapa. Exclusões canônicas (host do
// inventário, enlace da topologia) não passam por aqui e não são desfeitas.
export const HISTORY_LIMIT = 10;
export function pushHistory(stack, value, limit = HISTORY_LIMIT) {
  return [...stack, value].slice(-limit);
}
// Um estado antigo pode citar host/enlace que deixou de existir desde então; o servidor
// recusaria o mapa inteiro. Reconcilia com o inventário e a topologia atuais.
export function reconcileLayout(previous, current, hostIds, linkIds) {
  const hosts = new Set(hostIds.map(String)), known = new Set(linkIds);
  const has = id => hosts.has(String(id));
  const visible = previous.kind === 'custom' ? previous.host_ids.filter(has) : current.host_ids;
  const visibleSet = new Set(visible.map(String));
  const objects = new Set(previous.objects.map(o => 'object:' + o.id));
  const exists = ref => ref.startsWith('host:') ? visibleSet.has(ref.slice(5)) : objects.has(ref);
  return { ...previous, host_ids: visible,
    members: previous.members.filter(has),
    positions: Object.fromEntries(Object.entries(previous.positions).filter(([id]) => has(id))),
    edges: Object.fromEntries(Object.entries(previous.edges || {}).filter(([id]) => known.has(id))),
    visual_links: previous.visual_links.filter(l => exists(l.source) && exists(l.target)) };
}
