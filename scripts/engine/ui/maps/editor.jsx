import { useState, useEffect, useLayoutEffect, useMemo, useRef } from 'preact/hooks';
import { ReactFlow, ReactFlowProvider, Handle, Position, ConnectionMode, Background, Controls, MiniMap, NodeResizer, applyNodeChanges, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './editor.css';
import { separateEdges, nodeRect, straightGeometry } from './parallel-edges.js';
import { addBend, removeBend, orientRoute } from './orthogonal-route.js';
import { LineEditing, StraightEdge } from './straight-edges.jsx';
import { reconcileNodes, alignNodes, defaultHostPosition, orderedNodeIds, moveLayer, duplicateShape, removeMapNodes, contrastingText } from './node-state.js';
import iconCatalog from '../static/icons/network/catalog.json';
const iconFiles = new Map(iconCatalog.map(icon => [icon.id, '/icons/network/thumbnails/' + icon.file]));

const uid = () => globalThis.crypto?.randomUUID?.() || `item-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const hostId = id => 'host:' + id;
const objectId = id => 'object:' + id;
const roleLabel = { core: 'Core', distribution: 'Distribuição', access: 'Acesso', firewall: 'Firewall', wireless: 'Wireless', server: 'Servidor', other: 'Dispositivo' };
export const speeds = { '1G': { color: 'var(--map-1g)' }, '10G': { color: 'var(--map-10g)' }, WAN: { color: 'var(--map-wan)', dash: '7 5' } };
const multiSelectionKeys = ['Control', 'Meta'];
const speedStyle = speed => speeds[speed] || { color: 'var(--muted)', dash: '3 3' };
function NodeHandles() {
  return <>{[['top', Position.Top], ['bottom', Position.Bottom], ['left', Position.Left], ['right', Position.Right]].map(([id, position]) =>
    <Handle key={id} type="source" id={id} position={position} isConnectable={false} aria-hidden="true" />)}</>;
}
const connectable = node => !!(node?.data.hostId || node?.data.mapId || node?.type === 'shape');
function Device({ data, selected }) {
  const [imageFailed, setImageFailed] = useState(false);
  const image = !data.mapId && iconFiles.get(data.icon);
  useEffect(() => setImageFailed(false), [image]);
  return <div className={`device ${selected ? 'chosen' : ''} ${data.mapId ? 'map-ref' : ''}`}>
    {image && !imageFailed
      ? <img className="device-icon-image" src={image} alt="" width={44} height={44} draggable={false} decoding="async" onError={() => setImageFailed(true)} />
      : <span className="device-icon" aria-hidden="true">{data.mapId ? '▧' : data.role === 'server' ? '▥' : '▤'}</span>}
    <div><strong>{data.label}</strong><small>{data.ip}</small><span className="role">{data.mapId ? 'Outro mapa' : roleLabel[data.role] || data.role || 'Dispositivo'}</span></div>
    <NodeHandles />
  </div>;
}
function Note({ data }) { return <div className="map-note">{data.label}</div>; }
function Shape({ data, selected }) {
  const [failed, setFailed] = useState(false), image = iconFiles.get(data.icon);
  useEffect(() => setFailed(false), [image]);
  return <><NodeResizer isVisible={selected && !data.readOnly} minWidth={100} minHeight={60} />
    <div className={`map-shape ${data.form === 'ellipse' ? 'ellipse' : ''} ${selected ? 'chosen' : ''} ${image && !failed ? 'with-icon' : ''}`}
      style={{ background: data.color, borderColor: data.stroke, color: contrastingText(data.color), opacity: data.color || data.stroke ? 1 : undefined }}>
      {image && !failed && <img className="shape-icon-image" src={image} alt="" draggable={false} onError={() => setFailed(true)} />}
      <span>{data.label}</span>
    </div><NodeHandles /></>;
}
const nodeTypes = { device: Device, note: Note, shape: Shape };
const edgeTypes = { editableStraight: StraightEdge };
function makeNodes(map, hosts, readOnly) {
  const layers = new Map(orderedNodeIds(map).map((id, index) => [id, index]));
  const nodes = map.host_ids.map((id, index) => ({ id: hostId(id), type: 'device',
    position: { x: map.positions[id]?.x ?? defaultHostPosition(index).x, y: map.positions[id]?.y ?? defaultHostPosition(index).y }, zIndex: layers.get(hostId(id)),
    data: { hostId: id, label: hosts[id]?.hostname || id, ip: hosts[id]?.mgmt_ip || '', role: hosts[id]?.role, icon: hosts[id]?.icon } }));
  for (const o of map.objects) nodes.push({ id: objectId(o.id), type: o.type === 'reference' ? 'device' : o.type,
    position: o.position, zIndex: layers.get(objectId(o.id)), ...(o.type === 'shape' ? { style: { width: o.width, height: o.height } } : {}),
    data: { ...o, mapId: o.map_id, ip: o.type === 'reference' ? 'Toque para abrir' : '', readOnly } });
  return nodes;
}
function makeEdges(map, links) {
  const ids = new Set(map.host_ids);
  const physical = links.filter(l => ids.has(l.a.host) && ids.has(l.b.host)).map(l => ({
    id: l.id, source: hostId(l.a.host), target: hostId(l.b.host), sourceHandle: 'bottom', targetHandle: 'top',
    label: l.desc || '', data: { speed: l.speed, ...map.edges[l.id] },
    style: { stroke: speedStyle(l.speed).color, strokeDasharray: speedStyle(l.speed).dash },
  }));
  const nodeIds = new Set([...map.host_ids.map(hostId), ...map.objects.map(o => objectId(o.id))]);
  const visual = map.visual_links.filter(l => nodeIds.has(l.source) && nodeIds.has(l.target)).map(l => ({
    id: 'visual:' + l.id, source: l.source, target: l.target, sourceHandle: 'bottom', targetHandle: 'top', label: l.label || '',
    data: { speed: l.speed, anchors: l.anchors, route: l.route, visual: true }, style: { stroke: speedStyle(l.speed).color, strokeDasharray: '7 5' },
  }));
  return separateEdges([...physical, ...visual]);
}
function ColorField({ name, label, value, onChange, onError }) {
  const valid = /^#[0-9a-f]{6}$/i.test(value), input = useRef(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => setCopied(false), [value]);
  async function copy() {
    if (!valid) { input.current?.focus(); return; }
    try {
      if (navigator.clipboard?.writeText && globalThis.isSecureContext) await navigator.clipboard.writeText(value);
      else { input.current.select(); if (!document.execCommand('copy')) throw new Error('Selecione o código HEX e use Ctrl+C para copiar.'); }
      setCopied(true);
    } catch (error) { onError(error.message || 'Selecione o código HEX e use Ctrl+C para copiar.'); }
  }
  const description = name === 'color' ? 'cor de preenchimento' : 'cor do contorno';
  return <div className="map-color-field"><label htmlFor={'shape-' + name}>{label} (HEX)</label><div className="map-color-controls">
    <input type="color" aria-label={'Selecionar ' + description} value={valid ? value : '#000000'} onInput={e => onChange(e.currentTarget.value)} />
    <input ref={input} id={'shape-' + name} name={name} value={value} onInput={e => onChange(e.currentTarget.value)} pattern="#[0-9a-fA-F]{6}" required maxLength={7} spellCheck={false} aria-label={label + ' (HEX)'} />
    <button type="button" aria-label={'Copiar ' + description} onClick={copy}>{copied ? 'Copiado' : 'Copiar'}</button>
  </div></div>;
}
function MapContextMenu({ menu, onClose, children }) {
  const ref = useRef(null);
  const previousFocus = useRef(document.activeElement);
  useLayoutEffect(() => {
    const element = ref.current, box = element.getBoundingClientRect();
    element.style.left = Math.max(8, Math.min(menu.x, innerWidth - box.width - 8)) + 'px';
    element.style.top = Math.max(8, Math.min(menu.y, innerHeight - box.height - 8)) + 'px';
    element.querySelector('[role="menuitem"]:not(:disabled)')?.focus({ preventScroll: true });
  }, [menu]);
  useEffect(() => {
    const outside = event => { if (!ref.current?.contains(event.target)) onClose(); };
    const close = () => onClose();
    document.addEventListener('pointerdown', outside, true);
    addEventListener('resize', close);
    return () => { document.removeEventListener('pointerdown', outside, true); removeEventListener('resize', close); };
  }, []);
  function keyboard(event) {
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation(); onClose();
      previousFocus.current?.focus?.({ preventScroll: true });
      return;
    }
    if (event.target.tagName === 'SELECT') return;
    if (event.key === 'Tab') { onClose(); return; }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation();
    const items = [...ref.current.querySelectorAll('[role="menuitem"]:not(:disabled), select')];
    const index = items.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length;
    items[next]?.focus();
  }
  return <div ref={ref} className="map-context nodrag nopan" role="menu" aria-label={menu.kind === 'pane' ? 'Ações do mapa' : 'Ações do item'}
    style={{ left: menu.x, top: menu.y }} onKeyDown={keyboard} onContextMenu={event => event.preventDefault()}>{children}</div>;
}
export function MapEditor(props) { return <ReactFlowProvider><Editor {...props} /></ReactFlowProvider>; }
function Editor({ map, maps, hosts, links, readOnly, saving, status, saveError, onSave, onHost, onLink, onSwitch, onNewMap, onDeleteMap, onDeleteSelection, onError, onRetry, onReload, onBusy, IconPicker }) {
  const [layout, setLayout] = useState(map), [nodes, setNodes] = useState(() => makeNodes(map, hosts, readOnly));
  const layoutRef = useRef(map), nodesRef = useRef(nodes), gesture = useRef(false), ignoreDoubleClick = useRef(0);
  function visualNodes(value) { nodesRef.current = value; setNodes(value); }
  function nodeGesture(value) { gesture.current = value; onBusy(value); }
  const [selected, setSelected] = useState(null), [focus, setFocus] = useState(null);
  const [dialog, setDialog] = useState(null), [menu, setMenu] = useState(null);
  const [linkMode, setLinkMode] = useState(false), [origin, setOrigin] = useState(null);
  const [shapeIcon, setShapeIcon] = useState('');
  const [shapeColor, setShapeColor] = useState('#dbeafe'), [shapeStroke, setShapeStroke] = useState('#2563eb');
  const [multiSelect, setMultiSelect] = useState(false);
  const speed = '10G';
  const flow = useReactFlow();
  useEffect(() => { onBusy(!!dialog || !!menu || linkMode || multiSelect); }, [dialog, menu, linkMode, multiSelect]);
  const edges = useMemo(() => makeEdges(layout, links), [layout, links]);
  useEffect(() => {
    const changedMap = layoutRef.current.id !== map.id;
    if (!changedMap && gesture.current) return;
    layoutRef.current = map;
    setLayout(map);
    const desired = makeNodes(map, hosts, readOnly);
    visualNodes(changedMap ? desired : reconcileNodes(nodesRef.current, desired));
  }, [map, hosts, readOnly]);
  useEffect(() => { setSelected(null); setFocus(null); setMenu(null); setLinkMode(false); setMultiSelect(false); const t = setTimeout(() => flow.fitView({ padding: .2, maxZoom: 1.05 }), 80); return () => clearTimeout(t); }, [map.id]);
  function update(fn, syncNodes = true) {
    const value = fn(layoutRef.current);
    layoutRef.current = value;
    setLayout(value);
    if (syncNodes) visualNodes(reconcileNodes(nodesRef.current, makeNodes(value, hosts, readOnly)));
    onSave(value);
  }
  function saveLine(id, patch) {
    update(m => id.startsWith('visual:') ? { ...m, visual_links: m.visual_links.map(l => l.id === id.slice(7) ? { ...l, ...patch } : l) }
      : { ...m, edges: { ...m.edges, [id]: { ...m.edges[id], ...patch } } });
  }
  function selectLine(id) {
    setSelected(id);
    if (innerWidth < 760 && (selected !== id || flow.getZoom() < .7)) {
      const e = edges.find(e => e.id === id);
      flow.fitView({ nodes: [flow.getInternalNode(e.source), flow.getInternalNode(e.target)],
        padding: { top: '50px', right: '35px', bottom: '50px', left: '60px' }, maxZoom: 1.1, duration: 0 });
    }
  }
  function bend(action, id = selected) {
    const edge = edges.find(e => e.id === id); if (!edge) return;
    const a = nodeRect(flow.getInternalNode(edge.source)), b = nodeRect(flow.getInternalNode(edge.target));
    const base = { ...straightGeometry({ ...edge, a, b, lane: edge.data.lane, anchors: edge.data.anchors }), a, b };
    const route = edge.data.route ? orientRoute(base, edge.data.route) : null;
    const corner = focus?.id === id ? focus.corner : undefined;
    const patch = action === 'add' ? addBend(base, route, corner) : action === 'remove' ? removeBend(base, route, corner) : { anchors: base.anchors, route: null };
    if (!patch) return onError('Para formar um L com uma dobra e saídas a 90°, desloque um dos hosts na horizontal e na vertical.');
    saveLine(id, patch); setFocus(null);
  }
  function resetLine(id = selected) {
    if (id.startsWith('visual:')) saveLine(id, { anchors: null, route: null });
    else update(m => { const next = { ...m.edges }; delete next[id]; return { ...m, edges: next }; });
  }
  const canvas = useRef(null), paneTouch = useRef(null);
  const point = () => {
    const box = canvas.current.getBoundingClientRect();
    return flow.screenToFlowPosition({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
  };
  function selectedDevices() { return nodesRef.current.filter(node => node.selected && connectable(node)); }
  function clearSelection() {
    visualNodes(applyNodeChanges(nodesRef.current.filter(n => n.selected).map(n => ({ id: n.id, type: 'select', selected: false })), nodesRef.current));
    setSelected(null);
  }
  function context(event, kind = 'pane', id = null, corner) {
    event.preventDefault(); event.stopPropagation();
    const group = selectedDevices();
    const nextKind = (kind === 'selection' || kind === 'node' && group.some(n => n.id === id)) && group.length > 1 ? 'selection' : kind;
    if (kind === 'node' && nextKind !== 'selection') {
      visualNodes(applyNodeChanges(nodesRef.current.map(n => ({ id: n.id, type: 'select', selected: n.id === id })), nodesRef.current));
    }
    setSelected(nextKind === 'selection' ? null : id);
    if (corner !== undefined) setFocus({ id, corner });
    setMenu({ kind: nextKind, id, x: event.clientX, y: event.clientY,
      point: flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }) });
  }
  function menuFromButton(event) {
    const box = event.currentTarget.getBoundingClientRect();
    const kind = selectedDevices().length > 1 ? 'selection' : selected ? nodes.some(n => n.id === selected) ? 'node' : 'edge' : 'pane';
    setMenu({ kind, id: selected, x: box.right, y: box.bottom + 4, point: point() });
  }
  function startConnection(id = null) { setMultiSelect(false); clearSelection(); setLinkMode(true); setOrigin(id); }
  function startMultiSelection() { setLinkMode(false); clearSelection(); setMultiSelect(true); }
  function align(direction) {
    if (readOnly) return;
    try {
      const positions = alignNodes(selectedDevices(), direction);
      if (Object.keys(positions).length < 2) return;
      update(m => ({ ...m, positions: { ...m.positions, ...Object.fromEntries(Object.entries(positions).filter(([id]) => id.startsWith('host:')).map(([id, pos]) => [id.slice(5), { ...m.positions[id.slice(5)], ...pos }])) },
        objects: m.objects.map(o => positions[objectId(o.id)] ? { ...o, position: positions[objectId(o.id)] } : o) }));
      setMultiSelect(false);
    } catch (error) { onError(error.message); }
  }
  function editEdge(edge) { if (edge.data.visual) open('visual', edge); else onLink({ id: edge.id }); }

  function open(kind, object, pos) {
    setMenu(null);
    if (kind === 'shape') { setShapeIcon(object?.data.icon || ''); setShapeColor(object?.data.color || '#dbeafe'); setShapeStroke(object?.data.stroke || '#2563eb'); }
    setDialog({ kind, object, position: pos || point() });
  }
  function edit(n) { setMenu(null); if (n?.data.hostId) onHost({ id: n.data.hostId }); else if (n?.data.mapId) open('reference', n); else if (n) open(n.type, n); }
  function connect(n) {
    ignoreDoubleClick.current = Date.now() + 500;
    if (!origin) { setOrigin(n.id); return; }
    if (origin === n.id) return;
    setLinkMode(false); setOrigin(null);
    if (origin.startsWith('host:') && n.id.startsWith('host:')) onLink({ a: { host: origin.slice(5) }, b: { host: n.id.slice(5) }, speed });
    else update(m => ({ ...m, visual_links: [...m.visual_links, { id: uid(), source: origin, target: n.id, speed, label: '' }] }));
  }
  function nodeClick(e, n) {
    setMenu(null);
    if (multiSelect && connectable(n)) {
      ignoreDoubleClick.current = Date.now() + 500;
      const current = nodesRef.current.find(node => node.id === n.id);
      visualNodes(applyNodeChanges([{ id: n.id, type: 'select', selected: !current.selected }], nodesRef.current));
      setSelected(n.id); return;
    }
    setSelected(n.id);
    if (linkMode && connectable(n)) connect(n);
  }
  function changes(cs) {
    const nextNodes = applyNodeChanges(cs, nodesRef.current);
    visualNodes(nextNodes);
    if (readOnly) return;
    if (cs.some(c => c.dragging === true || c.resizing === true)) nodeGesture(true);
    const edits = cs.filter(c => c.type === 'position' && c.dragging === false && c.position || c.type === 'dimensions' && c.resizing === false && c.dimensions);
    if (edits.length) update(m => {
      const positions = { ...m.positions }, objects = m.objects.map(o => ({ ...o }));
      for (const c of edits) {
        const node = nextNodes.find(n => n.id === c.id);
        if (!node) continue;
        if (c.id.startsWith('host:') && c.position) positions[c.id.slice(5)] = { ...positions[c.id.slice(5)], ...node.position };
        const obj = objects.find(o => objectId(o.id) === c.id);
        if (obj) obj.position = { ...node.position };
        if (obj && c.dimensions) { obj.width = c.dimensions.width; obj.height = c.dimensions.height; }
      }
      return { ...m, positions, objects };
    }, false);
    if (cs.some(c => c.dragging === false || c.resizing === false)) nodeGesture(false);
  }
  function saveObject(e) {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
    const old = layoutRef.current.objects.find(o => objectId(o.id) === dialog.object?.id);
    if (dialog.kind === 'existing') {
      update(m => ({ ...m, members: [...new Set([...m.members, f.host])], host_ids: [...new Set([...m.host_ids, f.host])], positions: { ...m.positions, [f.host]: dialog.position } }));
    } else {
      const o = { ...old, id: old?.id || uid(), type: dialog.kind, position: old ? nodes.find(n => n.id === dialog.object.id)?.position || old.position : dialog.position,
        label: f.label || maps.find(m => m.id === f.map_id)?.name || '', form: f.form || old?.form || 'rect', width: old?.width || 320, height: old?.height || 200,
        ...(f.map_id ? { map_id: f.map_id } : {}), ...(dialog.kind === 'shape' ? { icon: shapeIcon || null, color: f.color, stroke: f.stroke } : {}) };
      update(m => ({ ...m, objects: old ? m.objects.map(item => item.id === old.id ? o : item) : [...m.objects, o] }));
    }
    setDialog(null);
  }
  function duplicate(id) {
    const newId = uid();
    update(m => duplicateShape(m, id, newId));
    visualNodes(applyNodeChanges(nodesRef.current.map(n => ({ id: n.id, type: 'select', selected: n.id === objectId(newId) })), nodesRef.current));
    setSelected(objectId(newId));
    canvas.current?.focus({ preventScroll: true });
  }
  function removeSelection() {
    if (readOnly) return;
    const ids = nodesRef.current.filter(n => n.selected).map(n => n.id);
    if (!ids.length) { if (selected) removeVisual(selected); return; }
    if (ids.some(id => id.startsWith('host:')) && layoutRef.current.kind !== 'custom') {
      setMenu(null); onDeleteSelection({ mapId: layoutRef.current.id, hostIds: ids.filter(id => id.startsWith('host:')).map(id => id.slice(5)),
        objectIds: ids.filter(id => id.startsWith('object:')).map(id => id.slice(7)) }); return;
    }
    update(m => removeMapNodes(m, ids));
    setSelected(null); setMultiSelect(false); setMenu(null);
  }
  function removeVisual(id = selected) {
    const node = nodes.find(n => n.id === id), edge = edges.find(e => e.id === id);
    if (node?.data.hostId) {
      if (layout.kind !== 'custom') return onDeleteSelection({ mapId: layout.id, hostIds: [node.data.hostId], objectIds: [] });
      update(m => removeMapNodes(m, [id]));
    } else if (node) update(m => removeMapNodes(m, [id]));
    else if (edge?.data.visual) update(m => ({ ...m, visual_links: m.visual_links.filter(l => 'visual:' + l.id !== id) }));
    else if (edge) { onLink({ id: edge.id, remove: true }); return; }
    setSelected(null);
  }
  function exportMap() {
    const blob = new Blob([JSON.stringify({ map: layout, hosts: Object.fromEntries(layout.host_ids.map(id => [id, hosts[id]])), links: links.filter(l => layout.host_ids.includes(l.a.host) && layout.host_ids.includes(l.b.host)) }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = `mapa-${layout.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const menuNode = nodes.find(n => n.id === menu?.id), menuEdge = edges.find(e => e.id === menu?.id);
  const action = (label, fn, danger = false) => <button type="button" role="menuitem" className={danger ? 'danger' : ''}
    onClick={() => { setMenu(null); fn(); }}>{label}</button>;
  return <section className="netops-maps" aria-label="Mapa de rede" onKeyDown={event => {
    if (event.key === 'Delete' && !dialog && !readOnly && !event.target.closest('input, textarea, select, [contenteditable="true"]')) {
      event.preventDefault(); event.stopPropagation(); removeSelection(); return;
    }
    if (event.key === 'Escape') { setMenu(null); setLinkMode(false); setMultiSelect(false); clearSelection(); }
    if (event.key === 'F10' && event.shiftKey) {
      event.preventDefault(); event.stopPropagation();
      const target = event.target.closest('[data-line-id], .react-flow__node');
      const id = target?.dataset.lineId || target?.dataset.id || selected;
      const box = (target || canvas.current).getBoundingClientRect();
      if (id) setSelected(id);
      setMenu({ kind: selectedDevices().length > 1 ? 'selection' : id ? nodes.some(n => n.id === id) ? 'node' : 'edge' : 'pane', id,
        x: box.x + Math.min(box.width, 180), y: box.y + Math.min(box.height, 80), point: point() });
    }
  }}>
    <div className="map-toolbar"><div className="map-picker"><label htmlFor="map-select">Mapa</label><select id="map-select" value={layout.id} disabled={saving} onChange={e => onSwitch(e.currentTarget.value)}>{maps.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
      {!readOnly && <button aria-label="Novo mapa" onClick={onNewMap}>+</button>}</div>
      <div className="map-tools"><button onClick={exportMap}>Exportar JSON</button>
        <button className="map-touch-actions" aria-label="Ações do mapa" aria-haspopup="menu" aria-expanded={!!menu} onClick={menuFromButton}>⋯</button>
      </div>
      <span className="map-sr-only" role="status" aria-live="polite">{readOnly ? 'Somente leitura' : status}</span>
    </div>
    <div className="map-workspace"><div ref={canvas} className="map-canvas" data-testid="map-canvas" tabIndex={0}
      onPointerDownCapture={event => {
        paneTouch.current = event.pointerType === 'touch' && event.isPrimary && event.target.classList.contains('react-flow__pane')
          ? { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false } : null;
      }} onPointerMoveCapture={event => {
        const tap = paneTouch.current;
        if (tap?.id === event.pointerId && Math.hypot(event.clientX - tap.x, event.clientY - tap.y) > 6) tap.moved = true;
      }} onPointerUpCapture={event => {
        const tap = paneTouch.current; paneTouch.current = null;
        // O React Flow suprime onPaneClick no toque quando selectionOnDrag está ativo.
        if (tap?.id === event.pointerId && !tap.moved && Math.hypot(event.clientX - tap.x, event.clientY - tap.y) <= 6 && event.target.classList.contains('react-flow__pane')) {
          clearSelection(); setMenu(null); setMultiSelect(false);
        }
      }} onPointerCancelCapture={() => { paneTouch.current = null; }} onPointerDown={event => {
      if (!event.target.closest('input, textarea, select, button, .react-flow__node')) event.currentTarget.focus({ preventScroll: true });
    }}>
      <LineEditing.Provider value={{ selected, select: selectLine, save: saveLine, disabled: readOnly || linkMode, busy: onBusy, contextMenu: (event, id, corner) => context(event, 'edge', id, corner), focus, focusCorner: (id, corner) => setFocus({ id, corner }) }}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onNodesChange={changes} nodesDraggable={!readOnly && !multiSelect && !linkMode} selectNodesOnDrag={!multiSelect && !linkMode} elementsSelectable={!multiSelect && !linkMode} nodesConnectable={false} connectionMode={ConnectionMode.Loose}
          onNodeClick={nodeClick} onNodeDoubleClick={(e, n) => { if (!multiSelect && !linkMode && Date.now() > ignoreDoubleClick.current) { if (n.data.mapId) onSwitch(n.data.mapId); else if (!readOnly) edit(n); } }}
          onEdgeClick={(e, edge) => { setMenu(null); selectLine(edge.id); }} onEdgeContextMenu={(event, edge) => context(event, 'edge', edge.id)} onPaneClick={() => { clearSelection(); setMenu(null); setMultiSelect(false); }}
          onNodeContextMenu={(event, node) => context(event, 'node', node.id)}
          onSelectionContextMenu={event => context(event, 'selection')} onSelectionStart={() => nodeGesture(true)} onSelectionEnd={() => nodeGesture(false)}
          onPaneContextMenu={event => context(event)} onMoveStart={() => setMenu(null)}
          onNodeDragStart={() => nodeGesture(true)} onNodeDragStop={() => nodeGesture(false)}
          fitView fitViewOptions={{ padding: .2, maxZoom: 1.05 }} minZoom={.15} maxZoom={2} nodeDragThreshold={3} deleteKeyCode={null} preventScrolling selectionOnDrag={!linkMode && !multiSelect} panOnDrag={[1]} selectionKeyCode="Shift" multiSelectionKeyCode={multiSelectionKeys} elevateNodesOnSelect={false}>
          <Background gap={24} size={1} color="var(--border)" /><Controls showInteractive={false} /><MiniMap className="map-overview" pannable zoomable />
        </ReactFlow>
      </LineEditing.Provider>
      <div className="canvas-caption"><strong>{layout.name}</strong><span>{layout.host_ids.length} hosts / {edges.length} conexões</span></div>
      {linkMode && <div className="connect-banner">{origin ? 'Toque no host ou forma de destino' : 'Toque no host ou forma de origem e depois no destino'}<button onClick={() => setLinkMode(false)}>Cancelar</button></div>}
      {multiSelect && <div className="connect-banner">Toque nos dispositivos para selecionar ({selectedDevices().length}). Use ⋯ para alinhar.<button onClick={() => { setMultiSelect(false); clearSelection(); }}>Cancelar</button></div>}
      {!nodes.length && <div className="map-empty">{layout.kind === 'custom' ? 'Adicione um host existente ou cadastre um novo dispositivo.' : 'Os dispositivos cadastrados em Hosts aparecem aqui automaticamente.'}</div>}
    </div>
    </div>
    {(status === 'Falha ao salvar' || status === 'Conflito de versão') && <div className="map-save-error" role="alert">
      <span>{saveError || `${status}. Seus ajustes ainda não foram salvos.`}</span>
      <button onClick={status === 'Conflito de versão' ? onReload : onRetry}>{status === 'Conflito de versão' ? 'Recarregar' : 'Tentar novamente'}</button>
    </div>}
    {menu && <MapContextMenu menu={menu} onClose={() => setMenu(null)}>
      {menu.kind === 'selection' ? <>
        {!readOnly && <>{action('Alinhar horizontalmente', () => align('horizontal'))}{action('Alinhar verticalmente', () => align('vertical'))}
          {action(layout.kind === 'custom' ? 'Remover seleção do mapa' : 'Excluir seleção', removeSelection, true)}</>}
        {action('Limpar seleção', () => { clearSelection(); setMultiSelect(false); })}
      </> : menu.kind === 'pane' ? <>
        {!readOnly && <>
          {action('Adicionar host', () => onHost({ point: menu.point, site: layout.site || '' }))}
          {action('Host existente', () => open('existing', null, menu.point))}
          {action('Ligar hosts', () => startConnection())}
          {action('Selecionar vários', startMultiSelection)}
          {action('Adicionar texto', () => open('note', null, menu.point))}
          {action('Adicionar forma', () => open('shape', null, menu.point))}
          {action('Referenciar mapa', () => open('reference', null, menu.point))}
          {layout.kind === 'custom' && <><div role="separator" />{action('Nome do mapa', () => open('rename'))}{action('Excluir mapa', onDeleteMap, true)}</>}
        </>}
        {action('Enquadrar mapa', () => flow.fitView({ padding: .2, maxZoom: 1.05 }))}
      </> : menuNode ? <>
        {menuNode.data.mapId && action('Abrir mapa', () => onSwitch(menuNode.data.mapId))}
        {!readOnly && <>
          {action('Editar', () => edit(menuNode))}
          {connectable(menuNode) && action('Ligar a outro dispositivo', () => startConnection(menuNode.id))}
          {action('Enviar para frente', () => update(m => moveLayer(m, menuNode.id, 'forward')))}
          {action('Enviar para trás', () => update(m => moveLayer(m, menuNode.id, 'backward')))}
          {menuNode.type === 'shape' && action('Duplicar', () => duplicate(menuNode.id))}
          {action(menuNode.data.hostId && layout.kind !== 'custom' ? 'Excluir host' : 'Remover do mapa', () => removeVisual(menuNode.id), true)}
        </>}
        {menuNode.data.hostId && action('Abrir inventário de hosts', () => { location.hash = 'hosts'; })}
      </> : menuEdge ? <>
        {!readOnly && <>
          {action('+ Dobra', () => bend('add', menuEdge.id))}
          {menuEdge.data.route && <>{action('Remover dobra', () => bend('remove', menuEdge.id))}{action('Linha reta', () => bend('straight', menuEdge.id))}</>}
          {action('Posição automática', () => resetLine(menuEdge.id))}
          <div role="separator" />
          {action('Editar', () => editEdge(menuEdge))}
          {action(menuEdge.data.visual ? 'Remover do mapa' : 'Excluir enlace', () => removeVisual(menuEdge.id), true)}
        </>}
        {readOnly && action('Enquadrar mapa', () => flow.fitView({ padding: .2, maxZoom: 1.05 }))}
      </> : action('Enquadrar mapa', () => flow.fitView({ padding: .2, maxZoom: 1.05 }))}
    </MapContextMenu>}
    {dialog && <div className="map-modal-bg"><section className="map-modal" role="dialog" aria-label="Editar mapa">
      <button className="map-close" aria-label="Fechar" onClick={() => setDialog(null)}>×</button>
      {dialog.kind === 'rename' ? <form onSubmit={e => { e.preventDefault(); const name = new FormData(e.currentTarget).get('name'); update(m => ({ ...m, name })); setDialog(null); }}><label>Nome do mapa<input name="name" defaultValue={layout.name} required maxLength={100} /></label><button className="primary">Salvar</button></form> : dialog.kind === 'visual' ? <form onSubmit={e => { e.preventDefault(); const label = new FormData(e.currentTarget).get('label'); update(m => ({ ...m, visual_links: m.visual_links.map(v => 'visual:' + v.id === dialog.object.id ? { ...v, label } : v) })); setDialog(null); }}><label>Descrição da referência<input name="label" defaultValue={dialog.object.label} maxLength={200} /></label><button className="primary">Salvar</button></form> : <form onSubmit={saveObject}>
        <h2>{{ note: 'Texto', shape: 'Forma', reference: 'Referência a mapa', existing: 'Adicionar host existente' }[dialog.kind]}</h2>
        {dialog.kind === 'existing' ? <label>Host<select name="host" required><option value="">Selecione</option>{Object.keys(hosts).filter(id => !layout.host_ids.includes(id)).map(id => <option value={id}>{id}</option>)}</select></label> : <label>{dialog.kind === 'reference' ? 'Rótulo (opcional)' : dialog.kind === 'shape' ? 'Texto (opcional)' : 'Texto'}<textarea name="label" required={dialog.kind === 'note'} maxLength={4000} defaultValue={dialog.object?.data.label || ''} /></label>}
        {dialog.kind === 'reference' && <label>Mapa de destino<select name="map_id" required defaultValue={dialog.object?.data.map_id || ''}><option value="">Selecione</option>{maps.filter(m => m.id !== layout.id).map(m => <option value={m.id}>{m.name}</option>)}</select></label>}
        {dialog.kind === 'shape' && <><IconPicker title="Ícone da forma" defaultLabel="Sem ícone" defaultHint="Sem ícone: manter somente o formato e o texto." value={shapeIcon} onChange={setShapeIcon} /><label>Formato<select name="form" defaultValue={dialog.object?.data.form || 'rect'}><option value="rect">Retângulo</option><option value="ellipse">Elipse</option></select></label>
          <ColorField name="color" label="Preenchimento" value={shapeColor} onChange={setShapeColor} onError={onError} />
          <ColorField name="stroke" label="Contorno" value={shapeStroke} onChange={setShapeStroke} onError={onError} />
          <div className="map-color-preview" aria-label="Prévia das cores" style={{ background: shapeColor, borderColor: shapeStroke, color: contrastingText(shapeColor) }}>Prévia</div></>}
        <div className="modal-actions"><button type="button" onClick={() => setDialog(null)}>Cancelar</button><button className="primary">Salvar</button></div>
      </form>}
    </section></div>}
  </section>;
}
