// Terminal web (xterm.js) ligado a um PTY no backend via WebSocket (/api/term).
// Quadros: teclas -> binário; saída do PTY -> binário; resize -> texto JSON {resize:[cols,rows]}.
import { html, useRef, useEffect, useState, t } from "../ui.js";
import { VaultBanner } from "../components.js";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { authToken } from "../api.js";
import { registerTermLinks } from "../term-links.js";

// Status values are internal (also compared below); only the label is translated.
const STATUS_KEYS = {
  conectado: "terminal.status_connected", conectando: "terminal.status_connecting",
  desconectado: "terminal.status_disconnected", desabilitado: "terminal.status_disabled", erro: "terminal.status_error",
};

const THEME = {
  background: "#11161c", foreground: "#e6ebf1", cursor: "#4aa3e0",
  selectionBackground: "#2a4866", black: "#11161c", brightBlack: "#5b6675",
};

export function TerminalPage() {
  const hostRef = useRef(null);
  const [status, setStatus] = useState("conectando");
  const [gen, setGen] = useState(0);

  useEffect(() => {
    const term = new Terminal({
      fontFamily: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
      fontSize: 13, cursorBlink: true, scrollback: 5000, theme: THEME,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    registerTermLinks(term); // URLs e ip:porta clicáveis (abre em aba nova)
    term.open(hostRef.current);
    try { fit.fit(); } catch (e) {}

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/term`
      + `?auth=${encodeURIComponent(authToken())}`);
    ws.binaryType = "arraybuffer";
    const enc = new TextEncoder();
    const sendResize = () => { if (ws.readyState === 1) ws.send(JSON.stringify({ resize: [term.cols, term.rows] })); };

    ws.onopen = () => { setStatus("conectado"); sendResize(); term.focus(); };
    ws.onmessage = (e) => {
      if (typeof e.data === "string") term.write(e.data);
      else term.write(new Uint8Array(e.data));
    };
    ws.onclose = (e) => {
      setStatus(e.code === 4403 ? "desabilitado" : "desconectado");
      if (e.code === 4403)
        term.write(`\r\n\x1b[33m${t("terminal.disabled_on_server")}\x1b[0m\r\n`);
      else term.write(`\r\n\x1b[31m${t("terminal.session_ended")}\x1b[0m\r\n`);
    };
    ws.onerror = () => setStatus("erro");

    const dataSub = term.onData((d) => { if (ws.readyState === 1) ws.send(enc.encode(d)); });
    const onWinResize = () => { try { fit.fit(); sendResize(); } catch (e) {} };
    addEventListener("resize", onWinResize);
    let ro = null;
    if (window.ResizeObserver) { ro = new ResizeObserver(onWinResize); ro.observe(hostRef.current); }

    return () => {
      removeEventListener("resize", onWinResize);
      if (ro) ro.disconnect();
      dataSub.dispose();
      try { ws.close(); } catch (e) {}
      term.dispose();
    };
  }, [gen]);

  const badge = { conectado: "ok", conectando: "", desconectado: "warn", desabilitado: "danger", erro: "danger" }[status] || "";
  const statusLabel = STATUS_KEYS[status] ? t(STATUS_KEYS[status]) : status;
  return html`<div class="term-page">
    <div class="page-title">
      <h1>${t("terminal.title")}</h1>
      <span class="badge ${badge}">${statusLabel}</span>
      <span class="spacer"></span>
      <span class="help mono">${t("terminal.help_shell")}</span>
      ${(status === "desconectado" || status === "erro") &&
        html`<button class="sm" onClick=${() => setGen((g) => g + 1)}>${t("terminal.reconnect")}</button>`}
    </div>
    <${VaultBanner} />
    <div class="term-host" ref=${hostRef}></div>
  </div>`;
}
