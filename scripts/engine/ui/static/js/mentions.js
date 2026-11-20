// Menções de hosts, grupos e itens do Cofre de senhas na caixa de mensagem da aba Claude: "#mikrotik"
// abre uma lista com `host:<hostname>`, `group:<grupo>` e `senha:<item>`. Lógica pura (sem DOM) — testada em
// tests/mentions.test.mjs. O Composer só cuida da tela.
//
// Formato do texto: `#host:<hostname>`, `#group:<NOME>` e `#senha:<ID do item>` (espaços do hostname viram "_").
// `#senha:` nunca leva valor: o agente recebe só as referências nvault:// (uso via `nvault run`).
// No envio, `expandMentions` acrescenta um bloco com os IDs reais do inventário, para o
// agente não precisar adivinhar quais hosts pertencem a um grupo.

export const MENTION_NOTE = "[NetOps — menções]";   // i18n-ok: AI-context marker (matched by text)

// Loaded as plain source by node tests: no imports; globalThis.netopsT with the Portuguese fallback.
// Only the menu labels are translated; the text sent to the agent (expandMentions/addQuoteNote) stays as is.
const tr = (key, vars, fallback) => { const out = globalThis.netopsT ? globalThis.netopsT(key, vars) : key; return out === key ? fallback : out; };

const norm = (s) => String(s == null ? "" : s).toLowerCase();
const tokenName = (s) => String(s).trim().replace(/\s+/g, "_");

// Mesmo slug de lib/pwvault.slugify (referência nvault://item/campo).
export const vaultSlug = (t) => String(t || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48).replace(/-+$/, "") || "item";

// Itens do Cofre de senhas (GET /vault/items) -> { id, title, template, fields: [{field, kind, ref}], token }.
export function buildVaultItems(resp) {
  return ((resp && resp.items) || []).map((it) => ({
    id: it.id, title: String(it.title || it.id), template: String(it.template_label || ""), token: "#senha:" + it.id,   // ID numérico estável
    fields: (it.values || []).map((v) => ({ field: v.field, kind: v.kind, ref: `nvault://${it.id}/${vaultSlug(v.field)}` })),
  }));
}

// Normaliza a resposta de GET /hosts em { hosts: [...], groups: [...] } já com o que o menu usa.
// `vaultResp` (opcional) = GET /vault/items; sem permissão/cofre, fica sem senhas.
export function buildCatalog(resp, vaultResp = null) {
  const rows = (resp && resp.hosts) || [];
  const hosts = rows.map((r) => {
    const e = r.effective || {}, x = r.explicit || {};
    const hostname = String(x.hostname || e.hostname || r.id);
    return { id: r.id, hostname, ip: String(e.mgmt_ip || x.mgmt_ip || ""), vendor: String(e.vendor || ""), group: String(x.group || ""),
             token: "#host:" + tokenName(hostname) };
  });
  const names = new Set([...((resp && resp.groups) || []), ...hosts.map((h) => h.group).filter(Boolean)]);
  const groups = [...names].sort().map((name) => ({
    name, token: "#group:" + tokenName(name), members: hosts.filter((h) => h.group === name),
  }));
  return { hosts, groups, vault: buildVaultItems(vaultResp) };
}

// Token em edição junto ao cursor: `#` no início ou depois de espaço, seguido de texto sem espaço.
// Devolve { start, end, query, kind } (o prefixo "host:"/"group:" digitado vira `kind`).
export function findMentionToken(text, caret) {
  const before = String(text).slice(0, caret);
  const m = /(^|\s)#([^\s#]*)$/.exec(before);
  if (!m) return null;
  const start = before.length - m[2].length - 1;
  let query = m[2], kind = null;
  const k = /^(host|group|senha):(.*)$/i.exec(query);
  if (k) { kind = k[1].toLowerCase(); query = k[2]; }
  return { start, end: caret, query, kind };
}

// Lista de sugestões: grupos (pelo nome) e hosts (hostname, id ou IP) que contêm a busca.
// Grupo e hosts com o mesmo termo aparecem juntos, cada um com seu rótulo.
export function searchMentions(catalog, query, kind = null, limit = 12) {
  const q = norm(query).replace(/_/g, " ").trim();
  const hit = (...fields) => !q || fields.some((f) => norm(f).replace(/_/g, " ").includes(q));
  const out = [];
  if (kind !== "host") {
    for (const g of catalog.groups) if (hit(g.name))
      out.push({ kind: "group", label: g.name, token: g.token, detail: tr("mentions.hosts_count", { count: g.members.length }, g.members.length + " host(s)"), rank: norm(g.name).startsWith(q) ? 0 : 1 });
  }
  if (kind !== "group") {
    for (const h of catalog.hosts) if (hit(h.hostname, h.id, h.ip))
      out.push({ kind: "host", label: h.hostname, token: h.token, detail: [h.ip, h.group].filter(Boolean).join(" · "), rank: norm(h.hostname).startsWith(q) ? 0 : 2 });
  }
  if (kind !== "host" && kind !== "group") {
    for (const v of catalog.vault || []) if (hit(v.title, String(v.id), v.template))
      out.push({ kind: "senha", label: `${v.title} (${v.id})`, token: v.token, detail: [v.template, tr("mentions.fields_count", { count: v.fields.length }, v.fields.length + " campo(s)")].filter(Boolean).join(" · "),
                 rank: norm(v.title).startsWith(q) || norm(v.id).startsWith(q) ? 1 : 3 });
  }
  out.sort((a, b) => a.rank - b.rank);     // estável: dentro do mesmo rank mantém a ordem (grupos antes de hosts)
  return out.slice(0, limit);
}

// Troca o token em edição pelo escolhido (+ espaço) e devolve o novo texto e a posição do cursor.
export function applyMention(text, tok, item) {
  const head = text.slice(0, tok.start) + item.token + " ";
  const rest = text.slice(tok.end).replace(/^ /, "");
  return { text: head + rest, caret: head.length };
}

// Acha no texto os tokens `#host:…`/`#group:…` que existem no inventário.
export function mentionsIn(text, catalog) {
  const found = { hosts: new Map(), groups: new Map(), vault: new Map() };
  const hostBy = new Map(catalog.hosts.map((h) => [norm(h.token), h]));
  const groupBy = new Map(catalog.groups.map((g) => [norm(g.token), g]));
  const vaultBy = new Map((catalog.vault || []).map((v) => [norm(v.token), v]));
  for (const m of String(text).matchAll(/(^|\s)(#(?:host|group|senha):[^\s#]+)/gi)) {
    const raw = norm(m[2]);
    for (const t of [raw, raw.replace(/[.,;:!?)]+$/, "")]) {   // 2ª tentativa: pontuação colada no fim da frase
      if (hostBy.has(t)) { found.hosts.set(hostBy.get(t).id, hostBy.get(t)); break; }
      if (groupBy.has(t)) { found.groups.set(groupBy.get(t).name, groupBy.get(t)); break; }
      if (vaultBy.has(t)) { found.vault.set(vaultBy.get(t).id, vaultBy.get(t)); break; }
    }
  }
  return found;
}

// Texto que vai ao agente: o que o usuário digitou + bloco com os IDs do inventário.
export function expandMentions(text, catalog) {
  if (!catalog) return text;
  const f = mentionsIn(text, catalog);
  if (!f.hosts.size && !f.groups.size && !f.vault.size) return text;
  const hostLine = (h) => `host id ${h.id} (${h.hostname}${h.ip ? ", " + h.ip : ""})`;
  const lines = [];
  for (const h of f.hosts.values()) lines.push(`- ${h.token} = ${hostLine(h)}`);
  for (const g of f.groups.values()) {
    lines.push(`- ${g.token} = grupo do inventário com ${g.members.length} host(s): ` +
      (g.members.length ? g.members.map(hostLine).join("; ") : "nenhum"));
  }
  for (const v of f.vault.values()) {
    lines.push(`- ${v.token} = item ${v.id} "${v.title}" do Cofre de senhas${v.template ? ` (template ${v.template})` : ""}; referências: ` +
      (v.fields.length ? v.fields.map((x) => `${x.ref} (${x.field}, ${x.kind === "secret" ? "segredo" : "texto"})`).join("; ") : "nenhum campo") +
      ". Use só via `nvault run -- <comando>` (scripts/tools/secrets/SKILL.md); nunca leia nem mostre o valor.");
  }
  return `${text}\n\n${MENTION_NOTE}\n${lines.join("\n")}`;
}

// Citações numeradas (**[n]** + "> trecho"): instrução ao agente para responder item a item citando "[n]",
// o que permite à tela transformar esses "[n]" em links de volta à citação.
export const QUOTE_NOTE = "[NetOps — citações]";   // i18n-ok: AI-context marker (matched by text)
export function addQuoteNote(text) {
  if (!/^\*\*\[\d+\]\*\*$/m.test(text) || String(text).includes(QUOTE_NOTE)) return text;
  return `${text}\n\n${QUOTE_NOTE}\nO usuário citou trechos de respostas suas, numerados **[n]**. Responda a cada um separadamente e, ao tratar de cada citação, escreva o número exatamente no formato [n] (ex.: [1], [2]) no início do trecho da resposta.`;
}

// Para exibir a bolha do usuário sem os blocos técnicos (ao vivo e no histórico relido).
export function stripMentionNote(text) {
  const t = String(text);
  const cuts = [MENTION_NOTE, QUOTE_NOTE].map((n) => t.indexOf("\n\n" + n + "\n")).filter((i) => i >= 0);
  return cuts.length ? t.slice(0, Math.min(...cuts)) : text;
}
