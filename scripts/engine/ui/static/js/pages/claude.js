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
import { validSessionId, claudeSessionHash, readClaudeRoute, lastClaudeSession,
  rememberClaudeSession, forgetClaudeSession, replaceClaudeHash, copyClaudeSessionLink } from "../claude-sessions.js";

async function copySessionLink(id) {
  try { await copyClaudeSessionLink(id); toast.ok("Link da sessão copiado"); }
  catch (e) { toast.err(e.message || "Não foi possível copiar o link."); }
}

// Comandos que a ABA resolve sozinha — NÃO vão para o modelo. `/login` é comando da TUI do
// Claude Code: ele não existe no protocolo do SDK, então nunca vem na lista de slash do init
// e, sem isto, digitar "/login" só mandaria a string pro agente. Aqui ele abre o fluxo OAuth
// do servidor (ver services/claude_auth.py).
const LOCAL_SLASH = ["login", "logout", "auth"];
const LOCAL_SLASH_RE = /^\/(login|logout|auth)\b/i;

// Modos de operação expostos (todos, incl. bypass — decisão do projeto).
const MODES = [
  { value: "plan", label: "Plano (só leitura)" },
  { value: "default", label: "Perguntar antes" },
  { value: "acceptEdits", label: "Auto-editar" },
  { value: "dontAsk", label: "Não perguntar (nega o resto)" },
  { value: "bypassPermissions", label: "Bypass — full-auto ⚠" },
];

// Modelos oferecidos no seletor. Sonnet é o padrão econômico (ver claude_svc._options): o
// lançamento força "sonnet" p/ não herdar um alias quebrado do store. Trocar aqui aplica na
// sessão viva (set_model) e passa em ?model= no próximo (re)lançamento.
// Rede de segurança se GET /claude/models falhar (o servidor também tem fallback próprio).
// Formato {id, name} — o mesmo do endpoint. A lista REAL vem dinâmica da API (claude_models.py).
const MODELS_FALLBACK = [
  { id: "claude-sonnet-4-5", name: "Claude Sonnet 4.5" },
  { id: "claude-opus-4-8", name: "Claude Opus 4.8" },
  { id: "claude-haiku-4-5", name: "Claude Haiku 4.5" },
];

// O erro de modelo do CLI vem em inglês ("issue with the selected model … may not exist …").
// Detecta p/ abrir o modal de troca em vez de só cuspir o erro na transcrição.
function isModelError(detail) {
  const d = String(detail || "");
  return /model|modelo/i.test(d) && /(exist|access|selected|not found|unavailable|inv[aá]lid|dispon)/i.test(d);
}

// A CLI mascara rate limit (HTTP 429) como "issue with the selected model (X)". Se X é um
// modelo que a conta TEM (está na lista), o problema real é LIMITE DE USO — trocar de modelo
// não adianta (o 429 bloqueia todos). Detecta p/ mostrar o aviso certo, sem chamada extra.
function looksRateLimited(detail, models) {
  const d = String(detail || "");
  if (/rate.?limit|429|too many|overloaded|usage limit/i.test(d)) return true;
  const m = /selected model \(([^)]+)\)/i.exec(d);
  if (m && Array.isArray(models)) {
    const id = m[1].trim();
    return models.some((x) => x.id === id);
  }
  return false;
}

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
  const [modelSel, setModelSel] = useState("");         // modelo escolhido (vazio até carregar do servidor)
  const [models, setModels] = useState(MODELS_FALLBACK); // modelos disponíveis (lidos de /claude/models)
  const [sessionId, setSessionId] = useState("");
  const [slash, setSlash] = useState([]);             // nomes de slash commands (do init)
  const [input, setInput] = useState("");
  const [gen, setGen] = useState(0);                  // bump => reconecta
  const [showSessions, setShowSessions] = useState(false);
  const [active, setActive] = useState(false);        // há sessão ligada? (independe da rota)
  const [auth, setAuth] = useState(null);             // login do `claude` {loggedIn, email, store…}
  const [showAuth, setShowAuth] = useState(false);    // modal do fluxo de login
  const [showModelPick, setShowModelPick] = useState(false); // modal de troca de modelo (após erro)
  const [modelErr, setModelErr] = useState("");       // mensagem do erro de modelo (mostrada no modal)
  const [showRateLimit, setShowRateLimit] = useState(false); // modal de limite de uso (429 disfarçado)
  const [rateLimitDetail, setRateLimitDetail] = useState(""); // mensagem crua do erro
  const wsRef = useRef(null);
  const fileRef = useRef(null);
  const sessionIdRef = useRef("");      // sid vigente (p/ retomar na reconexao automatica)
  const modelRef = useRef("");          // modelo vigente (vai no ?model=; vazio => default do servidor)
  const modelsRef = useRef(MODELS_FALLBACK); // espelho da lista (p/ detectar 429 disfarçado no onmessage)
  const noReconnectRef = useRef(false); // erro terminal (rate limit/modelo): NÃO reconectar em loop
  const failCountRef = useRef(0);       // quedas seguidas sem conectar (circuit breaker anti-tempestade)
  const resumeIdRef = useRef("");       // alvo de retomada explicita (Sessoes / Nova sessao)
  const manualCloseRef = useRef(false); // fechamento deliberado (encerrar/nova sessao): nao reconectar
  const retryRef = useRef(0);           // tentativa de reconexao (backoff exponencial)
  const reconnTimerRef = useRef(null);  // timer do proximo reconnect
  const hbRef = useRef(null);           // intervalo de heartbeat/watchdog (detecta half-open)
  const activeRef = useRef(false);
  const selectionRef = useRef(null);    // UUID selecionado ou "new" até o init do SDK
  const routeRequestRef = useRef(0);    // invalida resoluções de rota atrasadas
  const connectionRef = useRef(0);      // invalida callbacks do socket anterior imediatamente

  function activateSession(id, force = false) {
    const target = id || "new";
    if (!force && activeRef.current && selectionRef.current === target) return;
    connectionRef.current++;
    selectionRef.current = target;
    resumeIdRef.current = id || "";
    sessionIdRef.current = id || "";
    activeRef.current = true;
    setInput(""); setShowSessions(false);
    setSessionId(id || ""); setItems([]); setWorking(false); setStatus("conectando");
    setActive(true); setGen((g) => g + 1);
  }

  function identifySession(id) {
    if (!validSessionId(id)) return;
    const changed = sessionIdRef.current !== id;
    setSessionId(id); sessionIdRef.current = id;
    selectionRef.current = id; resumeIdRef.current = id;
    const route = readClaudeRoute(location.hash);
    // Um init antigo não pode trocar um link explícito recém-aberto.
    if (route && route.kind === "session" && route.id !== id) return;
    if (changed) rememberClaudeSession(id);
    if (route && route.kind !== "invalid") replaceClaudeHash(claudeSessionHash(id));
  }

  async function openRoute() {
    const request = ++routeRequestRef.current;
    const route = readClaudeRoute(location.hash);
    if (!route) return; // navegar para Hosts mantém a sessão viva no dock
    const current = () => request === routeRequestRef.current;
    try {
      if (route.kind === "invalid") throw new Error("Link de sessão inválido. Escolha uma conversa em Sessões ou abra Nova sessão.");
      if (route.kind === "new") { activateSession(""); return; }
      if (route.kind === "session") {
        if (activeRef.current && sessionIdRef.current === route.id) return;
        await api.get(`/claude/sessions/${encodeURIComponent(route.id)}`);
        if (!current()) return;
        rememberClaudeSession(route.id);
        activateSession(route.id);
        return;
      }
      if (activeRef.current) {
        if (sessionIdRef.current) replaceClaudeHash(claudeSessionHash(sessionIdRef.current));
        else replaceClaudeHash("#claude/new");
        return;
      }
      let id = lastClaudeSession();
      if (id) {
        try { await api.get(`/claude/sessions/${encodeURIComponent(id)}`); }
        catch (e) {
          if (e.status !== 404) throw e;
          forgetClaudeSession(id); id = "";
        }
      }
      if (!current()) return;
      if (!id) {
        const data = await api.get("/claude/sessions");
        if (!current()) return;
        id = (data.sessions || []).find((s) => validSessionId(s.id))?.id || "";
      }
      if (id) rememberClaudeSession(id);
      activateSession(id);
      replaceClaudeHash(id ? claudeSessionHash(id) : "#claude/new");
    } catch (e) {
      if (!current()) return;
      endSession();
      setStatus("erro");
      setItems([{ type: "error", detail: e.status === 404
        ? "Sessão não encontrada neste projeto. Escolha outra em Sessões ou abra Nova sessão."
        : e.message || "Não foi possível abrir a sessão. Tente novamente." }]);
    }
  }

  // O provider acompanha também voltar/avançar: a página cheia não remonta entre UUIDs.
  useEffect(() => {
    const onRoute = () => { openRoute(); };
    addEventListener("hashchange", onRoute);
    onRoute();
    return () => { routeRequestRef.current++; removeEventListener("hashchange", onRoute); };
  }, []);

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

  // Estado do login do agente. Consultado ao ligar a sessão e depois de todo erro — quando a
  // credencial expira o SDK só devolve um erro opaco, então perguntar ao servidor é o jeito
  // honesto de saber se o que falta é login.
  const refreshAuth = useCallback(async () => {
    try { const d = await api.get("/claude/auth/status"); setAuth(d); return d; }
    catch (_) { setAuth(null); return null; }
  }, []);

  // Releitura MANUAL dos modelos (botão "Verificar modelos" no perfil). Força ir à API (o
  // automático é no máx. 1x/semana). Devolve {models, default} p/ o chamador avisar/atualizar.
  const refreshModels = useCallback(async () => {
    const d = await api.post("/claude/models/refresh");
    if (Array.isArray(d.models) && d.models.length) { setModels(d.models); modelsRef.current = d.models; }
    if (d.default && !modelRef.current) { setModelSel(d.default); modelRef.current = d.default; }
    return d;
  }, []);
  useEffect(() => { if (active) refreshAuth(); }, [active, gen]);

  // Modelos disponíveis: lidos dinamicamente do servidor (que lê da API — sem hard-code).
  // Popula o seletor e define o padrão econômico; o init depois ajusta p/ o modelo real vigente.
  useEffect(() => {
    api.get("/claude/models").then((d) => {
      if (Array.isArray(d.models) && d.models.length) { setModels(d.models); modelsRef.current = d.models; }
      if (d.default && !modelRef.current) { setModelSel(d.default); modelRef.current = d.default; }
    }).catch(() => {});
  }, []);

  // ---- ciclo de vida do WebSocket: conecta enquanto `active` e RECONECTA sozinho ----
  // Só desliga em troca de sessão (gen) ou ao encerrar (active=false). Trocar de ROTA não
  // desmonta o provider, então a conexão — e o turno em andamento — sobrevive à navegação.
  // Uma queda de conexao (ex.: troca de rede muda o IP e quebra a 4-tupla TCP) NAO exige
  // Ctrl+F5: o cliente reconecta com backoff e RETOMA o sid vigente (?resume=<sid>).
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    const generation = connectionRef.current;
    const current = () => !disposed && generation === connectionRef.current;
    manualCloseRef.current = false;
    retryRef.current = 0;
    noReconnectRef.current = false;
    failCountRef.current = 0;
    const rid = resumeIdRef.current;
    setItems([]); setWorking(false);
    setSessionId(rid || ""); sessionIdRef.current = rid || "";
    setStatus("conectando");
    // retomada explicita: carrega o historico da sessao na transcricao.
    const open = async (reconnect) => {
      if (!current()) return;
      if (reconnTimerRef.current) { clearTimeout(reconnTimerRef.current); reconnTimerRef.current = null; }
      const resume = reconnect ? sessionIdRef.current : rid;
      setStatus("conectando");
      // Carrega antes de abrir o socket: uma leitura atrasada não apaga streaming/permissões.
      if (resume) {
        try {
          const h = await api.get(`/claude/sessions/${encodeURIComponent(resume)}/messages`);
          if (!current()) return;
          setItems(h.items || []);
        } catch (_) {}
      }
      if (!current()) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/claude`
        + `?auth=${encodeURIComponent(authToken())}`
        + (modelRef.current ? `&model=${encodeURIComponent(modelRef.current)}` : "")
        + (resume ? `&resume=${encodeURIComponent(resume)}` : ""));
      wsRef.current = ws;
      const currentSocket = () => current() && wsRef.current === ws;

      ws.onopen = () => {
        if (!currentSocket()) return;
        failCountRef.current = 0; setStatus("pronto");                 // conectou = conectado; zera o breaker
      };
      ws.onerror = () => {};
      ws.onclose = (event) => {                        // caiu = desconectado
        if (!currentSocket()) return;
        if (manualCloseRef.current) return;           // fechamento deliberado (encerrar / troca de sessão)
        setWorking(false);
        if (event.code === 4409 || event.code === 4404) {
          noReconnectRef.current = true;
          setStatus("desconectado");
          setItems((prev) => [...closeOpen(prev), { type: "error", detail: event.code === 4409
            ? "Esta sessão foi aberta em outra aba. Recarregue para retomá-la aqui."
            : "Sessão não encontrada. Escolha outra em Sessões ou abra Nova sessão." }]);
          return;
        }
        // Erro TERMINAL (rate limit / modelo inválido): reconectar+retomar em loop só MARTELA o
        // token do agente e mantém o 429 aceso. Não reconecta — o modal já orienta. (2026-09-28)
        if (noReconnectRef.current) { setStatus("erro"); return; }
        // Circuit breaker: várias quedas seguidas SEM conectar (ex.: agente morre no start) =>
        // para de tentar, em vez de criar tempestade de reconexão. Uma conexão OK zera o contador.
        failCountRef.current += 1;
        if (failCountRef.current >= 4) { setStatus("erro"); return; }
        setStatus("desconectado");
        reconnTimerRef.current = setTimeout(() => open(true), 3000);
      };

      ws.onmessage = (e) => {
        if (!currentSocket()) return;
        let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
        switch (ev.type) {
          case "system":
            if (ev.subtype === "init") {
              const d = ev.data || {};
              if (d.model) { setModel(d.model); setModelSel(d.model); modelRef.current = d.model; }
              if (d.permissionMode) setMode(d.permissionMode);
              if (d.session_id) identifySession(d.session_id);
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
          case "reattached":
            setWorking(!!ev.busy);   // re-anexou a uma sessão viva: reflete se há turno rodando
            break;
          case "result":
            setWorking(false);
            if (ev.session_id) identifySession(ev.session_id);
            setItems((prev) => {
              const next = closeOpen(prev);
              next.push({ type: "result", cost: ev.cost_usd, usage: ev.usage, isError: ev.is_error });
              return next;
            });
            break;
          case "error":
            setWorking(false);
            if (ev.detail === "too_many_sessions") {   // teto estático do servidor: não martela reconectando
              noReconnectRef.current = true;
              setItems((prev) => [...closeOpen(prev), { type: "error", detail: "Muitas sessões Claude abertas — feche alguma e tente de novo." }]);
              break;
            }
            setItems((prev) => [...closeOpen(prev), { type: "error", detail: ev.detail }]);
            if (looksRateLimited(ev.detail, modelsRef.current)) { noReconnectRef.current = true; setRateLimitDetail(ev.detail); setShowRateLimit(true); }  // 429: não reconectar em loop
            else if (isModelError(ev.detail)) { noReconnectRef.current = true; setModelErr(ev.detail); setShowModelPick(true); }  // modelo inválido: para e oferece troca
            refreshAuth();   // credencial expirada aparece como erro genérico; confirma no servidor
            break;
        }
      };
    };
    // Persistência (se ligada no servidor): pega o cookie de dono ANTES do 1º WS, p/ o
    // handshake já carregá-lo. 403 = persist desligado -> segue igual a antes.
    api.get("/claude/attach-ticket").then(() => open(false), () => open(false));

    return () => {
      disposed = true;
      manualCloseRef.current = true;                                 // impede reconexao ao trocar de sessao/encerrar
      if (reconnTimerRef.current) { clearTimeout(reconnTimerRef.current); reconnTimerRef.current = null; }
      if (hbRef.current) { clearInterval(hbRef.current); hbRef.current = null; }
      try { const w = wsRef.current; if (w && w.readyState === 1) w.send(JSON.stringify({ type: "bye" })); } catch (_) {}  // fechamento deliberado: mata a sessão viva
      try { wsRef.current && wsRef.current.close(); } catch (_) {}
      wsRef.current = null;
    };
  }, [active, gen]);

  function submit() {
    const text = input.trim();
    if (!text) return;
    // /login, /logout, /auth são resolvidos AQUI (o SDK não os conhece) e funcionam mesmo
    // com a sessão caída — que é exatamente quando você precisa deles.
    if (LOCAL_SLASH_RE.test(text)) { setInput(""); setShowAuth(true); return; }
    if (status !== "pronto" || working) return;
    if (!send({ type: "prompt", text })) { toast.err("Sem conexão"); return; }
    setItems((prev) => [...prev, { type: "user", text }]);
    setInput("");
    setWorking(true);
  }

  function stop() {
    if (send({ type: "interrupt" })) toast.info("Interrompendo…");
  }

  function newSession() {
    routeRequestRef.current++;
    activateSession("", true);
    if (location.hash !== "#claude/new") location.hash = "#claude/new";
  }
  function resumeSession(id) {
    if (!validSessionId(id)) return;
    setShowSessions(false);
    if (location.hash === claudeSessionHash(id)) openRoute();
    else location.hash = claudeSessionHash(id);
  }

  // Pós-login: o subprocesso `claude` vivo ainda carrega a credencial velha, então é preciso
  // relançar. RETOMA o mesmo sid — a conversa continua de onde parou (o histórico é relido do
  // transcript). Sem sid ainda, cai numa sessão nova.
  function relaunch() {
    const sid = sessionIdRef.current || "";
    activateSession(sid, true);
  }

  // Encerra a conversa (fecha o dock): derruba o WS e limpa o estado.
  const endSession = useCallback(() => {
    routeRequestRef.current++;
    connectionRef.current++;
    activeRef.current = false; selectionRef.current = null;
    manualCloseRef.current = true;
    if (reconnTimerRef.current) { clearTimeout(reconnTimerRef.current); reconnTimerRef.current = null; }
    try { const w = wsRef.current; if (w && w.readyState === 1) w.send(JSON.stringify({ type: "bye" })); } catch (_) {}  // encerrar: mata a sessão viva
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

  // Troca o modelo: aplica na sessão viva (set_model) e memoriza p/ o próximo (re)lançamento.
  function changeModel(m) {
    setModelSel(m);
    modelRef.current = m;
    if (status === "pronto") send({ type: "set_model", model: m });
  }

  // Escolha no modal de erro: memoriza o modelo e RELANÇA a sessão (a anterior falhou ao lançar,
  // então set_model não bastaria). Retoma o mesmo sid quando há um; senão, sessão nova.
  function pickModelAndRelaunch(m) {
    setModelSel(m);
    modelRef.current = m;
    setShowModelPick(false);
    const sid = sessionIdRef.current || "";
    activateSession(sid, true);
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
    status, items, working, mode, model, modelSel, models, sessionId, slash, input, setInput,
    showSessions, setShowSessions, badge, disabled, hasSession, fileRef,
    send, submit, stop, newSession, resumeSession, answerPermission, changeMode, changeModel, uploadFile,
    endSession,
    auth, showAuth, setShowAuth, refreshAuth, relaunch, refreshModels,
    showModelPick, setShowModelPick, modelErr, pickModelAndRelaunch,
    showRateLimit, setShowRateLimit, rateLimitDetail,
  };
}

// --------------------------------------------------------------------- visões
// Transcrição rolável (compartilhada). Cada instância faz seu próprio auto-scroll ao fim.
function Transcript() {
  const { items, status, answerPermission, auth, setShowAuth } = useClaude();
  const scrollRef = useRef(null);
  useEffect(() => { const el = scrollRef.current; if (el) el.scrollTop = el.scrollHeight; }, [items]);
  const loggedOut = auth && auth.available && !auth.loggedIn;
  return html`<div class="cc-transcript" ref=${scrollRef}>
    ${loggedOut && html`<${LoginBanner} auth=${auth} onLogin=${() => setShowAuth(true)} />`}
    ${items.length === 0 && status === "pronto" && !loggedOut && html`<div class="cc-hint help">
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
  const { input, setInput, submit, stop, working, disabled, mode, changeMode, modelSel, models, changeModel, uploadFile, slash, fileRef } = useClaude();
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
  // Os comandos locais (/login…) entram na lista mesmo desconectado — vêm da aba, não do init.
  const slashQuery = /^\/(\S*)$/.exec(input);
  const slashMatches = slashQuery
    ? [...LOCAL_SLASH, ...slash.filter((c) => !LOCAL_SLASH.includes(c))]
        .filter((c) => c.startsWith(slashQuery[1])).slice(0, 8)
    : [];

  // A caixa NUNCA trava: desconectado ainda dá p/ digitar /login (é justamente aí que se precisa).
  const isLocal = LOCAL_SLASH_RE.test(input.trim());
  const cantSend = (disabled && !isLocal) || !input.trim();

  return html`<div class="cc-composer-wrap">
    ${slashMatches.length > 0 && html`<div class="cc-slash-menu">
      ${slashMatches.map((c) => html`<button key=${c} class="cc-slash" onClick=${() => setInput("/" + c + " ")}>/${c}</button>`)}
    </div>`}
    <div class="cc-composer">
      <textarea ref=${taRef} rows="1"
        placeholder=${disabled
          ? "Sem sessão — digite /login para entrar, ou aguarde a reconexão"
          : "Mensagem (Enter envia · Shift+Enter quebra linha · / para comandos)"}
        value=${input}
        onInput=${(e) => setInput(e.target.value)} onKeyDown=${onKeyDown}></textarea>
      <div class="cc-composer-bar">
        <div class="cc-composer-left">
          <label class="cc-modepick" title="Modo de permissão do agente">
            <select value=${mode} onChange=${(e) => changeMode(e.target.value)} disabled=${disabled}>
              ${MODES.map((m) => html`<option key=${m.value} value=${m.value} selected=${m.value === mode}>${m.label}</option>`)}
            </select>
          </label>
          <label class="cc-modelpick" title="Modelo — lido da API; Sonnet é o mais econômico">
            <select value=${modelSel} onChange=${(e) => changeModel(e.target.value)}>
              ${models.map((m) => html`<option key=${m.id} value=${m.id} selected=${m.id === modelSel}>${m.name}</option>`)}
            </select>
          </label>
        </div>
        <div class="cc-composer-actions">
          <input type="file" ref=${fileRef} style="display:none"
            onChange=${(e) => { uploadFile(e.target.files[0]); e.target.value = ""; }} />
          <button class="sm" disabled=${disabled} onClick=${() => fileRef.current && fileRef.current.click()}
            title="Anexa um arquivo (vira @caminho na mensagem)">📎 Anexar</button>
          ${working
            ? html`<button class="danger" onClick=${stop} title="Interrompe o agente (Esc)">⏹ Parar</button>`
            : html`<button class="primary" disabled=${cantSend} onClick=${submit}>Enviar</button>`}
        </div>
      </div>
    </div>
  </div>`;
}

// Página cheia; seleção da sessão é controlada pelo fragmento da URL no provider.
export function ClaudeCodePage() {
  const s = useClaude();
  return html`<div class="claude-page">
    <div class="page-title">
      <h1>Claude Code</h1>
      <span class="badge ${s.badge}">${s.status}</span>
      ${s.auth && s.auth.available && html`<button
        class=${"sm cc-authbtn " + (s.auth.loggedIn ? "" : "danger")}
        onClick=${() => s.setShowAuth(true)}
        title=${s.auth.loggedIn ? "Conta do agente (/login)" : "O agente está deslogado — clique para entrar"}>
        ${s.auth.loggedIn ? "👤 " + (s.auth.email || s.auth.authMethod || "conectado") : "🔓 entrar (/login)"}
      </button>`}
      <span class="spacer"></span>
      ${s.working && html`<button class="sm danger" onClick=${() => s.send({ type: "interrupt" })}>Interromper</button>`}
      <button class="sm" disabled=${!s.sessionId} onClick=${() => copySessionLink(s.sessionId)}>Copiar link</button>
      <button class="sm" onClick=${() => s.setShowSessions(true)} title="Ver e retomar sessões anteriores">Sessões</button>
      <button class="sm" onClick=${s.newSession} title="Encerra esta sessão e abre uma nova">Nova sessão</button>
    </div>
    <${VaultBanner} />
    <${Transcript} />
    <${Composer} />
    ${s.showSessions && html`<${SessionsModal} currentId=${s.sessionId}
      onClose=${() => s.setShowSessions(false)} onResume=${s.resumeSession} />`}
    ${s.showAuth && html`<${LoginModal} auth=${s.auth} onClose=${() => s.setShowAuth(false)}
      onChanged=${s.refreshAuth} onRelaunch=${s.relaunch} onVerifyModels=${s.refreshModels} />`}
    ${s.showModelPick && html`<${ModelPickModal} detail=${s.modelErr} current=${s.modelSel} models=${s.models}
      onClose=${() => s.setShowModelPick(false)} onPick=${s.pickModelAndRelaunch} />`}
    ${s.showRateLimit && html`<${RateLimitModal} detail=${s.rateLimitDetail}
      onClose=${() => s.setShowRateLimit(false)} />`}
  </div>`;
}

// Aviso no topo da transcrição quando o agente está deslogado — é o que explica a aba morta.
function LoginBanner({ auth, onLogin }) {
  return html`<div class="card cc-auth-banner">
    <b>O agente Claude está deslogado.</b>
    <div class="help">
      A credencial fica em <code class="mono">${(auth.store && auth.store.credentials) || "~/.claude/.credentials.json"}</code>
      — o store do usuário <b>${(auth.store && auth.store.user) || "?"}</b>, que é quem roda o servidor.
      Logar por outro usuário (o terminal web, por exemplo) não vale para esta aba.
    </div>
    <div class="cc-perm-actions">
      <button class="sm primary" onClick=${onLogin}>Entrar</button>
    </div>
  </div>`;
}

// Fluxo de login OAuth conduzido pelo servidor (WS /api/claude/login): o CLI devolve a URL,
// você abre no SEU navegador, cola o código de volta. Ver services/claude_auth.py.
function LoginModal({ auth, onClose, onChanged, onRelaunch, onVerifyModels }) {
  const [phase, setPhase] = useState("idle");   // idle|starting|url|done|error
  const [modelChecks, setModelChecks] = useState(0);   // cliques em "Verificar modelos"
  const [modelWarn, setModelWarn] = useState(false);   // aviso de uso excessivo (3+ cliques)
  const [url, setUrl] = useState("");
  const [code, setCode] = useState("");
  const [log, setLog] = useState([]);
  const [result, setResult] = useState(null);   // status final do servidor
  const [checking, setChecking] = useState(false);  // código enviado, aguardando veredito
  const wsRef = useRef(null);
  const aliveRef = useRef(true);   // fechar o modal derruba o WS; não mexer em estado depois disso

  useEffect(() => () => {
    aliveRef.current = false;
    try { wsRef.current && wsRef.current.close(); } catch (_) {}   // fecha o WS => o servidor mata o `claude auth login`
  }, []);

  function start(mode) {
    setPhase("starting"); setUrl(""); setCode(""); setLog([]); setResult(null); setChecking(false);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/claude/login?auth=${encodeURIComponent(authToken())}`);
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "start", mode }));
    ws.onclose = () => { if (aliveRef.current) setPhase((p) => (p === "done" ? p : "error")); };
    ws.onmessage = (e) => {
      if (!aliveRef.current) return;
      let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
      if (ev.type === "url") { setUrl(ev.url); setPhase("url"); }
      // O CLI re-pergunta quando o código não cola direito: volta a liberar o campo.
      else if (ev.type === "awaiting_code") setChecking(false);
      else if (ev.type === "log") setLog((l) => [...l, ev.text].slice(-8));
      else if (ev.type === "error") { setLog((l) => [...l, ev.detail]); setPhase("error"); setChecking(false); }
      else if (ev.type === "done") {
        setResult(ev.status); setPhase("done"); setChecking(false);
        onChanged && onChanged();
        if (ev.ok) toast.ok("Agente autenticado"); else toast.err("Login não concluído");
        try { ws.close(); } catch (_) {}
      }
    };
  }

  function sendCode() {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== 1 || !code.trim()) return;
    ws.send(JSON.stringify({ type: "code", code: code.trim() }));
    setCode(""); setChecking(true);
  }

  async function doLogout() {
    try { const d = await api.post("/claude/auth/logout"); setResult(d); onChanged && onChanged(); toast.ok("Agente deslogado"); }
    catch (_) { toast.err("Falha ao deslogar"); }
  }

  // "Verificar modelos": relê a lista da API na hora. No 3º clique (e além) mostra o aviso
  // de que verificar em excesso pode estourar o rate limit (429) e travar o Claude.
  async function verifyModels() {
    const n = modelChecks + 1;
    setModelChecks(n);
    if (n >= 3) setModelWarn(true);
    try {
      const d = onVerifyModels && (await onVerifyModels());
      toast.ok("Modelos atualizados: " + ((d && d.models && d.models.length) || 0));
    } catch (_) {
      toast.err("Falha ao verificar modelos");
    }
  }

  const cur = result || auth || {};
  const busy = phase === "starting" || phase === "url";

  return html`<${Modal} title="Conta do agente Claude" onClose=${onClose} wide=${true}>
    <div class="cc-auth-state">
      ${cur.loggedIn
        ? html`<span class="badge ok">conectado</span> <b>${cur.email || cur.authMethod || "conta ativa"}</b>
               ${cur.subscriptionType ? html` <span class="help">· ${cur.subscriptionType}</span>` : ""}`
        : html`<span class="badge danger">deslogado</span> <span class="help">${cur.detail || "nenhuma credencial no store"}</span>`}
    </div>
    ${cur.store && html`<div class="help mono cc-auth-store">
      store: ${cur.store.credentials} (usuário ${cur.store.user})
    </div>`}

    ${phase === "idle" && html`<div>
      ${modelWarn && html`<div class="card cc-model-warn">
        ⚠ <b>Verificar modelos em excesso</b> consome a cota da conta e pode gerar
        <b>bloqueio temporário (rate limit / HTTP 429)</b>, que trava TODO o Claude Code.
        A lista já é relida automaticamente no máximo <b>uma vez por semana</b> — use este
        botão só quando realmente precisar.
      </div>`}
      <div class="modal-actions">
        ${cur.loggedIn && html`<button class="sm" onClick=${verifyModels}
          title="Relê os modelos disponíveis da API (no automático, no máx. 1x/semana)">Verificar modelos</button>`}
        ${cur.loggedIn && html`<button class="sm danger" onClick=${doLogout}>Sair da conta</button>`}
        <button class="sm" onClick=${() => start("console")} title="Cobrança por uso da API (Anthropic Console)">Entrar com API (Console)</button>
        <button class="primary" onClick=${() => start("claudeai")}>Entrar com assinatura Claude</button>
      </div>
    </div>`}

    ${url && phase !== "done" && html`<div class="cc-auth-step">
      <div><b>1.</b> Abra este endereço no seu navegador e autorize:</div>
      <a class="cc-auth-url mono" href=${url} target="_blank" rel="noopener noreferrer">${url}</a>
      <div class="cc-perm-actions">
        <button class="sm" onClick=${() => { navigator.clipboard?.writeText(url); toast.ok("URL copiada"); }}>Copiar URL</button>
      </div>
      <div><b>2.</b> Cole aqui o código que a página devolver:</div>
      <div class="cc-auth-code">
        <input type="password" value=${code} autoFocus placeholder="código de autorização"
          onInput=${(e) => setCode(e.target.value)}
          onKeyDown=${(e) => { if (e.key === "Enter") sendCode(); }} />
        <button class="primary" disabled=${!code.trim() || checking} onClick=${sendCode}>
          ${checking ? "Verificando…" : "Concluir"}</button>
      </div>
    </div>`}

    ${busy && !url && html`<div class="help">Iniciando o fluxo de login…</div>`}
    ${log.length > 0 && html`<pre class="cc-pre">${log.join("\n")}</pre>`}

    ${phase === "done" && html`<div class="modal-actions">
      ${cur.loggedIn
        ? html`<button class="primary" onClick=${() => { onRelaunch(); onClose(); }}
            title="Relança o agente com a credencial nova, retomando esta mesma conversa">
            Recarregar sessão</button>`
        : html`<button onClick=${() => setPhase("idle")}>Tentar de novo</button>`}
    </div>`}
    ${phase === "error" && html`<div class="modal-actions">
      <button onClick=${() => setPhase("idle")}>Tentar de novo</button>
    </div>`}
  <//>`;
}

// Modal que aparece quando o modelo escolhido falha (ex.: alias inexistente): mostra a
// mensagem do CLI e deixa escolher outro modelo, relançando a sessão.
// Modal de limite de uso: aparece quando o erro "de modelo" é, na verdade, um 429 disfarçado
// (o modelo é válido). Explica que é cota da conta e que trocar de modelo não resolve.
function RateLimitModal({ detail, onClose }) {
  return html`<${Modal} title="Limite de uso atingido (rate limit)" onClose=${onClose}>
    <div class="cc-model-pick">
      <div class="card cc-model-warn">
        A conta atingiu um <b>limite temporário de uso (HTTP 429)</b>. A API rejeita
        <b>todos os modelos</b> por um tempo — por isso trocar de modelo não resolve, e a
        mensagem "issue with the selected model" da CLI é enganosa: o problema é a cota.
      </div>
      <p class="help">A API não informa o horário exato de liberação. Costuma liberar em
        minutos até ~1h (rajada) ou até ~5h (teto do plano). Aguarde e tente de novo — evite
        reenviar em sequência, pois isso realimenta o bloqueio.</p>
      ${detail && html`<p class="cc-model-msg mono">${detail}</p>`}
    </div>
  <//>`;
}

function ModelPickModal({ detail, current, models, onClose, onPick }) {
  return html`<${Modal} title="Problema com o modelo" onClose=${onClose}>
    <div class="cc-model-pick">
      <p class="cc-model-msg">${detail}</p>
      <p class="help">Escolha um modelo para trocar e reiniciar a conversa:</p>
      <div class="cc-model-opts">
        ${models.map((m) => html`<button key=${m.id}
            class=${"cc-opt" + (m.id === current ? " sel" : "")}
            onClick=${() => onPick(m.id)}>
          <b>${m.name}</b>
        </button>`)}
      </div>
    </div>
  <//>`;
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
      <a class="sm dock-btn" href=${claudeSessionHash(s.sessionId)} title="Abrir em tela cheia">⤢</a>
      <button class="sm dock-btn" onClick=${s.endSession} title="Encerrar conversa">✕</button>
    </div>
    <${Transcript} />
    <${Composer} />
    ${s.showAuth && html`<${LoginModal} auth=${s.auth} onClose=${() => s.setShowAuth(false)}
      onChanged=${s.refreshAuth} onRelaunch=${s.relaunch} onVerifyModels=${s.refreshModels} />`}
    ${s.showModelPick && html`<${ModelPickModal} detail=${s.modelErr} current=${s.modelSel} models=${s.models}
      onClose=${() => s.setShowModelPick(false)} onPick=${s.pickModelAndRelaunch} />`}
    ${s.showRateLimit && html`<${RateLimitModal} detail=${s.rateLimitDetail}
      onClose=${() => s.setShowRateLimit(false)} />`}
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
    try { await api.del(`/claude/sessions/${encodeURIComponent(id)}`); forgetClaudeSession(id); load(q); }
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
            <div class="cc-sess-title"><a href=${claudeSessionHash(s.id)} onClick=${(e) => {
              e.stopPropagation();
              if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey && e.button === 0) {
                e.preventDefault(); onResume(s.id);
              }
            }}>${hl(s.title, term)}</a>${s.id === currentId ? html` <span class="badge ok">atual</span>` : ""}</div>
            ${s.preview && html`<div class="cc-sess-prev help">${hl(s.preview, term)}</div>`}
            ${s.snippet && html`<div class="cc-sess-snip help">${hl(s.snippet, term)}</div>`}
            <div class="cc-sess-meta help mono">${fmtTime(s.mtime)} · ${(s.id || "").slice(0, 8)}${s.branch ? " · " + s.branch : ""}</div>
          </div>
          <button class="sm" title="Copiar link da sessão" onClick=${(e) => { e.stopPropagation(); copySessionLink(s.id); }}>Copiar link</button>
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
