// A fronteira do editor adapta IDs numéricos para os identificadores do React Flow.
export function parseHostId(value) {
  if (typeof value === "string" && /^[1-9]\d*$/.test(value)) value = Number(value);
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) throw new Error("ID inteiro de host inválido");
  return value;
}

export function nodeHostId(value) {
  if (typeof value !== "string" || !value.startsWith("host:")) throw new Error("Nó de host inválido");
  return parseHostId(value.slice(5));
}

export function referenceToNode(ref) {
  if (typeof ref === "string") return ref; // somente a visão legada, sem edição
  return ref.kind === "host" ? "host:" + ref.host_id : "object:" + ref.object_id;
}

export function nodeToReference(node) {
  if (node.startsWith("host:")) return { kind: "host", host_id: nodeHostId(node) };
  if (node.startsWith("object:") && node.length > 7) return { kind: "object", object_id: node.slice(7) };
  throw new Error("Ponta de conexão inválida");
}

export function mapToView(map) {
  return { ...map,
    positions: Array.isArray(map.positions) ? Object.fromEntries(map.positions.map(({ host_id, ...point }) => [host_id, point])) : map.positions || {},
    visual_links: (map.visual_links || []).map(link => ({ ...link, source: referenceToNode(link.source), target: referenceToNode(link.target) })),
  };
}

export function snapshotToView(snapshot) {
  return { ...snapshot, hosts: Array.isArray(snapshot.hosts) ? Object.fromEntries(snapshot.hosts.map(host => [host.id, host])) : snapshot.hosts,
    maps: snapshot.maps.map(mapToView) };
}

export function mapToWire(map) {
  const { host_ids, ...value } = map;
  return { ...value, members: value.members.map(parseHostId),
    positions: Object.entries(value.positions).map(([id, point]) => ({ host_id: parseHostId(id), ...point })),
    visual_links: value.visual_links.map(link => ({ ...link, source: nodeToReference(link.source), target: nodeToReference(link.target) })),
  };
}

export const hostLabel = host => `${host.hostname || "Host"}${host.mgmt_ip ? ` (${host.mgmt_ip})` : ""}`;
