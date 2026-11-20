import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../static/js/mentions.js", import.meta.url), "utf8");
const m = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));

const catalog = m.buildCatalog({
  groups: ["MIKROTIK", "LINUX"],
  hosts: [
    { id: 1, explicit: { hostname: "001 Mikrotik Test", group: "MIKROTIK" }, effective: { mgmt_ip: "10.0.0.1", vendor: "MIKROTIK" } },
    { id: 2, explicit: { hostname: "RT-CORE-01", group: "MIKROTIK" }, effective: { mgmt_ip: "10.0.0.2", vendor: "MIKROTIK" } },
    { id: 3, explicit: { hostname: "srv-mikrotik-backup", group: "LINUX" }, effective: { mgmt_ip: "10.0.0.3", vendor: "LINUX" } },
    { id: 4, explicit: { hostname: "ZABBIX" }, effective: { mgmt_ip: "10.0.0.4" } },
  ],
});

test("token em edição: # no início ou após espaço, nunca no meio de palavra", () => {
  assert.deepEqual(m.findMentionToken("acesse #mik", 11), { start: 7, end: 11, query: "mik", kind: null });
  assert.deepEqual(m.findMentionToken("#", 1), { start: 0, end: 1, query: "", kind: null });
  assert.equal(m.findMentionToken("issue#12", 8), null);
  assert.equal(m.findMentionToken("acesse #mik agora", 17), null);          // cursor depois do espaço
  assert.deepEqual(m.findMentionToken("#group:mi", 9), { start: 0, end: 9, query: "mi", kind: "group" });
});

test("busca acha grupo e hosts que contêm o termo (também no meio do nome)", () => {
  const r = m.searchMentions(catalog, "mikrotik");
  assert.deepEqual(r.map((x) => x.token), ["#group:MIKROTIK", "#host:001_Mikrotik_Test", "#host:srv-mikrotik-backup"]);
  assert.equal(r[0].kind, "group");
  assert.equal(r[0].detail, "2 host(s)");
});

test("busca por IP, id e filtro de tipo", () => {
  assert.deepEqual(m.searchMentions(catalog, "10.0.0.4").map((x) => x.token), ["#host:ZABBIX"]);
  assert.deepEqual(m.searchMentions(catalog, "mikrotik", "group").map((x) => x.kind), ["group"]);
  assert.ok(m.searchMentions(catalog, "mikrotik", "host").every((x) => x.kind === "host"));
  assert.equal(m.searchMentions(catalog, "xyz-nada").length, 0);
});

test("aplicar troca o token e posiciona o cursor depois do espaço", () => {
  const text = "acesse #mik agora";
  const tok = m.findMentionToken(text, 11);
  const r = m.applyMention(text, tok, { token: "#group:MIKROTIK" });
  assert.equal(r.text, "acesse #group:MIKROTIK agora");
  assert.equal(r.caret, "acesse #group:MIKROTIK ".length);
});

test("expandir: grupo vira lista de hosts; sem menção nada muda; bolha esconde o bloco", () => {
  const typed = "acesse #group:MIKROTIK e veja #host:ZABBIX.";
  const out = m.expandMentions(typed, catalog);
  assert.ok(out.startsWith(typed + "\n\n" + m.MENTION_NOTE));
  assert.match(out, /grupo do inventário com 2 host\(s\): host id 1 .*; host id 2/);
  assert.match(out, /#host:ZABBIX = host id 4/);
  assert.equal(m.stripMentionNote(out), typed);
  assert.equal(m.expandMentions("sem menção #nada", catalog), "sem menção #nada");
  assert.equal(m.expandMentions("#group:INEXISTENTE", catalog), "#group:INEXISTENTE");
});

test("#senha: itens do Cofre de senhas viram referências nvault:// (nunca valor)", () => {
  const cat = m.buildCatalog({ groups: [], hosts: [] }, { items: [
    { id: "coolify-producao", title: "Coolify produção", template_label: "API",
      values: [{ field: "URL", kind: "text", value: "https://c.example" }, { field: "API key", kind: "secret", set: true }] }] });
  const tok = m.findMentionToken("usa #senha:cool", 15);
  assert.equal(tok.kind, "senha");
  const items = m.searchMentions(cat, "coolify", null);
  assert.deepEqual(items.map((i) => [i.kind, i.token]), [["senha", "#senha:coolify-producao"]]);
  assert.equal(m.searchMentions(cat, "coolify", "host").length, 0);
  const out = m.expandMentions("acessa o coolify com #senha:coolify-producao.", cat);
  assert.ok(out.includes("nvault://coolify-producao/api-key (API key, segredo)"));
  assert.ok(out.includes("nvault://coolify-producao/url (URL, texto)"));
  assert.ok(out.includes("nvault run"));
  assert.ok(!out.includes("https://c.example"), "não manda nem o valor de texto");
  assert.equal(m.stripMentionNote(out), "acessa o coolify com #senha:coolify-producao.");
  assert.deepEqual(m.buildCatalog({ hosts: [] }, null).vault, []);
});
