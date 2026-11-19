// Menu Arquivos: o sistema de arquivos DESTE servidor (NetOps), estilo explorador/MobaXterm.
// URL (core/rules/urls-navegacao.md): #files?path=/etc&q=filtro&sort=-mtime&hidden=0&open=/etc/hosts&root=1
//   path = pasta aberta (Voltar do navegador = pasta anterior); open = arquivo aberto no editor;
//   root=1 = modo root (sessão curta via administração Local; o token NUNCA vai para a URL — F5 pede de novo).
// Normal: roda como a conta do servidor (`netops`) e abre na pasta do NetOps. "Abrir como root" usa o
// host Local (senha do admin local no cofre, destrancado) — ver services/root_files_svc.py.
import { html, useState, useEffect, api, toast } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { FileBrowser } from "../file-browser.js";

let rootSrc = "";   // token da sessão root (memória da aba)

export function FilesPage() {
  const r = useMenuRoute("files");
  const p = r.params;
  const wantRoot = p.root === "1";
  const [info, setInfo] = useState(null);
  const [rootSt, setRootSt] = useState(null);
  const [src, setSrc] = useState(wantRoot && rootSrc ? rootSrc : "local");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { api.get("/files/info?src=local").then(setInfo).catch((e) => setErr(e.message || String(e))); }, []);
  useEffect(() => {
    if (info && info.user !== "root") api.get("/files/root/status").then(setRootSt).catch(() => setRootSt(null));
  }, [info]);
  useEffect(() => { if (!wantRoot) setSrc("local"); else if (rootSrc) setSrc(rootSrc); }, [wantRoot]);

  const home = (info && info.home) || "/";
  const state = { path: p.path || (src === "local" ? home : "/root"), q: p.q || "", sort: p.sort || "", hidden: p.hidden !== "0", open: p.open || "" };
  function setState(patch, { push = false } = {}) {
    const out = {};
    for (const [k, v] of Object.entries(patch)) {
      if (k === "hidden") out.hidden = v ? "" : "0";
      else if (k === "sort") out.sort = v === "name" ? "" : v;
      else out[k] = v || "";
    }
    if ("path" in patch && !("open" in patch)) out.open = "";
    push ? r.pushParams(out) : r.setParams(out);
  }
  async function openRoot() {
    setBusy(true);
    try {
      const out = await api.post("/files/root/open", {});
      rootSrc = out.src; setSrc(out.src);
      r.pushParams({ root: "1", path: "/root", open: "" });
      toast("ok", "Modo root aberto (expira após 5 min sem uso)");
    } catch (e) { toast("err", e.message || String(e)); }
    finally { setBusy(false); }
  }
  async function closeRoot() {
    const t = rootSrc; rootSrc = ""; setSrc("local");
    r.pushParams({ root: "", path: home, open: "" });
    if (t) api.post("/files/root/close", { src: t }).catch(() => {});
  }

  const inRoot = src !== "local";
  const rootBtn = info && info.user !== "root" && !inRoot && html`<button class="sm danger needs-server-admin"
      disabled=${busy || !(rootSt && rootSt.ready)} onClick=${openRoot}
      title=${rootSt ? (rootSt.ready ? "Gerenciar como root (sessão curta, auditada)" : rootSt.detail || "indisponível") : "verificando…"}>
      🔓 Abrir como root</button>`;
  return html`<div class="files-page">
    <div class="page-title"><h1>Arquivos</h1>
      ${info && !inRoot && html`<span class="help">Servidor <b>${info.hostname}</b> · usuário <b>${info.user}</b>${info.user === "root"
        ? " (acesso total — cuidado ao apagar)" : ""}</span>`}
      ${rootBtn}
      ${rootSt && !rootSt.ready && !inRoot && info && info.user !== "root" && html`<span class="muted">${rootSt.detail}</span>`}
    </div>
    ${inRoot && html`<div class="card err" role="alert" style="display:flex;gap:1rem;align-items:center">
      <b>⚠ MODO ROOT</b> — você está gerenciando este servidor como <b>root</b>. Toda ação é auditada; a sessão
      fecha sozinha após 5 min sem uso. <button class="sm" onClick=${closeRoot}>Sair do modo root</button></div>`}
    ${wantRoot && !inRoot && html`<div class="card warn">A sessão root desta aba terminou (recarregou a página ou expirou). Clique em
      “Abrir como root” para abrir outra, ou <a href="#files">volte aos arquivos normais</a>.</div>`}
    ${err ? html`<div class="err">${err}</div>`
      : info && html`<${FileBrowser} key=${src} src=${src} home=${inRoot ? "/root" : home} state=${state} setState=${setState} />`}
  </div>`;
}
