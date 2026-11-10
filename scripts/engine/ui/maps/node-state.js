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
