// Página Claude Code — chat com o agente (claude-agent-sdk) via WebSocket (/api/claude).
// A SESSÃO VIVE ACIMA DO ROTEADOR: toda a lógica (WebSocket + estado) mora no
// ClaudeProvider, montado uma única vez no App (fora do swap de rota). Trocar de página
// NÃO mata a conversa. Há duas visões do mesmo estado vivo: a página cheia (ClaudeCodePage)
// e um chat compacto encaixado à direita (ChatDock), que aparece quando você navega para
// outra rota com uma conversa viva — dá p/ acompanhar o streaming, enviar e aprovar.
// Protocolo JSON nos dois sentidos (ver scripts/engine/ui/services/claude_svc.py).
import { html, useState, useEffect, useRef, useCallback, toast, api } from "../ui.js";
import { createContext } from "preact";
import { useContext } from "preact/hooks";
import { MarkdownView, VaultBanner, Modal } from "../components.js";
import { authToken } from "../api.js";

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

// ------------------------------------------------------------------ contexto
// Uma única sessão viva, compartilhada por todas as visões (página cheia + dock).
const ClaudeCtx = createContext(null);
export function useClaude() { return useContext(ClaudeCtx); }

export function ClaudeProvider({ children }) {
  const value = useClaudeSession();
  return html`<${ClaudeCtx.Provider} value=${value}>${children}<//>`;
}

// Hook que concentra TODO o ciclo de vida da sessão (WS + transcrição + ações). Roda uma
// única vez, no provider. `active` liga/desliga a conexão sem depender da rota atual — por
// isso a conversa (e um turno em andamento) sobrevive à navegação entre páginas.
function useClaudeSession() {
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
  const [active, setActive] = useState(false);        // há sessão ligada? (independe da rota)
  const wsRef = useRef(null);
  const fileRef = useRef(null);
  const sessionIdRef = useRef("");      // sid vigente (p/ retomar na reconexao automatica)
  const resumeIdRef = useRef("");       // alvo de retomada explicita (Sessoes / Nova sessao)
  const manualCloseRef = useRef(false); // fechamento deliberado (encerrar/nova sessao): nao reconectar
  const retryRef = useRef(0);           // tentativa de reconexao (backoff exponencial)
  const reconnTimerRef = useRef(null);  // timer do proximo reconnect
  const hbRef = useRef(null);           // intervalo de heartbeat/watchdog (detecta half-open)

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

  // Liga a sessão (chamado ao abrir a página do Claude). Idempotente.
  const ensureActive = useCallback(() => setActive(true), []);

  // ---- ciclo de vida do WebSocket: conecta enquanto `active` e RECONECTA sozinho ----
  // Só desliga em troca de sessão (gen) ou ao encerrar (active=false). Trocar de ROTA não
  // desmonta o provider, então a conexão — e o turno em andamento — sobrevive à navegação.
  // Uma queda de conexao (ex.: troca de rede muda o IP e quebra a 4-tupla TCP) NAO exige
  // Ctrl+F5: o cliente reconecta com backoff e RETOMA o sid vigente (?resume=<sid>).
  useEffect(() => {
    if (!active) return;
    manualCloseRef.current = false;
    retryRef.current = 0;
    const rid = resumeIdRef.current;
    setItems([]); setWorking(false);
    setSessionId(rid || ""); sessionIdRef.current = rid || "";
    setStatus("conectando");
    // retomada explicita: carrega o historico da sessao na transcricao.
    if (rid) api.get(`/claude/sessions/${rid}/messages`).then((h) => setItems(h.items || [])).catch(() => {});

    const open = (reconnect) => {
      if (reconnTimerRef.current) { clearTimeout(reconnTimerRef.current); reconnTimerRef.current = null; }
      const resume = reconnect ? sessionIdRef.current : rid;
      setStatus("conectando");
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/claude`
        + `?auth=${encodeURIComponent(authToken())}`
        + (resume ? `&resume=${encodeURIComponent(resume)}` : ""));
      wsRef.current = ws;

      ws.onopen = () => setStatus("pronto");           // conectou = conectado
      ws.onerror = () => {};
      ws.onclose = () => {                             // caiu = desconectado, tenta de novo em 3s.
        if (manualCloseRef.current) return;           // fechamento deliberado (encerrar / troca de sessão)
        setWorking(false);
        setStatus("desconectado");
        reconnTimerRef.current = setTimeout(() => open(true), 3000);
      };

      ws.onmessage = (e) => {
        let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
        switch (ev.type) {
          case "system":
            if (ev.subtype === "init") {
              const d = ev.data || {};
              if (d.model) setModel(d.model);
              if (d.permissionMode) setMode(d.permissionMode);
              if (d.session_id) { setSessionId(d.session_id); sessionIdRef.current = d.session_id; }
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
            if (ev.session_id) { setSessionId(ev.session_id); sessionIdRef.current = ev.session_id; }
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
    };
    open(false);

    return () => {
      manualCloseRef.current = true;                                 // impede reconexao ao trocar de sessao/encerrar
      if (reconnTimerRef.current) { clearTimeout(reconnTimerRef.current); reconnTimerRef.current = null; }
      if (hbRef.current) { clearInterval(hbRef.current); hbRef.current = null; }
      try { wsRef.current && wsRef.current.close(); } catch (_) {}
      wsRef.current = null;
    };
  }, [active, gen]);

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

  function newSession() { resumeIdRef.current = ""; setResumeId(""); setActive(true); setGen((g) => g + 1); }
  function resumeSession(id) { resumeIdRef.current = id; setResumeId(id); setShowSessions(false); setActive(true); setGen((g) => g + 1); }

  // Encerra a conversa (fecha o dock): derruba o WS e limpa o estado.
  const endSession = useCallback(() => {
    manualCloseRef.current = true;
    if (reconnTimerRef.current) { clearTimeout(reconnTimerRef.current); reconnTimerRef.current = null; }
    try { wsRef.current && wsRef.current.close(); } catch (_) {}
    wsRef.current = null;
    resumeIdRef.current = ""; sessionIdRef.current = "";
    setActive(false); setWorking(false); setItems([]); setSessionId(""); setStatus("conectando");
  }, []);

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
    const headers = {};
    const a = authToken(); if (a) headers["X-Netops-Session"] = a;
    try {
      const res = await fetch("/api/claude/upload", { method: "POST", headers, body: fd });
      if (!res.ok) { toast.err("Upload falhou (" + res.status + ")"); return; }
      const d = await res.json();
      setInput((v) => (v ? v.replace(/\s*$/, " ") : "") + "@" + d.path + " ");
      toast.ok("Anexado: " + d.name);
    } catch (_) { toast.err("Upload falhou"); }
  }

  const badge = { pronto: "ok", conectando: "", reconectando: "warn", desconectado: "warn", desabilitado: "danger", erro: "danger" }[status] || "";
  const disabled = status !== "pronto";
  // "Conversa viva" = ligada e com algo acontecendo (turno rodando ou já há mensagens).
  const hasSession = active && (working || items.length > 0);

  return {
    status, items, working, mode, model, sessionId, slash, input, setInput,
    showSessions, setShowSessions, badge, disabled, hasSession, fileRef,
    send, submit, stop, newSession, resumeSession, answerPermission, changeMode, uploadFile,
    ensureActive, endSession,
  };
}

// --------------------------------------------------------------------- visões
// Transcrição rolável (compartilhada). Cada instância faz seu próprio auto-scroll ao fim.
function Transcript() {
  const { items, status, answerPermission } = useClaude();
  const scrollRef = useRef(null);
  useEffect(() => { const el = scrollRef.current; if (el) el.scrollTop = el.scrollHeight; }, [items]);
  return html`<div class="cc-transcript" ref=${scrollRef}>
    ${items.length === 0 && status === "pronto" && html`<div class="cc-hint help">
      Pronto. Peça em linguagem natural, use <code>/comandos</code> ou anexe arquivos.
      Em <b>Plano</b> ele só lê; troque para <b>Perguntar antes</b> p/ aplicar mudanças com confirmação.
    </div>`}
    ${status === "desabilitado" && html`<div class="card cc-off">
      Página Claude Code desabilitada no servidor. Suba com <code>--enable-claude</code> (e sem <code>--read-only</code>).
    </div>`}
    ${items.map((it, i) => html`<${Item} key=${i} it=${it} onPermission=${answerPermission} />`)}
  </div>`;
}

// Caixa de mensagem (compartilhada): textarea que cresce com o conteúdo + barra interna
// com Modo, meta, anexar e enviar/parar. Menu de slash aparece logo acima.
function Composer() {
  const { input, setInput, submit, stop, working, disabled, mode, changeMode, model, sessionId, uploadFile, slash, fileRef } = useClaude();
  const taRef = useRef(null);
  // textarea que cresce com o conteúdo: começa em 1 linha e sobe até o teto (CSS), aí rola.
  useEffect(() => {
    const el = taRef.current; if (!el) return;
    el.style.height = "auto"; el.style.height = el.scrollHeight + "px";
  }, [input]);

  function onKeyDown(e) {
    if (e.key === "Escape" && working) { e.preventDefault(); stop(); return; }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  }

  // sugestões de slash: só quando o texto começa com "/" e ainda não tem espaço.
  const slashQuery = /^\/(\S*)$/.exec(input);
  const slashMatches = slashQuery ? slash.filter((c) => c.startsWith(slashQuery[1])).slice(0, 8) : [];

  return html`<div class="cc-composer-wrap">
    ${slashMatches.length > 0 && html`<div class="cc-slash-menu">
      ${slashMatches.map((c) => html`<button key=${c} class="cc-slash" onClick=${() => setInput("/" + c + " ")}>/${c}</button>`)}
    </div>`}
    <div class="cc-composer">
      <textarea ref=${taRef} rows="1"
        placeholder=${disabled ? "Conectando…" : "Mensagem (Enter envia · Shift+Enter quebra linha · / para comandos)"}
        value=${input} disabled=${disabled}
        onInput=${(e) => setInput(e.target.value)} onKeyDown=${onKeyDown}></textarea>
      <div class="cc-composer-bar">
        <div class="cc-composer-left">
          <label class="cc-modepick" title="Modo de permissão do agente">
            <select value=${mode} onChange=${(e) => changeMode(e.target.value)} disabled=${disabled}>
              ${MODES.map((m) => html`<option key=${m.value} value=${m.value} selected=${m.value === mode}>${m.label}</option>`)}
            </select>
          </label>
          ${(model || sessionId) && html`<span class="cc-meta mono">${
            [model, sessionId && "sessão " + sessionId.slice(0, 8)].filter(Boolean).join(" · ")
          }</span>`}
        </div>
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
    </div>
  </div>`;
}

// Página cheia (#claude). Liga a sessão ao montar.
export function ClaudeCodePage() {
  const s = useClaude();
  useEffect(() => { s.ensureActive(); }, []);
  return html`<div class="claude-page">
    <div class="page-title">
      <h1>Claude Code</h1>
      <span class="badge ${s.badge}">${s.status}</span>
      <span class="spacer"></span>
      ${s.working && html`<button class="sm danger" onClick=${() => s.send({ type: "interrupt" })}>Interromper</button>`}
      <button class="sm" onClick=${() => s.setShowSessions(true)} title="Ver e retomar sessões anteriores">Sessões</button>
      <button class="sm" onClick=${s.newSession} title="Encerra esta sessão e abre uma nova">Nova sessão</button>
    </div>
    <${VaultBanner} />
    <${Transcript} />
    <${Composer} />
    ${s.showSessions && html`<${SessionsModal} currentId=${s.sessionId}
      onClose=${() => s.setShowSessions(false)} onResume=${s.resumeSession} />`}
  </div>`;
}

// Chat compacto encaixado à direita — aparece quando você navega p/ outra rota com uma
// conversa viva. Mesma sessão da página cheia; dá p/ acompanhar, enviar e aprovar.
export function ChatDock() {
  const s = useClaude();
  return html`<aside class="chat-dock">
    <div class="chat-dock-head">
      <span class="badge ${s.badge} dot" title=${s.status}></span>
      <b>Claude Code</b>
      ${s.working && html`<span class="chat-dock-live">● ao vivo</span>`}
      <span class="spacer"></span>
      <a class="sm dock-btn" href="#claude" title="Abrir em tela cheia">⤢</a>
      <button class="sm dock-btn" onClick=${s.endSession} title="Encerrar conversa">✕</button>
    </div>
    <${Transcript} />
    <${Composer} />
  </aside>`;
}

// Lista de sessões passadas (retomar / excluir) — com busca por título e conteúdo.
function SessionsModal({ currentId, onClose, onResume }) {
  const [list, setList] = useState(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");

  const load = (query) => {
    const term = (query || "").trim();
    if (!term) {
      setList(null);
      api.get("/claude/sessions").then((d) => setList(d.sessions || [])).catch(() => setList([]));
    } else {
      api.get("/claude/sessions/search?q=" + encodeURIComponent(term))
        .then((d) => setList(d.sessions || [])).catch(() => setList([]));
    }
  };
  useEffect(() => { load(""); }, []);
  // debounce: busca por título + conteúdo da conversa enquanto digita
  useEffect(() => { const h = setTimeout(() => load(q), 250); return () => clearTimeout(h); }, [q]);

  async function del(id, e) {
    e.stopPropagation();
    setBusy(true);
    try { await api.del(`/claude/sessions/${id}`); load(q); }
    catch (_) { toast.err("Falha ao excluir"); }
    finally { setBusy(false); }
  }

  const term = q.trim();
  return html`<${Modal} title="Sessões anteriores" onClose=${onClose} wide=${true}>
    <input class="cc-sess-search" type="search" value=${q} autoFocus
      placeholder="Buscar por título ou conteúdo da conversa…"
      onInput=${(e) => setQ(e.target.value)} />
    ${list == null
      ? html`<div class="help">Carregando…</div>`
      : list.length === 0
      ? html`<div class="help">${term ? "Nenhuma sessão casa com a busca." : "Nenhuma sessão neste projeto ainda."}</div>`
      : html`<div class="cc-sess-list">
        ${list.map((s) => html`<div key=${s.id} class=${"cc-sess" + (s.id === currentId ? " atual" : "")}
            onClick=${() => onResume(s.id)} title="Retomar esta sessão">
          <div class="cc-sess-main">
            <div class="cc-sess-title">${hl(s.title, term)}${s.id === currentId ? html` <span class="badge ok">atual</span>` : ""}</div>
            ${s.preview && html`<div class="cc-sess-prev help">${hl(s.preview, term)}</div>`}
            ${s.snippet && html`<div class="cc-sess-snip help">${hl(s.snippet, term)}</div>`}
            <div class="cc-sess-meta help mono">${fmtTime(s.mtime)} · ${(s.id || "").slice(0, 8)}${s.branch ? " · " + s.branch : ""}</div>
          </div>
          <button class="sm danger" disabled=${busy} title="Excluir sessão" onClick=${(e) => del(s.id, e)}>🗑</button>
        </div>`)}
      </div>`}
  <//>`;
}

// Realça as ocorrências de `term` em `text` (case-insensitive) com <mark>.
function hl(text, term) {
  const s = text == null ? "" : String(text);
  const t = (term || "").trim();
  if (!t) return s;
  const low = s.toLowerCase(), qq = t.toLowerCase();
  const parts = [];
  let i = 0, k = 0;
  while (true) {
    const idx = low.indexOf(qq, i);
    if (idx === -1) { parts.push(s.slice(i)); break; }
    if (idx > i) parts.push(s.slice(i, idx));
    parts.push(html`<mark key=${"m" + k++}>${s.slice(idx, idx + qq.length)}</mark>`);
    i = idx + qq.length;
  }
  return parts;
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
