// Links e preferência de conversa; o histórico continua no transcript do servidor.
const LAST_SESSION_KEY = "netops_claude_last_session";
const SESSION_ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

export function validSessionId(id) { return typeof id === "string" && SESSION_ID.test(id); }

export function claudeSessionHash(id) {
  return validSessionId(id) ? "#claude/" + id : "#claude";
}

export function readClaudeRoute(hash) {
  if (hash === "#claude" || hash === "#claude/") return { kind: "last" };
  if (!hash.startsWith("#claude/")) return null;
  if (hash === "#claude/new") return { kind: "new" };
  const id = hash.slice("#claude/".length);
  return validSessionId(id) ? { kind: "session", id } : { kind: "invalid" };
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
  if (location.hash === hash) return;
  history.replaceState(null, "", hash);
  dispatchEvent(new Event("hashchange"));
}

export async function copyClaudeSessionLink(id) {
  if (!validSessionId(id)) throw new Error("A sessão ainda não tem um link.");
  const url = new URL(location.href);
  url.search = ""; // Nunca copiar parâmetros de autenticação de um link legado.
  url.hash = claudeSessionHash(id);
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
