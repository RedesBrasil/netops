// Cliente HTTP do NetOps Console. O acesso é autenticado pelo LOGIN (senha-mestra do cofre):
// o sid da sessão é enviado no header X-Netops-Session em todo request.

// Sessão de login (senha-mestra): sid emitido por /auth/login, enviado no header X-Netops-Session.
let AUTH = "";
try { AUTH = sessionStorage.getItem("netops_auth") || ""; } catch (e) {}
export function authToken() { return AUTH; }
export function setAuthToken(t) {
  AUTH = t || "";
  try { t ? sessionStorage.setItem("netops_auth", t) : sessionStorage.removeItem("netops_auth"); } catch (e) {}
}
export function clearAuthToken() { setAuthToken(""); }

// Callback de "sessão perdida" (401 auth_required): o front volta pra tela de login.
let _onUnauthorized = null;
export function setOnUnauthorized(fn) { _onUnauthorized = fn; }

export class ApiError extends Error {
  constructor(status, payload) { super(payload?.detail || payload?.error || `HTTP ${status}`); this.status = status; this.payload = payload; }
}
export class ConflictError extends ApiError {}
export class ValidationError extends ApiError {
  get fieldErrors() { return this.payload?.errors || []; }
}
export class VaultLockedError extends ApiError {}

async function req(method, path, { body, rev } = {}) {
  const headers = {};
  if (AUTH) headers["X-Netops-Session"] = AUTH;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (rev) headers["If-Match"] = rev;
  const res = await fetch("/api" + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  let payload = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) { try { payload = await res.json(); } catch (e) {} }
  if (res.ok) return res.status === 204 ? null : payload;
  if (res.status === 409) throw new ConflictError(409, payload);
  if (res.status === 422) throw new ValidationError(422, payload);
  if (res.status === 423) throw new VaultLockedError(423, payload);
  // Sessão de login expirada/ausente: limpa e avisa o shell pra voltar ao login.
  if (res.status === 401 && payload?.error === "auth_required") {
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
