// Menu Arquivos: o sistema de arquivos DESTE servidor (NetOps), estilo explorador/MobaXterm.
// URL (core/rules/urls-navegacao.md): #files?path=/etc&q=filtro&sort=-mtime&hidden=0&open=/etc/hosts
//   path = pasta aberta (Voltar do navegador = pasta anterior); open = arquivo aberto no editor.
import { html, useState, useEffect, api } from "../ui.js";
import { useMenuRoute } from "../route.js";
import { FileBrowser } from "../file-browser.js";

export function FilesPage() {
  const r = useMenuRoute("files");
  const p = r.params;
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.get("/files/info?src=local").then(setInfo).catch((e) => setErr(e.message || String(e))); }, []);

  const state = { path: p.path || "/", q: p.q || "", sort: p.sort || "", hidden: p.hidden !== "0", open: p.open || "" };
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

  return html`<div class="files-page">
    <div class="page-title"><h1>Arquivos</h1>
      ${info && html`<span class="help">Servidor <b>${info.hostname}</b> · usuário <b>${info.user}</b>${info.user === "root"
        ? " (acesso total — cuidado ao apagar)" : ""}</span>`}
    </div>
    ${err ? html`<div class="err">${err}</div>`
      : html`<${FileBrowser} src="local" home="/" state=${state} setState=${setState} />`}
  </div>`;
}
