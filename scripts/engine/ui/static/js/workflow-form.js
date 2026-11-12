// Formulário visual de workflow (*.workflow.yaml). Edita o YAML via Document da lib `yaml`,
// que preserva comentários, ordem e campos desconhecidos — só o que você muda é reescrito.
import YAML from "yaml";
import { html, useState, useRef, useEffect, api } from "./ui.js";
import { Field } from "./components.js";

const TYPES = ["inline", "subagent", "checkpoint"];
const lines = (v) => (Array.isArray(v) ? v.join("\n") : v || "");
const toList = (t) => t.split("\n").map((x) => x.trim()).filter(Boolean);

export function WorkflowForm({ value, onChange }) {
  const docRef = useRef(null);
  const [, bump] = useState(0);
  const [agents, setAgents] = useState([]);
  if (docRef.current === null) docRef.current = YAML.parseDocument(value || "");
  useEffect(() => { api.get("/agents").then((d) => setAgents((d.agents || []).map((a) => a.id).filter(Boolean))).catch(() => {}); }, []);
  const doc = docRef.current;
  if (doc.errors.length) return html`<div class="yaml-bad">⚠ YAML inválido: ${doc.errors[0].message.split("\n")[0]}. Corrija em “Texto puro”.</div>`;
  if (!doc.getIn(["workflow"])) return html`<div class="help">Este arquivo não tem a chave <code>workflow:</code> — use “Texto puro”.</div>`;

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
  const remove = (i) => { if (confirm(`Remover o passo ${i + 1}?`)) { steps.items.splice(i, 1); commit(); } };
  const add = () => {
    const n = String(nSteps + 1).padStart(2, "0");
    const node = doc.createNode({ id: n, name: "Novo passo", type: "subagent", agent: "executor", instructions: "O que o agente deve fazer neste passo." });
    if (steps) steps.items.push(node); else doc.setIn(["workflow", "steps"], doc.createNode([{ id: n, name: "Novo passo", type: "subagent", agent: "executor", instructions: "" }]));
    commit();
  };

  const txt = (label, path, opts = {}) => html`<${Field} label=${label} hint=${opts.hint}>
    ${opts.area
      ? html`<textarea rows=${opts.rows || 3} value=${get(path) ?? ""} onInput=${(e) => set(path, e.target.value)}></textarea>`
      : html`<input value=${get(path) ?? ""} list=${opts.list} onInput=${(e) => set(path, e.target.value)} />`}<//>`;
  const list = (label, path, hint) => html`<${Field} label=${label} hint=${hint || "um por linha"}>
    <textarea rows="3" value=${lines(doc.getIn(path) ? doc.getIn(path).toJSON?.() ?? doc.getIn(path) : "")}
      onInput=${(e) => set(path, toList(e.target.value), true)}></textarea><//>`;

  return html`<div class="wf-form">
    <datalist id="wf-agents">${agents.map((a) => html`<option key=${a} value=${a} />`)}</datalist>
    <div class="card">
      <div class="row">${txt("ID", ["workflow", "id"])}${txt("Nome", ["workflow", "name"])}</div>
      ${txt("Descrição", ["workflow", "description"], { area: true })}
      ${list("Gatilhos (frases que disparam o workflow)", ["workflow", "triggers"])}
    </div>
    <h3 style="margin:14px 0 8px">Passos (${nSteps})</h3>
    ${(steps?.items || []).map((_, i) => {
      const P = (k) => ["workflow", "steps", i, k];
      return html`<div class="card" key=${i} style="margin-bottom:10px">
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
          <b>Passo ${i + 1}</b><span class="spacer"></span>
          <button type="button" title="Subir" disabled=${i === 0} onClick=${() => move(i, -1)}>↑</button>
          <button type="button" title="Descer" disabled=${i === nSteps - 1} onClick=${() => move(i, 1)}>↓</button>
          <button type="button" class="danger" onClick=${() => remove(i)}>Remover</button>
        </div>
        <div class="row">${txt("ID", P("id"))}${txt("Nome", P("name"))}</div>
        <div class="row">
          <${Field} label="Tipo"><select value=${get(P("type")) ?? "subagent"} onChange=${(e) => set(P("type"), e.target.value)}>
            ${TYPES.map((t) => html`<option value=${t}>${t}</option>`)}</select><//>
          ${txt("Agente", P("agent"), { list: "wf-agents" })}
        </div>
        ${txt("Instruções", P("instructions"), { area: true, rows: 4 })}
        <div class="row">${list("Arquivos de entrada", P("inputFiles"))}${list("Arquivos de saída", P("outputFiles"))}</div>
        ${txt("Critérios de qualidade", P("qualityCriteria"), { area: true, rows: 2 })}
        ${list("Condições de veto", P("vetoConditions"), "um por linha — se ocorrer, o passo é barrado")}
      </div>`;
    })}
    <button type="button" onClick=${add}>+ Adicionar passo</button>
  </div>`;
}
