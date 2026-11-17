// Links clicáveis no terminal web (xterm.js): URLs (http/https/ftp, www.) e ip:porta (10.0.0.1:8006,
// [::1]:80 etc.). Usa a API nativa registerLinkProvider do xterm (sem addon extra). Clique abre numa aba nova.
// ip:porta vira https:// nas portas de HTTPS conhecidas (443, 8443, 8006 PVE, 8007 PBS...) e http:// nas demais.
// 0.0.0.0 e loopback (127.x) não viram link: no navegador do usuário apontariam para a máquina errada.
// findLinks é pura (sem DOM): tests/term-links.test.mjs.

const OCT = String.raw`(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)`;
const IP4 = String.raw`(?:${OCT}\.){3}${OCT}`;
const PORT = String.raw`(?:6553[0-5]|655[0-2]\d|65[0-4]\d\d|6[0-4]\d{3}|[1-9]\d{0,3})`;
const PATH = String.raw`(?:\/[^\s<>"'\x60\x00-\x1f\x7f-\x9f]*)?`;
const RULES = [
  ["url", String.raw`\b(?:https?|ftp):\/\/[^\s<>"'\x60\x00-\x1f\x7f-\x9f]+`],
  ["www", String.raw`(?<![\w/.@-])www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::${PORT})?${PATH}`],
  ["ip6", String.raw`(?<![\w:.\]])\[[0-9a-f:]*:[0-9a-f:]*\]:${PORT}(?!\d)${PATH}`],
  ["ip4", String.raw`(?<![\w.\-])${IP4}:${PORT}(?![\w])${PATH}`],
];
const RE = new RegExp(RULES.map(([, r]) => `(${r})`).join("|"), "gi");
const HTTPS_PORTS = new Set(["443", "8443", "9443", "8006", "8007", "943", "4443"]);

// Tira pontuação que costuma colar no fim ("veja http://x.com/a)." ) e parênteses/colchetes sem par.
function trimTail(s) {
  for (;;) {
    const last = s[s.length - 1];
    if (/[.,;:!?'"]/.test(last)) { s = s.slice(0, -1); continue; }
    const pairs = { ")": "(", "]": "[", "}": "{" };
    if (pairs[last] && (s.split(last).length - 1) > (s.split(pairs[last]).length - 1)) { s = s.slice(0, -1); continue; }
    return s;
  }
}

function toUrl(kind, text) {
  if (kind === "url") return text;
  if (kind === "www") return "https://" + text;
  const m = /^(\[[^\]]+\]|[^:]+):(\d+)/.exec(text);
  const host = m[1];
  if (kind === "ip4" && (/^(?:0\.0\.0\.0|127\.)/.test(host))) return null;
  if (kind === "ip6" && /^\[(?:::1?|0*:)*\]$/.test(host)) return null;
  return (HTTPS_PORTS.has(m[2]) ? "https://" : "http://") + text;
}

// -> [{ start, end (exclusivo), text, url }]
export function findLinks(line) {
  const out = [];
  RE.lastIndex = 0;
  let m;
  while ((m = RE.exec(line))) {
    const kind = RULES[m.slice(1).findIndex((g) => g !== undefined)][0];
    const text = trimTail(m[0]);
    if (!text) continue;
    const url = toUrl(kind, text);
    if (!url) continue;
    out.push({ start: m.index, end: m.index + text.length, text, url });
  }
  return out;
}

// Registra o provedor no Terminal do xterm. Trata linhas quebradas (wrap): o link pode atravessar linhas.
export function registerTermLinks(term, open = (url) => window.open(url, "_blank", "noopener,noreferrer")) {
  return term.registerLinkProvider({
    provideLinks(y, callback) {
      const buf = term.buffer.active;
      let first = y - 1;
      while (first > 0 && buf.getLine(first)?.isWrapped) first--;
      let last = y - 1;
      while (buf.getLine(last + 1)?.isWrapped) last++;
      let text = "";
      const cells = []; // índice da string -> {x, y} (1-based) da célula
      for (let ly = first; ly <= last; ly++) {
        const line = buf.getLine(ly);
        if (!line) continue;
        for (let x = 0; x < line.length; x++) {
          const c = line.getCell(x);
          if (!c || c.getWidth() === 0) continue;
          const ch = c.getChars() || " ";
          for (let k = 0; k < ch.length; k++) { text += ch[k]; cells.push({ x: x + 1, y: ly + 1 }); }
        }
      }
      const links = [];
      for (const l of findLinks(text)) {
        const a = cells[l.start], b = cells[l.end - 1];
        if (!a || !b || y < a.y || y > b.y) continue;
        links.push({
          range: { start: { x: a.x, y: a.y }, end: { x: b.x, y: b.y } },
          text: l.text,
          activate: () => open(l.url),
        });
      }
      callback(links.length ? links : undefined);
    },
  });
}
