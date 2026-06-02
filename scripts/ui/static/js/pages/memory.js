// Memória: arquivo único memory/MEMORY.md (preferências, fatos da rede e lições aprendidas).
import { html, useState, useEffect, api, useResource, Spinner, toast, handleError } from "../ui.js";
import { MarkdownEditor } from "../components.js";

export function MemoryPage() {
  const res = useResource("/memory");
  const [text, setText] = useState(null);
  const [rev, setRev] = useState(null);
  useEffect(() => { if (res.data) { setText(res.data.text); setRev(res.data.rev); } }, [res.data]);

  async function save() {
    try { const r = await api.put("/memory", { text }, rev); setRev(r.rev); toast.ok("Salvo"); }
    catch (e) { handleError(e); }
  }

  return html`<div>
    <div class="page-title"><h1>Memória</h1></div>
    <div class="help" style="margin-bottom:8px">
      Arquivo único <b>MEMORY.md</b> — preferências, fatos da rede e lições aprendidas, em seções.
    </div>
    ${res.loading || text === null
      ? html`<${Spinner} />`
      : html`<div>
          <${MarkdownEditor} value=${text} onChange=${setText} />
          <div style="margin-top:12px"><button class="primary" onClick=${save}>Salvar</button></div>
        </div>`}
  </div>`;
}
