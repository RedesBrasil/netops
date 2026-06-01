// Cliente HTTP do NetOps Console. Captura o token da URL (?token=...), guarda em memória
// e o envia em todo request. Limpa o token da barra de endereço (não fica no histórico).

let TOKEN = "";
(function captureToken() {
  const u = new URL(location.href);
  const t = u.searchParams.get("token");
  if (t) {
    TOKEN = t;
    try { sessionStorage.setItem("netops_token", t); } catch (e) {}
    u.searchParams.delete("token");
    history.replaceState(null, "", u.pathname + u.hash);
  } else {
    try { TOKEN = sessionStorage.getItem("netops_token") || ""; } catch (e) {}
  }
})();

export class ApiError extends Error {
  constructor(status, payload) { super(payload?.detail || payload?.error || `HTTP ${status}`); this.status = status; this.payload = payload; }
}
export class ConflictError extends ApiError {}
export class ValidationError extends ApiError {
  get fieldErrors() { return this.payload?.errors || []; }
}
export class VaultLockedError extends ApiError {}

async function req(method, path, { body, rev } = {}) {
  const headers = { "Authorization": "Bearer " + TOKEN };
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
  throw new ApiError(res.status, payload);
}

export const api = {
  get: (p) => req("GET", p),
  post: (p, body, rev) => req("POST", p, { body, rev }),
  put: (p, body, rev) => req("PUT", p, { body, rev }),
  patch: (p, body, rev) => req("PATCH", p, { body, rev }),
  del: (p, rev) => req("DELETE", p, { rev }),
};
