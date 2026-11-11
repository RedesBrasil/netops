import { createContext } from 'preact';
import { useContext, useRef, useState } from 'preact/hooks';
import { BaseEdge, EdgeLabelRenderer, useInternalNode, useReactFlow, useViewport } from '@xyflow/react';
import { nodeRect, straightGeometry, nearestAnchor, anchorPoint, slideLine } from './parallel-edges.js';
import { routeGeometry, moveRoute, moveSingleBend, orientRoute } from './orthogonal-route.js';

export const LineEditing = createContext(null);
export function StraightEdge(props) {
  const source = useInternalNode(props.source), target = useInternalNode(props.target);
  const editing = useContext(LineEditing);
  const flow = useReactFlow();
  const { zoom } = useViewport();
  const [draft, setDraft] = useState(null);
  const drag = useRef(null);
  if (!source || !target) return null;
  const a = nodeRect(source), b = nodeRect(target);
  const savedRoute = draft?.route === undefined ? props.data.route : draft.route;
  const base = straightGeometry({ ...props, a, b, lane: props.data.lane, anchors: draft?.anchors || props.data.anchors });
  const route = savedRoute ? orientRoute(base, savedRoute) : null;
  const geometry = route ? routeGeometry(base, route) : base;
  const active = editing.selected === props.id;
  const { index, count } = props.data.lane;
  const label = props.label ? count > 1 ? `${index + 1}: ${props.label}` : props.label : '';

  function change(state, part, control, point, delta) {
    const { geometry, a, b, route } = state;
    if (part === 'source' || part === 'target') {
      const anchors = { ...geometry.anchors, [part]: nearestAnchor(part === 'source' ? a : b, point) };
      const nextBase = { ...geometry, anchors, start: anchorPoint(a, anchors.source), end: anchorPoint(b, anchors.target) };
      return route ? { anchors, route: orientRoute(nextBase, route) } : { anchors };
    }
    if (route && !route.tracks.length) return moveSingleBend({ ...geometry, a, b }, delta);
    return route ? { anchors: geometry.anchors, route: moveRoute(route, part, control, delta) } : { anchors: slideLine(a, b, geometry, delta) };
  }
  function start(event, part, control) {
    if (event.button !== 0 || !event.isPrimary || editing.disabled) return;
    event.preventDefault(); event.stopPropagation();
    editing.select(props.id);
    editing.busy?.(true);
    if (part === 'corner') editing.focusCorner(props.id, control);
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { pointerId: event.pointerId, part, control, point: flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }), a, b, geometry, route, latest: null };
  }
  function move(event) {
    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;
    event.preventDefault(); event.stopPropagation();
    const point = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    const delta = { x: point.x - state.point.x, y: point.y - state.point.y };
    if (Math.hypot(delta.x, delta.y) * zoom < 3 && !state.latest) return;
    state.latest = change(state, state.part, state.control, point, delta);
    setDraft(state.latest);
  }
  function finish(event) {
    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;
    event.stopPropagation();
    if (state.latest && event.type === 'pointerup') editing.save(props.id, state.latest);
    drag.current = null; setDraft(null); editing.busy?.(false);
  }
  function keyboard(event, part, control) {
    const steps = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (!steps[event.key] || editing.disabled) return;
    event.preventDefault(); event.stopPropagation();
    const [x, y] = steps[event.key], delta = { x: x * 8, y: y * 8 };
    const point = part === 'source' ? geometry.start : geometry.end;
    editing.save(props.id, change({ geometry, a, b, route }, part, control, { x: point.x + delta.x, y: point.y + delta.y }, delta));
  }
  const events = (part, control) => ({
    onPointerDown: event => start(event, part, control), onPointerMove: move,
    onPointerUp: finish, onPointerCancel: finish, onLostPointerCapture: finish,
    onClick: event => { event.stopPropagation(); if (!editing.disabled) { editing.select(props.id); if (part === 'corner') editing.focusCorner(props.id, control); } },
    onContextMenu: event => {
      event.preventDefault(); event.stopPropagation();
      editing.contextMenu?.(event, props.id, part === 'corner' ? control : undefined);
    },
    onMouseDown: event => event.stopPropagation(),
    onKeyDown: event => keyboard(event, part, control),
  });
  const position = (x, y) => ({ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)${active ? ` scale(${1 / zoom})` : ''}` });
  const labelX = geometry.labelX + (active && route && geometry.labelAxis === 'y' ? 42 / zoom : 0);
  const labelY = geometry.labelY - (active && route && geometry.labelAxis === 'x' ? 30 / zoom : 0);
  return <>
    <g data-straight-count={count} data-straight-index={index} data-orthogonal={route ? 'true' : 'false'} className="nodrag nopan straight-line" {...events('line')}>
      <title>{`Ligação ${index + 1} de ${count}: ${props.label}. Selecione para ajustar o trajeto.`}</title>
      <BaseEdge id={props.id} path={geometry.path} style={{ ...props.style, strokeWidth: active ? 3 : 2, strokeLinejoin: 'miter' }} interactionWidth={28} markerStart={props.markerStart} markerEnd={props.markerEnd} />
    </g>
    <EdgeLabelRenderer>
      <button className={`nodrag nopan line-label ${active ? 'line-label-active' : ''} ${!label && !active ? 'line-label-empty' : ''}`} style={position(labelX, labelY)}
        data-line-id={props.id} data-line-part="line" aria-label={`Mover ligação ${index + 1}: ${props.label}`}
        title={route ? 'Arraste para mover os trechos internos' : 'Arraste para deslocar esta linha'} {...events('line')}>{active && <span aria-hidden="true">↔ </span>}{label}</button>
      {active && <>
        <button className="nodrag nopan line-endpoint" style={position(geometry.start.x, geometry.start.y)} data-line-id={props.id} data-line-part="source"
          aria-label="Mover ponta A" title="Arraste a ponta A pela borda do host" {...events('source')}>A</button>
        <button className="nodrag nopan line-endpoint" style={position(geometry.end.x, geometry.end.y)} data-line-id={props.id} data-line-part="target"
          aria-label="Mover ponta B" title="Arraste a ponta B pela borda do host" {...events('target')}>B</button>
        {route && geometry.segments.filter(s => s.index > 0 && s.index <= route.tracks.length && s.length > 60 / zoom).map(s =>
          <button key={`segment-${s.index}`} className="nodrag nopan line-segment" style={position(s.x, s.y)} data-line-id={props.id} data-line-part="segment" data-control-index={s.index}
            aria-label={`Mover trecho ${s.index + 1}`} title="Arraste este trecho para mudar sua posição" {...events('segment', s.index)}>{s.axis === 'x' ? '↕' : '↔'}</button>)}
        {route && geometry.points.slice(1, -1).map((p, i) => <button key={`corner-${i + 1}`} className={`nodrag nopan line-corner ${editing.focus?.id === props.id && editing.focus.corner === i + 1 ? 'focused' : ''}`}
          style={position(p.x, p.y)} data-line-id={props.id} data-line-part="corner" data-control-index={i + 1}
          aria-label={`Mover dobra ${i + 1}`} title="Arraste o canto. Selecione para adicionar ou remover dobras aqui." {...events('corner', i + 1)}>{i + 1}</button>)}
      </>}
    </EdgeLabelRenderer>
  </>;
}
