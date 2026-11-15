/* Service worker do NetOps Console (PWA).
 *
 * O console é 100% dinâmico (API, WebSockets, terminal, aba Claude): NÃO há modo offline de
 * verdade. Este worker existe para (1) tornar o app instalável e (2) mostrar uma página
 * "sem conexão" decente em vez do erro do navegador quando o servidor está fora (ex.: reinício).
 *
 * Regras de segurança (não mudar sem pensar):
 *  - NUNCA interceptar /api/* nem WebSocket: tem credencial, sessão, tickets de download e dados de rede.
 *  - NUNCA guardar JS/CSS/HTML do app em cache: o servidor já revalida tudo (ETag); cache aqui
 *    serviria front velho contra backend novo depois de atualização.
 *  - Só a página offline e os ícones ficam em cache (CACHE abaixo).
 * Mudou este arquivo → o navegador instala a nova versão sozinho (sw.js é servido com no-cache).
 */
const CACHE = "netops-shell-v1";
const PRECACHE = [
  "/offline.html",
  "/icons/pwa/icon-192.png",
  "/icons/pwa/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || req.mode !== "navigate") return;   // só navegação; o resto vai direto à rede
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  event.respondWith(
    fetch(req).catch(() => caches.match("/offline.html").then((r) => r || Response.error()))
  );
});
