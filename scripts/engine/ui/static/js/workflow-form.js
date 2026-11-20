// Formulário visual de workflow (*.workflow.yaml). Edita o YAML via Document da lib `yaml`,
// que preserva comentários, ordem e campos desconhecidos — só o que você muda é reescrito.
import YAML from "yaml";
import { html, useState, useRef, useEffect, api, t } from "./ui.js";
import { Field } from "./components.js";

const TYPES = ["inline", "subagent", "checkpoint"];
const lines = (v) => (Array.isArray(v) ? v.join("\n") : v || "");
const toList = (str) => str.split("\n").map((x) => x.trim()).filter(Boolean);

export function WorkflowForm({ value, onChange }) {
  const docRef = useRef(null);
  const [, bump] = useState(0);
  const [agents, setAgents] = useState([]);
  if (docRef.current === null) docRef.current = YAML.parseDocument(value || "");
  useEffect(() => { api.get("/agents").then((d) => setAgents((d.agents || []).map((a) => a.id).filter(Boolean))).catch(() => {}); }, []);
  const doc = docRef.current;
  if (doc.errors.length) return html`<div class="yaml-bad">${t("workflow_form.yaml_invalid", { error: doc.errors[0].message.split("\n")[0] })}</div>`;
  if (!doc.getIn(["workflow"])) return html`<div class="help">${t("workflow_form.no_workflow_key_before")} <code>workflow:</code> ${t("workflow_form.no_workflow_key_after")}</div>`;

  const commit = () => { onChange(doc.toString({ lineWidth: 120, flowCollectionPadding: false })); bump((n) => n + 1); };
  const get = (path) => doc.getIn(path);
  const set = (path, val, asList) => {
    const empty = asList ? val.length === 0 : val === "" || val == null;
    if (empty) { if (doc.hasIn(path)) doc.deleteIn(path); }
    else {
      const old = doc.getIn(path, true);
      const node = doc.createNode(val);
      if (asList && old && old.flow !== undefined) node.flow = old.flow;   // lista inline [a, b] continua inline
      doc.setIn(path, node);
    }
    commit();
  };
  const steps = doc.getIn(["workflow", "steps"], true);
  const nSteps = steps?.items?.length || 0;
  const move = (i, d) => { const it = steps.items; const j = i + d; if (j < 0 || j >= it.length) return; [it[i], it[j]] = [it[j], it[i]]; commit(); };
  const remove = (i) => { if (confirm(t("workflow_form.remove_step_confirm", { n: i + 1 }))) { steps.items.splice(i, 1); commit(); } };
  const add = () => {
    const n = String(nSteps + 1).padStart(2, "0");
    const node = doc.createNode({ id: n, name: t("workflow_form.new_step_name"), type: "subagent", agent: "executor", instructions: t("workflow_form.new_step_instructions") });
    if (steps) steps.items.push(node); else doc.setIn(["workflow", "steps"], doc.createNode([{ id: n, name: t("workflow_form.new_step_name"), type: "subagent", agent: "executor", instructions: "" }]));
    commit();
  };

  const txt = (label, path, opts = {}) => html`<${Field} label=${label} hint=${opts.hint}>
    ${opts.area
      ? html`<textarea rows=${opts.rows || 3} value=${get(path) ?? ""} onInput=${(e) => set(path, e.target.value)}></textarea>`
      : html`<input value=${get(path) ?? ""} list=${opts.list} onInput=${(e) => set(path, e.target.value)} />`}<//>`;
  const list = (label, path, hint) => html`<${Field} label=${label} hint=${hint || t("workflow_form.one_per_line")}>
    <textarea rows="3" value=${lines(doc.getIn(path) ? doc.getIn(path).toJSON?.() ?? doc.getIn(path) : "")}
      onInput=${(e) => set(path, toList(e.target.value), true)}></textarea><//>`;

  return html`<div class="wf-form">
    <datalist id="wf-agents">${agents.map((a) => html`<option key=${a} value=${a} />`)}</datalist>
    <div class="card">
      <div class="row">${txt(t("workflow_form.id"), ["workflow", "id"])}${txt(t("workflow_form.name"), ["workflow", "name"])}</div>
      ${txt(t("workflow_form.description"), ["workflow", "description"], { area: true })}
      ${list(t("workflow_form.triggers"), ["workflow", "triggers"])}
    </div>
    <h3 style="margin:14px 0 8px">${t("workflow_form.steps_title", { n: nSteps })}</h3>
    ${(steps?.items || []).map((_, i) => {
      const P = (k) => ["workflow", "steps", i, k];
      return html`<div class="card" key=${i} style="margin-bottom:10px">
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
          <b>${t("workflow_form.step_n", { n: i + 1 })}</b><span class="spacer"></span>
          <button type="button" title=${t("workflow_form.move_up")} disabled=${i === 0} onClick=${() => move(i, -1)}>↑</button>
          <button type="button" title=${t("workflow_form.move_down")} disabled=${i === nSteps - 1} onClick=${() => move(i, 1)}>↓</button>
          <button type="button" class="danger" onClick=${() => remove(i)}>${t("workflow_form.remove")}</button>
        </div>
        <div class="row">${txt(t("workflow_form.id"), P("id"))}${txt(t("workflow_form.name"), P("name"))}</div>
        <div class="row">
          <${Field} label=${t("workflow_form.type")}><select value=${get(P("type")) ?? "subagent"} onChange=${(e) => set(P("type"), e.target.value)}>
            ${TYPES.map((ty) => html`<option value=${ty}>${ty}</option>`)}</select><//>
          ${txt(t("workflow_form.agent"), P("agent"), { list: "wf-agents" })}
        </div>
        ${txt(t("workflow_form.instructions"), P("instructions"), { area: true, rows: 4 })}
        <div class="row">${list(t("workflow_form.input_files"), P("inputFiles"))}${list(t("workflow_form.output_files"), P("outputFiles"))}</div>
        ${txt(t("workflow_form.quality_criteria"), P("qualityCriteria"), { area: true, rows: 2 })}
        ${list(t("workflow_form.veto_conditions"), P("vetoConditions"), t("workflow_form.veto_hint"))}
      </div>`;
    })}
    <button type="button" onClick=${add}>${t("workflow_form.add_step")}</button>
  </div>`;
}
