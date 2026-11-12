// Editor visual de Markdown (WYSIWYG): o usuário formata com botões, sem saber a sintaxe.
// Internamente: Markdown -> HTML (marked) -> contenteditable -> Markdown (turndown).
// O DOM é a fonte da verdade enquanto o editor está aberto (nunca regravar por 'value': perderia o cursor).
// O Markdown só é regerado quando o usuário EDITA (evento input); abrir/ler nunca reformata o arquivo.
import { marked } from "marked";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";
import { html, useRef, useEffect, useState } from "./ui.js";

function makeTurndown() {
  const td = new TurndownService({
    headingStyle: "atx", bulletListMarker: "-", codeBlockStyle: "fenced",
    emDelimiter: "*", strongDelimiter: "**", hr: "---",
  });
  td.use(gfm);
  // Escape mínimo: o padrão do turndown enche o texto de "\\_" e "\\-"; aqui só protegemos o que quebraria o Markdown.
  td.escape = (t) => t
    .replace(/\\/g, "\\\\").replace(/([*`<])/g, "\\$1")
    .replace(/(^|[^\w])_|_(?=[^\w]|$)/g, (m) => m.replace("_", "\\_"))
    .replace(/^(\s*)([#>+-])(\s)/gm, "$1\\$2$3").replace(/^(\s*\d+)\.(\s)/gm, "$1\\.$2");
  // Item de lista compacto ("- texto"), sem os 3 espaços nem linhas em branco do padrão.
  td.addRule("listItem", {
    filter: "li",
    replacement: (content, node, opts) => {
      const text = content.replace(/^\n+/, "").replace(/\n+$/, "").replace(/\n{2,}/g, "\n");
      const par = node.parentNode;
      const idx = par.nodeName === "OL" ? Array.prototype.indexOf.call(par.children, node) + (Number(par.getAttribute("start")) || 1) : 0;
      const prefix = par.nodeName === "OL" ? idx + ". " : opts.bulletListMarker + " ";
      return prefix + text.replace(/\n/g, "\n" + " ".repeat(prefix.length)) + (node.nextSibling ? "\n" : "");
    },
  });
  // <pre> sem <code> (criado pelo botão de bloco de código) também vira bloco cercado.
  td.addRule("preBlock", {
    filter: (n) => n.nodeName === "PRE" && !(n.firstChild && n.firstChild.nodeName === "CODE"),
    replacement: (_c, n) => "\n\n```\n" + n.textContent.replace(/\n$/, "") + "\n```\n\n",
  });
  return td;
}
let _td = null;
const toMarkdown = (el) => (_td ||= makeTurndown()).turndown(el.innerHTML).trim() + "\n";

function clean(s) {
  return s.replace(/<\/?(script|style|iframe|object|embed)[^>]*>/gi, "")
    .replace(/\son\w+="[^"]*"/gi, "").replace(/\son\w+='[^']*'/gi, "").replace(/javascript:/gi, "");
}
const toHtml = (md) => clean(marked.parse(md || "", { breaks: false }));

const exec = (cmd, val) => document.execCommand(cmd, false, val);

export function WysiwygEditor({ value, onChange }) {
  const ref = useRef(null);
  const [block, setBlock] = useState("p");

  useEffect(() => { ref.current.innerHTML = toHtml(value); exec("defaultParagraphSeparator", "p"); }, []);

  const emit = () => { onChange(toMarkdown(ref.current)); };
  const run = (cmd, val) => { ref.current.focus(); exec(cmd, val); emit(); syncBlock(); };
  const syncBlock = () => {
    const v = (document.queryCommandValue("formatBlock") || "p").toLowerCase().replace(/[<>]/g, "");
    setBlock(["h1", "h2", "h3", "blockquote", "pre"].includes(v) ? v : "p");
  };
  const setBlockType = (t) => run("formatBlock", t === "p" ? "p" : t);
  const inlineCode = () => {
    const sel = String(window.getSelection() || "");
    if (sel) run("insertHTML", `<code>${sel.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</code>`);
  };
  const link = () => {
    const url = prompt("Endereço do link (https://…):", "https://");
    if (url && url !== "https://") run("createLink", url);
  };
  const table = () => run("insertHTML",
    "<table><thead><tr><th>Coluna 1</th><th>Coluna 2</th></tr></thead><tbody><tr><td>&nbsp;</td><td>&nbsp;</td></tr></tbody></table><p><br></p>");
  const onPaste = (e) => {
    const t = e.clipboardData?.getData("text/plain");
    if (t == null) return;
    e.preventDefault();
    // Texto colado é tratado como Markdown (renderiza); HTML de outros sites é descartado.
    exec("insertHTML", toHtml(t).trim());
    emit();
  };
  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); link(); }
  };

  const B = (label, title, fn, cls = "") => html`<button type="button" class="wy-btn ${cls}" title=${title}
    onMouseDown=${(e) => e.preventDefault()} onClick=${fn}>${label}</button>`;

  return html`<div class="wy">
    <div class="wy-bar">
      <select class="wy-block" title="Tamanho / tipo do texto" value=${block}
        onChange=${(e) => setBlockType(e.target.value)}>
        <option value="p">Texto normal</option>
        <option value="h1">Título grande</option>
        <option value="h2">Título médio</option>
        <option value="h3">Título pequeno</option>
        <option value="blockquote">Citação</option>
        <option value="pre">Bloco de código</option>
      </select>
      ${B(html`<b>N</b>`, "Negrito (Ctrl+B)", () => run("bold"))}
      ${B(html`<i>I</i>`, "Itálico (Ctrl+I)", () => run("italic"))}
      ${B(html`<s>S</s>`, "Tachado", () => run("strikeThrough"))}
      ${B("</>", "Código em linha", inlineCode, "mono")}
      <span class="wy-sep"></span>
      ${B("• Lista", "Lista com marcadores", () => run("insertUnorderedList"))}
      ${B("1. Lista", "Lista numerada", () => run("insertOrderedList"))}
      ${B("Link", "Inserir link (Ctrl+K)", link)}
      ${B("Tabela", "Inserir tabela", table)}
      ${B("―", "Linha horizontal", () => run("insertHorizontalRule"))}
      <span class="wy-sep"></span>
      ${B("↶", "Desfazer (Ctrl+Z)", () => run("undo"))}
      ${B("↷", "Refazer (Ctrl+Y)", () => run("redo"))}
    </div>
    <div ref=${ref} class="md wy-area" contenteditable="true" spellcheck="true"
      onInput=${emit} onPaste=${onPaste} onKeyDown=${onKey}
      onKeyUp=${syncBlock} onMouseUp=${syncBlock}></div>
  </div>`;
}
