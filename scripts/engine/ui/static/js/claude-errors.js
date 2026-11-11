// Erros do SDK: disponibilidade no catálogo não comprova acesso nem limite de uso.
export function claudeErrorDetail(event) {
  const messages = [event.detail, ...(Array.isArray(event.errors) ? event.errors : []), event.result];
  return [...new Set(messages.filter((s) => typeof s === "string" && s.trim()))].join("\n")
    || (event.api_error_status ? `API Error: HTTP ${event.api_error_status}` : "Falha no agente Claude.");
}

export function classifyClaudeError(event) {
  const detail = claudeErrorDetail(event);
  const status = Number(event.api_error_status);
  const modelError = /model|modelo/i.test(detail) && /exist|access|selected|not found|unavailable|inv[aá]lid|dispon/i.test(detail);
  if (status === 429) return "rate_limit";
  // Status explícito prevalece sobre heurísticas de texto, inclusive 529/overloaded.
  if (status === 400 || status === 404) return modelError ? "model" : "other";
  if (status >= 400) return "other";
  if (event.error_code === "rate_limit" || /rate.?limit|\b429\b|too many requests|usage limit/i.test(detail)) return "rate_limit";
  if (event.error_code === "authentication_failed" || /\b(?:401|403|529)\b|overloaded/i.test(detail)) return "other";
  if (modelError) return "model";
  return "other";
}
