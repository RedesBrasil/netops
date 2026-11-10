// A mesma dupla de hosts compartilha as faixas, independentemente do sentido.
export function separateEdges(edges) {
  const groups = new Map();
  for (const edge of edges) {
    const key = JSON.stringify([edge.source, edge.target].sort());
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(edge);
  }
  const lanes = new Map();
  for (const group of groups.values()) {
    group.forEach((edge, index) => lanes.set(edge.id, { index, count: group.length }));
  }
  return edges.map(edge => ({ ...edge, type: 'editableStraight', data: { ...edge.data, lane: lanes.get(edge.id) } }));
}

export function nodeRect(node) {
  const position = node.internals?.positionAbsolute || node.position;
  const width = node.measured?.width || node.width || 198;
  const height = node.measured?.height || node.height || 91;
  return { x: position.x, y: position.y, width, height, cx: position.x + width / 2, cy: position.y + height / 2 };
}
const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
function support(rect, normal) { return (Math.abs(normal.x) * rect.width + Math.abs(normal.y) * rect.height) * .44; }

export function anchorPoint(rect, anchor) {
  const ratio = clamp(anchor.ratio, 0, 1);
  switch (anchor.side) {
    case 'left': return { x: rect.x, y: rect.y + rect.height * ratio };
    case 'right': return { x: rect.x + rect.width, y: rect.y + rect.height * ratio };
    case 'top': return { x: rect.x + rect.width * ratio, y: rect.y };
    default: return { x: rect.x + rect.width * ratio, y: rect.y + rect.height };
  }
}
export function nearestAnchor(rect, point) {
  const h = clamp((point.x - rect.x) / rect.width, 0, 1);
  const v = clamp((point.y - rect.y) / rect.height, 0, 1);
  return [
    { side: 'left', ratio: v }, { side: 'right', ratio: v },
    { side: 'top', ratio: h }, { side: 'bottom', ratio: h },
  ].reduce((best, anchor) => {
    const p = anchorPoint(rect, anchor);
    const distance = (p.x - point.x) ** 2 + (p.y - point.y) ** 2;
    return distance < best.distance ? { anchor, distance } : best;
  }, { distance: Infinity }).anchor;
}
function clipLine(rect, origin, direction) {
  let near = -Infinity, far = Infinity;
  for (const [axis, size] of [['x', 'width'], ['y', 'height']]) {
    if (Math.abs(direction[axis]) < 1e-9) {
      if (origin[axis] < rect[axis] - 1e-6 || origin[axis] > rect[axis] + rect[size] + 1e-6) return null;
      continue;
    }
    const t1 = (rect[axis] - origin[axis]) / direction[axis];
    const t2 = (rect[axis] + rect[size] - origin[axis]) / direction[axis];
    near = Math.max(near, Math.min(t1, t2)); far = Math.min(far, Math.max(t1, t2));
  }
  return near <= far ? { near, far } : null;
}
function intersections(a, b, origin, direction) {
  const first = clipLine(a, origin, direction), last = clipLine(b, origin, direction);
  if (!first || !last) return null;
  return {
    start: { x: origin.x + first.far * direction.x, y: origin.y + first.far * direction.y },
    end: { x: origin.x + last.near * direction.x, y: origin.y + last.near * direction.y },
  };
}
export function straightGeometry({ source, target, a, b, lane, anchors }) {
  let points;
  if (anchors?.source && anchors?.target) {
    points = { start: anchorPoint(a, anchors.source), end: anchorPoint(b, anchors.target) };
  } else {
    const dx = b.cx - a.cx, dy = b.cy - a.cy;
    const length = Math.hypot(dx, dy) || 1;
    const direction = { x: dx / length || (dy === 0 ? 1 : 0), y: dy / length };
    const sign = source < target ? 1 : -1;
    const normal = { x: -direction.y * sign, y: direction.x * sign };
    const maxOffset = Math.min(support(a, normal), support(b, normal));
    const gap = lane.count > 1 ? Math.min(30, maxOffset * 2 / (lane.count - 1)) : 0;
    const offset = (lane.index - (lane.count - 1) / 2) * gap;
    const origin = { x: a.cx + normal.x * offset, y: a.cy + normal.y * offset };
    points = intersections(a, b, origin, direction) || { start: { x: a.cx, y: a.cy }, end: { x: b.cx, y: b.cy } };
  }
  const { start, end } = points;
  const fraction = lane.count > 1 ? .3 + .4 * lane.index / (lane.count - 1) : .5;
  return {
    ...points,
    anchors: anchors?.source && anchors?.target ? anchors : { source: nearestAnchor(a, start), target: nearestAnchor(b, end) },
    path: `M ${start.x},${start.y} L ${end.x},${end.y}`,
    labelX: start.x + (end.x - start.x) * fraction,
    labelY: start.y + (end.y - start.y) * fraction,
  };
}

export function slideLine(a, b, geometry, delta) {
  const { start, end } = geometry;
  const dx = end.x - start.x, dy = end.y - start.y, length = Math.hypot(dx, dy);
  if (length < 1e-6) return geometry.anchors;
  const direction = { x: dx / length, y: dy / length };
  const normal = { x: -direction.y, y: direction.x };
  let low = -Infinity, high = Infinity;
  for (const rect of [a, b]) {
    const distance = (start.x - rect.cx) * normal.x + (start.y - rect.cy) * normal.y;
    const extent = support(rect, normal);
    low = Math.max(low, -extent - distance); high = Math.min(high, extent - distance);
  }
  if (low > high) return geometry.anchors;
  const shift = clamp(delta.x * normal.x + delta.y * normal.y, low, high);
  const points = intersections(a, b, { x: start.x + normal.x * shift, y: start.y + normal.y * shift }, direction);
  return points ? { source: nearestAnchor(a, points.start), target: nearestAnchor(b, points.end) } : geometry.anchors;
}
