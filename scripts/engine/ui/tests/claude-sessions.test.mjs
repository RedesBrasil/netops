import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../static/js/claude-sessions.js", import.meta.url), "utf8");
const sessions = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const A = "11111111-1111-4111-8111-111111111111";

test("rota distingue sessão explícita, última conversa, nova e IDs inválidos", () => {
  assert.deepEqual(sessions.readClaudeRoute("#claude/" + A), { kind: "session", id: A });
  assert.deepEqual(sessions.readClaudeRoute("#claude"), { kind: "last" });
  assert.deepEqual(sessions.readClaudeRoute("#claude/"), { kind: "last" });
  assert.deepEqual(sessions.readClaudeRoute("#claude/new"), { kind: "new" });
  for (const bad of ["../hosts", "%ZZ", "%2F", A + "/extra", A + "?auth=x", "not-a-uuid"]) {
    assert.deepEqual(sessions.readClaudeRoute("#claude/" + bad), { kind: "invalid" });
  }
  assert.equal(sessions.readClaudeRoute("#hosts"), null);
  assert.equal(sessions.claudeSessionHash(A), "#claude/" + A);
  assert.equal(sessions.claudeSessionHash("../hosts"), "#claude");
});

test("preferência guarda somente UUID e exclusão não apaga outra seleção", () => {
  const values = new Map();
  globalThis.localStorage = {
    getItem: (k) => values.get(k) ?? null,
    setItem: (k, v) => values.set(k, v),
    removeItem: (k) => values.delete(k),
  };
  sessions.rememberClaudeSession(A);
  assert.equal(sessions.lastClaudeSession(), A);
  sessions.rememberClaudeSession("not-a-uuid");
  sessions.forgetClaudeSession("other");
  assert.equal(sessions.lastClaudeSession(), A);
  sessions.forgetClaudeSession(A);
  assert.equal(sessions.lastClaudeSession(), "");
  values.set("netops_claude_last_session", "corrupt");
  assert.equal(sessions.lastClaudeSession(), "");
  globalThis.localStorage = { getItem() { throw Error("blocked"); }, setItem() { throw Error("blocked"); } };
  assert.equal(sessions.lastClaudeSession(), "");
  assert.doesNotThrow(() => sessions.rememberClaudeSession(A));
  assert.doesNotThrow(() => sessions.forgetClaudeSession(A));
  delete globalThis.localStorage;
});

test("link copiado identifica conversa e remove parâmetros da URL", async () => {
  globalThis.location = { href: "https://console.example/?auth=legacy#hosts" };
  globalThis.window = { isSecureContext: true };
  let copied;
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { clipboard: { writeText: async (s) => { copied = s; } } } });
  await sessions.copyClaudeSessionLink(A);
  assert.equal(copied, "https://console.example/#claude/" + A);
  await assert.rejects(() => sessions.copyClaudeSessionLink("invalid"));
  delete globalThis.location; delete globalThis.window; delete globalThis.navigator;
});

test("cópia funciona no console HTTP usando fallback e restaura o foco", async () => {
  globalThis.location = { href: "http://192.0.2.1:8765/#hosts" };
  globalThis.window = { isSecureContext: false };
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: {} });
  let removed = false, focused = false;
  const field = { style: {}, select() {}, remove() { removed = true; } };
  globalThis.document = {
    activeElement: { focus() { focused = true; } },
    createElement: () => field,
    body: { appendChild() {} },
    execCommand: (cmd) => cmd === "copy",
  };
  await sessions.copyClaudeSessionLink(A);
  assert.equal(field.value, "http://192.0.2.1:8765/#claude/" + A);
  assert.ok(removed && focused);
  delete globalThis.location; delete globalThis.window; delete globalThis.navigator; delete globalThis.document;
});
