// Links e preferência de conversa; o histórico continua no transcript do servidor.
const LAST_SESSION_KEY = "netops_claude_last_session";
const SESSION_ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

export function validSessionId(id) { return typeof id === "string" && SESSION_ID.test(id); }

// Projeto = pasta do servidor com nome. O id é um slug gerado pelo servidor; "new" é o formulário de criação.
const PROJECT_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
export function validProjectId(id) { return typeof id === "string" && PROJECT_ID.test(id) && id !== "new"; }

// Sem projeto: #claude/<id> (aba Claude Code, pasta do NetOps). Com projeto: #projects/<proj>/<id|new>.
export function claudeSessionHash(id, project = "") {
  if (validProjectId(project)) return "#projects/" + project + "/" + (validSessionId(id) ? id : "new");
  return validSessionId(id) ? "#claude/" + id : "#claude";
}

export function claudeNewHash(project = "") {
  return validProjectId(project) ? "#projects/" + project + "/new" : "#claude/new";
}

// Sufixos que abrem popups como URL própria (ex.: #claude/<id>/padroes, #claude/<id>/sessoes).
const PREFS_SUFFIX = "/padroes";
const SESSIONS_SUFFIX = "/sessoes";
const SUFFIXES = [PREFS_SUFFIX, SESSIONS_SUFFIX];
function modalSuffix(hash) {
  const hit = SUFFIXES.find((x) => hash.endsWith(x));
  if (!hit) return "";
  if (hash.startsWith("#claude")) return hit;
  // #projects/<proj>/<id|new>/padroes — só com 4 segmentos, para um projeto chamado "padroes" não virar popup.
  if (hash.startsWith("#projects/") && hash.split("/").length === 4) return hit;
  return "";
}
export function stripClaudeModal(hash) { const x = modalSuffix(hash); return x ? hash.slice(0, -x.length) : hash; }
export function claudePrefsOpen(hash = location.hash) { return modalSuffix(hash) === PREFS_SUFFIX; }
export function claudeSessionsOpen(hash = location.hash) { return modalSuffix(hash) === SESSIONS_SUFFIX; }
function setModalHash(suffix, open) {
  const base = stripClaudeModal(location.hash);
  if (open) { location.hash = (base || "#claude") + suffix; return; }
  if (modalSuffix(location.hash) === suffix) history.replaceState(null, "", base || "#claude");
  dispatchEvent(new Event("hashchange"));
}
export function setClaudePrefsHash(open) { setModalHash(PREFS_SUFFIX, open); }
export function setClaudeSessionsHash(open) { setModalHash(SESSIONS_SUFFIX, open); }

export function readClaudeRoute(hash) {
  hash = stripClaudeModal(hash);
  if (hash.startsWith("#projects/")) {
    // Só #projects/<proj>/<id|new> é conversa; #projects, #projects/new, #projects/<proj> e .../files são páginas
    // (a conversa viva segue no dock). Rota de projeto devolve também `project`.
    const parts = hash.slice(1).split("?")[0].split("/");
    if (parts.length < 3 || parts[1] === "new" || (parts.length === 3 && parts[2] === "")) return null;
    if (parts.length === 3 && parts[2] === "files") return null;   // #projects/<proj>/files = página de arquivos
    const project = parts[1];
    if (!validProjectId(project) || parts.length > 3) return { kind: "invalid" };
    if (parts[2] === "new") return { kind: "new", project };
    return validSessionId(parts[2]) ? { kind: "session", id: parts[2], project } : { kind: "invalid" };
  }
  if (hash === "#claude" || hash === "#claude/") return { kind: "last" };
  if (!hash.startsWith("#claude/")) return null;
  if (hash === "#claude/new") return { kind: "new" };
  const id = hash.slice("#claude/".length);
  return validSessionId(id) ? { kind: "session", id } : { kind: "invalid" };
}

// A tela cheia do chat: #claude[/...] ou #projects/<proj>/<id|new>. Outras rotas (inclusive a página do projeto) não são o chat.
export function isClaudeChatHash(hash) {
  return readClaudeRoute(hash || "") !== null;
}

export function lastClaudeSession() {
  try {
    const id = localStorage.getItem(LAST_SESSION_KEY);
    return validSessionId(id) ? id : "";
  } catch (_) { return ""; }
}

export function rememberClaudeSession(id) {
  if (!validSessionId(id)) return;
  try { localStorage.setItem(LAST_SESSION_KEY, id); } catch (_) {}
}

export function forgetClaudeSession(id) {
  try {
    if (localStorage.getItem(LAST_SESSION_KEY) === id) localStorage.removeItem(LAST_SESSION_KEY);
  } catch (_) {}
}

export function replaceClaudeHash(hash) {
  hash += modalSuffix(location.hash);   // não fecha o popup aberto (Padrões/Sessões)
  if (location.hash === hash) return;
  history.replaceState(null, "", hash);
  dispatchEvent(new Event("hashchange"));
}

export async function copyClaudeSessionLink(id, project = "") {
  if (!validSessionId(id)) throw new Error("A sessão ainda não tem um link.");
  const url = new URL(location.href);
  url.search = ""; // Nunca copiar parâmetros de autenticação de um link legado.
  url.hash = claudeSessionHash(id, project);
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(url.href);
    return;
  }
  // O console também roda em HTTP na LAN, onde Clipboard API não está disponível.
  const previous = document.activeElement;
  const field = document.createElement("textarea");
  field.value = url.href;
  field.style.cssText = "position:fixed;left:-9999px;top:0";
  document.body.appendChild(field);
  try {
    field.select();
    if (!document.execCommand("copy")) throw new Error("Não foi possível copiar o link.");
  } finally {
    field.remove();
    if (previous && previous.focus) previous.focus();
  }
}


// Prompt pré-preenchido (fork de conversa, botão "Abrir no Claude" da Central de Avisos).
// Grava {id: "<uuid>"|"new", text, t} em localStorage; a conversa-alvo ("proj|id") consome uma vez (2 min de validade).
export function takeClaudePrefill(target) {
  try {
    const f = JSON.parse(localStorage.getItem("cc-fork-prefill") || "null");
    if (!f || Date.now() - (f.t || 0) > 120000) return null;
    if (f.id !== target && !String(target).endsWith("|" + f.id)) return null;
    localStorage.removeItem("cc-fork-prefill");
    return String(f.text || "");
  } catch (_) { return null; }
}
