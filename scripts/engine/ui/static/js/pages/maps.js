// O editor trabalha sobre os mesmos hosts/enlaces das páginas de inventário.
import { html, useState, useEffect, useRef, api, Spinner, toast, handleError, Modal, ConfirmDialog } from "../ui.js";
import { HostForm } from "./hosts.js";
import { accessEntries, openEntry, AccessChooser } from "./host-term.js";
import { LinkForm, IconPicker } from "../components.js";
import { useMenuRoute, navigate, parseRoute } from "../route.js";
import { snapshotToView, mapToWire, hostLabel } from "../host-identity.js";

const blank = (id, name) => ({ id, name, kind: "custom", members: [], positions: {}, objects: [], edges: {}, visual_links: [] });
const persisted = mapToWire;
export function MapsPage() {
  const [snapshot, setSnapshot] = useState(null), [Editor, setEditor] = useState(null), [error, setError] = useState(null);
  // URL: #maps/<mapa>[?host=<id>|new][&link=<id>]  (core/rules/urls-navegacao.md)
  const r = useMenuRoute("maps");
  const current = r.segments[0] || sessionStorage.getItem("netops_map") || "all";
  const curId = () => { const p = parseRoute(); return (p.menu === "maps" && p.segments[0]) || sessionStorage.getItem("netops_map") || "all"; };   // leitura "ao vivo" (closures antigas)
  const setCurrent = (id, replace = false) => { sessionStorage.setItem("netops_map", id); navigate({ menu: "maps", segments: [id], params: replace ? parseRoute().params : {} }, { replace }); };
  const [status, setStatus] = useState("Salvo no servidor"), [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [deleting, setDeleting] = useState(false), deletion = useRef(false);
  const [hostDialog, setHostDialog] = useState(null), [linkDialog, setLinkDialog] = useState(null), [newMap, setNewMap] = useState(false), [confirm, setConfirm] = useState(null);
  const live = useRef(null), pending = useRef(new Map()), running = useRef(false), blocked = useRef(false), busy = useRef(false), mounted = useRef(true);
  const activity = useRef(0), readSequence = useRef(0);
  const dialogs = useRef(false); dialogs.current = !!(hostDialog || linkDialog || newMap || confirm);
  function setBusy(value) {
    if (value && !busy.current) activity.current++;
    busy.current = value;
  }
  function accept(data) {
    data = snapshotToView(data);
    const previousServer = live.current;
    live.current = data;
    if (mounted.current) {
      setSnapshot(previous => previous === previousServer && previous?.rev === data.rev && previous?.hosts_rev === data.hosts_rev &&
        previous?.topology.rev === data.topology.rev && previous?.read_only === data.read_only ? previous : data);
      const cur = curId(), next = data.map_aliases?.[cur] || (data.maps.some(m => m.id === cur) ? cur : "all");
      if (next !== parseRoute().segments[0] || parseRoute().menu !== "maps") { if (parseRoute().menu === "maps") setCurrent(next, true); }
    }
  }
  async function reload({ background = false } = {}) {
    const version = activity.current, sequence = ++readSequence.current;
    try {
      const data = snapshotToView(await api.get("/maps"));
      if (!mounted.current || sequence !== readSequence.current || version !== activity.current ||
          running.current || pending.current.size || blocked.current || busy.current || deletion.current || background && dialogs.current) return;
      accept(data); setError(null); return data;
    } catch (e) {
      if (mounted.current && sequence === readSequence.current && version === activity.current) setError(e);
      throw e;
    }
  }
  useEffect(() => {
    mounted.current = true;
    const css = document.querySelector('link[data-map-editor]');
    if (!css) { const l = document.createElement("link"); l.rel = "stylesheet"; l.href = "/vendor/map-editor.css"; l.dataset.mapEditor = "true"; document.head.append(l); }
    import("/vendor/map-editor.js").then(m => { if (mounted.current) setEditor(() => m.MapEditor); }).catch(setError);
    reload().catch(() => {});
    const poll = () => { if (mounted.current && !running.current && !pending.current.size && !blocked.current && !busy.current && !dialogs.current && !deletion.current && document.visibilityState === "visible") reload({ background: true }).catch(() => {}); };
    const timer = setInterval(poll, 8000);
    addEventListener("focus", poll); addEventListener("netops:changed", poll);
    const leave = event => { if (running.current || pending.current.size || deletion.current) { event.preventDefault(); event.returnValue = ""; } };
    addEventListener("beforeunload", leave);
    const navigate = event => {
      const link = event.target.closest?.('a[href^="#"]');
      if (link && link.hash.split("?")[0].split("/")[0] !== "#maps" && (running.current || pending.current.size || blocked.current || deletion.current)) {
        event.preventDefault(); event.stopPropagation();
        toast.err("Aguarde o salvamento do mapa ou resolva a falha antes de sair.");
      }
    };
    document.addEventListener("click", navigate, true);
    return () => { mounted.current = false; clearInterval(timer); removeEventListener("focus", poll); removeEventListener("netops:changed", poll); removeEventListener("beforeunload", leave); document.removeEventListener("click", navigate, true); };
  }, []);
  async function drain() {
    if (running.current || blocked.current || !pending.current.size) return;
    running.current = true; setSaving(true); setStatus("Salvando…"); setSaveError(null);
    try {
      while (pending.current.size) {
        const [id, map] = pending.current.entries().next().value;
        const s = live.current;
        const result = snapshotToView(await api.put(`/maps/${encodeURIComponent(id)}`, { map: persisted(map), hosts_rev: s.hosts_rev, topology_rev: s.topology.rev }, s.rev));
        if (pending.current.get(id) === map) pending.current.delete(id);
        live.current = result;
        // Uma confirmação de um gesto anterior não reposiciona o host ainda em arraste.
        if (!pending.current.size && !busy.current && mounted.current) setSnapshot(result);
      }
      if (mounted.current) setStatus("Salvo no servidor");
    } catch (e) {
      blocked.current = true;
      if (mounted.current) {
        setStatus(e.status === 409 ? "Conflito de versão" : "Falha ao salvar");
        const hint = e.recoveryHint || null;
        setSaveError(hint);
        if (hint) toast.err(hint); else handleError(e);
      }
    } finally { running.current = false; if (mounted.current) setSaving(false); }
  }
  function save(map) {
    activity.current++;
    pending.current.set(map.id, map);
    setSnapshot(s => ({ ...s, maps: s.maps.some(m => m.id === map.id) ? s.maps.map(m => m.id === map.id ? map : m) : [...s.maps, { ...map, host_ids: map.host_ids || [] }] }));
    drain();
  }
  async function flush() {
    if (deletion.current) return false;
    await drain();
    if (blocked.current || pending.current.size || running.current) { toast.err("Aguarde o salvamento do mapa ou resolva o conflito antes de continuar."); return false; }
    return true;
  }
  async function switchMap(id) { if (!await flush()) return; setCurrent(id); }
  const hostParam = r.params.host || "", linkParam = r.params.link || "";
  const hostRef = useRef(null), linkRef = useRef(null), opening = useRef(false);
  // "Acessar" no menu do host (mesma lógica da tela de hosts: 1 método abre direto, vários abrem a escolha).
  // Linhas do inventário em cache p/ o window.open ocorrer dentro do clique (senão o pop-up é bloqueado).
  const hostRows = useRef(null), [accessHost, setAccessHost] = useState(null);
  const loadHostRows = () => api.get("/hosts").then(h => { hostRows.current = h.hosts; return h.hosts; });
  useEffect(() => { loadHostRows().catch(() => {}); }, []);
  async function openAccess(hostId) {
    let row = hostRows.current?.find(x => x.id === hostId);
    if (!row) { try { row = (await loadHostRows()).find(x => x.id === hostId); } catch (e) { handleError(e); return; } }
    const entries = row ? accessEntries(row) : [];
    if (!entries.length) { toast.err("Host sem SSH/Telnet/HTTP(S) cadastrado."); return; }
    if (entries.length === 1 && hostRows.current?.includes(row)) { openEntry(row.id, entries[0]); loadHostRows().catch(() => {}); return; }
    setAccessHost(row);
  }
  async function openHost(args, fromUrl = false) {
    if (!await flush()) return;
    if (!fromUrl) { opening.current = true; r.pushParams({ host: args.id != null ? String(args.id) : "new", link: "" }); }
    try {
      const h = await api.get("/hosts");
      const host = args.id ? h.hosts.find(x => x.id === args.id) : { __new: true };
      if (!host) { toast.err("Host não encontrado"); r.setParams({ host: "" }); return; }
      setHostDialog({ host, groups: h.groups, rev: h.rev, initial: { site: args.site || "" },
        ...(args.point ? { placement: { map_id: live.current.maps.find(m => m.id === current)?.id || "all", maps_rev: live.current.rev, ...args.point } } : {}) });
    } catch (e) { handleError(e); }
    finally { opening.current = false; }
  }
  async function openLink(args, fromUrl = false) {
    if (!await flush()) return;
    if (!fromUrl && args.id != null && !args.remove) { opening.current = true; r.pushParams({ link: String(args.id), host: "" }); }
    const s = live.current, link = args.id ? s.topology.links.find(l => l.id === args.id) : { ...args, __new: true };
    if (args.remove) { setConfirm({ kind: "link", id: args.id }); return; }
    opening.current = false;
    if (!link) { toast.err("Enlace não encontrado"); r.setParams({ link: "" }); return; }
    setLinkDialog({ link, hosts: Object.values(s.hosts).map(host => ({ ...host, label: hostLabel(host) })), rev: s.topology.rev });
  }
  async function deleteSelection(selection) {
    if (!await flush()) return;
    deletion.current = true; setDeleting(true); activity.current++;
    let removed = 0;
    try {
      let rev = live.current.hosts_rev;
      for (const id of selection.hostIds) {
        const result = await api.del(`/hosts/${encodeURIComponent(id)}`, rev);
        rev = result.rev; removed++;
      }
      const data = snapshotToView(await api.get("/maps"));
      if (selection.objectIds.length) {
        const source = data.maps.find(m => m.id === selection.mapId), ids = new Set(selection.objectIds);
        if (source) {
          const map = { ...source, objects: source.objects.filter(o => !ids.has(o.id)),
            visual_links: source.visual_links.filter(l => !ids.has(l.source.replace(/^object:/, "")) && !ids.has(l.target.replace(/^object:/, ""))) };
          accept(await api.put(`/maps/${encodeURIComponent(map.id)}`, { map: persisted(map), hosts_rev: data.hosts_rev, topology_rev: data.topology.rev }, data.rev));
        } else accept(data);
      } else accept(data);
      setStatus("Salvo no servidor"); toast.ok("Seleção excluída");
    } catch (error) {
      handleError(error);
      if (removed) toast.err(`${removed} host(s) já removido(s). A exclusão parou; confira a seleção restante antes de tentar novamente.`);
      try { accept(await api.get("/maps")); } catch (refreshError) { handleError(refreshError); }
    } finally { deletion.current = false; if (mounted.current) setDeleting(false); }
  }
  const urlMap = r.segments[0] || "";
  useEffect(() => {   // URL com mapa inexistente/alias (digitada ou colada) → normaliza sem criar histórico
    if (!snapshot) return;
    const next = snapshot.map_aliases?.[urlMap || current] || (snapshot.maps.some(m => m.id === (urlMap || current)) ? (urlMap || current) : "all");
    if (next !== urlMap) setCurrent(next, true);
  }, [urlMap, snapshot]);
  hostRef.current = openHost; linkRef.current = openLink;
  useEffect(() => {   // deep link / Voltar: o parâmetro manda; fecha ou abre o diálogo para casar com a URL
    if (!snapshot || !Editor) return;
    if (!hostParam && hostDialog) setHostDialog(null);
    else if (hostParam && !hostDialog && !opening.current) hostRef.current(hostParam === "new" ? {} : { id: /^\d+$/.test(hostParam) ? Number(hostParam) : hostParam }, true);
  }, [hostParam, !!snapshot, !!Editor]);
  useEffect(() => {
    if (!snapshot || !Editor) return;
    if (!linkParam && linkDialog) setLinkDialog(null);
    else if (linkParam && !linkDialog && !opening.current) linkRef.current({ id: /^\d+$/.test(linkParam) ? Number(linkParam) : linkParam }, true);
  }, [linkParam, !!snapshot, !!Editor]);
  if (error && (!snapshot || !Editor)) return html`<div class="card">Não foi possível abrir os mapas: ${error.message}<button onClick=${reload}>Tentar novamente</button></div>`;
  if (!snapshot || !Editor) return html`<${Spinner} />`;
  const map = snapshot.maps.find(m => m.id === current) || snapshot.maps[0];
  return html`<div class="maps-page">
    <${Editor} IconPicker=${IconPicker} map=${map} maps=${snapshot.maps} hosts=${snapshot.hosts} links=${snapshot.topology.links} readOnly=${snapshot.read_only || deleting}
      saving=${saving || !!pending.current.size || deleting} status=${status} saveError=${saveError} onSave=${save} onHost=${openHost} onLink=${openLink} onSwitch=${switchMap} onAccess=${openAccess}
      onNewMap=${async () => { if (await flush()) setNewMap(true); }} onDeleteMap=${() => setConfirm({ kind: "map", id: map.id })}
      onDeleteSelection=${async selection => { if (await flush()) setConfirm({ kind: "selection", ...selection }); }}
      onError=${message => toast.err(message)} onBusy=${setBusy}
      onRetry=${() => { blocked.current = false; drain(); }} onReload=${() => setConfirm({ kind: "reload" })} />
    ${accessHost && html`<${AccessChooser} host=${accessHost} entries=${accessEntries(accessHost)} onClose=${() => setAccessHost(null)} />`}
    ${hostDialog && html`<${HostForm} ...${hostDialog} onClose=${() => { setHostDialog(null); r.pushParams({ host: "" }); reload().catch(handleError); }}
      onSaved=${() => { setHostDialog(null); r.pushParams({ host: "" }); reload().catch(handleError); }} />`}
    ${linkDialog && html`<${LinkForm} ...${linkDialog} onClose=${() => { setLinkDialog(null); r.pushParams({ link: "" }); }} onSaved=${() => { setLinkDialog(null); r.pushParams({ link: "" }); reload().catch(handleError); }} />`}
    ${newMap && html`<${Modal} title="Novo mapa" onClose=${() => setNewMap(false)}><form onSubmit=${e => {
      e.preventDefault(); const name = new FormData(e.currentTarget).get("name").trim(); if (!name) return;
      const id = "map-" + (globalThis.crypto?.randomUUID?.() || Date.now()); save(blank(id, name)); setCurrent(id); setNewMap(false);
    }}><label>Nome do mapa<input name="name" required maxlength="100" autofocus /></label><div class="modal-actions"><button type="button" onClick=${() => setNewMap(false)}>Cancelar</button><button class="primary">Criar mapa</button></div></form><//>`}
    ${confirm && html`<${ConfirmDialog} title=${confirm.kind === "reload" ? "Recarregar mapas" : "Confirmar exclusão"} danger=true
      message=${confirm.kind === "selection" ? `Excluir ${confirm.hostIds.length} host(s) do inventário e seus enlaces/referências em todos os mapas${confirm.objectIds.length ? `, além de ${confirm.objectIds.length} objeto(s) deste mapa` : ""}? Hosts: ${confirm.hostIds.map(id => hostLabel(snapshot.hosts[id] || {})).join(", ")}.` : confirm.kind === "map" ? `Excluir o mapa "${snapshot.maps.find(m => m.id === confirm.id)?.name || ""}"? Ele deixa de ser exibido, e as referências a ele em outros mapas são removidas. Hosts e enlaces do inventário são preservados, e o registro do mapa permanece no maps.yaml.` : confirm.kind === "link" ? "Excluir o enlace da topologia e de todos os mapas?" : "Descartar os ajustes locais não salvos e carregar a versão atual do servidor?"}
      onClose=${() => setConfirm(null)} onConfirm=${async () => {
        try {
          if (confirm.kind === "selection") { await deleteSelection(confirm); }
          else if (confirm.kind === "reload") { pending.current.clear(); blocked.current = false; await reload(); setStatus("Salvo no servidor"); setSaveError(null); }
          else { if (!await flush()) return; if (confirm.kind === "map") { accept(await api.del(`/maps/${confirm.id}`, live.current.rev)); setCurrent("all"); }
            else { await api.del(`/topology/link/${confirm.id}`, live.current.topology.rev); await reload(); } }
        } catch (e) { handleError(e); }
      }} />`}
  </div>`;
}
