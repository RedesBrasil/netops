// Página Claude Code — chat com o agente (claude-agent-sdk) via WebSocket (/api/claude).
// A SESSÃO VIVE ACIMA DO ROTEADOR: toda a lógica (WebSocket + estado) mora no
// ClaudeProvider, montado uma única vez no App (fora do swap de rota). Trocar de página
// NÃO mata a conversa. Há duas visões do mesmo estado vivo: a página cheia (ClaudeCodePage)
// e um chat compacto encaixado à direita (ChatDock), que aparece quando você navega para
// outra rota com uma conversa viva — dá p/ acompanhar o streaming, enviar e aprovar.
// Protocolo JSON nos dois sentidos (ver scripts/engine/ui/services/claude_svc.py).
import { html, useState, useEffect, useRef, useCallback, toast, api, refreshVault, can } from "../ui.js";
import { FileBrowser } from "../file-browser.js";
import { useDictation, MAX_SECONDS } from "../audio-dictation.js";
import { createContext } from "preact";
import { useContext } from "preact/hooks";
import { MarkdownView, VaultBanner, Modal, Field, UnlockModal } from "../components.js";
import { autoOpenFromText } from "../term-link.js";
import { authToken } from "../api.js";
import { buildCatalog, findMentionToken, searchMentions, applyMention, expandMentions, addQuoteNote, stripMentionNote } from "../mentions.js";
import { classifyClaudeError, claudeErrorDetail, friendlyClaudeError } from "../claude-errors.js";
import { takeClaudePrefill, validSessionId, validProjectId, claudeSessionHash, claudeNewHash, readClaudeRoute, lastClaudeSession,
  rememberClaudeSession, forgetClaudeSession, replaceClaudeHash, claudePrefsOpen, setClaudePrefsHash, claudeSessionsOpen, setClaudeSessionsHash, stripClaudeModal, copyClaudeSessionLink } from "../claude-sessions.js";

// `?project=<id>` (ou `&project=`) quando a conversa é de um Projeto; vazio = aba Claude Code (pasta do NetOps).
const projQ = (project, first = "?") => (project ? `${first}project=${encodeURIComponent(project)}` : "");

// Ctrl/Cmd+clique ou clique do meio (roda do mouse): abre o destino (#hash) em nova aba e NÃO altera a sessão atual.
// O clique do meio dispara `auxclick` (não `click`): ligue também onAuxClick e onMouseDown=${noAutoscroll}.
function openInNewWindow(e, hash) {
  if (!e || !(e.ctrlKey || e.metaKey || e.button === 1)) return false;
  e.preventDefault(); e.stopPropagation();
  window.open(location.pathname + location.search + hash, "_blank", "noopener");
  return true;
}

// Clique do meio no Windows/Linux liga o "autoscroll"; cancela p/ ele virar só um clique.
function noAutoscroll(e) { if (e.button === 1) e.preventDefault(); }

async function copySessionLink(id, project = "") {
  try { await copyClaudeSessionLink(id, project); toast.ok("Link da sessão copiado"); }
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
  { value: "default", label: "Perguntar antes", short: "Manual", icon: "✋", desc: "Pede aprovação antes de cada ação" },
  { value: "acceptEdits", label: "Auto-editar", short: "Auto-editar", icon: "‹›", desc: "Edita arquivos sozinho; pergunta o resto" },
  { value: "plan", label: "Plano (só leitura)", short: "Plano", icon: "☰", desc: "Explora e apresenta um plano antes de editar" },
  { value: "dontAsk", label: "Não perguntar", short: "Não perguntar", icon: "⌀", desc: "Nega tudo que não estiver pré-aprovado" },
  { value: "bypassPermissions", label: "Bypass — full-auto ⚠", short: "Bypass", icon: "⚡", desc: "Executa sem pedir aprovação, até comandos perigosos" },
];

// Permissões de rede (CRUD) do agente NOS EQUIPAMENTOS (session.py). O backend classifica cada
// comando (scripts/engine/lib/net_perms.py) e pede aprovação na tela se faltar categoria.
// Independe do modo acima (que governa arquivos/ferramentas locais). Full = as 4 marcadas.
const NETPERMS = [
  { value: "read", label: "Ler", short: "L", desc: "print, show, ping" },
  { value: "create", label: "Criar", short: "C", desc: "add" },
  { value: "edit", label: "Editar", short: "E", desc: "set, restart, reboot" },
  { value: "delete", label: "Apagar", short: "A", desc: "remove, no, rm" },
];
const NETPERMS_ALL = NETPERMS.map((p) => p.value);
const npNorm = (arr) => NETPERMS_ALL.filter((v) => Array.isArray(arr) ? arr.includes(v) : true);
const npFull = (arr) => npNorm(arr).length === NETPERMS_ALL.length;
const npShort = (arr) => {
  const n = npNorm(arr);
  if (n.length === NETPERMS_ALL.length) return "Full";
  if (!n.length) return "Nada";
  if (n.length === 1 && n[0] === "read") return "Só leitura";
  return NETPERMS.filter((p) => n.includes(p.value)).map((p) => p.short).join("·");
};

// Catálogo anunciado pelo mesmo CLI/provider que executa a conversa. Se indisponível,
// o CLI resolve seu próprio padrão; a UI não presume versões ou acesso da conta.
const MODELS_FALLBACK = [
  { id: "default", name: "Padrão do Claude Code" },
];

// Fecha o último item "aberto" (bolha em streaming) antes de empurrar outro tipo.
// Espelho da fila no navegador (por conversa): se o servidor perder a fila dele (reinício do
// console, sessão em modo clássico que morre com o socket), a aba a devolve ao reconectar.
// Só o texto, nada do projeto em disco. Entradas velhas (>24 h) são ignoradas.
const QUEUE_CACHE = "cc-queue:";
const QUEUE_TTL = 24 * 3600 * 1000;
function loadQueueCache(sid) {
  if (!sid) return [];
  try {
    const v = JSON.parse(localStorage.getItem(QUEUE_CACHE + sid) || "null");
    if (!v || !Array.isArray(v.items) || Date.now() - (v.at || 0) > QUEUE_TTL) return [];
    return v.items.filter((x) => x && typeof x.text === "string" && x.text.trim());
  } catch (_) { return []; }
}
function saveQueueCache(sid, items) {
  if (!sid) return;
  try {
    if (items.length) localStorage.setItem(QUEUE_CACHE + sid, JSON.stringify({ at: Date.now(), items }));
    else localStorage.removeItem(QUEUE_CACHE + sid);
  } catch (_) {}
}

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
// Dock aberto sobrevive ao F5/Ctrl+Shift+R: guarda (por aba) o id da conversa encaixada.
const DOCK_KEY = "netops_dock_session";
// Guarda também o Projeto (pasta) da conversa: sem ele, o F5 tentaria reabri-la na pasta do NetOps.
function setDockSession(id, project = "") { try { id ? sessionStorage.setItem(DOCK_KEY, JSON.stringify({ id, project: project || "" })) : sessionStorage.removeItem(DOCK_KEY); } catch (_) {} }
function getDockSession() {
  try {
    const raw = sessionStorage.getItem(DOCK_KEY) || "";
    const d = raw.startsWith("{") ? JSON.parse(raw) : { id: raw, project: "" };   // formato antigo: só o id
    return validSessionId(d.id) ? { id: d.id, project: validProjectId(d.project) ? d.project : "" } : null;
  } catch (_) { return null; }
}
export function useClaude() { return useContext(ClaudeCtx); }

export function ClaudeProvider({ children }) {
  const value = useClaudeSession();
  // Cofre trancado no meio de um pedido: o servidor segura o comando e manda `vault_request`;
  // o pop-up vale em QUALQUER rota/visão (página cheia, dock, celular). Destrancou -> o servidor
  // libera o comando sozinho (`vault_resolved`). Fechar o pop-up só o dispensa; o agente segue
  // aguardando e o pop-up volta ao reabrir/voltar à aba.
  return html`<${ClaudeCtx.Provider} value=${value}>${children}
    ${value.vaultAsk && html`<${UnlockModal} reason="O agente precisa de uma credencial do cofre para continuar. Destranque para liberar o comando — ele está aguardando."
      onClose=${() => value.setVaultAsk(false)} />`}<//>`;
}

// Hook que concentra TODO o ciclo de vida da sessão (WS + transcrição + ações). Roda uma
// única vez, no provider. `active` liga/desliga a conexão sem depender da rota atual — por
// isso a conversa (e um turno em andamento) sobrevive à navegação entre páginas.
function useClaudeSession() {
  const [status, setStatus] = useState("conectando"); // conectando|pronto|desconectado|desabilitado|erro
  const [items, setItems] = useState([]);             // transcript ordenado
  const [working, setWorking] = useState(false);      // turno em andamento
  const [queue, setQueue] = useState([]);             // fila do SERVIDOR [{id,text}] (roda ao fim do turno)
  const [pendingSend, setPendingSend] = useState(null); // {text} aguardando a escolha "agora" x "fila"
  const [mode, setMode] = useState("default");
  const [netperms, setNetpermsState] = useState(NETPERMS_ALL);   // permissões de rede da conversa
  const netpermsRef = useRef(NETPERMS_ALL);
  const setNetperms = useCallback((v) => { const n = npNorm(v); netpermsRef.current = n; setNetpermsState(n); }, []);
  const [netpermsMax, setNetpermsMax] = useState(null);   // teto do grupo de acesso (multiusuário)
  const [effort, setEffort] = useState(() => { try { return localStorage.getItem("cc-effort") || ""; } catch (_) { return ""; } });
  const effortRef = useRef(effort);
  const [ctxUse, setCtxUse] = useState(null);      // {total,max,percentage} do contexto
  const [lastUsage, setLastUsage] = useState(null); // usage do último turno (p/ cache)
  const [model, setModel] = useState("");
  const [modelSel, setModelSel] = useState("");         // modelo escolhido (vazio até carregar do servidor)
  const [models, setModels] = useState(MODELS_FALLBACK); // modelos disponíveis (lidos de /claude/models)
  const [sessionId, setSessionId] = useState("");
  const [project, setProject] = useState("");            // Projeto da conversa ("" = aba Claude Code)
  const projectRef = useRef("");
  const [slash, setSlash] = useState([]);             // nomes de slash commands (do init)
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState([]);   // [{path,name}] já enviados, ainda não mandados ao agente
  const [gen, setGen] = useState(0);                  // bump => reconecta
  const [showSessions, setShowSessionsState] = useState(() => claudeSessionsOpen());
  const setShowSessions = useCallback((v) => { setClaudeSessionsHash(!!v); }, []);
  const [active, setActive] = useState(false);        // há sessão ligada? (independe da rota)
  const [auth, setAuth] = useState(null);             // login do `claude` {loggedIn, email, store…}
  const [showAuth, setShowAuth] = useState(false);    // modal do fluxo de login
  const [showModelPick, setShowModelPick] = useState(false); // modal de troca de modelo (após erro)
  const [modelErr, setModelErr] = useState("");       // mensagem do erro de modelo (mostrada no modal)
  const [showRateLimit, setShowRateLimit] = useState(false); // modal de limite de uso (429 disfarçado)
  const [rateLimitDetail, setRateLimitDetail] = useState(""); // mensagem crua do erro
  const [vaultAsk, setVaultAsk] = useState(false);    // pop-up "cofre trancado — destrancar" (agente aguardando)
  const wsRef = useRef(null);
  const liveTextRef = useRef("");       // texto do agente no turno ao vivo (abertura automática de terminal)
  const liveTurnRef = useRef(String(Date.now()));
  const fileRef = useRef(null);
  const sessionIdRef = useRef("");      // sid vigente (p/ retomar na reconexao automatica)
  const defaultsRef = useRef({ model: "", mode: "default", catalogModel: "", netperms: NETPERMS_ALL }); // padrões p/ conversas novas
  const [prefs, setPrefs] = useState({ default_model: "", default_mode: "default", default_netperms: NETPERMS_ALL });
  const [showPrefs, setShowPrefsState] = useState(() => claudePrefsOpen());
  const setShowPrefs = useCallback((v) => { setClaudePrefsHash(!!v); }, []);
  // Prefill pedido com a conversa-alvo já aberta (activateSession não roda de novo): ex. Central de Avisos → #claude/new.
  useEffect(() => {
    const on = () => { const pre = takeClaudePrefill(selectionRef.current || ""); if (pre != null) setInput(pre); };
    addEventListener("netops:claude-prefill", on);
    return () => removeEventListener("netops:claude-prefill", on);
  }, []);
  useEffect(() => {
    const on = () => { setShowPrefsState(claudePrefsOpen()); setShowSessionsState(claudeSessionsOpen()); };
    addEventListener("hashchange", on); on();
    return () => removeEventListener("hashchange", on);
  }, []);
  const modelRef = useRef("");          // modelo vigente (vai no ?model=; vazio => default do servidor)
  const interruptedRef = useRef(false); // usuário clicou em Interromper neste turno (erro vira "cancelada")
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

  function activateSession(id, force = false, proj = projectRef.current) {
    proj = proj || "";
    // A seleção inclui o projeto: o mesmo "new" (ou uuid) em outro projeto é OUTRA conversa.
    const target = proj + "|" + (id || "new");
    if (!force && activeRef.current && selectionRef.current === target) return;
    connectionRef.current++;
    projectRef.current = proj; setProject(proj);
    if (!id || id !== sessionIdRef.current) setLastUsage(null);   // cache é por conversa: nova/outra sessão começa sem relógio
    selectionRef.current = target;
    resumeIdRef.current = id || "";
    sessionIdRef.current = id || "";
    activeRef.current = true;
    // fork / Central de Avisos: repõe o prompt no campo de digitação da conversa aberta
    const pre = takeClaudePrefill(target) || "";
    setInput(pre); setAttachments([]); setShowSessions(false);
    setShowModelPick(false); setShowRateLimit(false);
    if (!id) {   // conversa NOVA: começa nos padrões das configurações (não herda a anterior)
      const dflt = defaultsRef.current;
      const m = dflt.model || dflt.catalogModel || "";
      modelRef.current = m; setModelSel(m); setMode(dflt.mode || "default");
      setNetperms(dflt.netperms || NETPERMS_ALL);
    }
    setSessionId(id || ""); setItems([]); setWorking(false); setStatus("conectando");
    setActive(true); setGen((g) => g + 1);
  }

  // Ao conhecer a sessão (inclusive após F5), restaura o último cache salvo desta conversa.
  useEffect(() => {
    if (!sessionId) return;
    try {
      const u = JSON.parse(localStorage.getItem("cc-cache:" + sessionId) || "null");
      setLastUsage((cur) => (u && u._at && !(cur && cur._sid === sessionId && cur._at >= u._at) ? { ...u, _sid: sessionId }
        : (cur && cur._sid && cur._sid !== sessionId ? null : cur)));
    } catch (_) {}
  }, [sessionId]);

  function identifySession(id) {
    if (!validSessionId(id)) return;
    const changed = sessionIdRef.current !== id;
    setSessionId(id); sessionIdRef.current = id;
    selectionRef.current = projectRef.current + "|" + id; resumeIdRef.current = id;
    const route = readClaudeRoute(location.hash);
    // Um init antigo não pode trocar um link explícito recém-aberto (nem de outro projeto).
    if (route && route.kind === "session" && route.id !== id) return;
    if (route && (route.project || "") !== projectRef.current) return;
    if (changed && !projectRef.current) rememberClaudeSession(id);   // "última conversa" é só da aba Claude Code
    setDockSession(id, projectRef.current);
    if (route && route.kind !== "invalid") replaceClaudeHash(claudeSessionHash(id, projectRef.current));
  }

  async function openRoute() {
    const request = ++routeRequestRef.current;
    const route = readClaudeRoute(location.hash);
    if (!route) {   // navegar para Hosts mantém a sessão viva no dock
      const dock = getDockSession();   // recarga da página: reabre o dock da conversa que estava aberta
      if (dock && !activeRef.current) {
        try { await api.get(`/claude/sessions/${encodeURIComponent(dock.id)}${projQ(dock.project)}`); } catch (_) { setDockSession(""); return; }
        if (request === routeRequestRef.current && !activeRef.current) activateSession(dock.id, false, dock.project);
      }
      return;
    }
    const current = () => request === routeRequestRef.current;
    try {
      if (route.kind === "invalid") throw new Error("Link de sessão inválido. Escolha uma conversa em Sessões ou abra Nova sessão.");
      if (route.kind === "new") { activateSession("", false, route.project || ""); return; }
      if (route.kind === "session") {
        const rp = route.project || "";
        if (activeRef.current && sessionIdRef.current === route.id && projectRef.current === rp) return;
        await api.get(`/claude/sessions/${encodeURIComponent(route.id)}${projQ(rp)}`);
        if (!current()) return;
        if (!rp) rememberClaudeSession(route.id);
        activateSession(route.id, false, rp);
        return;
      }
      // #claude puro: uma conversa de Projeto ativa NÃO vale aqui (sessão de outra pasta) — cai na última do NetOps.
      if (activeRef.current && !projectRef.current) {
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
      activateSession(id, false, "");
      replaceClaudeHash(id ? claudeSessionHash(id) : "#claude/new");
    } catch (e) {
      if (!current()) return;
      endSession();
      setStatus("erro");
      setItems([{ type: "error", detail: e.status === 404
        ? "Sessão ou projeto não encontrado. Escolha outra em Sessões ou abra Nova sessão."
        : e.message || "Não foi possível abrir a sessão. Tente novamente." }]);
    }
  }

  // O provider acompanha também voltar/avançar: a página cheia não remonta entre UUIDs.
  useEffect(() => {
    const baseOf = stripClaudeModal;
    let lastBase = baseOf(location.hash);
    const onRoute = () => {
      const b = baseOf(location.hash);
      if (b === lastBase && sessionIdRef.current !== undefined && activeRef.current) return; // só um popup (Padrões/Sessões) abriu/fechou
      lastBase = b; openRoute();
    };
    addEventListener("hashchange", onRoute);
    onRoute();
    return () => { routeRequestRef.current++; removeEventListener("hashchange", onRoute); };
  }, []);

  const send = useCallback((obj) => {
    if (obj && obj.type === "interrupt") interruptedRef.current = true;
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
      next.push({ type: kind, text, open: true, ts: Date.now() });
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
    if (Array.isArray(d.models) && d.models.length) setModels(d.models);
    if (d.default && !modelRef.current) { setModelSel(d.default); modelRef.current = d.default; }
    return d;
  }, []);
  useEffect(() => { if (active) refreshAuth(); }, [active, gen]);

  // Modelos disponíveis: catálogo do CLI, sem inferência nem acesso direto a credenciais.
  // Popula o seletor e define o padrão econômico; o init depois ajusta p/ o modelo real vigente.
  useEffect(() => {
    Promise.all([api.get("/claude/models").catch(() => ({})), api.get("/claude/prefs").catch(() => ({}))]).then(([d, p]) => {
      if (Array.isArray(d.models) && d.models.length) setModels(d.models);
      defaultsRef.current = { model: p.default_model || "", mode: p.default_mode || "default", catalogModel: d.default || "",
        netperms: npNorm(p.default_netperms) };
      setPrefs({ default_model: p.default_model || "", default_mode: p.default_mode || "default", default_netperms: npNorm(p.default_netperms) });
      if (!modelRef.current && !sessionIdRef.current) {
        const m = defaultsRef.current.model || defaultsRef.current.catalogModel;
        if (m) { setModelSel(m); modelRef.current = m; }
        if (!activeRef.current || !sessionIdRef.current) { setMode(defaultsRef.current.mode); setNetperms(defaultsRef.current.netperms); }
      }
    });
  }, []);

  const savePrefs = useCallback(async (next) => {
    const p = await api.put("/claude/prefs", next);
    defaultsRef.current = { ...defaultsRef.current, model: p.default_model || "", mode: p.default_mode || "default",
      netperms: npNorm(p.default_netperms) };
    setPrefs({ default_model: p.default_model || "", default_mode: p.default_mode || "default", default_netperms: npNorm(p.default_netperms) });
    return p;
  }, []);

  function handleAgentError(ev) {
    const raw = claudeErrorDetail(ev);
    const detail = friendlyClaudeError(ev, { interrupted: interruptedRef.current });
    const kind = classifyClaudeError(ev);
    setShowModelPick(kind === "model");
    setShowRateLimit(kind === "rate_limit");
    setWorking(false);
    setItems((prev) => {
      const next = closeOpen(prev);
      if (next[next.length - 1]?.type !== "error" || next[next.length - 1].detail !== detail)
        next.push({ type: "error", detail, raw: raw !== detail ? raw : "" });
      return next;
    });
    if (kind === "rate_limit" || kind === "model") {
      noReconnectRef.current = true;
      if (kind === "rate_limit") { setRateLimitDetail(detail); setShowRateLimit(true); }
      else { setModelErr(detail); setShowModelPick(true); }
    }
  }

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
      setQueue([]); setPendingSend(null);   // a fila é do servidor: o re-anexo reenvia o estado real
      // Carrega antes de abrir o socket: uma leitura atrasada não apaga streaming/permissões.
      if (resume && !reconnect) {   // volta no ÚLTIMO modelo/modo desta conversa
        try {
          const p = await api.get(`/claude/prefs?sid=${encodeURIComponent(resume)}`);
          if (!current()) return;
          const sv = p.session || {};
          if (sv.model) { modelRef.current = sv.model; setModelSel(sv.model); }
          if (sv.mode) setMode(sv.mode);
          setNetperms(Array.isArray(sv.netperms) ? sv.netperms : NETPERMS_ALL);
        } catch (_) {}
      }
      if (resume) {
        try {
          const h = await api.get(`/claude/sessions/${encodeURIComponent(resume)}/messages${projQ(projectRef.current)}`);
          if (!current()) return;
          setItems(h.items || []);
        } catch (_) {}
      }
      if (!current()) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/claude`
        + `?auth=${encodeURIComponent(authToken())}`
        + (effortRef.current ? `&effort=${encodeURIComponent(effortRef.current)}` : "")
        + (modelRef.current ? `&model=${encodeURIComponent(modelRef.current)}` : "")
        + projQ(projectRef.current, "&")
        + (resume ? `&resume=${encodeURIComponent(resume)}` : `&netperms=${encodeURIComponent(netpermsRef.current.join(","))}`));
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
        // Quedas seguidas SEM conectar: NÃO desiste (celular bloqueado/sem rede volta minutos depois e
        // antes a aba ficava em "erro" com o agente vivo no servidor). Só espaça as tentativas
        // (backoff 3s→60s, teto 40 tentativas). Erros terminais já saíram acima (noReconnectRef).
        failCountRef.current += 1;
        if (failCountRef.current > 40) { setStatus("erro"); return; }
        setStatus("desconectado");
        const delay = Math.min(60000, 3000 * Math.pow(2, Math.max(0, failCountRef.current - 4)));
        // Renova o cookie de dono antes de reconectar: após um reinício do console o antigo
        // não vale mais.
        reconnTimerRef.current = setTimeout(() => {
          api.get("/claude/attach-ticket").then(() => open(true), () => open(true));
        }, delay);
      };

      ws.onmessage = (e) => {
        if (!currentSocket()) return;
        let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
        switch (ev.type) {
          case "system":
            if (ev.subtype === "commands") {
              const l = (ev.data || {}).slash_commands;
              if (Array.isArray(l) && l.length) setSlash(l);
            } else if (ev.subtype === "init") {
              const d = ev.data || {};
              // O init traz o id RESOLVIDO (pode diferir do id da lista): só informativo. A escolha
              // do usuário (modelRef) manda no seletor — antes isto o fazia "pular" sozinho.
              if (d.model) { setModel(d.model); if (!modelRef.current) { setModelSel(d.model); modelRef.current = d.model; } }
              if (d.permissionMode) setMode(d.permissionMode);
              if (Array.isArray(d.netPerms)) setNetperms(d.netPerms);
              if (d.session_id) identifySession(d.session_id);
              if (Array.isArray(d.slash_commands)) setSlash(d.slash_commands);
            }
            break;
          case "text_delta":
            appendDelta("assistant", ev.text);
            // Agente respondeu com link de terminal de host ("abre a borda") -> abre a janela sozinho.
            liveTextRef.current += ev.text;
            autoOpenFromText(liveTextRef.current, liveTurnRef.current);
            break;
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
            liveTextRef.current = ""; liveTurnRef.current = String(Date.now());
            setItems((prev) => closeOpen(prev));
            break;
          case "permission_request":
            setItems((prev) => {
              const next = closeOpen(prev);
              next.push({ type: "permission", id: ev.id, tool: ev.tool, input: ev.input, context: ev.context || {}, resolved: false });
              return next;
            });
            break;
          case "vault_request": setVaultAsk(true); break;
          case "vault_resolved": setVaultAsk(false); refreshVault(); break;
          case "cache_state":   // re-anexo: usa a IDADE real do último turno, não "agora"
            if (ev.usage) setLastUsage({ ...ev.usage, _at: Date.now() - (ev.age || 0) * 1000 });
            break;
          case "context_usage":
            setCtxUse({ total: ev.total, max: ev.max, percentage: ev.percentage });
            break;
          case "mode_changed":
            setMode(ev.mode);
            break;
          case "netperms_changed":
            if (Array.isArray(ev.perms)) setNetperms(ev.perms);
            setNetpermsMax(Array.isArray(ev.max) ? ev.max : null);   // teto do grupo do usuário (null = sem teto)
            break;
          case "reattached":
            setWorking(!!ev.busy);   // re-anexou a uma sessão viva: reflete se há turno rodando
            break;
          case "queue": {
            const items = Array.isArray(ev.items) ? ev.items : [];
            const sid = sessionIdRef.current;
            // Sessão NOVA no servidor (fila vazia de verdade) + cache na aba = a fila se perdeu
            // lá (reinício/modo clássico): devolve. No re-anexo (sem `fresh`) o servidor manda —
            // o que sumiu foi despachado de fato e reenviar duplicaria.
            if (ev.fresh && !items.length) {
              const cached = loadQueueCache(sid);
              if (cached.length) {
                send({ type: "queue_add", texts: cached.map((x) => x.text) });
                toast.info(cached.length === 1 ? "1 mensagem da fila foi restaurada." : `${cached.length} mensagens da fila foram restauradas.`);
                break;   // o servidor responde com a fila real; aí o cache é regravado
              }
            }
            setQueue(items);
            saveQueueCache(sid, items);
            break;
          }
          case "user_echo":   // pergunta digitada em OUTRA aba da mesma sessão
            setItems((prev) => [...closeOpen(prev), { type: "user", text: ev.text, ts: Date.now() }]);
            setWorking(true);
            break;
          case "queue_dispatched":   // item da fila virou turno no servidor
            setItems((prev) => [...closeOpen(prev), { type: "user", text: ev.text, queued: true, ts: Date.now() }]);
            setWorking(true);
            break;
          case "queue_restored": {   // turno interrompido/erro: a fila não roda sozinha, volta p/ a caixa
            const texts = (ev.items || []).map((x) => x.text).filter(Boolean);
            if (texts.length) {
              setInput((cur) => [...texts, cur].filter((t) => t && t.trim()).join("\n\n"));
              toast.info(texts.length === 1
                ? "Turno interrompido: a mensagem da fila voltou para a caixa."
                : `Turno interrompido: ${texts.length} mensagens da fila voltaram para a caixa.`);
            }
            break;
          }
          case "result":
            setWorking(false);
            const wasInterrupted = interruptedRef.current;
            if (ev.usage) {
              const sid = ev.session_id || sessionIdRef.current;
              const u = { ...ev.usage, _at: Date.now(), _sid: sid };
              setLastUsage(u);   // sobrevive ao F5 (o TTL é do relógio real)
              if (sid) { try { localStorage.setItem("cc-cache:" + sid, JSON.stringify(u)); } catch (_) {} }
            }
            if (ev.session_id) identifySession(ev.session_id);
            if (ev.is_error && (ev.result || ev.errors?.length || ev.api_error_status)) handleAgentError(ev);
            interruptedRef.current = false;
            setItems((prev) => {
              const next = closeOpen(prev);
              next.push({ type: "result", cost: ev.cost_usd, usage: ev.usage, isError: ev.is_error, cancelled: ev.is_error && wasInterrupted });
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
            handleAgentError(ev);
            refreshAuth();   // credencial expirada aparece como erro genérico; confirma no servidor
            break;
        }
      };
    };
    // Persistência (se ligada no servidor): pega o cookie de dono ANTES do 1º WS, p/ o
    // handshake já carregá-lo. 403 = persist desligado -> segue igual a antes.
    api.get("/claude/attach-ticket").then(() => open(false), () => open(false));

    // Celular bloqueado / navegador em segundo plano: o socket morre mas o agente segue no servidor
    // (persist). Ao voltar (visível / rede de volta / bfcache) reconecta NA HORA, sem esperar o backoff.
    const wake = () => {
      if (!current() || manualCloseRef.current || noReconnectRef.current) return;
      if (document.visibilityState === "hidden") return;
      const w = wsRef.current;
      if (w && (w.readyState === 0 || w.readyState === 1)) return;   // conectando/aberto
      failCountRef.current = 0;
      if (reconnTimerRef.current) { clearTimeout(reconnTimerRef.current); reconnTimerRef.current = null; }
      api.get("/claude/attach-ticket").then(() => open(true), () => open(true));
    };
    document.addEventListener("visibilitychange", wake);
    addEventListener("online", wake);
    addEventListener("pageshow", wake);

    return () => {
      document.removeEventListener("visibilitychange", wake);
      removeEventListener("online", wake);
      removeEventListener("pageshow", wake);
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
    const typed = input.trim();
    if (!typed && !attachments.length) return;
    const text = [...attachments.map((a) => "@" + a.path), addQuoteNote(expandMentions(typed, mentionCatalog))].filter(Boolean).join(" ");
    // /login, /logout, /auth são resolvidos AQUI (o SDK não os conhece) e funcionam mesmo
    // com a sessão caída — que é exatamente quando você precisa deles.
    if (LOCAL_SLASH_RE.test(text)) { setInput(""); setShowAuth(true); return; }
    if (status !== "pronto") return;
    // Agente ocupado: pergunta se a mensagem vai JÁ (absorvida no turno atual) ou para a FILA.
    if (working) { setPendingSend({ text }); return; }
    dispatch(text, false);
  }

  // `queued`: guarda na fila do servidor (só roda quando o turno inteiro terminar).
  // Sem `queued`, vai direto: com turno rodando, o agente lê e incorpora no que está fazendo.
  function dispatch(text, queued) {
    setPendingSend(null);
    if (!send({ type: "prompt", text, queue: !!queued })) { toast.err("Sem conexão"); return false; }
    if (!queued || !working) {
      setItems((prev) => [...prev, { type: "user", text, interjected: working && !queued, ts: Date.now() }]);
      setWorking(true);
    }
    setInput(""); setAttachments([]);
    return true;
  }
  const choosePending = (queued) => { if (pendingSend) dispatch(pendingSend.text, queued); };
  const cancelPending = () => setPendingSend(null);
  const queueRemove = (id) => send({ type: "queue_remove", id });
  const queueSendNow = (id) => send({ type: "queue_send_now", id });
  // Reordena: otimista na tela, o servidor devolve a ordem real (fonte da verdade).
  const queueMove = (id, to) => {
    setQueue((q) => {
      const i = q.findIndex((x) => x.id === id);
      if (i < 0 || to < 0 || to >= q.length || to === i) return q;
      const next = q.slice(); const [it] = next.splice(i, 1); next.splice(to, 0, it);
      return next;
    });
    send({ type: "queue_move", id, to });
  };

  function stop() {
    if (send({ type: "interrupt" })) toast.info("Interrompendo…");
  }

  // `proj` indefinido = continua no projeto atual; "" = aba Claude Code; "<id>" = esse projeto.
  function newSession(proj) {
    const pr = proj === undefined ? projectRef.current : (proj || "");
    routeRequestRef.current++;
    activateSession("", true, pr);
    const h = claudeNewHash(pr);
    if (location.hash !== h) location.hash = h;
  }
  function resumeSession(id, proj) {
    if (!validSessionId(id)) return;
    const pr = proj === undefined ? projectRef.current : (proj || "");
    setShowSessions(false);
    if (location.hash === claudeSessionHash(id, pr)) openRoute();
    else location.hash = claudeSessionHash(id, pr);
  }

  // Ramificar (fork): nova conversa com o histórico até o fim do turno deste prompt; a de
  // origem fica intacta. Histórico relido traz `uuid`; na conversa ao vivo os itens do stream
  // não têm, então vai o texto + qual ocorrência dele (prompts repetidos).
  const forkingRef = useRef(false);
  async function forkFrom(idx) {
    const sid = sessionIdRef.current;
    const it = items[idx];
    if (!sid || !it || it.type !== "user" || forkingRef.current) return;
    const norm = (t) => String(t || "").replace(/\s+/g, " ").trim();
    const occurrence = items.slice(0, idx).filter((x) => x.type === "user" && norm(x.text) === norm(it.text)).length;
    forkingRef.current = true;
    // Abre a aba nova JÁ no clique (antes do await) para o bloqueador de pop-up não barrar;
    // a aba atual segue intacta. Se bloquear, cai para abrir na mesma aba.
    let win = null;
    try { win = window.open("about:blank", "_blank"); } catch (_) { win = null; }
    try {
      const r = await api.post(`/claude/sessions/${encodeURIComponent(sid)}/fork${projQ(projectRef.current)}`,
        it.uuid ? { uuid: it.uuid } : { text: it.text, occurrence });
      const setPre = (id) => { try { localStorage.setItem("cc-fork-prefill", JSON.stringify({ id, text: it.text, t: Date.now() })); } catch (_) {} };
      const go = (hash, fallback) => {
        if (win && !win.closed) { win.location.href = location.origin + location.pathname + hash; win.focus && win.focus(); }
        else fallback();
      };
      if (r && validSessionId(r.id)) { setPre(r.id); toast.ok("Fork aberto em nova aba — prompt no campo"); go(claudeSessionHash(r.id, projectRef.current), () => resumeSession(r.id)); }
      else if (r && r.first) { setPre("new"); toast.ok("1º prompt — nova conversa em nova aba"); go(claudeNewHash(projectRef.current), () => newSession()); }
      else { if (win) win.close(); toast.err("Fork falhou"); }
    } catch (e) {
      if (win && !win.closed) win.close();
      toast.err("Fork falhou: " + ((e && e.payload && (e.payload.detail || e.payload.error)) || (e && e.message) || "erro"));
    } finally { forkingRef.current = false; }
  }

  // Editar prompt: APAGA este prompt e tudo depois dele NESTA conversa; o texto editado é reenviado
  // assim que a conversa (cortada) reconecta. Primeiro prompt = conversa nova com o texto editado.
  const editingRef = useRef(false);
  const autoSendRef = useRef(null);   // {sid, text}: enviado quando a conversa retomada fica "pronto"
  async function editFrom(idx, newText) {
    const sid = sessionIdRef.current;
    const it = items[idx];
    const text = String(newText || "").trim();
    if (!sid || !it || it.type !== "user" || !text || editingRef.current) return false;
    const norm = (t) => String(t || "").replace(/\s+/g, " ").trim();
    const occurrence = items.slice(0, idx).filter((x) => x.type === "user" && norm(x.text) === norm(it.text)).length;
    const ident = it.uuid ? { uuid: it.uuid } : { text: it.text, occurrence };
    editingRef.current = true;
    try {
      const plan = await api.post(`/claude/sessions/${encodeURIComponent(sid)}/rewind${projQ(projectRef.current)}`, { ...ident, dry: true });
      const n = Math.max(0, (plan.removed_prompts || 1) - 1);
      const msg = "Salvar e reenviar APAGA este prompt e tudo que veio depois"
        + (n ? ` (mais ${n} prompt${n > 1 ? "s" : ""} seguinte${n > 1 ? "s" : ""} e as respostas)` : " (a resposta dele)")
        + ".\nUma cópia de segurança fica no servidor. Continuar?";
      if (!window.confirm(msg)) return false;
      const r = await api.post(`/claude/sessions/${encodeURIComponent(sid)}/rewind${projQ(projectRef.current)}`, ident);
      if (r && r.first) { autoSendRef.current = { sid: "", text }; newSession(); }
      else { autoSendRef.current = { sid, text }; activateSession(sid, true); }
      toast.ok("Conversa cortada neste ponto — gerando nova resposta");
      return true;
    } catch (e) {
      toast.err("Editar falhou: " + ((e && e.payload && (e.payload.detail || e.payload.error)) || (e && e.message) || "erro"));
      return false;
    } finally { editingRef.current = false; }
  }
  useEffect(() => {
    const a = autoSendRef.current;
    if (!a || status !== "pronto" || sessionIdRef.current !== a.sid) return;
    autoSendRef.current = null;
    dispatch(addQuoteNote(expandMentions(a.text, mentionCatalog)), false);
  }, [status, sessionId]);

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
    resumeIdRef.current = ""; sessionIdRef.current = ""; projectRef.current = ""; setProject(""); setDockSession("");
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

  function changeNetperms(next) {
    setNetperms(next);                // otimista; confirma em netperms_changed
    send({ type: "set_netperms", perms: npNorm(next) });
  }

  function changeMode(m) {
    setMode(m);                       // otimista; confirma em mode_changed
    send({ type: "set_mode", mode: m });
  }

  // Esforço: o SDK só o aplica no (re)lançamento — vale a partir da próxima sessão/relançamento.
  function changeEffort(v) {
    setEffort(v); effortRef.current = v;
    try { localStorage.setItem("cc-effort", v); } catch (_) {}
    send({ type: "set_effort", effort: v });
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

  // Vários arquivos de uma vez: sobe em sequência (o servidor resolve nomes repetidos sem corrida).
  async function uploadFiles(files) {
    for (const f of files || []) await uploadFile(f);
  }

  async function uploadFile(file) {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const headers = {};
    const a = authToken(); if (a) headers["X-Netops-Session"] = a;
    try {
      const res = await fetch("/api/claude/upload" + projQ(projectRef.current), { method: "POST", headers, body: fd });
      if (!res.ok) { toast.err("Upload falhou (" + res.status + ")"); return; }
      const d = await res.json();
      setAttachments((v) => [...v, { path: d.path, name: d.name }]);
      toast.ok("Anexado: " + d.name);
    } catch (_) { toast.err("Upload falhou"); }
  }

  const badge = { pronto: "ok", conectando: "", reconectando: "warn", desconectado: "warn", desabilitado: "danger", erro: "danger" }[status] || "";
  const disabled = status !== "pronto";
  // "Conversa viva" = ligada e com algo acontecendo (turno rodando ou já há mensagens).
  const hasSession = active && (working || items.length > 0);
  useEffect(() => { if (active && sessionId && validSessionId(sessionId)) setDockSession(sessionId, project); }, [active, sessionId, project]);   // F5 reabre o dock

  return {
    effort, changeEffort, ctxUse, lastUsage,
    queue, pendingSend, choosePending, cancelPending, queueRemove, queueSendNow, queueMove,
    project, status, items, working, mode, netperms, netpermsMax, changeNetperms, model, modelSel, models, sessionId, slash, input, setInput, attachments, setAttachments,
    showSessions, setShowSessions, badge, disabled, hasSession, fileRef,
    prefs, savePrefs, showPrefs, setShowPrefs,
    send, submit, stop, newSession, resumeSession, forkFrom, editFrom, answerPermission, changeMode, changeModel, uploadFile, uploadFiles,
    endSession,
    auth, showAuth, setShowAuth, refreshAuth, relaunch, refreshModels,
    showModelPick, setShowModelPick, modelErr, pickModelAndRelaunch,
    showRateLimit, setShowRateLimit, rateLimitDetail,
    vaultAsk, setVaultAsk,
  };
}

// --------------------------------------------------------------------- visões
// Transcrição rolável (compartilhada). Cada instância faz seu próprio auto-scroll ao fim.
// Botão "Responder" sobre o trecho selecionado numa resposta do Claude: acrescenta a citação (> …)
// ao campo de mensagem SEM enviar. Dá para citar vários trechos em sequência e enviar tudo junto.
function ReplyQuote({ boxRef }) {
  const { setInput } = useClaude();
  const [pos, setPos] = useState(null);   // {x, y, text}
  useEffect(() => {
    const check = () => {
      const sel = window.getSelection && window.getSelection();
      const box = boxRef.current;
      if (!sel || sel.isCollapsed || !box || sel.rangeCount === 0) { setPos(null); return; }
      const r = sel.getRangeAt(0);
      const anc = r.commonAncestorContainer.nodeType === 1 ? r.commonAncestorContainer : r.commonAncestorContainer.parentElement;
      const msg = anc && anc.closest && anc.closest(".cc-msg.assistant");
      if (!msg || !box.contains(msg)) { setPos(null); return; }
      const text = sel.toString().trim();
      if (!text) { setPos(null); return; }
      const rect = r.getBoundingClientRect();
      setPos({ x: Math.min(Math.max(rect.left + rect.width / 2, 50), window.innerWidth - 50), y: Math.max(rect.top - 8, 44), text });
    };
    let t = null;
    const later = () => { clearTimeout(t); t = setTimeout(check, 60); };
    document.addEventListener("selectionchange", later);
    return () => { document.removeEventListener("selectionchange", later); clearTimeout(t); };
  }, []);
  if (!pos) return null;
  const add = () => {
    const quote = pos.text.split("\n").map((l) => (l.trim() ? "> " + l.trim() : ">")).join("\n");
    setInput((cur) => {
      const nums = [...(cur || "").matchAll(/^\*\*\[(\d+)\]\*\*/gm)].map((m) => +m[1]);
      const n = (nums.length ? Math.max(...nums) : 0) + 1;      // próxima numeração, a partir do que já está no campo
      return (cur && cur.trim() ? cur.replace(/\s+$/, "") + "\n\n" : "") + `**[${n}]**\n` + quote + "\n\n";
    });
    const sel = window.getSelection(); if (sel) sel.removeAllRanges();
    setPos(null);
    setTimeout(() => {
      const ta = document.querySelector(".cc-composer textarea");
      if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); ta.scrollTop = ta.scrollHeight; }
    }, 30);
  };
  return html`<button class="cc-reply-quote" style=${`left:${pos.x}px;top:${pos.y}px`}
    onMouseDown=${(e) => e.preventDefault()} onTouchStart=${(e) => e.stopPropagation()}
    onClick=${add} title="Citar este trecho no campo de mensagem (sem enviar)">↩ Responder</button>`;
}

function Transcript() {
  const { items, status, answerPermission, auth, setShowAuth, forkFrom, editFrom, sessionId } = useClaude();
  const scrollRef = useRef(null);
  // Só acompanha o fim se o usuário já estiver perto dele; se rolou para cima, não puxa de volta.
  const stickRef = useRef(true);
  const onScroll = () => { const el = scrollRef.current; if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; };
  useEffect(() => { stickRef.current = true; }, [sessionId]);
  useEffect(() => { const el = scrollRef.current; if (el && stickRef.current) el.scrollTop = el.scrollHeight; }, [items]);
  const loggedOut = auth && auth.available && !auth.loggedIn;
  return html`<div class="cc-transcript" ref=${scrollRef} onScroll=${onScroll}>
    ${loggedOut && html`<${LoginBanner} auth=${auth} onLogin=${() => setShowAuth(true)} />`}
    ${items.length === 0 && status === "pronto" && !loggedOut && html`<div class="cc-hint help">
      Pronto. Peça em linguagem natural, use <code>/comandos</code> ou anexe arquivos.
      Em <b>Plano</b> ele só lê; troque para <b>Perguntar antes</b> p/ aplicar mudanças com confirmação.
    </div>`}
    ${status === "desabilitado" && html`<div class="card cc-off">
      Página Claude Code desabilitada no servidor. Suba com <code>--enable-claude</code> (e sem <code>--read-only</code>).
    </div>`}
    ${groupTools(items).map((g) => g.tools
      ? html`<${ToolGroup} key=${"g" + g.start} tools=${g.tools} />`
      : html`<${Item} key=${g.i} it=${g.it} onPermission=${answerPermission}
      onFork=${sessionId ? () => forkFrom(g.i) : null}
      onEdit=${sessionId && status === "pronto" ? (t) => editFrom(g.i, t) : null} />`)}
    <${ReplyQuote} boxRef=${scrollRef} />
  </div>`;
}


// Miniatura de anexo: imagens do diretório de uploads são buscadas com o header de sessão
// (um <img src> puro não o envia) e exibidas via blob URL; outros arquivos viram um chip.
const UPLOAD_REF_RE = /@(runs\/claude\/uploads\/[A-Za-z0-9._-]+)/g;
const IMG_RE = /\.(png|jpe?g|gif|webp)$/i;
function AttachThumb({ path }) {
  const name = path.split("/").pop();
  const [url, setUrl] = useState("");
  const isImg = IMG_RE.test(name);
  useEffect(() => {
    if (!isImg) return;
    let dead = false, obj = "";
    const headers = {}; const a = authToken(); if (a) headers["X-Netops-Session"] = a;
    fetch("/api/claude/upload/" + encodeURIComponent(name), { headers })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => { if (b && !dead) { obj = URL.createObjectURL(b); setUrl(obj); } })
      .catch(() => {});
    return () => { dead = true; if (obj) URL.revokeObjectURL(obj); };
  }, [path]);
  const [big, setBig] = useState(false);
  useEffect(() => {
    if (!big) return;
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); setBig(false); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [big]);
  if (isImg && url) return html`<img class="cc-thumb" src=${url} alt=${name} title=${name} onClick=${() => setBig(true)} />
    ${big && html`<div class="cc-lightbox" onClick=${() => setBig(false)}>
      <button class="cc-lightbox-x" title="Fechar (Esc)" onClick=${() => setBig(false)}>✕ Fechar</button>
      <img src=${url} alt=${name} onClick=${(e) => e.stopPropagation()} />
    </div>`}`;
  return html`<span class="cc-file-chip" title=${path}>${isImg ? "🖼" : "📎"} ${name}</span>`;
}
// Copia o texto (Markdown) completo da resposta. HTTP puro não tem navigator.clipboard: usa textarea + execCommand.
async function copyReply(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else {
      const t = document.createElement("textarea");
      t.value = text; t.style.cssText = "position:fixed;opacity:0;top:0;left:0";
      document.body.appendChild(t); t.select();
      const ok = document.execCommand("copy"); t.remove();
      if (!ok) throw new Error("copy");
    }
    toast.ok("Resposta copiada");
  } catch (e) { toast.err("Não foi possível copiar a resposta."); }
}
// Botão direito na resposta (sem texto selecionado) abre um menu com "Copiar resposta".
// Com texto selecionado, deixa o menu nativo do navegador (copiar seleção).
function replyContextMenu(e, text) {
  if (!text || !String(text).trim()) return;
  if (String(window.getSelection && window.getSelection()).length) return;
  e.preventDefault();
  document.querySelectorAll(".cc-reply-menu").forEach((n) => n.remove());
  const m = document.createElement("div");
  m.className = "fm-menu cc-reply-menu";
  m.style.left = Math.min(e.clientX, innerWidth - 190) + "px";
  m.style.top = Math.min(e.clientY, innerHeight - 60) + "px";
  const b = document.createElement("button");
  b.textContent = "📋 Copiar resposta";
  b.onclick = () => { m.remove(); copyReply(String(text)); };
  m.appendChild(b);
  document.body.appendChild(m);
  const close = (ev) => { if (ev && ev.type === "keydown" && ev.key !== "Escape") return; m.remove(); ["mousedown", "scroll", "keydown", "blur"].forEach((t) => removeEventListener(t, close, true)); };
  setTimeout(() => ["mousedown", "scroll", "keydown", "blur"].forEach((t) => addEventListener(t, close, true)), 0);
}
// Data/hora discreta no canto da bolha (hoje: só hora; outro dia: dd/mm hh:mm).
function MsgTime({ ts }) {
  if (!ts) return null;
  const d = new Date(ts);
  if (isNaN(d)) return null;
  const hm = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const same = d.toDateString() === new Date().toDateString();
  const label = same ? hm : `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${hm}`;
  return html`<time class="cc-time" title=${d.toLocaleString("pt-BR")}>${label}</time>`;
}
// Mensagem do usuário com citações numeradas (**[n]** + linhas "> …"): cada citação vira um bloco
// clicável que rola até a resposta do Claude de onde o trecho saiu e a destaca.
const QUOTE_RE = /^\*\*\[(\d+)\]\*\*\n((?:>.*(?:\n|$))+)/gm;
const squash = (t) => (t || "").replace(/\s+/g, "");
// Localiza no DOM o trecho citado (ignora diferenças de espaço/quebra) e devolve um Range.
function findQuoteRange(root, quote) {
  const want = squash(quote);
  if (!want) return null;
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = []; let flat = "";
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const t = n.nodeValue;
    for (let i = 0; i < t.length; i++) if (!/\s/.test(t[i])) { nodes.push([n, i]); flat += t[i]; }
  }
  const at = flat.indexOf(want);
  if (at < 0) return null;
  const a = nodes[at], b = nodes[at + want.length - 1];
  const r = document.createRange();
  r.setStart(a[0], a[1]); r.setEnd(b[0], b[1] + 1);
  return r;
}
let hlTimer = null;
function clearQuoteHighlight() {
  clearTimeout(hlTimer);
  if (window.CSS && CSS.highlights) CSS.highlights.delete("cc-quote-hl");
  document.querySelectorAll(".cc-msg.cc-flash").forEach((e) => e.classList.remove("cc-flash"));
}
function showQuoteHighlight(range) {
  clearQuoteHighlight();
  if (window.CSS && CSS.highlights && window.Highlight) CSS.highlights.set("cc-quote-hl", new Highlight(range));
  else { const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range); }   // sem a API: usa a seleção
  const off = () => { clearQuoteHighlight(); document.removeEventListener("mousedown", off, true); };
  setTimeout(() => document.addEventListener("mousedown", off, true), 400);
  hlTimer = setTimeout(() => { clearQuoteHighlight(); document.removeEventListener("mousedown", off, true); }, 12000);
}
function flashEl(el) {
  el.classList.remove("cc-flash"); void el.offsetWidth; el.classList.add("cc-flash");
  setTimeout(() => el.classList.remove("cc-flash"), 2200);
}
function jumpToQuote(el, quote) {
  const root = el.closest(".cc-transcript");
  if (!root) return;
  const want = squash(quote);
  const all = [...root.querySelectorAll(".cc-msg.assistant")].filter((m) => squash(m.textContent).includes(want));
  if (!all.length) { toast("warn", "Não achei o trecho citado nesta conversa"); return; }
  const me = el.closest(".cc-msg");
  const before = all.filter((m) => me && (m.compareDocumentPosition(me) & Node.DOCUMENT_POSITION_FOLLOWING));
  const target = (before.length ? before : all).slice(-1)[0];
  const range = findQuoteRange(target, quote);
  if (range) {
    const host = range.startContainer.parentElement || target;
    host.scrollIntoView({ behavior: "smooth", block: "center" });
    showQuoteHighlight(range);
  } else {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    flashEl(target);
  }
}
// Resposta do Claude: "[n]" que se refere a uma citação numerada da mensagem anterior vira link
// que volta para aquela citação (e a destaca).
function AssistantMsg({ text, ts, role = "claude" }) {
  const ref = useRef(null);
  useEffect(() => {
    const msg = ref.current;
    if (!msg) return;
    let prev = msg.previousElementSibling;
    while (prev && !prev.classList.contains("user")) prev = prev.previousElementSibling;
    const nums = prev ? new Set([...prev.querySelectorAll(".cc-quote b")].map((b) => b.textContent.trim())) : new Set();
    if (!nums.size) return;
    const w = document.createTreeWalker(msg.querySelector(".md") || msg, NodeFilter.SHOW_TEXT);
    const todo = [];
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (n.parentElement.closest("pre,code,a,.cc-qref")) continue;
      if (/\[(\d{1,3})\]/.test(n.nodeValue)) todo.push(n);
    }
    for (const n of todo) {
      const frag = document.createDocumentFragment();
      let last = 0; const v = n.nodeValue; let changed = false;
      for (const m of v.matchAll(/\[(\d{1,3})\]/g)) {
        if (!nums.has(m[1])) continue;
        frag.append(v.slice(last, m.index));
        const a = document.createElement("a");
        a.className = "cc-qref"; a.dataset.n = m[1]; a.textContent = m[0]; a.title = "Ver de onde veio (sua citação " + m[1] + ")";
        frag.append(a); last = m.index + m[0].length; changed = true;
      }
      if (!changed) continue;
      frag.append(v.slice(last));
      n.replaceWith(frag);
    }
  }, [text]);
  const onClick = (e) => {
    const a = e.target.closest && e.target.closest(".cc-qref");
    if (!a) return;
    e.preventDefault();
    let prev = ref.current.previousElementSibling;
    while (prev && !prev.classList.contains("user")) prev = prev.previousElementSibling;
    const q = prev && [...prev.querySelectorAll(".cc-quote")].find((x) => x.querySelector("b").textContent.trim() === a.dataset.n);
    if (!q) return;
    q.scrollIntoView({ behavior: "smooth", block: "center" });
    const span = q.querySelector("span");
    if (span) { const r = document.createRange(); r.selectNodeContents(span); showQuoteHighlight(r); }
    else clearQuoteHighlight();
    flashEl(q);
  };
  return html`<div class="cc-msg assistant" ref=${ref} onClick=${onClick} onContextMenu=${(e) => replyContextMenu(e, text)}><div class="cc-role">${role}</div><${MarkdownView} text=${text} /><${MsgTime} ts=${ts} /></div>`;
}
function QuotedText({ text }) {
  const parts = []; let last = 0, m;
  QUOTE_RE.lastIndex = 0;
  while ((m = QUOTE_RE.exec(text))) {
    if (m.index > last) parts.push({ t: text.slice(last, m.index) });
    const q = m[2].split("\n").filter((l) => l.startsWith(">")).map((l) => l.replace(/^>\s?/, "")).join("\n").trim();
    parts.push({ n: m[1], q });
    last = m.index + m[0].length;
  }
  if (!parts.length) return text;
  if (last < text.length) parts.push({ t: text.slice(last) });
  return parts.map((p) => p.q === undefined ? p.t.replace(/^\n+/, "") : html`<div class="cc-quote" role="button" tabindex="0"
    title="Ir para a resposta citada"
    onClick=${(e) => jumpToQuote(e.currentTarget, p.q)}
    onKeyDown=${(e) => { if (e.key === "Enter") jumpToQuote(e.currentTarget, p.q); }}><b>${p.n}</b><span>${p.q}</span></div>`);
}
function UserMsg({ text: fullText, tag, ts, onFork, onEdit }) {
  const text = stripMentionNote(fullText);   // bloco de IDs das menções "#" só vai ao agente
  const refs = [...text.matchAll(UPLOAD_REF_RE)].map((m) => m[1]);
  const rest = text.replace(UPLOAD_REF_RE, "").replace(/[ \t]{2,}/g, " ").trim();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const startEdit = () => { setDraft(refs.length ? rest : text); setEditing(true); };
  async function save() {
    const t = draft.trim();
    if (!t || busy) return;
    setBusy(true);
    const full = [...refs.map((r) => "@" + r), t].join(" ");   // anexos originais seguem junto
    const ok = await onEdit(full);
    setBusy(false);
    if (ok) setEditing(false);
  }
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); setEditing(false); }
    else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
  };
  return html`<div class="cc-msg user"><div class="cc-role">você${tag && html` · <em>${tag}</em>`}</div>
    ${refs.length > 0 && html`<div class="cc-attach-row user">${refs.map((r) => html`<${AttachThumb} key=${r} path=${r} />`)}</div>`}
    ${editing
      ? html`<div class="cc-edit">
          <textarea class="cc-edit-box" rows=${Math.min(12, Math.max(3, draft.split("\n").length + 1))} value=${draft} autoFocus
            onInput=${(e) => setDraft(e.target.value)} onKeyDown=${onKey} disabled=${busy}></textarea>
          <div class="cc-edit-note">Salvar apaga tudo que veio depois deste prompt e gera uma nova resposta.</div>
          <div class="cc-edit-actions">
            <button class="sm" onClick=${() => setEditing(false)} disabled=${busy}>Cancelar</button>
            <button class="sm primary" onClick=${save} disabled=${busy || !draft.trim()}>${busy ? "Salvando…" : "Salvar e reenviar"}</button>
          </div>
        </div>`
      : (rest || !refs.length) && html`<div class="cc-usertext"><${QuotedText} text=${refs.length ? rest : text} /></div>`}
    <div class="cc-user-foot">
      ${onEdit && !editing && html`<button class="cc-fork" title="Editar: apaga este prompt e tudo depois dele nesta conversa e gera uma nova resposta com o texto editado"
        onClick=${startEdit}>✎ Editar</button>`}
      ${onFork && !editing && html`<button class="cc-fork" title="Ramificar: abre uma NOVA conversa no ponto ANTES deste prompt, com o texto já no campo (a original continua intacta)"
        onClick=${onFork}>⑂ Ramificar daqui</button>`}
      <${MsgTime} ts=${ts} /></div></div>`;
}

// Catálogo de hosts/grupos para as menções "#": uma busca por abertura do menu (TTL curto);
// o envio usa o que já está em cache (sincronamente) para expandir grupos em IDs.
let mentionCatalog = null, mentionLoadedAt = 0, mentionLoading = null;
function loadMentionCatalog(force) {
  if (!force && mentionCatalog && Date.now() - mentionLoadedAt < 30000) return Promise.resolve(mentionCatalog);
  if (!mentionLoading) {
    mentionLoading = api.get("/hosts").then((r) => { mentionCatalog = buildCatalog(r); mentionLoadedAt = Date.now(); return mentionCatalog; })
      .catch(() => mentionCatalog).finally(() => { mentionLoading = null; });
  }
  return mentionLoading;
}

// Caixa de mensagem (compartilhada): textarea que cresce com o conteúdo + barra interna
// com Modo, meta, anexar e enviar/parar. Menu de slash aparece logo acima.
function Composer() {
  const { effort, changeEffort, ctxUse, lastUsage, input, setInput, submit, stop, working, disabled, mode, changeMode, netperms, netpermsMax, changeNetperms, modelSel, models, changeModel, uploadFile, uploadFiles, slash, fileRef, attachments, setAttachments,
    queue, pendingSend, choosePending, cancelPending, queueRemove, queueSendNow, queueMove, sessionId } = useClaude();
  const taRef = useRef(null);
  // Menções "#host:…" / "#group:…": menu junto ao cursor, ↑↓ navega, Enter/Tab escolhe, Esc fecha.
  const [caret, setCaret] = useState(0);
  const [catalog, setCatalog] = useState(mentionCatalog);
  const [mSel, setMSel] = useState(0);
  const [mOff, setMOff] = useState("");                 // token fechado com Esc (reabre ao mudar o texto dele)
  const mTok = findMentionToken(input, Math.min(caret, input.length));
  const mKey = mTok ? `${mTok.start}|${mTok.kind}|${mTok.query}` : "";
  const mItems = mTok && mKey !== mOff && catalog ? searchMentions(catalog, mTok.query, mTok.kind) : [];
  useEffect(() => { if (mTok) loadMentionCatalog(!catalog).then((c) => c && setCatalog(c)); }, [!!mTok]);
  useEffect(() => { setMSel(0); }, [mTok && mTok.query, mTok && mTok.kind]);
  useEffect(() => { if (mOff && mKey !== mOff) setMOff(""); }, [mKey]);   // mudou o token: o Esc anterior não vale mais
  function pickMention(item) {
    const r = applyMention(input, mTok, item);
    setInput(r.text); setCaret(r.caret);
    setTimeout(() => {                                // só reposiciona se ninguém digitou nesse meio-tempo
      const el = taRef.current;
      if (el) { el.focus(); if (el.value === r.text) el.setSelectionRange(r.caret, r.caret); }
    }, 0);
  }
  const syncCaret = (e) => setCaret(e.target.selectionStart);
  // Ditado: a transcrição só preenche o rascunho (acrescenta ao fim); o envio segue manual.
  const dict = useDictation({
    conversationId: sessionId || "new",
    onText: (text) => { setInput((cur) => (cur.trim() ? cur.trimEnd() + " " + text : text)); setTimeout(() => taRef.current && taRef.current.focus(), 0); },
    onError: (msg) => toast.err(msg),
  });
  const mmss = (n) => Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0");
  // textarea que cresce com o conteúdo: começa em 1 linha e sobe até o teto (CSS), aí rola.
  useEffect(() => {
    const el = taRef.current; if (!el) return;
    el.style.height = "auto"; el.style.height = el.scrollHeight + "px";
  }, [input]);

  // Ctrl+V com imagem na área de transferência: sobe como anexo (vira @caminho), igual ao 📎.
  function onPaste(e) {
    const items = (e.clipboardData && e.clipboardData.items) || [];
    const imgs = [];
    for (const it of items) {
      if (it.kind === "file" && it.type.startsWith("image/")) { const f = it.getAsFile(); if (f) imgs.push(f); }
    }
    if (!imgs.length) return;              // texto comum: deixa colar normalmente
    e.preventDefault();
    if (disabled) { return; }
    const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    uploadFiles(imgs.map((f, i) => {
      const ext = (f.type.split("/")[1] || "png").replace("jpeg", "jpg").replace(/[^a-z0-9]/gi, "");
      return new File([f], `colada-${stamp}-${i + 1}.${ext}`, { type: f.type });
    }));
  }

  function onKeyDown(e) {
    if (mItems.length && !e.isComposing) {
      if (e.key === "ArrowDown") { e.preventDefault(); setMSel((mSel + 1) % mItems.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setMSel((mSel - 1 + mItems.length) % mItems.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pickMention(mItems[Math.min(mSel, mItems.length - 1)]); return; }
      if (e.key === "Escape") { e.preventDefault(); setMOff(mKey); return; }
    }
    if (e.key === "Escape" && working) { e.preventDefault(); stop(); return; }
    // Celular/tablet (toque como ponteiro principal): Enter quebra linha, envia só pelo botão ↑.
    // Desktop: Enter envia, Shift+Enter quebra linha.
    const touch = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !touch) { e.preventDefault(); submit(); }
  }

  // sugestões de slash: só quando o texto começa com "/" e ainda não tem espaço.
  // Os comandos locais (/login…) entram na lista mesmo desconectado — vêm da aba, não do init.
  const slashQuery = /^\/(\S*)$/.exec(input);
  const slashMatches = slashQuery
    ? [...LOCAL_SLASH, ...slash.filter((c) => !LOCAL_SLASH.includes(c))]
        .filter((c) => c.startsWith(slashQuery[1])).slice(0, 24)
    : [];

  // A caixa NUNCA trava: desconectado ainda dá p/ digitar /login (é justamente aí que se precisa).
  const isLocal = LOCAL_SLASH_RE.test(input.trim());
  const cantSend = (disabled && !isLocal) || (!input.trim() && !attachments.length);

  return html`<div class="cc-composer-wrap">
    ${queue.length > 0 && html`<${QueueList} queue=${queue} working=${working} disabled=${disabled}
      onRemove=${queueRemove} onSendNow=${queueSendNow} onMove=${queueMove} />`}
    ${pendingSend && html`<${SendChoice} text=${pendingSend.text} onChoose=${choosePending}
      onCancel=${() => { cancelPending(); taRef.current && taRef.current.focus(); }} />`}
    ${slashMatches.length > 0 && html`<div class="cc-slash-menu">
      ${slashMatches.map((c) => html`<button key=${c} class="cc-slash" onClick=${() => setInput("/" + c + " ")}>/${c}</button>`)}
    </div>`}
    ${mItems.length > 0 && html`<div class="cc-mention-menu" role="listbox" aria-label="Hosts e grupos">
      ${mItems.map((m, i) => html`<button key=${m.token} role="option" aria-selected=${i === mSel}
          class=${"cc-mention" + (i === mSel ? " sel" : "")}
          onMouseDown=${(e) => e.preventDefault()} onMouseEnter=${() => setMSel(i)} onClick=${() => pickMention(m)}>
        <span class=${"cc-mention-kind " + m.kind}>${m.kind === "group" ? "group" : "host"}</span>
        <b>${m.label}</b><small>${m.detail}</small>
      </button>`)}
    </div>`}
    <div class="cc-composer">
      ${attachments.length > 0 && html`<div class="cc-attach-row">
        ${attachments.map((a) => html`<div class="cc-attach" key=${a.path}>
          <${AttachThumb} path=${a.path} />
          <button class="cc-attach-x" title="Remover" onClick=${() => setAttachments((v) => v.filter((x) => x.path !== a.path))}>×</button>
        </div>`)}
      </div>`}
      <textarea ref=${taRef} rows="1"
        placeholder=${disabled
          ? "Sem sessão — digite /login para entrar, ou aguarde a reconexão"
          : (window.matchMedia && window.matchMedia("(pointer: coarse)").matches ? "Mensagem (Enter quebra linha · ↑ envia · / comandos · # hosts)" : "Mensagem (Enter envia · Shift+Enter quebra linha · / comandos · # hosts e grupos)")}
        value=${input}
        onInput=${(e) => { setInput(e.target.value); syncCaret(e); }} onKeyDown=${onKeyDown} onKeyUp=${syncCaret} onClick=${syncCaret} onPaste=${onPaste}></textarea>
      <div class="cc-composer-bar">
        <div class="cc-composer-left">
          <input type="file" multiple ref=${fileRef} style="display:none"
            onChange=${(e) => { const fs = Array.from(e.target.files || []); e.target.value = ""; uploadFiles(fs); }} />
          <button class="cc-iconbtn" disabled=${disabled} onClick=${() => fileRef.current && fileRef.current.click()}
            title="Anexar arquivos (vira @caminho; selecione vários) — ou cole uma imagem com Ctrl+V">+</button>
          ${dict.phase === "starting" && html`<span class="cc-dict">Abrindo microfone…</span>`}
          ${dict.phase === "recording" && html`<span class="cc-dict rec"><i class="cc-dict-dot"></i>Gravando ${mmss(dict.elapsed)} / ${mmss(MAX_SECONDS)}
            <button class="sm primary" onClick=${dict.stop}>Parar</button>
            <button class="sm" onClick=${dict.cancel}>Cancelar</button></span>`}
          ${dict.phase === "transcribing" && html`<span class="cc-dict">Transcrevendo áudio…
            <button class="sm" onClick=${dict.cancel}>Cancelar</button></span>`}
          <${CacheClock} usage=${lastUsage} />
          <${ContextRing} ctx=${ctxUse} />
          <${Popover} up=${true} btnClass="cc-pill" title="Modelo e esforço"
            label=${html`${(models.find((m) => m.id === modelSel) || { name: modelSel || "Modelo" }).name}${effort ? html` <em>${EFFORTS.find(([v]) => v === effort)[1]}</em>` : ""}`}>
            ${(close) => html`
              <div class="cc-pop-title">Selecione o modelo</div>
              <div class="cc-pop-scroll">
              ${(modelSel && !models.some((m) => m.id === modelSel) ? [...models, { id: modelSel, name: modelSel }] : models)
                .map((m) => html`<button key=${m.id} class=${"cc-pop-item" + (m.id === modelSel ? " sel" : "")}
                    onClick=${() => { changeModel(m.id); close(); }}>
                  <span><b>${m.name}</b>${m.description && html`<small>${m.description}</small>`}</span>
                  ${m.id === modelSel && html`<i>✓</i>`}
                </button>`)}
              </div>
              <${EffortRow} effort=${effort} changeEffort=${changeEffort} />`}
          <//>
        </div>
        <div class="cc-composer-actions">
          <${Popover} up=${true} align="right" btnClass=${"cc-pill cc-np-pill" + (npFull(netperms) ? "" : " restricted")}
            title="Permissões de rede: o que o agente pode fazer nos equipamentos"
            label=${html`<span class="cc-pill-ico">🔐</span><span class="cc-pill-txt"> Rede: ${npShort(netperms)}</span>`}>
            ${() => html`<${NetPermsPicker} value=${netperms} max=${netpermsMax} onChange=${changeNetperms} />`}
          <//>
          <${Popover} up=${true} align="right" btnClass="cc-pill" disabled=${disabled} title="Modo de permissão do agente"
            label=${html`<span class="cc-pill-ico">${(MODES.find((m) => m.value === mode) || MODES[0]).icon}</span><span class="cc-pill-txt"> ${(MODES.find((m) => m.value === mode) || MODES[0]).short}</span>`}>
            ${(close) => html`
              <div class="cc-pop-title">Modos</div>
              ${MODES.map((m) => html`<button key=${m.value} class=${"cc-pop-item" + (m.value === mode ? " sel" : "")}
                  onClick=${() => { changeMode(m.value); close(); }}>
                <span class="cc-pop-ico">${m.icon}</span>
                <span><b>${m.label}</b><small>${m.desc}</small></span>
                ${m.value === mode && html`<i>✓</i>`}
              </button>`)}
              <${EffortRow} effort=${effort} changeEffort=${changeEffort} />`}
          <//>
          ${dict.configured && dict.phase === "idle" && html`<button class="cc-iconbtn cc-mic" onClick=${dict.start}
            title="Ditar por voz (transcreve para o campo, sem enviar)" aria-label="Ditar por voz">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg></button>`}
          ${working && html`<button class="cc-send stop" onClick=${stop} title="Parar (Esc)" aria-label="Parar"><i class="cc-stopsq"></i></button>`}
          ${(!working || input.trim() || attachments.length > 0) && html`<button class="cc-send" disabled=${cantSend} onClick=${submit}
            title=${working ? "Enviar durante a execução — escolha: agora ou fila (Enter)" : "Enviar (Enter)"}>↑</button>`}
        </div>
      </div>
    </div>
  </div>`;
}

// Escolha ao enviar com o agente ocupado. Enter/A = agora · F = fila · Esc = cancelar.
function SendChoice({ text, onChoose, onCancel }) {
  // Foco no commit (ref callback), não num useEffect pós-paint: senão a tecla digitada logo
  // após o Enter ainda cai no textarea (corrida pega pelo teste de navegador).
  const focused = useRef(false);
  const nowRef = (el) => { if (el && !focused.current) { focused.current = true; el.focus(); } };
  function onKey(e) {
    const k = e.key.toLowerCase();
    if (k === "escape") { e.preventDefault(); e.stopPropagation(); onCancel(); }
    else if (k === "a") { e.preventDefault(); onChoose(false); }
    else if (k === "f") { e.preventDefault(); onChoose(true); }
  }
  const preview = text.length > 140 ? text.slice(0, 140) + "…" : text;
  return html`<div class="cc-sendchoice" role="dialog" aria-label="Como enviar a mensagem" onKeyDown=${onKey}>
    <div class="cc-sendchoice-q">O agente está trabalhando. Como enviar esta mensagem?</div>
    <div class="cc-sendchoice-text">${preview}</div>
    <div class="cc-sendchoice-opts">
      <button ref=${nowRef} class="sm primary" onClick=${() => onChoose(false)}
        title="O agente lê e incorpora no que está fazendo agora (atalho: A)"><b>Enviar agora</b><small>incorpora na tarefa atual</small></button>
      <button class="sm" onClick=${() => onChoose(true)}
        title="Só executa depois que a tarefa atual terminar por completo (atalho: F)"><b>Colocar na fila</b><small>roda quando a tarefa terminar</small></button>
      <button class="sm ghost" onClick=${onCancel} title="Voltar a editar (Esc)">Cancelar</button>
    </div>
  </div>`;
}

// Mensagens na fila do servidor: rodam uma por vez, cada uma quando o turno anterior termina.
// Reordenar = arrastar pela alça ⠿ (Pointer Events: mouse E toque — o DnD nativo do HTML não
// funciona em tela de toque). A lista reordena AO VIVO durante o arraste e só manda
// `queue_move` ao soltar. Com a alça focada, ↑/↓ do teclado movem o item (acessibilidade).
function QueueList({ queue, working, disabled, onRemove, onSendNow, onMove }) {
  const listRef = useRef(null);
  const [drag, setDrag] = useState(null);          // {id, items, from} durante o arraste
  const dragRef = useRef(null); dragRef.current = drag;
  const focusId = useRef(null);                     // devolve o foco à alça após mover pelo teclado

  // Durante o arraste: escuta na janela (a linha muda de lugar no DOM e perderia o pointer capture).
  useEffect(() => {
    if (!drag) return;
    const move = (e) => {
      const d = dragRef.current; if (!d || !listRef.current) return;
      e.preventDefault();
      // Posição alvo = quantas OUTRAS linhas têm o meio acima do ponteiro (estável: não depende
      // da linha arrastada, que já está se mexendo).
      let to = 0;
      for (const row of listRef.current.querySelectorAll("[data-qid]")) {
        if (row.dataset.qid === d.id) continue;
        const r = row.getBoundingClientRect();
        if (e.clientY > r.top + r.height / 2) to++;
      }
      const cur = d.items.findIndex((x) => x.id === d.id);
      if (to === cur) return;
      const items = d.items.filter((x) => x.id !== d.id);
      items.splice(to, 0, d.items[cur]);
      setDrag({ ...d, items });
    };
    const up = () => {
      const d = dragRef.current; setDrag(null);
      if (!d) return;
      const to = d.items.findIndex((x) => x.id === d.id);
      if (to !== d.from && to >= 0) onMove(d.id, to);
    };
    const cancel = (e) => { if (e.key === "Escape") { e.preventDefault(); setDrag(null); } };
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    window.addEventListener("keydown", cancel, true);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      window.removeEventListener("keydown", cancel, true);
    };
  }, [!!drag]);

  useEffect(() => {
    if (!focusId.current || !listRef.current) return;
    const h = listRef.current.querySelector(`[data-qid="${focusId.current}"] .cc-queue-grip`);
    focusId.current = null;   // uma vez só (o reordenamento otimista já renderizou a nova posição)
    if (h && document.activeElement !== h) h.focus();
  });

  function startDrag(e, q, i) {
    if (disabled || queue.length < 2 || (e.button != null && e.button !== 0)) return;
    e.preventDefault();
    focusId.current = null;
    setDrag({ id: q.id, from: i, items: queue.slice() });
  }
  function onGripKey(e, q, i) {
    const to = e.key === "ArrowUp" ? i - 1 : e.key === "ArrowDown" ? i + 1 : null;
    if (to === null) return;
    e.preventDefault();
    if (to < 0 || to >= queue.length) return;
    focusId.current = q.id;
    onMove(q.id, to);
  }

  // Durante o arraste mostra a ordem provisória (sem perder itens que o servidor mudou no meio).
  const shown = drag
    ? [...drag.items.filter((x) => queue.some((q) => q.id === x.id)), ...queue.filter((q) => !drag.items.some((x) => x.id === q.id))]
    : queue;
  return html`<div class=${"cc-queue" + (drag ? " dragging" : "")} ref=${listRef}>
    <div class="cc-queue-head">Na fila (${queue.length}) — ${working ? "roda quando a tarefa atual terminar" : "aguardando: ⚡ envia, ou roda no fim da próxima tarefa"}</div>
    ${shown.map((q, i) => html`<div class=${"cc-queue-item" + (drag && drag.id === q.id ? " drag" : "")} key=${q.id} data-qid=${q.id}>
      ${queue.length > 1 && html`<button class="cc-queue-grip" disabled=${disabled}
        title="Arraste para reordenar (ou ↑/↓ com a alça focada)" aria-label=${"Reordenar: posição " + (i + 1) + " de " + shown.length}
        onPointerDown=${(e) => startDrag(e, q, i)} onKeyDown=${(e) => onGripKey(e, q, i)}>⠿</button>`}
      <span class="cc-queue-n">${i + 1}</span>
      <span class="cc-queue-text" title=${q.text}>${q.text}</span>
      <button class="cc-iconbtn" disabled=${disabled} title="Enviar agora (o agente incorpora na tarefa atual)" onClick=${() => onSendNow(q.id)}>⚡</button>
      <button class="cc-iconbtn" disabled=${disabled} title="Tirar da fila" onClick=${() => onRemove(q.id)}>×</button>
    </div>`)}
  </div>`;
}

const EFFORTS = [["low", "baixo"], ["medium", "médio"], ["high", "alto"], ["xhigh", "extra"], ["max", "máx"]];
const fmtK = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n));

// Popover simples (abre p/ cima, fecha ao clicar fora). `children` é função (close) => conteúdo.
function Popover({ label, children, btnClass, title, up, align, disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const off = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", off); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  const kids = Array.isArray(children) ? children[0] : children;
  return html`<span class="cc-popwrap" ref=${ref}>
    <button class=${btnClass} title=${title} disabled=${disabled} onClick=${() => setOpen(!open)}>${label}</button>
    ${open && html`<div class=${"cc-pop" + (align === "right" ? " right" : "")}>${kids(() => setOpen(false))}</div>`}
  </span>`;
}

// Linha "Esforço" com trilho de pontos (vazio = padrão do agente, mostrado em "médio" apagado).
function EffortRow({ effort, changeEffort }) {
  const cur = EFFORTS.find(([v]) => v === effort);
  return html`<div class="cc-pop-sep"></div>
    <div class="cc-effortrow" title="Vale a partir da próxima sessão/relançamento">
      <span>Esforço${cur ? html` <em>(${cur[1]})</em>` : html` <em>(padrão)</em>`}</span>
      <span class="cc-dots">
        ${EFFORTS.map(([v, l], i) => html`<button key=${v} class=${"cc-dot" + (v === effort ? " on" : "")}
          title=${l} onClick=${() => changeEffort(v)}></button>`)}
      </span>
    </div>`;
}

// Bolinha da janela de contexto: preenche conforme o uso; tooltip com o percentual.
function ContextRing({ ctx }) {
  if (!ctx || typeof ctx.percentage !== "number") return null;
  const pct = Math.min(100, Math.max(0, ctx.percentage)), r = 7, c = 2 * Math.PI * r;
  return html`<span class=${"cc-ctxring" + (pct >= 85 ? " warn" : "")}
      title=${`Janela de contexto: ${pct.toFixed(1)}% usado · ${fmtK(ctx.total)} / ${fmtK(ctx.max)} tokens`}>
    <svg width="18" height="18" viewBox="0 0 18 18">
      <circle cx="9" cy="9" r=${r} fill="none" stroke="currentColor" stroke-opacity=".25" stroke-width="2.5" />
      <circle cx="9" cy="9" r=${r} fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
        stroke-dasharray=${c} stroke-dashoffset=${c * (1 - pct / 100)} transform="rotate(-90 9 9)" />
    </svg>
  </span>`;
}

// Relógio do cache de prompt (ícone + tempo restante). TTL: 5 min (1 h se houve escrita ephemeral_1h);
// reinicia a cada requisição — contamos do fim do último turno.
function CacheClock({ usage }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  if (!usage || !usage._at || ((usage.cache_read_input_tokens || 0) + (usage.cache_creation_input_tokens || 0)) === 0) return null;
  const ttl = ((usage.cache_creation || {}).ephemeral_1h_input_tokens || 0) > 0 ? 3600 : 300;
  const n = Math.max(0, Math.ceil(ttl - (now - usage._at) / 1000));
  const txt = n >= 3600 ? "1h" : n >= 120 ? Math.ceil(n / 60) + "m" : n + "s";
  const tip = n > 0 ? `Cache de prompt ativo — cerca de ${Math.ceil(n / 60)} min restantes` : "Cache de prompt expirado — a próxima resposta relê o contexto inteiro (mais lenta e cara)";
  return html`<span class=${"cc-cache" + (n === 0 ? " off" : "")} title=${tip}>
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6.2"/><path d="M8 4.5V8l2.3 1.5" stroke-linecap="round"/></svg>
    ${n > 0 ? txt : "exp."}</span>`;
}

// Página cheia; seleção da sessão é controlada pelo fragmento da URL no provider.
export function ClaudeSessionTitle() {
  const s = useClaude();
  const [title, setTitle] = useState("");
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!s.sessionId) { setTitle(""); setDone(false); return; }
    let dead = false;
    api.get(s.project ? `/projects/${encodeURIComponent(s.project)}/sessions` : "/claude/sessions").then((d) => {
      const f = (d.sessions || []).find((x) => x.id === s.sessionId);
      if (!dead) { setTitle(f && f.title ? f.title : ""); setDone(!!(f && f.completed)); }
    }).catch(() => {});
    return () => { dead = true; };
  }, [s.sessionId, s.working, s.project]);
  useEffect(() => { if (s.working) setDone(false); }, [s.working]);   // novo pedido reabre a sessão (o servidor também desmarca)
  async function toggle(e) {
    const v = e.target.checked;
    setDone(v);
    try { await api.put(`/claude/sessions/${encodeURIComponent(s.sessionId)}/completed${projQ(s.project)}`, { completed: v }); }
    catch (_) { setDone(!v); toast.err("Falha ao salvar a marca de concluída"); }
  }
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  function startEdit() { if (!validSessionId(s.sessionId) || !title) return; setDraft(title); setEditing(true); }
  async function commit() {
    const v = draft.trim();
    setEditing(false);
    if (!v || v === title) return;
    try { await api.put(`/claude/sessions/${encodeURIComponent(s.sessionId)}/title${projQ(s.project)}`, { title: v }); setTitle(v.slice(0, 80)); toast.ok("Sessão renomeada"); }
    catch (_) { toast.err("Falha ao renomear a sessão"); }
  }
  return html`${validSessionId(s.sessionId) && html`<label class="cc-topbar-chk"
      title=${done ? "Sessão concluída por completo (clique para desmarcar)" : "Marcar sessão como concluída por completo"}>
      <input type="checkbox" aria-label="Sessão concluída por completo" checked=${done} onChange=${toggle} />
    </label>`}${editing
      ? html`<input class="cc-topbar-title-edit" value=${draft} autoFocus maxlength="120" aria-label="Renomear sessão"
          onInput=${(e) => setDraft(e.target.value)} onBlur=${commit}
          onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); else if (e.key === "Escape") { setEditing(false); } }} />`
      : title && html`<span class="cc-topbar-title" title=${title + " — duplo clique para renomear"} onDblClick=${startEdit}>${title}</span><button class="sm cc-sess-ib" style="margin-left:4px" title="Renomear sessão (o nome fica fixo)" aria-label="Renomear sessão" onClick=${startEdit}>✎</button>`}`;
}

// Bolinha de status sempre visível na barra do topo (no celular o resto vai p/ a folha "⋯").
// Bolinha de conexão com o agente: verde = conectado (pronto), amarela piscando = conectando,
// vermelha = desconectado/erro. O texto fica no tooltip (e para leitor de tela).
const STATUS_TIP = { pronto: "Agente conectado", conectando: "Conectando ao agente…", reconectando: "Reconectando ao agente…",
  desconectado: "Agente desconectado — tentando reconectar", desabilitado: "Aba Claude desabilitada", erro: "Erro na conexão com o agente" };
function StatusDot({ cls = "" }) {
  const s = useClaude();
  const kind = s.status === "pronto" ? "ok" : (s.status === "conectando" || s.status === "reconectando") ? "wait" : "danger";
  const tip = STATUS_TIP[s.status] || s.status;
  return html`<span class=${"cc-conn " + kind + " " + cls} title=${tip} role="status" aria-label=${tip}></span>`;
}
export function ClaudeStatusDot() { return html`<${StatusDot} cls="mob-only-dot" />`; }

function ProjectFilesToggle({ project }) {
  const [open, setOpen] = useProjectFilesOpen(project);
  return html`<button class=${"sm needs-projects-files" + (open ? " primary" : "")} aria-pressed=${open}
    onClick=${() => setOpen(!open)} title=${open ? "Fechar os arquivos do projeto" : "Ver os arquivos do projeto ao lado do chat"}>📁 Arquivos</button>`;
}

export function ClaudeTopbarControls() {
  const s = useClaude();
  // Ordem (padrão de mercado): ação primária → navegação → estado → configurações.
  // O mesmo DOM alimenta o desktop (barra) e o celular (folha "⋯").
  return html`
    <button class="sm primary" onClick=${(e) => { if (!openInNewWindow(e, claudeNewHash(s.project))) s.newSession(); }}
      onAuxClick=${(e) => openInNewWindow(e, claudeNewHash(s.project))} onMouseDown=${noAutoscroll}
      title="Encerra esta sessão e abre uma nova (Ctrl+clique abre em nova janela)">＋ Nova sessão</button>
    <button class="sm cc-sessbtn" onClick=${() => s.setShowSessions(true)} title="Ver e retomar sessões anteriores">Sessões</button>
    ${s.project && html`<${ProjectFilesToggle} project=${s.project} />`}
    <${StatusDot} cls="desk-only" />
    <div class="keep-open"><${VaultBanner} compact=${true} /></div>
    ${s.auth && s.auth.available && !s.auth.loggedIn && html`<button class="sm danger" onClick=${() => s.setShowAuth(true)}
      title="O agente está deslogado — clique para entrar">entrar (/login)</button>`}
    <button class="sm icon-btn" onClick=${() => s.setShowPrefs(true)} aria-label="Configurações"
      title="Configurações: conta do agente, modelo, modo de permissão e ditado">⚙<span class="mob-label">Configurações</span></button>`;
}

// Painel de arquivos ao lado do chat de um Projeto: FECHADO por padrão, abre pelo botão 📁 da barra.
// Estado (aberto + pasta) por projeto em localStorage: é estado de visualização, como o dock — a URL
// da conversa (#projects/<id>/<uuid>) não muda. Página cheia com URL própria: #projects/<id>/files.
const PJF_KEY = (p) => "netops_pjfiles_" + p;
function pjFilesGet(p) { try { return JSON.parse(localStorage.getItem(PJF_KEY(p)) || "{}"); } catch (_) { return {}; } }
function pjFilesSet(p, patch) {
  try { localStorage.setItem(PJF_KEY(p), JSON.stringify({ ...pjFilesGet(p), ...patch })); } catch (_) {}
  dispatchEvent(new CustomEvent("netops:pjfiles", { detail: p }));
}
export function useProjectFilesOpen(project) {
  const [open, setOpen] = useState(() => !!(project && pjFilesGet(project).open));
  useEffect(() => {
    setOpen(!!(project && pjFilesGet(project).open));
    const on = (e) => { if (e.detail === project) setOpen(!!pjFilesGet(project).open); };
    addEventListener("netops:pjfiles", on);
    return () => removeEventListener("netops:pjfiles", on);
  }, [project]);
  return [open, (v) => project && pjFilesSet(project, { open: !!v })];
}

function ProjectFilesPanel({ project }) {
  const [root, setRoot] = useState(null);
  const [err, setErr] = useState("");
  const [st, setSt] = useState(() => ({ path: pjFilesGet(project).path || "", q: "", sort: "", hidden: true, open: "" }));
  const [, setOpen] = useProjectFilesOpen(project);
  useEffect(() => {
    setErr(""); setRoot(null);
    api.get(`/files/info?src=${encodeURIComponent("project:" + project)}`)
      .then((i) => { setRoot(i.root); setSt((s) => ({ ...s, path: s.path || i.root })); })
      .catch((e) => setErr((e && e.payload && (e.payload.detail || e.payload.error)) || e.message || String(e)));
  }, [project]);
  useEffect(() => { if (st.path) pjFilesSet(project, { path: st.path }); }, [st.path]);
  const setState = (patch) => setSt((s) => ({ ...s, ...patch }));
  return html`<aside class="cc-files" aria-label="Arquivos do projeto">
    <div class="cc-files-head">
      <b>📁 Arquivos do projeto</b><span class="spacer"></span>
      <a class="sm btn" href=${"#projects/" + project + "/files"} title="Abrir em tela cheia">⤢</a>
      <button class="sm" onClick=${() => setOpen(false)} title="Fechar painel" aria-label="Fechar painel de arquivos">✕</button>
    </div>
    ${err ? html`<div class="fm-msg-box err">${err}</div>` : !root ? html`<div class="fm-msg-box">Abrindo…</div>`
      : html`<${FileBrowser} src=${"project:" + project} home=${root} state=${st} setState=${setState} compact />`}
  </aside>`;
}

export function ClaudeCodePage() {
  const s = useClaude();
  const [filesOpen] = useProjectFilesOpen(s.project);
  const showFiles = !!s.project && filesOpen && can("projects.files");
  return html`<div class=${"cc-split" + (showFiles ? " with-files" : "")}><div class="claude-page">
    <${Transcript} />
    <${Composer} />
    ${s.showSessions && html`<${SessionsModal} currentId=${s.sessionId} project=${s.project}
      onClose=${() => s.setShowSessions(false)} onResume=${(id) => s.resumeSession(id)} />`}
    ${s.showAuth && html`<${LoginModal} auth=${s.auth} onClose=${() => s.setShowAuth(false)}
      onChanged=${s.refreshAuth} onRelaunch=${s.relaunch} onVerifyModels=${s.refreshModels} />`}
    ${s.showModelPick && html`<${ModelPickModal} detail=${s.modelErr} current=${s.modelSel} models=${s.models}
      onClose=${() => s.setShowModelPick(false)} onPick=${s.pickModelAndRelaunch} />`}
    ${s.showRateLimit && html`<${RateLimitModal} detail=${s.rateLimitDetail}
      onClose=${() => s.setShowRateLimit(false)} />`}
    ${s.showPrefs && html`<${PrefsModal} prefs=${s.prefs} models=${s.models} onSave=${s.savePrefs}
      auth=${s.auth} onAccount=${() => { s.setShowPrefs(false); s.setShowAuth(true); }}
      onClose=${() => s.setShowPrefs(false)} />`}
  </div>${showFiles && html`<${ProjectFilesPanel} key=${s.project} project=${s.project} />`}</div>`;
}

// Padrões p/ conversas NOVAS. Conversas existentes sempre voltam no último modelo/modo usados.
function PrefsModal({ prefs, models, onSave, onClose, auth, onAccount }) {
  const [model, setM] = useState(prefs.default_model || "");
  const [mode, setMd] = useState(prefs.default_mode || "default");
  const [np, setNp] = useState(npNorm(prefs.default_netperms));
  async function save() {
    try { await onSave({ default_model: model, default_mode: mode, default_netperms: np }); toast.ok("Padrões salvos"); onClose(); }
    catch (_) { toast.err("Falha ao salvar"); }
  }
  return html`<${Modal} title="Configurações" onClose=${onClose}>
    ${auth && auth.available && html`<div class="cc-prefs-account">
      <h4>Conta do agente (Claude)</h4>
      <div class="cc-prefs-account-row">
        <span>${auth.loggedIn ? html`👤 <b>${auth.email || auth.authMethod || "conectado"}</b>` : html`<span class="err">Deslogado</span>`}</span>
        <span style="flex:1"></span>
        <button class=${"sm " + (auth.loggedIn ? "" : "primary")} onClick=${onAccount}>${auth.loggedIn ? "Gerenciar conta" : "Entrar (/login)"}</button>
      </div>
    </div>`}
    <h4>Padrões para novas conversas</h4>
    <${Field} label="Modelo padrão">
      <select value=${model} onChange=${(e) => setM(e.target.value)}>
        <option value="">Automático (Sonnet mais recente)</option>
        ${models.map((m) => html`<option key=${m.id} value=${m.id}>${m.name}</option>`)}
      </select><//>
    <${Field} label="Modo de permissão padrão"
      hint="Vale só para conversas novas. Ao reabrir uma conversa, ela volta no último modelo e modo usados nela.">
      <select value=${mode} onChange=${(e) => setMd(e.target.value)}>
        ${MODES.map((m) => html`<option key=${m.value} value=${m.value}>${m.label}</option>`)}
      </select><//>
    <${Field} label="Permissões nos equipamentos"
      hint="Para conversas novas. Desmarcado: pede aprovação.">
      <${NetPermsPicker} value=${np} onChange=${setNp} compact=${true} /><//>
    <div class="modal-actions">
      <button onClick=${onClose}>Cancelar</button>
      <button class="primary" onClick=${save}>Salvar</button>
    </div>
    <${AudioSettings} />
  <//>`;
}

// Configurações → Transcrição de áudio (Cloudflare Workers AI). O token nunca volta do servidor.
const CF_TOKEN_URL = "https://dash.cloudflare.com/?to=/:account/api-tokens&permissionGroupKeys=%5B%7B%22key%22%3A%22a92d2450e05d4e7bb7d0a64968f83d11%22%2C%22type%22%3A%22read%22%7D%2C%7B%22key%22%3A%22bacc64e0f6c34fc0883a1223f938a104%22%2C%22type%22%3A%22edit%22%7D%5D&name=Workers%20AI%20Transcricao";
const CF_ID_URL = "https://developers.cloudflare.com/workers-ai/get-started/rest-api/#1-get-api-token-and-account-id";
function AudioSettings() {
  const [cfg, setCfg] = useState(null);
  const [aid, setAid] = useState("");
  const [tok, setTok] = useState("");
  const [busy, setBusy] = useState(false);
  const hdr = () => { const h = { "Content-Type": "application/json" }; const a = authToken(); if (a) h["X-Netops-Session"] = a; return h; };
  async function call(method, path, body) {
    const r = await fetch("/api/audio/" + path, { method, headers: hdr(), body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Falha (" + r.status + ")");
    return d;
  }
  const [choices, setChoices] = useState(null);   // contas a escolher quando o token enxerga várias
  const apply = (d) => { setChoices(null); setCfg(d); setAid(d.account_id || ""); setTok(""); window.dispatchEvent(new Event("netops-audio-config")); };
  useEffect(() => { call("GET", "config").then((d) => { setCfg(d); setAid(d.account_id || ""); }).catch(() => setCfg({})); }, []);
  async function run(fn, okMsg) {
    setBusy(true);
    try { await fn(); if (okMsg) toast.ok(okMsg); } catch (e) { toast.err(e.message); } finally { setBusy(false); }
  }
  const save = () => run(async () => {
    // token novo sem escolha de conta = redescobre a conta pelo token (não reenvia o ID salvo, que pode ser de outra conta)
    const d = await call("PUT", "config", { account_id: tok && !choices ? "" : aid, token: tok });
    if (d.needs_account) { setChoices(d.accounts); setAid(d.accounts[0].id); toast.ok("Escolha a conta e salve de novo"); return; }
    apply(d);
  }, "");
  const remove = () => run(async () => apply(await call("DELETE", "config")), "Configuração removida");
  const test = () => run(() => call("POST", "test"), "Token ativo nesta conta");
  return html`<div class="cc-audio-cfg">
    <h4>Transcrição de áudio (ditado)</h4>
    <${Field} label="Cloudflare API Token"
      hint=${cfg && cfg.has_token ? "Token configurado. Deixe vazio para manter, ou cole outro para substituir." : "Só o token: o Account ID é descoberto sozinho. Permissões: Workers AI Read e Edit."}>
      <input type="password" autocomplete="off" value=${tok} onInput=${(e) => setTok(e.target.value)}
        placeholder=${cfg && cfg.has_token ? "Token configurado" : "Cole o token"} /><//>
    ${choices && html`<${Field} label="Conta" hint="Este token enxerga mais de uma conta.">
      <select value=${aid} onChange=${(e) => setAid(e.target.value)}>
        ${choices.map((c) => html`<option key=${c.id} value=${c.id}>${c.name || c.id}</option>`)}
      </select><//>`}
    ${cfg && cfg.account_id && !choices && html`<div class="help">Conta: <code class="mono">${cfg.account_id}</code></div>`}
    <div class="modal-actions" style="justify-content:flex-start;flex-wrap:wrap">
      <a class="btn sm" href=${CF_TOKEN_URL} target="_blank" rel="noopener noreferrer">Criar token na Cloudflare</a>
      <button class="sm primary" disabled=${busy} onClick=${save}>Salvar</button>
      <button class="sm" disabled=${busy || !(cfg && cfg.configured)} onClick=${test}>Testar token</button>
      <button class="sm" disabled=${busy || !(cfg && cfg.has_token)} onClick=${remove}>Remover</button>
    </div>
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
  const [checkingModels, setCheckingModels] = useState(false);
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

  // Redescobre o catálogo do CLI sem enviar prompt ao modelo.
  async function verifyModels() {
    if (checkingModels) return;
    setCheckingModels(true);
    try {
      const d = onVerifyModels && (await onVerifyModels());
      toast.ok("Modelos atualizados: " + ((d && d.models && d.models.length) || 0));
    } catch (_) {
      toast.err("Falha ao verificar modelos");
    } finally {
      setCheckingModels(false);
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
      <div class="modal-actions">
        ${cur.loggedIn && html`<button class="sm" onClick=${verifyModels} disabled=${checkingModels}
          title="Relê o catálogo do Claude Code instalado, sem enviar mensagem">${checkingModels ? "Verificando…" : "Verificar modelos"}</button>`}
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

// Limite exige evidência explícita do SDK/API. Erro genérico de modelo permite troca.
function RateLimitModal({ detail, onClose }) {
  return html`<${Modal} title="Limite de uso atingido (rate limit)" onClose=${onClose}>
    <div class="cc-model-pick">
      <div class="card cc-model-warn">
        O serviço informou um <b>limite temporário de uso</b> para esta solicitação.
        Aguarde antes de tentar novamente.
      </div>
      <p class="help">Consulte o detalhe abaixo para orientações de liberação.
        O erro não comprova bloqueio dos demais modelos.</p>
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
      <${StatusDot} />
      <b>Claude Code</b>
      ${s.working && html`<span class="chat-dock-live">● ao vivo</span>`}
      <span class="spacer"></span>
      <a class="sm dock-btn" href=${claudeSessionHash(s.sessionId, s.project)} title="Abrir em tela cheia">⤢</a>
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
function SessionsModal({ currentId, onClose, onResume, project = "" }) {
  return html`<${Modal} title="Sessões anteriores" onClose=${onClose} wide=${true}>
    <${SessionsList} currentId=${currentId} project=${project} onResume=${onResume} />
  <//>`;
}

// Lista de sessões de uma pasta: a do NetOps (project vazio) ou a de um Projeto. Usada no modal
// "Sessões" do chat e na página do projeto (#projects/<id>), com busca, concluída, renomear e excluir.
export function SessionsList({ currentId = "", project = "", onResume, q: qProp, onQ }) {
  const [list, setList] = useState(null);
  const [busy, setBusy] = useState(false);
  const [qLocal, setQLocal] = useState("");
  const q = qProp !== undefined ? qProp : qLocal;           // controlado (URL ?q=) ou local
  const setQ = onQ || setQLocal;
  const base = project ? `/projects/${encodeURIComponent(project)}/sessions` : "/claude/sessions";
  // filtro "só pendentes" (não concluídas); lembrado entre aberturas do modal
  const [onlyPending, setOnlyPending] = useState(() => { try { return localStorage.getItem("netops.cc.sessOnlyPending") === "1"; } catch (_) { return false; } });
  const setPending = (v) => { setOnlyPending(v); try { localStorage.setItem("netops.cc.sessOnlyPending", v ? "1" : "0"); } catch (_) {} };

  const load = (query, silent) => {
    const term = (query || "").trim();
    if (!term) {
      if (!silent) setList(null);
      api.get(base).then((d) => setList(d.sessions || [])).catch(() => setList([]));
    } else {
      api.get(base + "/search?q=" + encodeURIComponent(term))
        .then((d) => setList(d.sessions || [])).catch(() => setList([]));
    }
  };
  useEffect(() => { load(q); }, [project]);
  // debounce: busca por título + conteúdo da conversa enquanto digita
  useEffect(() => { const h = setTimeout(() => load(q), 250); return () => clearTimeout(h); }, [q]);
  // atualiza o status (em andamento × finalizada) enquanto o modal está aberto
  useEffect(() => { const h = setInterval(() => load(q, true), 4000); return () => clearInterval(h); }, [q]);

  async function del(id, e) {
    e.stopPropagation();
    setBusy(true);
    try { await api.del(`/claude/sessions/${encodeURIComponent(id)}${projQ(project)}`); forgetClaudeSession(id); load(q); }
    catch (_) { toast.err("Falha ao excluir"); }
    finally { setBusy(false); }
  }

  // checkbox manual "concluída por completo" (persiste no servidor); atualiza a lista na hora
  async function toggleDone(id, completed) {
    setList((cur) => (cur || []).map((x) => (x.id === id ? { ...x, completed } : x)));
    try { await api.put(`/claude/sessions/${encodeURIComponent(id)}/completed${projQ(project)}`, { completed }); }
    catch (_) {
      toast.err("Falha ao salvar a marca de concluída");
      setList((cur) => (cur || []).map((x) => (x.id === id ? { ...x, completed: !completed } : x)));
    }
  }

  const [menu, setMenu] = useState(null);       // {x, y, s}
  const [renaming, setRenaming] = useState(null); // {id, draft}
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    addEventListener("click", close); addEventListener("scroll", close, true);
    return () => { removeEventListener("click", close); removeEventListener("scroll", close, true); };
  }, [menu]);
  async function commitRename() {
    const r = renaming; setRenaming(null);
    if (!r) return;
    const v = r.draft.trim();
    const cur = (list || []).find((x) => x.id === r.id);
    if (!v || (cur && v === cur.title)) return;
    try {
      await api.put(`/claude/sessions/${encodeURIComponent(r.id)}/title${projQ(project)}`, { title: v });
      setList((l) => (l || []).map((x) => (x.id === r.id ? { ...x, title: v.slice(0, 80) } : x)));
      toast.ok("Sessão renomeada");
    } catch (_) { toast.err("Falha ao renomear a sessão"); }
  }

  const term = q.trim();
  const shown = list && onlyPending ? list.filter((x) => !x.completed) : list;
  return html`<div class="cc-sess-wrap">
    <input class="cc-sess-search" type="search" value=${q} autoFocus
      placeholder="Buscar por título ou conteúdo da conversa…"
      onInput=${(e) => setQ(e.target.value)} />
    <label class="cc-sess-filter help" style="display:flex;gap:6px;align-items:center;margin:6px 0">
      <input type="checkbox" checked=${onlyPending} onChange=${(e) => setPending(e.target.checked)} />
      Mostrar somente as sessões pendentes (não concluídas)
    </label>
    ${shown == null
      ? html`<div class="help">Carregando…</div>`
      : shown.length === 0
      ? html`<div class="help">${onlyPending ? "Nenhuma sessão pendente." : term ? "Nenhuma sessão casa com a busca." : "Nenhuma sessão neste projeto ainda."}</div>`
      : html`<div class="cc-sess-list">
        ${shown.map((s) => html`<div key=${s.id} class=${"cc-sess" + (s.id === currentId ? " atual" : "") + (s.completed ? " concluida" : "")}
            onClick=${(e) => { if (renaming && renaming.id === s.id) return; if (!openInNewWindow(e, claudeSessionHash(s.id, project))) onResume(s.id); }}
            onContextMenu=${(e) => { e.preventDefault(); e.stopPropagation(); setMenu({ x: e.clientX, y: e.clientY, s }); }}
            onAuxClick=${(e) => openInNewWindow(e, claudeSessionHash(s.id, project))} onMouseDown=${noAutoscroll}
            title="Retomar esta sessão (Ctrl+clique ou clique do meio abre em nova aba)">
          <span class=${"cc-sess-st " + (s.waiting ? "wait" : s.running ? "run" : "done")}
            title=${s.waiting ? "Aguardando sua resposta ou aprovação" : s.running ? "Em andamento" : "Finalizada"}
            aria-label=${s.waiting ? "Aguardando sua resposta ou aprovação" : s.running ? "Em andamento" : "Finalizada"}>${s.waiting ? "!" : s.running ? "" : "✓"}</span>
          <div class="cc-sess-main">
            <div class="cc-sess-title">${renaming && renaming.id === s.id
              ? html`<input class="cc-sess-rename" value=${renaming.draft} autoFocus maxlength="120" aria-label="Renomear sessão"
                  onClick=${(e) => e.stopPropagation()} onInput=${(e) => setRenaming({ id: s.id, draft: e.target.value })}
                  onBlur=${commitRename}
                  onKeyDown=${(e) => { e.stopPropagation(); if (e.key === "Enter") e.target.blur(); else if (e.key === "Escape") setRenaming(null); }} />`
              : html`<a href=${claudeSessionHash(s.id, project)} onAuxClick=${(e) => e.stopPropagation()} onClick=${(e) => {
              e.stopPropagation();
              if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey && e.button === 0) {
                e.preventDefault(); onResume(s.id);
              }
            }}>${hl(s.title, term)}</a>`}${s.id === currentId ? html` <span class="badge ok">atual</span>` : ""}</div>
            ${s.preview && html`<div class="cc-sess-prev help">${hl(s.preview, term)}</div>`}
            ${s.snippet && html`<div class="cc-sess-snip help">${hl(s.snippet, term)}</div>`}
            <div class="cc-sess-meta help mono">${fmtShort(s.mtime)} · ${(s.id || "").slice(0, 8)}</div>
          </div>
          <div class="cc-sess-acts" onClick=${(e) => e.stopPropagation()} onMouseDown=${(e) => e.stopPropagation()}>
            <label class="cc-sess-chk" title=${s.completed ? "Concluída por completo (clique para desmarcar)" : "Marcar como concluída por completo"}>
              <input type="checkbox" aria-label="Concluída por completo" checked=${!!s.completed} onChange=${(e) => toggleDone(s.id, e.target.checked)} />
            </label>
            <button class="sm cc-sess-ib" title="Renomear sessão (o nome fica fixo)" aria-label="Renomear sessão" onClick=${(e) => { e.stopPropagation(); setRenaming({ id: s.id, draft: s.title }); }}>✎</button>
            <button class="sm cc-sess-ib" title="Copiar link da sessão" aria-label="Copiar link da sessão" onClick=${(e) => { e.stopPropagation(); copySessionLink(s.id, project); }}>🔗</button>
            <button class="sm danger cc-sess-ib" disabled=${busy} title="Excluir sessão" aria-label="Excluir sessão" onClick=${(e) => del(s.id, e)}>🗑</button>
          </div>
        </div>`)}
      </div>`}
    ${menu && html`<div class="fm-menu" style=${`left:${Math.min(menu.x, innerWidth - 190)}px;top:${Math.min(menu.y, innerHeight - 130)}px`} onClick=${(e) => e.stopPropagation()}>
      <button onClick=${() => { const m = menu.s; setMenu(null); setRenaming({ id: m.id, draft: m.title }); }}>Renomear</button>
      <button onClick=${() => { const m = menu.s; setMenu(null); onResume(m.id); }}>Retomar</button>
      <button onClick=${() => { const m = menu.s; setMenu(null); copySessionLink(m.id, project); }}>Copiar link</button>
      <hr /><button class="fm-danger" onClick=${(e) => { const m = menu.s; setMenu(null); del(m.id, e); }}>Excluir</button>
    </div>`}
  </div>`;
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

// "14/11 10:08" (ano só se não for o corrente) — cabe na linha do celular.
function fmtShort(ms) {
  if (!ms) return "";
  try {
    const d = new Date(ms), p2 = (n) => String(n).padStart(2, "0");
    const y = d.getFullYear() === new Date().getFullYear() ? "" : "/" + d.getFullYear();
    return `${p2(d.getDate())}/${p2(d.getMonth() + 1)}${y} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
  } catch (_) { return ""; }
}

function fmtTime(ms) {
  if (!ms) return "";
  try { return new Date(ms).toLocaleString(); } catch (_) { return ""; }
}

function Item({ it, onPermission, onFork, onEdit }) {
  if (it.type === "user")
    return html`<${UserMsg} text=${it.text} tag=${it.interjected ? "durante a execução" : it.queued ? "da fila" : ""} ts=${it.ts} onFork=${onFork} onEdit=${onEdit} />`;

  if (it.type === "assistant")
    return html`<${AssistantMsg} text=${it.text} ts=${it.ts} />`;

  if (it.type === "note")
    return it.title
      ? html`<details class="cc-thinking"><summary>${it.title}</summary><${MarkdownView} text=${it.text} /></details>`
      : html`<div class="cc-msg assistant" onContextMenu=${(e) => replyContextMenu(e, it.text)}><div class="cc-role">sistema</div><${MarkdownView} text=${it.text} /><${MsgTime} ts=${it.ts} /></div>`;

  if (it.type === "thinking")
    return html`<details class="cc-thinking"><summary>pensando…</summary><pre>${it.text}</pre></details>`;

  if (it.type === "tool") return html`<${ToolCard} it=${it} />`;

  if (it.type === "permission") {
    if (it.tool === "AskUserQuestion") return html`<${AskQuestion} it=${it} onPermission=${onPermission} />`;
    if (it.tool === "NetPerms") return html`<${NetPermsCard} it=${it} onPermission=${onPermission} />`;
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
      ${it.cancelled ? "resposta cancelada pelo usuário" : it.isError ? "turno terminou com erro" : "turno concluído"}${typeof it.cost === "number" ? ` · ~$${it.cost.toFixed(4)}` : ""}
    </div>`;

  if (it.type === "error")
    return html`<div class="cc-error">${it.detail}
      ${it.raw && html`<details class="cc-error-raw"><summary>detalhes técnicos</summary><pre>${it.raw}</pre></details>`}
    </div>`;

  return null;
}

// Seletor das permissões de rede: "Full" + as 4 categorias (checkbox). Usado no composer e nos Padrões.
function NetPermsPicker({ value, onChange, compact, max = null }) {
  // max = teto do grupo de acesso do usuário (multiusuário). Acima dele: desabilitado e sem aprovação.
  const allowed = Array.isArray(max) ? max : NETPERMS_ALL;
  const cur = npNorm(value).filter((v) => allowed.includes(v));
  const full = cur.length === NETPERMS_ALL.length;
  const capped = allowed.length < NETPERMS_ALL.length;
  const toggle = (v) => onChange(cur.includes(v) ? cur.filter((x) => x !== v) : npNorm([...cur, v]));
  return html`<div class=${"cc-np" + (compact ? " compact" : "")}>
    ${!compact && html`<div class="cc-pop-title">Nos equipamentos</div>`}
    <label class=${"cc-np-row full" + (capped ? " capped" : "")}>
      <input type="checkbox" disabled=${capped} checked=${full} onChange=${() => onChange(full ? [] : NETPERMS_ALL)} />
      <b>Full</b>
    </label>
    ${NETPERMS.map((p) => html`<label key=${p.value} class=${"cc-np-row" + (allowed.includes(p.value) ? "" : " capped")}
        title=${allowed.includes(p.value) ? "" : "Seu grupo de acesso não permite"}>
      <input type="checkbox" disabled=${!allowed.includes(p.value)} checked=${cur.includes(p.value)} onChange=${() => toggle(p.value)} />
      <b>${p.label}</b><small>${p.desc}</small>
    </label>`)}
    ${!compact && html`<div class="cc-np-help">${capped ? "Desmarcado: pede sua aprovação. Cinza: fora do seu grupo (bloqueado)."
      : "Desmarcado: pede sua aprovação."}</div>`}
  </div>`;
}

// Pedido de aprovação de um comando fora das permissões de rede (hook NetPerms do backend).
function NetPermsCard({ it, onPermission }) {
  const inp = it.input || {};
  const lbl = (v) => (NETPERMS.find((p) => p.value === v) || { label: v }).label;
  const missing = inp.missing || [];
  const calls = inp.calls || [];
  return html`<div class="cc-perm cc-np-card ${it.resolved ? "resolved" : ""}">
    <div class="cc-perm-head">🔐 <b>Fora das permissões</b>
      ${missing.map((m) => html` <span class="cc-np-badge miss">${lbl(m)}</span>`)}</div>
    ${calls.length ? calls.map((c, i) => html`<div key=${i} class="cc-np-call">
        <div class="help">host ${c.host_id != null ? "#" + c.host_id : (c.host || c.session || "?")}${c.note ? " · " + c.note : ""}</div>
        ${(c.commands || []).map((x, j) => html`<div key=${j} class="cc-np-cmd">
          <code>${x.command}</code>
          ${(x.needs || []).map((n) => html`<span class=${"cc-np-badge" + (missing.includes(n) ? " miss" : "")}>${lbl(n)}</span>`)}
        </div>`)}
      </div>`)
      : html`<${Collapsible} text=${inp.command || ""} max=${4} />`}
    ${it.resolved
      ? html`<div class="cc-perm-done ${it.decision}">${it.decision === "allow" ? "✓ liberado" : "✗ negado"}</div>`
      : html`<div class="cc-perm-actions">
          <button class="sm" onClick=${() => onPermission(it.id, "deny")}>Negar</button>
          <button class="sm primary" onClick=${() => onPermission(it.id, "allow")}>Aprovar este</button>
        </div>`}
  </div>`;
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

// Agrupa chamadas de ferramenta e blocos "pensando…" consecutivos numa só linha de chips.
function groupTools(items) {
  const out = [];
  items.forEach((it, i) => {
    if (it.type === "tool" || it.type === "thinking") {
      const last = out[out.length - 1];
      if (last && last.tools) last.tools.push(it);
      else out.push({ tools: [it], start: i });
    } else out.push({ it, i });
  });
  return out;
}

// Chips lado a lado (só o nome); clicar abre o card completo da ferramenta abaixo da linha.
function ToolGroup({ tools }) {
  const [open, setOpen] = useState({});
  const toggle = (k) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const icon = (st) => ({ running: "⏳", done: "✓", error: "✗" }[st] || "•");
  return html`<div class="cc-toolgroup">
    <div class="cc-chips">
      ${tools.map((t, k) => t.type === "thinking"
        ? html`<button type="button" key=${k} title="pensando…"
            class="cc-chip think ${open[k] ? "open" : ""}" aria-expanded=${!!open[k]}
            onClick=${() => toggle(k)}>💭 pensando…</button>`
        : html`<button type="button" key=${k} title=${primaryString(t.input) || ""}
            class="cc-chip ${t.tstatus} ${open[k] ? "open" : ""}" aria-expanded=${!!open[k]}
            onClick=${() => toggle(k)}>${icon(t.tstatus)} ${t.name}</button>`)}
    </div>
    ${tools.map((t, k) => open[k] && (t.type === "thinking"
      ? html`<details class="cc-thinking" open key=${"d" + k}><summary>pensando…</summary><pre>${t.text}</pre></details>`
      : html`<${ToolCard} key=${"d" + k} it=${t} initialOpen=${true} />`))}
  </div>`;
}

// Card de ferramenta compacto: recolhido = 1 linha (ícone + nome + resumo truncado); clicar no
// cabeçalho expande entrada/saída completas. Cada card expande de forma independente.
function ToolCard({ it, initialOpen = false }) {
  const [open, setOpen] = useState(initialOpen);
  const icon = { running: "⏳", done: "✓", error: "✗" }[it.tstatus] || "•";
  const prim = primaryString(it.input);
  const hasBigExtra = ["content", "new_string", "old_string"].some(
    (k) => typeof (it.input || {})[k] === "string" && it.input[k].length > 120);
  const headLine = (prim != null ? prim : fmt(it.input)).split("\n")[0] || "";
  const detail = (prim != null && !hasBigExtra) ? prim : fmt(it.input);
  const resLines = it.result != null ? String(it.result).split("\n").length : 0;
  return html`<div class="cc-tool ${it.tstatus} ${open ? "open" : ""}">
    <button type="button" class="cc-tool-head" aria-expanded=${open}
        onClick=${() => setOpen((o) => !o)}>
      <span class="cc-tool-ico">${icon}</span><b>${it.name}</b>
      ${headLine && html`<span class="cc-tool-desc mono">${headLine}</span>`}
      ${!open && resLines > 0 && html`<span class="cc-tool-n">${resLines}\u00a0l</span>`}
      <span class="cc-tool-caret">${open ? "▾" : "▸"}</span>
    </button>
    ${open && html`<div class="cc-tool-body">
      <pre class="cc-pre">${detail}</pre>
      ${it.result != null && html`<${Collapsible} text=${it.result} max=${12} kind=${it.isError ? "err" : ""} />`}
    </div>`}
  </div>`;
}
