// Terminal web (xterm.js) ligado a um PTY no backend via WebSocket (/api/term).
// Quadros: teclas -> binário; saída do PTY -> binário; resize -> texto JSON {resize:[cols,rows]}.
import { html, useRef, useEffect, useState } from "../ui.js";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { sessionToken } from "../api.js";

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
    term.open(hostRef.current);
    try { fit.fit(); } catch (e) {}

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/term?token=${encodeURIComponent(sessionToken())}`);
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
        term.write("\r\n\x1b[33mTerminal desabilitado no servidor. Suba com --enable-terminal (e sem --read-only).\x1b[0m\r\n");
      else term.write("\r\n\x1b[31m— sessão encerrada —\x1b[0m\r\n");
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
  return html`<div class="term-page">
    <div class="page-title">
      <h1>Terminal</h1>
      <span class="badge ${badge}">${status}</span>
      <span class="spacer"></span>
      <span class="help mono">shell real em /home/francisco/netops · execução de comandos</span>
      ${(status === "desconectado" || status === "erro") &&
        html`<button class="sm" onClick=${() => setGen((g) => g + 1)}>Reconectar</button>`}
    </div>
    <div class="term-host" ref=${hostRef}></div>
  </div>`;
}
