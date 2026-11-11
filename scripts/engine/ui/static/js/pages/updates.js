// Atualizações oficiais: notas como texto, sem HTML remoto e sem tokens no navegador.
import { html, useState, useEffect, useRef, api, Modal, Spinner } from "../ui.js";

const JOB_KEY = "netops_update_job";
const FINISHED = new Set(["completed", "failed", "rolled_back", "recovery_failed"]);
const PHASES = {
  queued: "Atualização confirmada", downloading: "Baixando a release", validating: "Validando o pacote",
  backup: "Criando e verificando backup", preparing: "Preparando dependências", applying: "Aplicando atualização",
  restarting: "Reiniciando o console", rolling_back: "Restaurando a versão anterior",
  completed: "Atualização concluída", failed: "Atualização cancelada", rolled_back: "Versão anterior restaurada",
  recovery_failed: "Recuperação manual necessária",
};

export function UpdatesControl() {
  const [open, setOpen] = useState(!!sessionStorage.getItem(JOB_KEY));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [offline, setOffline] = useState(false);
  const busy = !!data?.job?.id && !FINISHED.has(data.job.phase);
  const pending = sessionStorage.getItem(JOB_KEY);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    api.get("/updates/status").then((d) => { if (mounted.current) setData(d); }).catch(() => {});
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!open || (!busy && !pending)) return;
    let cancelled = false;
    async function poll() {
      try {
        const d = await api.get("/updates/status");
        if (cancelled) return;
        setData((old) => ({ ...old, ...d, can_apply: d.job?.phase === "completed" ? false : old?.can_apply }));
        setOffline(false);
        if (d.job?.id && FINISHED.has(d.job.phase)) sessionStorage.removeItem(JOB_KEY);
      } catch (e) {
        if (!cancelled) setOffline(true);
      }
    }
    poll();
    const timer = setInterval(poll, 2000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [open, busy, pending]);

  async function check() {
    setOpen(true); setLoading(true); setError(""); setConfirm(false);
    try { setData(await api.get("/updates/check")); }
    catch (e) { setError(e.message || "Não foi possível consultar as releases."); }
    finally { setLoading(false); }
  }

  async function apply() {
    setSubmitting(true); setError("");
    try {
      const job = await api.post("/updates/apply", { release_id: data.releases[0].id, confirm: true });
      sessionStorage.setItem(JOB_KEY, job.id);
      setData((old) => ({ ...old, job }));
      setConfirm(false);
    } catch (e) { setError(e.message || "Não foi possível iniciar a atualização."); }
    finally { setSubmitting(false); }
  }

  const latest = data?.releases?.[0];
  return html`<div class="updates-control">
    ${data?.current_version && html`<span class="updates-version">v${data.current_version}</span>`}
    <button class="sm" onClick=${busy || pending ? () => setOpen(true) : check}>${busy ? "Atualização em andamento" : "Verificar atualizações"}</button>
    ${open && html`<${Modal} title="Atualizações do NetOps" wide=${true} onClose=${() => setOpen(false)}>
      <div class="updates-panel" role="region" aria-label="Atualizações">
        ${data && html`<p>Versão instalada: <b>v${data.current_version}</b></p>`}
        ${loading && html`<${Spinner} />`}
        ${error && html`<p class="updates-error" role="alert">${error}</p>`}
        ${offline && html`<p role="status">Console reiniciando ou indisponível. Aguardando reconexão. Pode ser necessário entrar novamente.</p>`}
        ${data?.job?.id && html`<section class="updates-progress" aria-live="polite">
          <b>${PHASES[data.job.phase] || data.job.phase}</b>
          <p>${data.job.detail || "Acompanhe as etapas. Seus dados locais serão preservados."}</p>
          ${data.job.backup && html`<p>Backup privado no servidor: <code>${data.job.backup}</code></p>`}
          ${!!data.job.preserved?.length && html`<details><summary>Personalizações preservadas (${data.job.preserved.length})</summary>
            <ul>${data.job.preserved.map((p) => html`<li key=${p}><code>${p}</code></li>`)}</ul></details>`}
          ${data.job.phase === "completed" && html`<button class="primary" onClick=${() => location.reload()}>Recarregar interface atualizada</button>`}
        </section>`}
        ${data?.no_releases && html`<p>Nenhuma release publicada no GitHub ainda.</p>`}
        ${data?.releases?.length === 0 && !data.no_releases && html`<p>Não há versão estável mais recente que a instalada.</p>`}
        ${!data?.managed && html`<p class="help">O reinício automático exige iniciar o console por <code>scripts/engine/ui/start.sh</code>.</p>`}
        ${data?.requires_setup && html`<p class="help">Inicialize o cofre e faça login no console antes de aplicar atualizações.</p>`}
        ${data?.read_only && html`<p class="help">Modo somente leitura: você pode consultar novidades, mas não atualizar.</p>`}
        ${latest && !latest.installable && html`<p class="help">A última release ainda não contém um pacote oficial verificável.</p>`}
        ${data?.releases?.map((r) => html`<section class="update-release" key=${r.id}>
          <h3>${r.tag} ${r.published_at && html`<small>${new Date(r.published_at).toLocaleDateString("pt-BR")}</small>`}</h3>
          <pre class="update-changelog">${r.changelog}</pre>
          <a href=${r.url} target="_blank" rel="noopener noreferrer">Ver release no GitHub</a>
        </section>`)}
        ${confirm && html`<section class="updates-confirm">
          <h3>Atualizar para ${latest.tag}?</h3>
          <p>Salve os formulários abertos e encerre terminais, agentes e backups em execução. Um backup privado será verificado antes de substituir o código.</p>
          <p>O console ficará indisponível por alguns instantes. Se a nova versão falhar, o atualizador tentará restaurar a anterior. Mantenha também um backup externo.</p>
          <button disabled=${submitting} onClick=${() => setConfirm(false)}>Cancelar</button>
          <button class="primary" disabled=${submitting} onClick=${apply}>${submitting ? "Confirmando…" : "Criar backup e atualizar"}</button>
        </section>`}
        <div class="modal-actions">
          <button onClick=${() => setOpen(false)}>Fechar</button>
          <button disabled=${loading || busy || submitting} onClick=${check}>Verificar novamente</button>
          ${latest && !confirm && html`<button class="primary" disabled=${!data.can_apply || busy || submitting} onClick=${() => setConfirm(true)}>Atualizar para ${latest.tag}</button>`}
        </div>
      </div>
    <//>`}
  </div>`;
}
