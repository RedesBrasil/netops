// Rota central: #menu/seg1/seg2?chave=valor  (regra: core/rules/urls-navegacao.md)
import { useState, useEffect } from "preact/hooks";

export function parseRoute(hash = location.hash) {
  const raw = String(hash || "").replace(/^#/, "");
  const q = raw.indexOf("?");
  const path = q < 0 ? raw : raw.slice(0, q);
  const params = {};
  if (q >= 0) for (const [k, v] of new URLSearchParams(raw.slice(q + 1))) params[k] = v;
  const safe = (s) => { try { return decodeURIComponent(s); } catch { return s; } };
  const parts = path.split("/").filter(Boolean).map(safe);
  return { menu: parts[0] || "", segments: parts.slice(1), params };
}

// Só grava parâmetros com valor (URL limpa quando nada está filtrado).
export function buildRoute({ menu, segments = [], params = {} }) {
  const path = [menu, ...segments].map(encodeURIComponent).join("/");
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== "" && v != null) qs.set(k, v);
  const s = qs.toString();
  return "#" + path + (s ? "?" + s : "");
}

// Navega: replace=true não cria entrada no histórico (filtros ao digitar).
export function navigate(route, { replace = false } = {}) {
  const hash = typeof route === "string" ? route : buildRoute(route);
  if (location.hash === hash) return;
  if (replace) { history.replaceState(null, "", hash); dispatchEvent(new Event("hashchange")); }
  else location.hash = hash;
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute());
  useEffect(() => {
    const on = () => setRoute(parseRoute());
    addEventListener("hashchange", on); return () => removeEventListener("hashchange", on);
  }, []);
  return route;
}
