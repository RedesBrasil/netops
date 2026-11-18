import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../static/js/claude-sessions.js", import.meta.url), "utf8");
const s = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const A = "11111111-1111-4111-8111-111111111111";

test("hash de sessão: sem projeto é #claude, com projeto é #projects/<proj>/<id|new>", () => {
  assert.equal(s.claudeSessionHash(A), "#claude/" + A);
  assert.equal(s.claudeSessionHash(A, "meu-site"), "#projects/meu-site/" + A);
  assert.equal(s.claudeSessionHash("", "meu-site"), "#projects/meu-site/new");
  assert.equal(s.claudeNewHash(), "#claude/new");
  assert.equal(s.claudeNewHash("meu-site"), "#projects/meu-site/new");
});

test("projeto inválido nunca vira caminho: cai na aba Claude Code", () => {
  for (const bad of ["../x", "A", "a/b", "new", "", "-x", "x".repeat(70)]) {
    assert.equal(s.validProjectId(bad), false, bad);
    assert.equal(s.claudeSessionHash(A, bad), "#claude/" + A, bad);
  }
  assert.equal(s.validProjectId("meu-site-2"), true);
});

test("rota de conversa de projeto devolve o projeto", () => {
  assert.deepEqual(s.readClaudeRoute("#projects/meu-site/" + A), { kind: "session", id: A, project: "meu-site" });
  assert.deepEqual(s.readClaudeRoute("#projects/meu-site/new"), { kind: "new", project: "meu-site" });
  assert.deepEqual(s.readClaudeRoute("#projects/meu-site/not-a-uuid"), { kind: "invalid" });
  assert.deepEqual(s.readClaudeRoute("#projects/INVALIDO/" + A), { kind: "invalid" });
  assert.deepEqual(s.readClaudeRoute("#projects/meu-site/" + A + "/extra"), { kind: "invalid" });
});

test("páginas de projeto não são o chat (a conversa viva segue no dock)", () => {
  for (const page of ["#projects", "#projects/", "#projects/new", "#projects/meu-site", "#projects/meu-site/"]) {
    assert.equal(s.readClaudeRoute(page), null, page);
    assert.equal(s.isClaudeChatHash(page), false, page);
  }
  assert.equal(s.isClaudeChatHash("#projects/meu-site/new"), true);
  assert.equal(s.isClaudeChatHash("#claude"), true);
  assert.equal(s.isClaudeChatHash("#hosts"), false);
  assert.equal(s.isClaudeChatHash("#claudexyz"), false);
});

test("popup Padrões/Sessões só vale com 4 segmentos (projeto chamado 'padroes' não vira popup)", () => {
  assert.equal(s.claudePrefsOpen("#projects/meu-site/" + A + "/padroes"), true);
  assert.equal(s.claudeSessionsOpen("#projects/meu-site/new/sessoes"), true);
  assert.equal(s.claudePrefsOpen("#projects/padroes"), false);
  assert.equal(s.claudeSessionsOpen("#projects/meu-site/sessoes"), false);
  assert.equal(s.stripClaudeModal("#projects/meu-site/" + A + "/padroes"), "#projects/meu-site/" + A);
  assert.equal(s.stripClaudeModal("#projects/padroes"), "#projects/padroes");
});

test("#projects/<proj>/files é página (arquivos do projeto), não conversa", () => {
  assert.equal(s.readClaudeRoute("#projects/meu-site/files"), null);
  assert.equal(s.readClaudeRoute("#projects/meu-site/files?path=%2Fopt%2Fx&open=%2Fopt%2Fx%2Fa"), null);
  assert.equal(s.isClaudeChatHash("#projects/meu-site/files"), false);
  assert.deepEqual(s.readClaudeRoute("#projects/meu-site/" + A), { kind: "session", id: A, project: "meu-site" });
});
