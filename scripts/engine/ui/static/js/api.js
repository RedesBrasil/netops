// Cliente HTTP do NetOps Console. O acesso é autenticado pelo LOGIN (senha-mestra do cofre):
// o sid da sessão é enviado no header X-Netops-Session em todo request.

// O sid é compartilhado entre abas da mesma origem; a senha nunca é armazenada.
const AUTH_KEY = "netops_auth";
let AUTH = "";
try { AUTH = sessionStorage.getItem(AUTH_KEY) || ""; } catch (e) {}
try {
  const shared = localStorage.getItem(AUTH_KEY);
  if (shared !== null) AUTH = shared;
  else if (AUTH) localStorage.setItem(AUTH_KEY, AUTH);
  sessionStorage.removeItem(AUTH_KEY);
} catch (e) {}
export function authToken() {
  try { AUTH = localStorage.getItem(AUTH_KEY) || ""; } catch (e) {}
  return AUTH;
}
export function setAuthToken(t) {
  AUTH = t || "";
  // Vazio registra logout: abas legadas não podem reimportar um sid antigo ao recarregar.
  try { localStorage.setItem(AUTH_KEY, AUTH); } catch (e) {}
  try { sessionStorage.removeItem(AUTH_KEY); } catch (e) {}
}
export function clearAuthToken() { setAuthToken(""); }

let _onAuthChange = null;
export function setOnAuthChange(fn) { _onAuthChange = fn; }
if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key !== AUTH_KEY && event.key !== null) return;
  try { if (event.storageArea && event.storageArea !== localStorage) return; } catch (e) {}
  try { sessionStorage.removeItem(AUTH_KEY); } catch (e) {}
  authToken();
  if (_onAuthChange) _onAuthChange();
});

// Callback de "sessão perdida" (401 auth_required): o front volta pra tela de login.
let _onUnauthorized = null;
export function setOnUnauthorized(fn) { _onUnauthorized = fn; }

export class ApiError extends Error {
  constructor(status, payload) { super(typeof payload?.detail === "string" ? payload.detail : payload?.error || `HTTP ${status}`); this.status = status; this.payload = payload; }
}
export class ConflictError extends ApiError {}
export class ValidationError extends ApiError {
  get recoveryHint() {
    if (!Array.isArray(this.payload?.detail)) return null;
    const unsupportedShapeIcon = this.payload.detail.some(error => {
      const loc = Array.isArray(error.loc) ? error.loc : [];
      const path = loc[0] === "body" ? loc.slice(1) : loc;
      return error.type === "extra_forbidden" && path.length === 4 &&
        path[0] === "map" && path[1] === "objects" &&
        Number.isInteger(path[2]) && path[2] >= 0 && path[3] === "icon";
    });
    return unsupportedShapeIcon
      ? "Este servidor ainda não aceita ícones nas formas. Atualize o NetOps e reinicie o console no servidor. Seus ajustes ainda não foram salvos."
      : null;
  }
  get fieldErrors() {
    if (Array.isArray(this.payload?.errors)) return this.payload.errors;
    // FastAPI/Pydantic usa detail; a validação de domínio usa errors.
    // Expõe só caminho e mensagem, nunca o input recebido pelo servidor.
    if (!Array.isArray(this.payload?.detail)) return [];
    return this.payload.detail.map(error => ({
      loc: (Array.isArray(error.loc) ? error.loc.filter(part => part !== "body") : []).join("/"),
      msg: error.type === "missing" ? "Campo obrigatório" : error.msg || "Valor inválido",
    }));
  }
}
export class VaultLockedError extends ApiError {}

async function req(method, path, { body, rev } = {}) {
  const headers = {};
  const sentAuth = authToken();
  if (sentAuth) headers["X-Netops-Session"] = sentAuth;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (rev) headers["If-Match"] = rev;
  const res = await fetch("/api" + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  let payload = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) { try { payload = await res.json(); } catch (e) {} }
  if (res.ok) {
    if (method !== "GET") window.dispatchEvent(new CustomEvent("netops:changed", { detail: path }));
    return res.status === 204 ? null : payload;
  }
  if (res.status === 409) throw new ConflictError(409, payload);
  if (res.status === 422) throw new ValidationError(422, payload);
  if (res.status === 423) throw new VaultLockedError(423, payload);
  // Sessão de login expirada/ausente: limpa e avisa o shell pra voltar ao login.
  if (res.status === 401 && payload?.error === "auth_required" && authToken() === sentAuth) {
    clearAuthToken();
    if (_onUnauthorized) _onUnauthorized();
  }
  throw new ApiError(res.status, payload);
}

export const api = {
  get: (p) => req("GET", p),
  post: (p, body, rev) => req("POST", p, { body, rev }),
  put: (p, body, rev) => req("PUT", p, { body, rev }),
  patch: (p, body, rev) => req("PATCH", p, { body, rev }),
  del: (p, rev) => req("DELETE", p, { rev }),
};
