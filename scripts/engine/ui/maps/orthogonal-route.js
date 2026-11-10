import { anchorPoint } from './parallel-edges.js';

const other = axis => axis === 'x' ? 'y' : 'x';
const atAxis = (route, index) => index % 2 === 0 ? route.axis : other(route.axis);
const distance = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
const EXIT_LENGTH = 36;
const sideDirection = side => ({
  left: { axis: 'x', sign: -1 }, right: { axis: 'x', sign: 1 },
  top: { axis: 'y', sign: -1 }, bottom: { axis: 'y', sign: 1 },
})[side];

// Só os cotovelos das extremidades se adaptam ao lado escolhido no host.
export function orientRoute(base, route) {
  const source = sideDirection(base.anchors?.source?.side);
  const target = sideDirection(base.anchors?.target?.side);
  if (!route || !source || !target) return route;
  const result = { ...route, tracks: [...route.tracks] };
  const sourceExit = base.start[source.axis] + source.sign * EXIT_LENGTH;
  const targetExit = base.end[target.axis] + target.sign * EXIT_LENGTH;
  if (result.axis !== source.axis) {
    result.axis = source.axis;
    result.tracks.unshift(sourceExit);
  }
  if (!result.tracks.length) {
    const cross = other(source.axis);
    if (target.axis === cross && (base.end[source.axis] - base.start[source.axis]) * source.sign >= EXIT_LENGTH &&
        (base.start[cross] - base.end[cross]) * target.sign >= EXIT_LENGTH) return result;
    result.tracks.push(sourceExit);
  }
  if ((result.tracks[0] - base.start[source.axis]) * source.sign < EXIT_LENGTH) result.tracks[0] = sourceExit;
  if (atAxis(result, result.tracks.length + 1) !== target.axis) result.tracks.push(targetExit);
  const last = result.tracks.length - 1;
  if ((result.tracks[last] - base.end[target.axis]) * target.sign < EXIT_LENGTH) result.tracks[last] = targetExit;
  // Um único cotovelo compartilhado pode não atender às duas saídas opostas.
  if (result.tracks.length === 1 && (result.tracks[0] - base.start[source.axis]) * source.sign < EXIT_LENGTH) {
    const cross = other(source.axis);
    const middle = (base.start[cross] + base.end[cross]) / 2;
    result.tracks = [sourceExit, Math.abs(base.start[cross] - base.end[cross]) < 20 ? middle + 72 : middle, targetExit];
  }
  return result;
}

export function routePoints(start, end, route) {
  const points = [{ ...start }];
  route.tracks.forEach((value, index) => points.push({ ...points[points.length - 1], [atAxis(route, index)]: value }));
  const lastAxis = atAxis(route, route.tracks.length);
  points.push({ ...points[points.length - 1], [lastAxis]: end[lastAxis] }, { ...end });
  return points;
}
export function routeGeometry(base, route) {
  route = orientRoute(base, route);
  const points = routePoints(base.start, base.end, route);
  const segments = points.slice(0, -1).map((point, index) => {
    const end = points[index + 1];
    return { index, axis: atAxis(route, index), length: distance(point, end), x: (point.x + end.x) / 2, y: (point.y + end.y) / 2 };
  });
  const labelSegment = segments.reduce((best, segment) => segment.length > best.length ? segment : best, segments[0]);
  return { ...base, points, segments, labelX: labelSegment.x, labelY: labelSegment.y, labelAxis: labelSegment.axis,
    path: points.map((point, index) => `${index ? 'L' : 'M'} ${point.x},${point.y}`).join(' ') };
}
function coordinateRange(rect, axis) {
  return [rect[axis], rect[axis] + rect[axis === 'x' ? 'width' : 'height']];
}
function closestInRanges(value, ranges) {
  return ranges.filter(([low, high]) => low <= high).map(([low, high]) => Math.max(low, Math.min(high, value)))
    .sort((a, b) => Math.abs(a - value) - Math.abs(b - value))[0];
}
function atCoordinate(rect, side, value) {
  const [low, high] = coordinateRange(rect, other(sideDirection(side).axis));
  return { side, ratio: (value - low) / (high - low) };
}

// Um L precisa de lados perpendiculares. Reposiciona as pontas, nunca os hosts.
function singleBend(base) {
  const sides = ['left', 'right', 'top', 'bottom'];
  for (const sourceSide of [base.anchors.source.side, ...sides.filter(s => s !== base.anchors.source.side)]) {
    const source = sideDirection(sourceSide), axis = source.axis, cross = other(axis);
    const start = anchorPoint(base.a, { side: sourceSide, ratio: .5 });
    for (const targetSide of [base.anchors.target.side, ...sides.filter(s => s !== base.anchors.target.side)]) {
      const target = sideDirection(targetSide);
      if (target.axis !== cross) continue;
      const end = anchorPoint(base.b, { side: targetSide, ratio: .5 });
      const [sLow, sHigh] = coordinateRange(base.a, cross), [tLow, tHigh] = coordinateRange(base.b, axis);
      const sExit = end[cross] + target.sign * EXIT_LENGTH, tExit = start[axis] + source.sign * EXIT_LENGTH;
      const s = closestInRanges(base.start[cross], [[target.sign > 0 ? Math.max(sLow, sExit) : sLow, target.sign < 0 ? Math.min(sHigh, sExit) : sHigh]]);
      const t = closestInRanges(base.end[axis], [[source.sign > 0 ? Math.max(tLow, tExit) : tLow, source.sign < 0 ? Math.min(tHigh, tExit) : tHigh]]);
      if (s !== undefined && t !== undefined) return {
        anchors: { source: atCoordinate(base.a, sourceSide, s), target: atCoordinate(base.b, targetSide, t) },
        route: { axis, tracks: [] },
      };
    }
  }
  return null;
}

// Trocar a quantidade de cantos troca o eixo de chegada. Ajusta só a ponta B.
function finishBend(base, route) {
  if (!route.tracks.length) return singleBend(base);
  const tracks = [...route.tracks], source = sideDirection(base.anchors.source.side);
  for (let i = 0; i < tracks.length; i++) {
    const axis = atAxis(route, i), previous = i > 1 ? tracks[i - 2] : base.start[axis];
    if (!i) {
      if ((tracks[i] - previous) * source.sign < EXIT_LENGTH) tracks[i] = previous + source.sign * EXIT_LENGTH;
    } else if (Math.abs(tracks[i] - previous) < 24) tracks[i] = previous + (tracks[i] < previous ? -36 : 36);
  }
  const last = tracks.length - 1, axis = atAxis(route, tracks.length + 1), cross = other(axis);
  const sides = axis === 'x' ? ['left', 'right'] : ['top', 'bottom'];
  const candidates = [];
  for (const side of sides) {
    const { sign } = sideDirection(side), end = anchorPoint(base.b, { side, ratio: .5 });
    let value = tracks[last];
    if ((value - end[axis]) * sign < EXIT_LENGTH) value = end[axis] + sign * EXIT_LENGTH;
    const previous = last > 1 ? tracks[last - 2] : base.start[axis];
    if (Math.abs(value - previous) < 24) value += sign * 36;
    if (last === 0 && (value - base.start[axis]) * source.sign < EXIT_LENGTH) continue;
    const before = last > 0 ? tracks[last - 1] : base.start[cross];
    const [low, high] = coordinateRange(base.b, cross);
    const coordinate = closestInRanges(base.end[cross], [[low, Math.min(high, before - 24)], [Math.max(low, before + 24), high]]);
    if (coordinate === undefined) continue;
    candidates.push({ value, anchor: atCoordinate(base.b, side, coordinate), cost: Math.abs(value - tracks[last]) + Math.abs(coordinate - base.end[cross]) });
  }
  candidates.sort((a, b) => a.cost - b.cost);
  const best = candidates[0];
  if (!best) return null;
  tracks[last] = best.value;
  return { anchors: { ...base.anchors, target: best.anchor }, route: { ...route, tracks } };
}
export function moveSingleBend(base, delta) {
  const axis = sideDirection(base.anchors.source.side).axis, cross = other(axis);
  return singleBend({ ...base, start: { ...base.start, [cross]: base.start[cross] + delta[cross] },
    end: { ...base.end, [axis]: base.end[axis] + delta[axis] } });
}
export function addBend(base, route, corner) {
  if (!route) return singleBend(base);
  route = orientRoute(base, route);
  const points = routePoints(base.start, base.end, route);
  if (!Number.isInteger(corner) || corner < 1 || corner > points.length - 2) {
    let score = -1;
    for (let i = 1; i < points.length - 1; i++) {
      const room = Math.min(distance(points[i - 1], points[i]), distance(points[i], points[i + 1]));
      if (room > score) { score = room; corner = i; }
    }
  }
  const a = points[corner - 1], b = points[corner], c = points[corner + 1];
  const axis = atAxis(route, corner - 1), cross = other(axis);
  const first = { ...a, [axis]: (a[axis] + b[axis]) / 2 };
  const second = { ...first, [cross]: (b[cross] + c[cross]) / 2 };
  const corners = points.slice(1, -1);
  corners.splice(corner - 1, 1, first, second);
  return finishBend(base, { ...route, tracks: corners.slice(0, -1).map((point, i) => point[atAxis(route, i)]) });
}
export function removeBend(base, route, corner) {
  if (!route) return null;
  route = orientRoute(base, route);
  const corners = routePoints(base.start, base.end, route).slice(1, -1);
  if (corners.length === 1) return { anchors: base.anchors, route: null };
  const index = Number.isInteger(corner) ? Math.max(0, Math.min(corners.length - 1, corner - 1)) : corners.length - 1;
  corners.splice(index, 1);
  return finishBend(base, { ...route, tracks: corners.slice(0, -1).map((point, i) => point[atAxis(route, i)]) });
}
export function moveRoute(route, part, index, delta) {
  const tracks = [...route.tracks];
  if (part === 'line') tracks.forEach((value, i) => { tracks[i] = value + delta[atAxis(route, i)]; });
  if (part === 'segment' && index > 0 && index <= tracks.length) tracks[index - 1] += delta[atAxis(route, index - 1)];
  if (part === 'corner') for (const i of [index - 2, index - 1]) if (i >= 0 && i < tracks.length) tracks[i] += delta[atAxis(route, i)];
  return { ...route, tracks };
}
