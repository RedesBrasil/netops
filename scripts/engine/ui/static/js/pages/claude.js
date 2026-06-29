// Página Claude Code — chat com o agente (claude-agent-sdk) via WebSocket (/api/claude).
// Protocolo JSON nos dois sentidos (ver scripts/engine/ui/services/claude_svc.py).
// Streaming de texto/pensamento, cards de ferramenta, aprovação na tela, troca de modo,
// menu de slash, anexar arquivos, interromper e nova sessão.
import { html, useState, useEffect, useRef, useCallback, toast, api } from "../ui.js";
import { MarkdownView, VaultBanner, Modal } from "../components.js";
import { sessionToken, authToken } from "../api.js";

// Modos de operação expostos (todos, incl. bypass — decisão do projeto).
const MODES = [
  { value: "plan", label: "Plano (só leitura)" },
  { value: "default", label: "Perguntar antes" },
  { value: "acceptEdits", label: "Auto-editar" },
  { value: "dontAsk", label: "Não perguntar (nega o resto)" },
  { value: "bypassPermissions", label: "Bypass — full-auto ⚠" },
];

// Fecha o último item "aberto" (bolha em streaming) antes de empurrar outro tipo.
function closeOpen(arr) {
  if (!arr.length) return arr.slice();
  const next = arr.slice();
  const last = next[next.length - 1];
  if (last && last.open) next[next.length - 1] = { ...last, open: false };
  return next;
}

export function ClaudeCodePage() {
  const [status, setStatus] = useState("conectando"); // conectando|pronto|desconectado|desabilitado|erro
  const [items, setItems] = useState([]);             // transcript ordenado
  const [working, setWorking] = useState(false);      // turno em andamento
  const [mode, setMode] = useState("default");
  const [model, setModel] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [slash, setSlash] = useState([]);             // nomes de slash commands (do init)
  const [input, setInput] = useState("");
  const [gen, setGen] = useState(0);                  // bump => reconecta
  const [resumeId, setResumeId] = useState("");       // se setado, retoma a sessão ao reconectar
  const [showSessions, setShowSessions] = useState(false);
  const wsRef = useRef(null);
  const scrollRef = useRef(null);
  const fileRef = useRef(null);

  const send = useCallback((obj) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(obj)); return true; }
    return false;
  }, []);

  // Append de delta de streaming na bolha aberta do mesmo tipo (texto ou pensamento).
  const appendDelta = useCallback((kind, text) => {
    if (!text) return;
    setItems((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.type === kind && last.open) {
        const next = prev.slice();
        next[next.length - 1] = { ...last, text: last.text + text };
        return next;
      }
      const next = closeOpen(prev);
      next.push({ type: kind, text, open: true });
      return next;
    });
  }, []);

  // ---- ciclo de vida do WebSocket (reabre quando `gen` muda) ----
  useEffect(() => {
    setItems([]); setWorking(false); setSessionId(resumeId || "");
    setStatus("conectando");
    // retomando: carrega o histórico da sessão na transcrição.
    if (resumeId) api.get(`/claude/sessions/${resumeId}/messages`).then((h) => setItems(h.items || [])).catch(() => {});
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/claude`
      + `?token=${encodeURIComponent(sessionToken())}&auth=${encodeURIComponent(authToken())}`
      + (resumeId ? `&resume=${encodeURIComponent(resumeId)}` : ""));
    wsRef.current = ws;

    ws.onopen = () => setStatus("pronto");
    ws.onerror = () => setStatus("erro");
    ws.onclose = (e) => setStatus(e.code === 4403 ? "desabilitado" : "desconectado");

    ws.onmessage = (e) => {
      let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
      switch (ev.type) {
        case "system":
          if (ev.subtype === "init") {
            const d = ev.data || {};
            if (d.model) setModel(d.model);
            if (d.permissionMode) setMode(d.permissionMode);
            if (d.session_id) setSessionId(d.session_id);
            if (Array.isArray(d.slash_commands)) setSlash(d.slash_commands);
          }
          break;
        case "text_delta": appendDelta("assistant", ev.text); break;
        case "thinking_delta": appendDelta("thinking", ev.text); break;
        case "tool_use":
          setItems((prev) => {
            const next = closeOpen(prev);
            next.push({ type: "tool", id: ev.id, name: ev.name, input: ev.input, tstatus: "running" });
            return next;
          });
          break;
        case "tool_result":
          setItems((prev) => prev.map((it) =>
            it.type === "tool" && it.id === ev.tool_use_id
              ? { ...it, result: ev.content, isError: ev.is_error, tstatus: ev.is_error ? "error" : "done" }
              : it));
          break;
        case "assistant_end":
          setItems((prev) => closeOpen(prev));
          break;
        case "permission_request":
          setItems((prev) => {
            const next = closeOpen(prev);
            next.push({ type: "permission", id: ev.id, tool: ev.tool, input: ev.input, context: ev.context || {}, resolved: false });
            return next;
          });
          break;
        case "mode_changed":
          setMode(ev.mode);
          break;
        case "result":
          setWorking(false);
          if (ev.session_id) setSessionId(ev.session_id);
          setItems((prev) => {
            const next = closeOpen(prev);
            next.push({ type: "result", cost: ev.cost_usd, usage: ev.usage, isError: ev.is_error });
            return next;
          });
          break;
        case "error":
          setWorking(false);
          setItems((prev) => [...closeOpen(prev), { type: "error", detail: ev.detail }]);
          break;
      }
    };

    return () => { try { ws.close(); } catch (_) {} wsRef.current = null; };
  }, [gen]);

  // auto-scroll p/ o fim quando o transcript cresce.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items]);

  function submit() {
    const text = input.trim();
    if (!text || status !== "pronto" || working) return;
    if (!send({ type: "prompt", text })) { toast.err("Sem conexão"); return; }
    setItems((prev) => [...prev, { type: "user", text }]);
    setInput("");
    setWorking(true);
  }

  function stop() {
    if (send({ type: "interrupt" })) toast.info("Interrompendo…");
  }

  function newSession() { setResumeId(""); setGen((g) => g + 1); }
  function resumeSession(id) { setResumeId(id); setShowSessions(false); setGen((g) => g + 1); }

  function answerPermission(id, decision, updatedInput) {
    const msg = { type: "permission", id, decision };
    if (updatedInput) msg.updated_input = updatedInput;
    send(msg);
    setItems((prev) => prev.map((it) =>
      it.type === "permission" && it.id === id
        ? { ...it, resolved: true, decision, answers: updatedInput && updatedInput.answers }
        : it));
  }

  function changeMode(m) {
    setMode(m);                       // otimista; confirma em mode_changed
    send({ type: "set_mode", mode: m });
  }

  async function uploadFile(file) {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const headers = { Authorization: "Bearer " + sessionToken() };
    const a = authToken(); if (a) headers["X-Netops-Session"] = a;
    try {
      const res = await fetch("/api/claude/upload", { method: "POST", headers, body: fd });
      if (!res.ok) { toast.err("Upload falhou (" + res.status + ")"); return; }
      const d = await res.json();
      setInput((v) => (v ? v.replace(/\s*$/, " ") : "") + "@" + d.path + " ");
      toast.ok("Anexado: " + d.name);
    } catch (_) { toast.err("Upload falhou"); }
  }

  function onKeyDown(e) {
    if (e.key === "Escape" && working) { e.preventDefault(); stop(); return; }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  }

  // sugestões de slash: só quando o texto começa com "/" e ainda não tem espaço.
  const slashQuery = /^\/(\S*)$/.exec(input);
  const slashMatches = slashQuery
    ? slash.filter((c) => c.startsWith(slashQuery[1])).slice(0, 8)
    : [];

  const badge = { pronto: "ok", conectando: "", desconectado: "warn", desabilitado: "danger", erro: "danger" }[status] || "";
  const disabled = status !== "pronto";

  return html`<div class="claude-page">
    <div class="page-title">
      <h1>Claude Code</h1>
      <span class="badge ${badge}">${status}</span>
      <span class="spacer"></span>
      ${working && html`<button class="sm danger" onClick=${() => send({ type: "interrupt" })}>Interromper</button>`}
      <button class="sm" onClick=${() => setShowSessions(true)} title="Ver e retomar sessões anteriores">Sessões</button>
      <button class="sm" onClick=${newSession} title="Encerra esta sessão e abre uma nova">Nova sessão</button>
    </div>
    <${VaultBanner} />

    <div class="cc-toolbar">
      <label class="cc-modepick">Modo:
        <select value=${mode} onChange=${(e) => changeMode(e.target.value)} disabled=${disabled}>
          ${MODES.map((m) => html`<option key=${m.value} value=${m.value} selected=${m.value === mode}>${m.label}</option>`)}
        </select>
      </label>
      ${model && html`<span class="cc-meta mono">modelo: ${model}</span>`}
      ${sessionId && html`<span class="cc-meta mono">sessão: ${sessionId.slice(0, 8)}</span>`}
      <span class="spacer"></span>
      <span class="cc-meta help">cwd: /home/francisco/netops · executa comandos e edita arquivos</span>
    </div>

    <div class="cc-transcript" ref=${scrollRef}>
      ${items.length === 0 && status === "pronto" && html`<div class="cc-hint help">
        Pronto. Peça em linguagem natural, use <code>/comandos</code> ou anexe arquivos.
        Em <b>Plano</b> ele só lê; troque para <b>Perguntar antes</b> p/ aplicar mudanças com confirmação.
      </div>`}
      ${status === "desabilitado" && html`<div class="card cc-off">
        Página Claude Code desabilitada no servidor. Suba com <code>--enable-claude</code> (e sem <code>--read-only</code>).
      </div>`}
      ${items.map((it, i) => html`<${Item} key=${i} it=${it} onPermission=${answerPermission} />`)}
    </div>

    ${slashMatches.length > 0 && html`<div class="cc-slash-menu">
      ${slashMatches.map((c) => html`<button key=${c} class="cc-slash" onClick=${() => setInput("/" + c + " ")}>/${c}</button>`)}
    </div>`}

    <div class="cc-composer">
      <textarea placeholder=${disabled ? "Conectando…" : "Mensagem (Enter envia · Shift+Enter quebra linha · / para comandos)"}
        value=${input} disabled=${disabled}
        onInput=${(e) => setInput(e.target.value)} onKeyDown=${onKeyDown}></textarea>
      <div class="cc-composer-actions">
        <input type="file" ref=${fileRef} style="display:none"
          onChange=${(e) => { uploadFile(e.target.files[0]); e.target.value = ""; }} />
        <button class="sm" disabled=${disabled} onClick=${() => fileRef.current && fileRef.current.click()}
          title="Anexa um arquivo (vira @caminho na mensagem)">📎 Anexar</button>
        ${working
          ? html`<button class="danger" onClick=${stop} title="Interrompe o agente (Esc)">⏹ Parar</button>`
          : html`<button class="primary" disabled=${disabled || !input.trim()} onClick=${submit}>Enviar</button>`}
      </div>
    </div>

    ${showSessions && html`<${SessionsModal} currentId=${sessionId}
      onClose=${() => setShowSessions(false)} onResume=${resumeSession} />`}
  </div>`;
}

// Lista de sessões passadas (retomar / excluir).
function SessionsModal({ currentId, onClose, onResume }) {
  const [list, setList] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => { setList(null); api.get("/claude/sessions").then((d) => setList(d.sessions || [])).catch(() => setList([])); };
  useEffect(() => { load(); }, []);

  async function del(id, e) {
    e.stopPropagation();
    setBusy(true);
    try { await api.del(`/claude/sessions/${id}`); load(); }
    catch (_) { toast.err("Falha ao excluir"); }
    finally { setBusy(false); }
  }

  return html`<${Modal} title="Sessões anteriores" onClose=${onClose} wide=${true}>
    ${list == null
      ? html`<div class="help">Carregando…</div>`
      : list.length === 0
      ? html`<div class="help">Nenhuma sessão neste projeto ainda.</div>`
      : html`<div class="cc-sess-list">
        ${list.map((s) => html`<div key=${s.id} class=${"cc-sess" + (s.id === currentId ? " atual" : "")}
            onClick=${() => onResume(s.id)} title="Retomar esta sessão">
          <div class="cc-sess-main">
            <div class="cc-sess-title">${s.title}${s.id === currentId ? html` <span class="badge ok">atual</span>` : ""}</div>
            ${s.preview && html`<div class="cc-sess-prev help">${s.preview}</div>`}
            <div class="cc-sess-meta help mono">${fmtTime(s.mtime)} · ${(s.id || "").slice(0, 8)}${s.branch ? " · " + s.branch : ""}</div>
          </div>
          <button class="sm danger" disabled=${busy} title="Excluir sessão" onClick=${(e) => del(s.id, e)}>🗑</button>
        </div>`)}
      </div>`}
  <//>`;
}

function fmtTime(ms) {
  if (!ms) return "";
  try { return new Date(ms).toLocaleString(); } catch (_) { return ""; }
}

function Item({ it, onPermission }) {
  if (it.type === "user")
    return html`<div class="cc-msg user"><div class="cc-role">você</div><div class="cc-usertext">${it.text}</div></div>`;

  if (it.type === "assistant")
    return html`<div class="cc-msg assistant"><div class="cc-role">claude</div><${MarkdownView} text=${it.text} /></div>`;

  if (it.type === "thinking")
    return html`<details class="cc-thinking"><summary>pensando…</summary><pre>${it.text}</pre></details>`;

  if (it.type === "tool") return html`<${ToolCard} it=${it} />`;

  if (it.type === "permission") {
    if (it.tool === "AskUserQuestion") return html`<${AskQuestion} it=${it} onPermission=${onPermission} />`;
    const ctx = it.context || {};
    return html`<div class="cc-perm ${it.resolved ? "resolved" : ""}">
      <div class="cc-perm-head">🔑 permissão: <b>${it.tool}</b>${ctx.title ? " — " + ctx.title : ""}</div>
      <${Collapsible} text=${fmt(it.input)} max=${4} />
      ${ctx.blocked_path && html`<div class="help">caminho: ${ctx.blocked_path}</div>`}
      ${it.resolved
        ? html`<div class="cc-perm-done ${it.decision}">${it.decision === "allow" ? "✓ aprovado" : "✗ negado"}</div>`
        : html`<div class="cc-perm-actions">
            <button class="sm" onClick=${() => onPermission(it.id, "deny")}>Negar</button>
            <button class="sm primary" onClick=${() => onPermission(it.id, "allow")}>Aprovar</button>
          </div>`}
    </div>`;
  }

  if (it.type === "result")
    return html`<div class="cc-result ${it.isError ? "err" : ""}">
      ${it.isError ? "turno terminou com erro" : "turno concluído"}${typeof it.cost === "number" ? ` · ~$${it.cost.toFixed(4)}` : ""}
    </div>`;

  if (it.type === "error")
    return html`<div class="cc-error">erro: ${it.detail}</div>`;

  return null;
}

function fmt(obj) {
  try { return JSON.stringify(obj, null, 2); } catch (_) { return String(obj); }
}

// Ferramenta AskUserQuestion: pergunta de múltipla escolha (estilo Claude Code). Renderiza as
// opções clicáveis + "Outro" e devolve a escolha em updated_input.answers (pergunta -> rótulo).
function AskQuestion({ it, onPermission }) {
  const questions = (it.input && it.input.questions) || [];
  const [sel, setSel] = useState({});      // qi -> rótulo | rótulo[] | "__other__"
  const [other, setOther] = useState({});  // qi -> texto custom

  if (it.resolved) {
    return html`<div class="cc-ask resolved">
      <div class="cc-perm-head">🔑 <b>${it.tool}</b></div>
      ${questions.map((q, qi) => html`<div key=${qi} class="cc-ask-q">
        <div class="cc-ask-title">${q.question}</div>
        <div class="cc-perm-done ${it.decision === "allow" ? "allow" : "deny"}">
          ${it.decision === "allow" ? "✓ " + ((it.answers && it.answers[q.question]) || "respondido") : "✗ pulado"}</div>
      </div>`)}
    </div>`;
  }

  function pick(qi, label, multi) {
    setSel((s) => {
      if (!multi) return { ...s, [qi]: label };
      const cur = Array.isArray(s[qi]) ? s[qi] : [];
      return { ...s, [qi]: cur.includes(label) ? cur.filter((x) => x !== label) : [...cur, label] };
    });
  }
  const isPicked = (qi, label, multi) => {
    const v = sel[qi];
    return multi ? Array.isArray(v) && v.includes(label) : v === label;
  };
  const answered = questions.every((q, qi) => {
    const v = sel[qi];
    if (v === "__other__") return (other[qi] || "").trim().length > 0;
    if (Array.isArray(v)) return v.length > 0;
    return v != null && v !== "";
  });

  function submit() {
    const answers = {};
    questions.forEach((q, qi) => {
      let v = sel[qi];
      if (v === "__other__") v = (other[qi] || "").trim();
      else if (Array.isArray(v)) v = v.join(", ");
      answers[q.question] = v || "";
    });
    onPermission(it.id, "allow", { ...it.input, answers });
  }

  return html`<div class="cc-ask">
    <div class="cc-perm-head">🔑 <b>${it.tool}</b></div>
    ${questions.map((q, qi) => html`<div key=${qi} class="cc-ask-q">
      <div class="cc-ask-title">${q.question}${q.multiSelect ? html` <span class="help">(várias)</span>` : ""}</div>
      <div class="cc-ask-opts">
        ${(q.options || []).map((o) => html`<button key=${o.label}
            class=${"cc-opt" + (isPicked(qi, o.label, q.multiSelect) ? " sel" : "")}
            onClick=${() => pick(qi, o.label, q.multiSelect)}>
          <b>${o.label}</b>${o.description ? html`<span class="cc-opt-desc">${o.description}</span>` : ""}
        </button>`)}
        <button class=${"cc-opt" + (sel[qi] === "__other__" ? " sel" : "")}
          onClick=${() => pick(qi, "__other__", false)}>Outro…</button>
      </div>
      ${sel[qi] === "__other__" && html`<input class="cc-ask-other" placeholder="Sua resposta"
        value=${other[qi] || ""} onInput=${(e) => setOther((s) => ({ ...s, [qi]: e.target.value }))} />`}
    </div>`)}
    <div class="cc-perm-actions">
      <button class="sm" onClick=${() => onPermission(it.id, "deny")}>Pular</button>
      <button class="sm primary" disabled=${!answered} onClick=${submit}>Responder</button>
    </div>
  </div>`;
}

// Texto longo recolhido (prévia de `max` linhas) + botão de expandir — estilo Claude Code.
function Collapsible({ text, max = 2, kind }) {
  const [open, setOpen] = useState(false);
  const t = text == null ? "" : String(text);
  const lines = t.split("\n");
  const big = lines.length > max || t.length > 400;
  if (!big) return html`<pre class="cc-pre ${kind || ""}">${t}</pre>`;
  let preview = lines.slice(0, max).join("\n");
  if (preview.length > 400) preview = preview.slice(0, 400) + " …";
  return html`<div>
    <pre class="cc-pre ${kind || ""}">${open ? t : preview}</pre>
    <button class="cc-expand" onClick=${() => setOpen((o) => !o)}>
      ${open ? "▾ recolher" : `▸ mostrar tudo (${lines.length} linhas)`}
    </button>
  </div>`;
}

// Valor "principal" legível de uma chamada de ferramenta (caminho, comando, padrão…).
function primaryString(input) {
  const i = input || {};
  for (const k of ["command", "file_path", "path", "pattern", "query", "url", "prompt", "notebook_path"]) {
    if (typeof i[k] === "string" && i[k]) {
      if (k === "pattern" && typeof i.path === "string" && i.path) return `${i[k]}  (em ${i.path})`;
      return i[k];
    }
  }
  return null;
}

// Card de ferramenta compacto: cabeçalho com resumo (1 linha) + entrada/saída recolhidas.
function ToolCard({ it }) {
  const icon = { running: "⏳", done: "✓", error: "✗" }[it.tstatus] || "•";
  const prim = primaryString(it.input);
  const hasBigExtra = ["content", "new_string", "old_string"].some(
    (k) => typeof (it.input || {})[k] === "string" && it.input[k].length > 120);
  const headLine = (prim != null ? prim : fmt(it.input)).split("\n")[0] || "";
  const headShort = headLine.length > 120 ? headLine.slice(0, 120) + "…" : headLine;
  const detail = (prim != null && !hasBigExtra) ? prim : fmt(it.input);
  const detailBig = detail.split("\n").length > 2 || detail.length > 120 || hasBigExtra;
  return html`<div class="cc-tool ${it.tstatus}">
    <div class="cc-tool-head"><span>${icon}</span> <b>${it.name}</b>
      ${headShort && html`<span class="cc-tool-desc mono">${headShort}</span>`}</div>
    ${detailBig && html`<${Collapsible} text=${detail} max=${2} />`}
    ${it.result != null && html`<${Collapsible} text=${it.result} max=${2} kind=${it.isError ? "err" : ""} />`}
  </div>`;
}
