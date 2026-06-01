// Topologia (network/topology.yaml): links + segments + regenerar topology.md.
import { html, useState, useEffect, api, useResource, Spinner, Badge, toast, handleError } from "../ui.js";
import { ResourceTable, Field, RefSelect, EnumSelect, Modal, ConfirmDialog, MarkdownView } from "../components.js";

export function TopologyPage() {
  const res = useResource("/topology");
  const [hosts, setHosts] = useState([]);
  const [editLink, setEditLink] = useState(null);
  const [editSeg, setEditSeg] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [md, setMd] = useState(null);
  useEffect(() => { api.get("/hosts").then((d) => setHosts(d.hosts.map((h) => h.id))); }, []);
  if (res.loading) return html`<${Spinner} />`;
  if (res.error) return html`<div class="card">Erro: ${res.error.message}</div>`;
  const { links, segments, rev } = res.data;

  const linkCols = [
    { key: "a", label: "Ponta A", render: (r) => html`<span class="mono">${r.a.host}:${r.a.port}</span>` },
    { key: "b", label: "Ponta B", render: (r) => html`<span class="mono">${r.b.host}:${r.b.port}</span>` },
    { key: "media", label: "Meio", render: (r) => r.media || "—" },
    { key: "speed", label: "Velocidade", render: (r) => r.speed || "—" },
    { key: "desc", label: "Descrição", render: (r) => html`${r.desc || ""}${r.dangling?.length ? html` <span class="dangling">⚠ host fora do inventário: ${r.dangling.join(", ")}</span>` : ""}` },
  ];
  const segCols = [
    { key: "name", label: "Segmento", render: (r) => html`<b>${r.name}</b>` },
    { key: "vlan", label: "VLAN", render: (r) => r.vlan ?? "—" },
    { key: "subnet", label: "Sub-rede", render: (r) => html`<span class="mono">${r.subnet || "—"}</span>` },
  ];

  return html`<div>
    <div class="page-title"><h1>Topologia</h1><span class="spacer"></span>
      <button onClick=${async () => { try { const r = await api.post("/topology/render"); setMd(r.markdown); toast.ok("topology.md regenerado"); } catch (e) { handleError(e); } }}>Regenerar diagrama</button></div>

    <div class="page-title"><h2 style="font-size:16px;margin:0">Enlaces</h2><span class="spacer"></span>
      <button class="primary" onClick=${() => setEditLink({ __new: true })}>+ Enlace</button></div>
    <${ResourceTable} columns=${linkCols} rows=${links.map((l) => ({ ...l, _key: l.index }))}
      actions=${(r) => html`<button class="sm" onClick=${() => setEditLink(r)}>Editar</button>
        <button class="sm danger" onClick=${() => setConfirm({ kind: "link", index: r.index })}>Excluir</button>`}
      empty="Nenhum enlace." />

    <div class="page-title" style="margin-top:20px"><h2 style="font-size:16px;margin:0">Segmentos</h2><span class="spacer"></span>
      <button class="primary" onClick=${() => setEditSeg({ __new: true })}>+ Segmento</button></div>
    <${ResourceTable} columns=${segCols} rows=${segments.map((s) => ({ ...s, _key: s.index }))}
      actions=${(r) => html`<button class="sm" onClick=${() => setEditSeg(r)}>Editar</button>
        <button class="sm danger" onClick=${() => setConfirm({ kind: "segment", index: r.index })}>Excluir</button>`}
      empty="Nenhum segmento." />

    ${md && html`<div class="card" style="margin-top:20px"><${MarkdownView} text=${md} /></div>`}

    ${editLink && html`<${LinkForm} link=${editLink} hosts=${hosts} rev=${rev}
        onClose=${() => setEditLink(null)} onSaved=${() => { setEditLink(null); res.reload(); }} />`}
    ${editSeg && html`<${SegForm} seg=${editSeg} rev=${rev}
        onClose=${() => setEditSeg(null)} onSaved=${() => { setEditSeg(null); res.reload(); }} />`}
    ${confirm && html`<${ConfirmDialog} title="Excluir" danger=true message="Remover este item da topologia?"
        onClose=${() => setConfirm(null)} onConfirm=${async () => {
          try { await api.del(`/topology/${confirm.kind}s/${confirm.index}`, rev); toast.ok("Removido"); res.reload(); }
          catch (e) { handleError(e); } }} />`}
  </div>`;
}

function LinkForm({ link, hosts, rev, onClose, onSaved }) {
  const isNew = !!link.__new;
  const [f, setF] = useState({
    ah: link.a?.host || "", ap: link.a?.port || "", bh: link.b?.host || "", bp: link.b?.port || "",
    media: link.media ?? null, speed: link.speed || "", desc: link.desc || "",
  });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  async function save() {
    const body = { a: { host: f.ah, port: f.ap }, b: { host: f.bh, port: f.bp } };
    if (f.media) body.media = f.media; if (f.speed) body.speed = f.speed; if (f.desc) body.desc = f.desc;
    try {
      if (isNew) await api.post("/topology/links", body, rev);
      else await api.put(`/topology/links/${link.index}`, body, rev);
      toast.ok("Enlace salvo"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? "Novo enlace" : "Editar enlace"} onClose=${onClose}>
    <div class="row">
      <${Field} label="Host A"><${RefSelect} value=${f.ah} options=${hosts} onChange=${(v) => set("ah", v)} /><//>
      <${Field} label="Porta A"><input value=${f.ap} placeholder="ex.: ether2" onInput=${(e) => set("ap", e.target.value)} /><//>
    </div>
    <div class="row">
      <${Field} label="Host B"><${RefSelect} value=${f.bh} options=${hosts} onChange=${(v) => set("bh", v)} /><//>
      <${Field} label="Porta B"><input value=${f.bp} onInput=${(e) => set("bp", e.target.value)} /><//>
    </div>
    <div class="row">
      <${Field} label="Meio"><${EnumSelect} value=${f.media} options=${["fiber", "copper"]} onChange=${(v) => set("media", v)} /><//>
      <${Field} label="Velocidade"><input value=${f.speed} placeholder="ex.: 10G" onInput=${(e) => set("speed", e.target.value)} /><//>
    </div>
    <${Field} label="Descrição"><input value=${f.desc} onInput=${(e) => set("desc", e.target.value)} /><//>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Salvar</button></div>
  <//>`;
}

function SegForm({ seg, rev, onClose, onSaved }) {
  const isNew = !!seg.__new;
  const [f, setF] = useState({ name: seg.name || "", vlan: seg.vlan ?? "", subnet: seg.subnet || "" });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  async function save() {
    const body = { name: f.name };
    if (f.vlan !== "" && f.vlan != null) body.vlan = Number(f.vlan);
    if (f.subnet) body.subnet = f.subnet;
    try {
      if (isNew) await api.post("/topology/segments", body, rev);
      else await api.put(`/topology/segments/${seg.index}`, body, rev);
      toast.ok("Segmento salvo"); onSaved();
    } catch (e) { handleError(e); }
  }
  return html`<${Modal} title=${isNew ? "Novo segmento" : "Editar segmento"} onClose=${onClose}>
    <${Field} label="Nome"><input value=${f.name} onInput=${(e) => set("name", e.target.value)} /><//>
    <div class="row">
      <${Field} label="VLAN"><input type="number" value=${f.vlan} onInput=${(e) => set("vlan", e.target.value)} /><//>
      <${Field} label="Sub-rede (CIDR)"><input value=${f.subnet} placeholder="10.0.0.0/24" onInput=${(e) => set("subnet", e.target.value)} /><//>
    </div>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button><button class="primary" onClick=${save}>Salvar</button></div>
  <//>`;
}
