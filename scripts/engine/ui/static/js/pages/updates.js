// Atualizações oficiais: notas como texto, sem HTML remoto e sem tokens no navegador.
import { html, useState, useEffect, useRef, api, Modal, Spinner, t, fmtDate } from "../ui.js";
import { useMenuRoute } from "../route.js";

const JOB_KEY = "netops_update_job";
const FINISHED = new Set(["completed", "failed", "rolled_back", "recovery_failed", "migration_failed"]);
// Phase -> catalog key (translated at render time).
const PHASES = {
  queued: "updates.phase_queued", downloading: "updates.phase_downloading", validating: "updates.phase_validating",
  backup: "updates.phase_backup", preparing: "updates.phase_preparing", applying: "updates.phase_applying",
  restarting: "updates.phase_restarting", rolling_back: "updates.phase_rolling_back",
  completed: "updates.phase_completed", failed: "updates.phase_failed", rolled_back: "updates.phase_rolled_back",
  recovery_failed: "updates.phase_recovery_failed",
  migrating: "updates.phase_migrating",
  migration_failed: "updates.phase_migration_failed",
};

// part: "version" = só o número (topbar); "button" = botão + painel (Configuração).
export function UpdatesControl({ part = "button" } = {}) {
  // URL: #settings/updates abre o painel (core/rules/urls-navegacao.md)
  const rt = useMenuRoute("settings");
  const open = part === "button" && rt.segments[0] === "updates";
  const setOpen = (v) => (v ? rt.open("updates") : rt.close());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [offline, setOffline] = useState(false);
  const busy = !!data?.job?.id && !FINISHED.has(data.job.phase);
  const pending = sessionStorage.getItem(JOB_KEY);
  const mounted = useRef(true);

  useEffect(() => {   // deep link / job em andamento reabrem o painel
    if (part !== "button") return;
    if (sessionStorage.getItem(JOB_KEY)) { if (!open) setOpen(true); }
    else if (open) check();
  }, []);
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
    catch (e) { setError(e.message || t("updates.check_failed")); }
    finally { setLoading(false); }
  }

  async function apply() {
    setSubmitting(true); setError("");
    try {
      const job = await api.post("/updates/apply", { release_id: data.releases[0].id, confirm: true });
      sessionStorage.setItem(JOB_KEY, job.id);
      setData((old) => ({ ...old, job }));
      setConfirm(false);
    } catch (e) { setError(e.message || t("updates.apply_failed")); }
    finally { setSubmitting(false); }
  }

  const latest = data?.releases?.[0];
  if (part === "version")
    return data?.current_version ? html`<span class="updates-version">v${data.current_version}</span>` : null;
  return html`<div class="updates-control">
    <button class="sm" onClick=${busy || pending ? () => setOpen(true) : check}>${busy ? t("updates.in_progress") : t("updates.check_btn")}</button>
    ${open && html`<${Modal} title=${t("updates.title")} wide=${true} onClose=${() => setOpen(false)}>
      <div class="updates-panel" role="region" aria-label=${t("updates.region_label")}>
        ${data && html`<p>${t("updates.installed_version")} <b>v${data.current_version}</b></p>`}
        ${loading && html`<${Spinner} />`}
        ${error && html`<p class="updates-error" role="alert">${error}</p>`}
        ${offline && html`<p role="status">${t("updates.offline")}</p>`}
        ${data?.job?.id && html`<section class="updates-progress" aria-live="polite">
          <b>${PHASES[data.job.phase] ? t(PHASES[data.job.phase]) : data.job.phase}</b>
          <p>${data.job.detail || t("updates.job_default_detail")}</p>
          ${data.job.backup && html`<p>${t("updates.private_backup")} <code>${data.job.backup}</code></p>`}
          ${!!data.job.preserved?.length && html`<details><summary>${t("updates.preserved", { n: data.job.preserved.length })}</summary>
            <ul>${data.job.preserved.map((p) => html`<li key=${p}><code>${p}</code></li>`)}</ul></details>`}
          ${data.job.phase === "completed" && html`<button class="primary" onClick=${() => location.reload()}>${t("updates.reload_ui")}</button>`}
        </section>`}
        ${data?.no_releases && html`<p>${t("updates.no_releases")}</p>`}
        ${data?.releases?.length === 0 && !data.no_releases && html`<p>${t("updates.up_to_date")}</p>`}
        ${!data?.managed && html`<p class="help">${t("updates.unmanaged")} <code>scripts/engine/ui/start.sh</code>.</p>`}
        ${data?.requires_setup && html`<p class="help">${t("updates.requires_setup")}</p>`}
        ${data?.read_only && html`<p class="help">${t("updates.read_only")}</p>`}
        ${latest && !latest.installable && html`<p class="help">${t("updates.not_installable")}</p>`}
        ${data?.releases?.map((r) => html`<section class="update-release" key=${r.id}>
          <h3>${r.tag} ${r.published_at && html`<small>${fmtDate(r.published_at)}</small>`}</h3>
          <pre class="update-changelog">${r.changelog}</pre>
          <a href=${r.url} target="_blank" rel="noopener noreferrer">${t("updates.view_on_github")}</a>
        </section>`)}
        ${confirm && html`<section class="updates-confirm">
          <h3>${t("updates.confirm_title", { tag: latest.tag })}</h3>
          <p>${t("updates.confirm_body_1")}</p>
          <p>${t("updates.confirm_body_2")}</p>
          <button disabled=${submitting} onClick=${() => setConfirm(false)}>${t("common.cancel")}</button>
          <button class="primary" disabled=${submitting} onClick=${apply}>${submitting ? t("updates.confirming") : t("updates.backup_and_update")}</button>
        </section>`}
        <div class="modal-actions">
          <button onClick=${() => setOpen(false)}>${t("common.close")}</button>
          <button disabled=${loading || busy || submitting} onClick=${check}>${t("updates.check_again")}</button>
          ${latest && !confirm && html`<button class="primary" disabled=${!data.can_apply || busy || submitting} onClick=${() => setConfirm(true)}>${t("updates.update_to", { tag: latest.tag })}</button>`}
        </div>
      </div>
    <//>`}
  </div>`;
}
