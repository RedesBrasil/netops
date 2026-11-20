// Abre o terminal web de host (#hostterm/<id>?method=&port=) numa JANELA NOVA.
// Usado pelo botão "⌨ Acessar" (pages/host-term.js), por links no markdown (components.js) e pela
// abertura automática quando o agente da aba Claude responde com o link (pages/claude.js).
// Sem imports de páginas: evita ciclo components.js <-> host-term.js.
import { toast, t } from "./ui.js";

// Mesmo nome de janela por host+método+porta: pedir de novo foca a janela que já está aberta.
export function openTermHref(href, { fallbackHere = false } = {}) {
  const hash = href.slice(href.indexOf("#"));
  const m = /^#hostterm\/([^?]+)\?(.*)$/.exec(hash) || [];
  const qs = new URLSearchParams(m[2] || "");
  const name = `netops-term-${m[1] || "x"}-${qs.get("method") || ""}-${qs.get("port") || ""}`.replace(/[^\w-]/g, "_");
  const w = window.open(location.pathname + hash, name, "popup,width=1100,height=700");
  if (w) { try { w.focus(); } catch (e) {} return true; }
  if (fallbackHere) location.hash = hash.slice(1);
  return false;
}

// Abertura automática a partir do texto do agente (sem clique do usuário: o navegador pode
// bloquear o pop-up -> avisa e o link continua na resposta para um clique).
const autoOpened = new Set();
export function autoOpenFromText(text, scope = "") {
  // Só links markdown COMPLETOS "](#hostterm/...)": o texto chega em pedaços (stream) e um link
  // pela metade abriria a URL errada.
  for (const [, href] of (text || "").matchAll(/\]\((#hostterm\/[^\s)]+)\)/g)) {
    const key = scope + "|" + href;
    if (autoOpened.has(key)) continue;
    autoOpened.add(key);
    if (!openTermHref(href))
      toast.info(t("host_term.popup_blocked_link"));
  }
}
