// Página Claude Code — chat com o agente (claude-agent-sdk) via WebSocket (/api/claude).
// Protocolo JSON nos dois sentidos (ver scripts/ui/services/claude_svc.py).
// Streaming de texto/pensamento, cards de ferramenta, aprovação na tela, troca de modo,
// menu de slash, anexar arquivos, interromper e nova sessão.
import { html, useState, useEffect, useRef, useCallback, toast } from "../ui.js";
import { MarkdownView, VaultBanner } from "../components.js";
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
  const [gen, setGen] = useState(0);                  // bump => reconecta (nova sessão)
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
    setItems([]); setWorking(false); setSessionId("");
    setStatus("conectando");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/claude`
      + `?token=${encodeURIComponent(sessionToken())}&auth=${encodeURIComponent(authToken())}`);
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
    if (!text || status !== "pronto") return;
    if (!send({ type: "prompt", text })) { toast.err("Sem conexão"); return; }
    setItems((prev) => [...prev, { type: "user", text }]);
    setInput("");
    setWorking(true);
  }

  function answerPermission(id, decision) {
    send({ type: "permission", id, decision });
    setItems((prev) => prev.map((it) =>
      it.type === "permission" && it.id === id ? { ...it, resolved: true, decision } : it));
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
      <button class="sm" onClick=${() => setGen((g) => g + 1)} title="Encerra esta sessão e abre uma nova">Nova sessão</button>
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
        <button class="primary" disabled=${disabled || !input.trim()} onClick=${submit}>Enviar</button>
      </div>
    </div>
  </div>`;
}

function Item({ it, onPermission }) {
  if (it.type === "user")
    return html`<div class="cc-msg user"><div class="cc-role">você</div><div class="cc-usertext">${it.text}</div></div>`;

  if (it.type === "assistant")
    return html`<div class="cc-msg assistant"><div class="cc-role">claude</div><${MarkdownView} text=${it.text} /></div>`;

  if (it.type === "thinking")
    return html`<details class="cc-thinking"><summary>pensando…</summary><pre>${it.text}</pre></details>`;

  if (it.type === "tool") {
    const icon = { running: "⏳", done: "✓", error: "✗" }[it.tstatus] || "•";
    return html`<div class="cc-tool ${it.tstatus}">
      <div class="cc-tool-head">${icon} <b>${it.name}</b></div>
      <pre class="cc-tool-input">${fmt(it.input)}</pre>
      ${it.result != null && html`<pre class="cc-tool-result ${it.isError ? "err" : ""}">${it.result}</pre>`}
    </div>`;
  }

  if (it.type === "permission") {
    const ctx = it.context || {};
    return html`<div class="cc-perm ${it.resolved ? "resolved" : ""}">
      <div class="cc-perm-head">🔑 permissão: <b>${it.tool}</b>${ctx.title ? " — " + ctx.title : ""}</div>
      <pre class="cc-tool-input">${fmt(it.input)}</pre>
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
