// Realce de sintaxe da saída do terminal de host, no estilo do "Syntax highlighting → Standard keywords" do
// MobaXterm: pinta IPv4 e MAC (magenta), palavras de erro (vermelho), de aviso (amarelo) e de sucesso (verde).
// Só pinta texto SEM cor própria: se o equipamento já manda cores (MikroTik, ls --color, vim, htop),
// não interfere; telas cheias (alternate screen) ficam intactas. Puro (sem DOM): tests/term-highlight.test.mjs.

const ESC = "\x1b";
// Sequências de escape completas: CSI, OSC (até BEL ou ST), charset, e as de 1 caractere.
const ESC_RE = /\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()*+][0-9A-Za-z]|[=>78DEHMNOZc\\])/y;

const RULES = [
  // MAC antes do IPv4 (não colidem, mas a ordem deixa explícito)
  ["95", String.raw`\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b`],
  ["95", String.raw`(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\/(?:3[0-2]|[12]?\d))?(?![\d.]*\d)`],
  ["91", String.raw`\b(?:errors?|err|fail(?:ed|ure|ures|s)?|denied|refused|fatal|critical|crit|unreachable|timed out|timeout|invalid|not found|no such file or directory)\b`],
  ["93", String.raw`\b(?:warn(?:ing|ings)?|deprecated)\b`],
  ["92", String.raw`\b(?:ok|success(?:ful|fully)?|succeeded|passed|connected)\b`],
];
const TOKEN_RE = new RegExp(RULES.map(([, r]) => `(${r})`).join("|"), "gi");
const COLORS = RULES.map(([c]) => c);

export function colorize(text) {
  return text.replace(TOKEN_RE, (m, ...groups) => {
    const i = groups.findIndex((g, k) => k < COLORS.length && g !== undefined);
    return `${ESC}[${COLORS[i]}m${m}${ESC}[39m`;
  });
}

// SGR que deixa o texto "colorido por conta própria" (cor de frente/fundo, inverso). 0/39/49 limpam.
function sgrState(params, colored) {
  const ps = params === "" ? ["0"] : params.split(/[;:]/);
  let c = colored;
  for (let i = 0; i < ps.length; i++) {
    const n = Number(ps[i] || 0);
    if (n === 0) c = false;
    else if (n === 39 || n === 27) c = false;
    else if ((n >= 30 && n <= 37) || (n >= 90 && n <= 97) || n === 7) c = true;
    else if (n === 38 || n === 48) { c = c || n === 38; i += ps[i + 1] === "5" ? 2 : 4; }
  }
  return c;
}

// Fluxo com estado: guarda escape incompleto e a "palavra" parcial do fim do bloco (um IP pode chegar
// partido em dois pacotes). flush() devolve o que ficou retido (chamado por timer curto).
export function createHighlighter() {
  let colored = false, alt = false, pending = "";
  function feed(chunk, { final = false } = {}) {
    const s = pending + chunk;
    pending = "";
    let out = "", i = 0, plain = "";
    const emitPlain = () => { if (plain) { out += colored || alt ? plain : colorize(plain); plain = ""; } };
    while (i < s.length) {
      const j = s.indexOf(ESC, i);
      if (j < 0) { plain += s.slice(i); i = s.length; break; }
      plain += s.slice(i, j);
      ESC_RE.lastIndex = j;
      const m = ESC_RE.exec(s);
      if (!m) {
        if (!final && s.length - j < 64) { emitPlain(); pending = s.slice(j); return out; }   // escape partido
        plain += ESC; i = j + 1; continue;
      }
      emitPlain();
      const seq = m[0];
      out += seq;
      const csi = /^\x1b\[([?0-9;:]*)([a-zA-Z])$/.exec(seq);
      if (csi) {
        if (csi[2] === "m" && !csi[1].startsWith("?")) colored = sgrState(csi[1], colored);
        else if ((csi[2] === "h" || csi[2] === "l") && /^\?(1049|1047|47)$/.test(csi[1])) alt = csi[2] === "h";
      }
      i = j + seq.length;
    }
    if (!final && plain) {
      const tail = /[0-9A-Za-z.:/-]+$/.exec(plain);     // pode ser o começo de um IP/MAC/palavra
      if (tail && tail[0].length < plain.length + 1 && tail[0].length <= 40) {
        pending = tail[0];
        plain = plain.slice(0, plain.length - tail[0].length);
      }
    }
    emitPlain();
    return out;
  }
  return {
    feed,
    flush: () => (pending ? feed("", { final: true }) : ""),
    get pending() { return pending; },
  };
}
