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

// Texto claro para o usuário (o texto técnico original continua disponível em "detalhes técnicos").
// `interrupted` = o usuário clicou em Interromper neste turno.
export function friendlyClaudeError(event, { interrupted = false } = {}) {
  const detail = claudeErrorDetail(event);
  const status = Number(event.api_error_status);
  const code = event.error_code;
  if (interrupted || /interrupted by user|request was aborted|\babort(ed)?\b|cancel+ed/i.test(detail))
    return "Resposta cancelada pelo usuário.";
  if (status === 429 || code === "rate_limit" || /rate.?limit|too many requests|usage limit/i.test(detail))
    return "Limite de uso atingido. Aguarde um pouco e tente de novo.";
  if (status === 401 || status === 403 || code === "authentication_failed" || /authenticat|invalid api key|oauth|not logged in|\/login/i.test(detail))
    return "Falha de autenticação no Claude. Faça login de novo (/login).";
  if (code === "billing_error" || /credit balance|billing/i.test(detail))
    return "Problema de crédito/cobrança na conta do Claude.";
  if (classifyClaudeError(event) === "model") return "Modelo indisponível ou sem acesso. Escolha outro modelo.";
  if (status === 529 || /overloaded/i.test(detail)) return "Serviço do Claude sobrecarregado. Tente novamente em instantes.";
  if (status >= 500 || code === "server_error") return "Erro no servidor do Claude. Tente novamente em instantes.";
  if (/ede_diagnostic|ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|socket hang up|network|fetch failed|connection (error|closed|reset|lost)|stream (ended|closed)|timed? ?out/i.test(detail))
    return "Erro de rede: a conexão com o Claude caiu no meio da resposta. Tente novamente.";
  if (/too many sessions|too_many_sessions/i.test(detail)) return "Muitas sessões Claude abertas. Feche alguma e tente de novo.";
  if (/process (exited|terminated)|exit code|CLI/i.test(detail)) return "O agente Claude foi encerrado inesperadamente. Tente novamente.";
  return "Falha no agente Claude.";
}
