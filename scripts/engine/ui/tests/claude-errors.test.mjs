import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../static/js/claude-errors.js", import.meta.url), "utf8");
const { classifyClaudeError, claudeErrorDetail } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const modelError = "There's an issue with the selected model (claude-sonnet-4-5). It may not exist or you may not have access to it.";

test("erro da imagem permite trocar modelo sem inventar limite de uso", () => {
  assert.equal(classifyClaudeError({ detail: modelError }), "model");
  assert.equal(classifyClaudeError({ is_error: true, result: modelError }), "model");
  assert.equal(classifyClaudeError({ errors: [modelError] }), "model");
  assert.equal(classifyClaudeError({ result: modelError, api_error_status: 404 }), "model");
  assert.equal(classifyClaudeError({ result: modelError, api_error_status: 400 }), "model");
});

test("429 explícito é limite; sobrecarga 529 e falha de acesso são distintos", () => {
  assert.equal(classifyClaudeError({ detail: modelError, api_error_status: 429 }), "rate_limit");
  assert.equal(classifyClaudeError({ error_code: "rate_limit" }), "rate_limit");
  assert.equal(classifyClaudeError({ detail: "Too many requests" }), "rate_limit");
  for (const status of [401, 403, 500, 529]) {
    assert.equal(classifyClaudeError({ detail: modelError, api_error_status: status }), "other");
  }
  assert.equal(classifyClaudeError({ detail: "API Error: 529 overloaded" }), "other");
  assert.equal(classifyClaudeError({ detail: modelError, error_code: "authentication_failed" }), "other");
});

test("detalhe preserva resultado/erros sem repetir mensagens iguais", () => {
  assert.equal(claudeErrorDetail({ detail: modelError, errors: [modelError], result: modelError }), modelError);
  assert.equal(claudeErrorDetail({ errors: ["Erro A", "Erro B"] }), "Erro A\nErro B");
  assert.equal(claudeErrorDetail({ api_error_status: 429 }), "API Error: HTTP 429");
});

const { friendlyClaudeError } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
test("mensagens amigáveis em português", () => {
  assert.match(friendlyClaudeError({ detail: "[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=tool_use" }), /Erro de rede/);
  assert.match(friendlyClaudeError({ detail: "x" }, { interrupted: true }), /cancelada pelo usuário/);
  assert.match(friendlyClaudeError({ api_error_status: 429 }), /Limite de uso/);
  assert.match(friendlyClaudeError({ api_error_status: 529 }), /sobrecarregado/);
  assert.match(friendlyClaudeError({ error_code: "authentication_failed" }), /autenticação/);
});
