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
