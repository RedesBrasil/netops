import { createContext } from 'preact';
import { useContext, useRef, useState } from 'preact/hooks';
import { BaseEdge, EdgeLabelRenderer, useInternalNode, useReactFlow, useViewport } from '@xyflow/react';
import { nodeRect, straightGeometry, nearestAnchor, anchorPoint, slideLine } from './parallel-edges.js';
import { routeGeometry, moveRoute, moveSingleBend, orientRoute } from './orthogonal-route.js';

export const LineEditing = createContext(null);
export function StraightEdge(props) {
  const source = useInternalNode(props.source), target = useInternalNode(props.target);
  const editing = useContext(LineEditing);
  const t = editing.t || (key => key);
  const flow = useReactFlow();
  const { zoom } = useViewport();
  const [draft, setDraft] = useState(null);
  const drag = useRef(null), labelShift = useRef({ x: 0, y: 0 });
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
    drag.current = { pointerId: event.pointerId, part, control, point: flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }), a, b, geometry, route, offset: draft?.label_offset || props.data.label_offset || { x: Math.round(labelShift.current.x), y: Math.round(labelShift.current.y) }, latest: null };
  }
  function move(event) {
    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;
    event.preventDefault(); event.stopPropagation();
    const point = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    const delta = { x: point.x - state.point.x, y: point.y - state.point.y };
    if (Math.hypot(delta.x, delta.y) * zoom < 3 && !state.latest) return;
    state.latest = state.part === 'label' ? { label_offset: { x: Math.round(state.offset.x + delta.x), y: Math.round(state.offset.y + delta.y) } }
      : change(state, state.part, state.control, point, delta);
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
    if (part === 'label') { const o = props.data.label_offset || { x: Math.round(labelShift.current.x), y: Math.round(labelShift.current.y) }; editing.save(props.id, { label_offset: { x: o.x + delta.x, y: o.y + delta.y } }); return; }
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
  // Ao selecionar, a descrição se afasta da linha só na tela (autoShift). Com posição manual o
  // deslocamento salvo já é tudo: o texto fica exatamente onde foi solto, selecionado ou não.
  const autoShift = { x: active && route && geometry.labelAxis === 'y' ? 42 / zoom : 0, y: active && route && geometry.labelAxis === 'x' ? -30 / zoom : 0 };
  const manual = draft?.label_offset || props.data.label_offset;
  labelShift.current = autoShift;
  const offset = manual || { x: 0, y: 0 };
  const labelX = geometry.labelX + offset.x + (manual ? 0 : autoShift.x);
  const labelY = geometry.labelY + offset.y + (manual ? 0 : autoShift.y);
  return <>
    <g data-straight-count={count} data-straight-index={index} data-orthogonal={route ? 'true' : 'false'} className="nodrag nopan straight-line" {...events('line')}>
      <title>{t('map_editor.line_title', { n: index + 1, count, label: props.label })}</title>
      <BaseEdge id={props.id} path={geometry.path} style={{ ...props.style, strokeWidth: active ? 3 : 2, strokeLinejoin: 'miter' }} interactionWidth={28} markerStart={props.markerStart} markerEnd={props.markerEnd} />
    </g>
    <EdgeLabelRenderer>
      <button className={`nodrag nopan line-label ${active ? 'line-label-active' : ''} ${!label && !active ? 'line-label-empty' : ''}`} style={position(labelX, labelY)}
        data-line-id={props.id} data-line-part="line" aria-label={t('map_editor.move_line_aria', { n: index + 1, label: props.label })}
        title={route ? t('map_editor.drag_segments_title') : t('map_editor.drag_line_title')} {...events('line')}>{active && <span aria-hidden="true">↔ </span>}{label}</button>
      {active && <>
        {label && <button className="nodrag nopan line-labelmove" style={position(labelX, labelY - 44 / zoom)} data-line-id={props.id} data-line-part="label"
          aria-label={t('map_editor.move_label_aria')} title={t('map_editor.move_label_title')} {...events('label')}>✥</button>}
        <button className="nodrag nopan line-endpoint" style={position(geometry.start.x, geometry.start.y)} data-line-id={props.id} data-line-part="source"
          aria-label={t('map_editor.move_end_aria', { end: 'A' })} title={t('map_editor.move_end_title', { end: 'A' })} {...events('source')}>A</button>
        <button className="nodrag nopan line-endpoint" style={position(geometry.end.x, geometry.end.y)} data-line-id={props.id} data-line-part="target"
          aria-label={t('map_editor.move_end_aria', { end: 'B' })} title={t('map_editor.move_end_title', { end: 'B' })} {...events('target')}>B</button>
        {route && geometry.segments.filter(s => s.index > 0 && s.index <= route.tracks.length && s.length > 60 / zoom).map(s =>
          <button key={`segment-${s.index}`} className="nodrag nopan line-segment" style={position(s.x, s.y)} data-line-id={props.id} data-line-part="segment" data-control-index={s.index}
            aria-label={t('map_editor.move_segment_aria', { n: s.index + 1 })} title={t('map_editor.move_segment_title')} {...events('segment', s.index)}>{s.axis === 'x' ? '↕' : '↔'}</button>)}
        {route && geometry.points.slice(1, -1).map((p, i) => <button key={`corner-${i + 1}`} className={`nodrag nopan line-corner ${editing.focus?.id === props.id && editing.focus.corner === i + 1 ? 'focused' : ''}`}
          style={position(p.x, p.y)} data-line-id={props.id} data-line-part="corner" data-control-index={i + 1}
          aria-label={t('map_editor.move_corner_aria', { n: i + 1 })} title={t('map_editor.move_corner_title')} {...events('corner', i + 1)}>{i + 1}</button>)}
      </>}
    </EdgeLabelRenderer>
  </>;
}
