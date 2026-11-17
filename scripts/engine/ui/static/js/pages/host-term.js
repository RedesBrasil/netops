// Terminal web de HOST (SSH/Telnet) — abre numa janela própria, já autenticado pelo servidor.
// URL: #hostterm/<id>?method=ssh|telnet&port=N  (core/rules/urls-navegacao.md)
// WebSocket /api/term/host/<id>: teclas -> binário; resize -> JSON {resize:[c,r]};
// servidor -> binário (saída) ou JSON {status, ...}. A senha nunca passa pelo navegador.
import { html, useRef, useEffect, useState, Modal, api, refreshVault, toast } from "../ui.js";
import { UnlockModal } from "../components.js";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { authToken } from "../api.js";
import { useRoute } from "../route.js";
import { openTermHref } from "../term-link.js";
import { FileBrowser, ToolIcon } from "../file-browser.js";
import { createHighlighter } from "../term-highlight.js";
import { registerTermLinks } from "../term-links.js";

const TERM_METHODS = ["ssh", "telnet"];
const DEFAULT_PORT = { ssh: 22, telnet: 23 };
const THEME = {
  background: "#11161c", foreground: "#e6ebf1", cursor: "#4aa3e0",
  selectionBackground: "#2a4866", black: "#11161c", brightBlack: "#5b6675",
  // cores "bright" vivas como no MobaXterm (usadas também pelo realce de IP/MAC/erros)
  brightRed: "#ff5f5f", brightGreen: "#5fd75f", brightYellow: "#ffd75f", brightMagenta: "#ff5fff",
};

// Mesma regra do backend (host_term_svc.access_entries): principal + extra_access, só ssh/telnet,
// sem duplicata método+porta; extra sem credencial herda a do host.
export function terminalEntries(row) {
  const eff = row.effective || {};
  const principal = eff.access || {};
  const items = [{ method: principal.method || "ssh", port: principal.port, credential: eff.credential },
    ...(eff.extra_access || row.explicit?.extra_access || []).map((x) => ({ method: x.method, port: x.port, credential: x.credential || eff.credential }))];
  const out = []; const seen = new Set();
  for (const it of items) {
    const method = String(it.method || "").toLowerCase();
    if (!TERM_METHODS.includes(method)) continue;
    const port = Number(it.port) || DEFAULT_PORT[method];
    if (seen.has(`${method}:${port}`)) continue;
    seen.add(`${method}:${port}`);
    out.push({ method, port, credential: it.credential || "" });
  }
  return out;
}

// Acesso web (http/https) — espelho de terminal_access.web_entries (mudar os dois juntos).
const WEB_METHODS = ["http", "https"];
const WEB_DEFAULT_PORT = { http: 80, https: 443 };
const APP_BY_VENDOR = { proxmox: "proxmox", zabbix: "zabbix" };   // = web_login.APP_BY_VENDOR
const APP_DEFAULT_PATH = { zabbix: "/zabbix" };                 // = web_login.APP_DEFAULT_PATH
export function webEntries(row) {
  const eff = row.effective || {};
  const principal = eff.access || {};
  const defaultApp = APP_BY_VENDOR[String(eff.vendor || "").toLowerCase()] || "";
  const items = [{ method: principal.method, port: principal.port, credential: eff.credential },
    ...(eff.extra_access || row.explicit?.extra_access || []).map((x) => ({ ...x, credential: x.credential || eff.credential }))];
  const out = []; const seen = new Set();
  for (const it of items) {
    const method = String(it.method || "").toLowerCase();
    if (!WEB_METHODS.includes(method)) continue;
    const port = Number(it.port) || WEB_DEFAULT_PORT[method];
    if (seen.has(`${method}:${port}`)) continue;
    seen.add(`${method}:${port}`);
    const app = String(it.app || defaultApp || "").toLowerCase();
    out.push({ kind: "web", method, port, credential: it.credential || "", app, path: it.path || APP_DEFAULT_PATH[app] || "/" });
  }
  return out;
}

export function accessEntries(row) {
  return [...terminalEntries(row).map((e) => ({ kind: "term", ...e })), ...webEntries(row)];
}

// Abre a interface web numa ABA nova já autenticada. O servidor faz o login (POST /web-launch) e devolve o
// "handoff": um formulário que a própria aba envia ao host (o cookie é gravado pelo host). Sem navegador
// controlado pelo servidor. A aba é aberta ANTES do await (senão o pop-up é bloqueado).
// Apps cujo login termina numa tela intermediária do próprio host (Proxmox: 301 -> /api2/html): o POST roda
// numa janelinha auxiliar (cookie é por navegador, vale p/ todas as abas) e a aba principal só mostra
// "Autenticando…" e vai direto para a interface. Janelinha barrada pelo bloqueador = POST na própria aba.
const AUX_LOGIN_APPS = ["proxmox"];

export async function openWebLaunch(id, entry) {
  const name = `netops-web-${id}-${entry.port}`.replace(/[^\w-]/g, "_");
  const w = window.open("about:blank", name);
  if (!w) { toast("err", "Pop-up bloqueado: permita pop-ups para este site e tente de novo."); return; }
  let aux = null;
  if (AUX_LOGIN_APPS.includes(entry.app)) {
    try { aux = window.open("about:blank", name + "-auth", "popup,width=420,height=180"); } catch (e) { aux = null; }
  }
  const say = (win, text) => { try { win.document.title = text; win.document.body.style.cssText = "font:16px sans-serif;background:#11161c;color:#e6ebf1;padding:2em"; win.document.body.textContent = text; } catch (e) {} };
  say(w, `Autenticando em ${entry.app || "host"}… redirecionando.`);
  if (aux) say(aux, "Autenticando…");
  try {
    const r = await api.post(`/hosts/${encodeURIComponent(id)}/web-launch`, { method: entry.method, port: entry.port });
    if (r.mode === "form_post") {
      const target = aux ? name + "-auth" : name;
      const f = document.createElement("form");
      f.method = "POST"; f.action = r.action; f.target = target; f.style.display = "none";
      for (const [k, v] of Object.entries(r.fields || {})) {
        const i = document.createElement("input"); i.type = "hidden"; i.name = k; i.value = v; f.appendChild(i);
      }
      document.body.appendChild(f); f.submit(); f.remove();     // os campos saem da página na hora
      if (r.then_url) setTimeout(() => {
        try { w.location.href = r.then_url; w.focus(); } catch (e) {}
        if (aux) setTimeout(() => { try { aux.close(); } catch (e) {} }, 400);
      }, (r.then_delay_ms || 0) + (aux ? 300 : 0));
      else if (aux) setTimeout(() => { try { aux.close(); } catch (e) {} }, 1500);
    } else if (r.then_url) {
      if (aux) { try { aux.close(); } catch (e) {} }
      w.location.href = r.then_url;
      if (r.note) toast("info", r.note);
    }
  } catch (e) {
    try { w.close(); } catch (e2) {}
    if (aux) { try { aux.close(); } catch (e2) {} }
    toast("err", `Acesso web: ${e.message || e}`);
  }
}

export function openEntry(id, entry) {
  return entry.kind === "web" ? openWebLaunch(id, entry) : openHostTerminal(id, entry);
}

export function hostTermUrl(id, entry) {
  return `#hostterm/${encodeURIComponent(id)}?method=${entry.method}&port=${entry.port}`;
}

// Janela nova (uma por host+método: clicar de novo foca a mesma janela). Popup bloqueado: abre aqui.
export function openHostTerminal(id, entry) {
  openTermHref(hostTermUrl(id, entry), { fallbackHere: true });
}

// Popup de escolha quando o host tem mais de um método de terminal.
export function AccessChooser({ host, entries, onClose }) {
  const name = host.explicit?.hostname || host.id;
  return html`<${Modal} title=${`Acessar ${name}`} onClose=${onClose}>
    <p class="help">Escolha o método de acesso (terminal ou interface web):</p>
    <div class="access-choices">
      ${entries.map((e, i) => html`<button key=${i} class=${i === 0 ? "primary" : ""}
          onClick=${() => { openEntry(host.id, e); onClose(); }}>
        <b>${e.kind === "web" ? "WEB " : ""}${e.method.toUpperCase()}</b> <span class="mono">:${e.port}</span>
        ${e.kind === "web"
          ? html` <span class="help">· ${e.app ? "login automático (" + e.app + ")" : "abre a página (login manual)"}</span>`
          : e.credential ? html` <span class="help">· ${e.credential}</span>` : html` <span class="help">· sem credencial (pede senha)</span>`}
      </button>`)}
    </div>
    <div class="modal-actions"><button onClick=${onClose}>Cancelar</button></div>
  <//>`;
}

export function HostTermPage() {
  const route = useRoute();
  const id = route.segments[0] || "";
  const method = route.params.method || "";
  const port = route.params.port || "";
  const hostRef = useRef(null);
  const [status, setStatus] = useState("conectando");
  const [info, setInfo] = useState({});
  const [gen, setGen] = useState(0);
  const [vaultAsk, setVaultAsk] = useState(false);   // popup "Destrancar o cofre"
  const wsRef = useRef(null);
  const [sftp, setSftp] = useState(null);
  const [highlight, setHighlightRaw] = useState(() => localStorage.getItem("netops_term_highlight") !== "0");
  const highlightRef = useRef(highlight);
  const setHighlight = (v) => { highlightRef.current = v; setHighlightRaw(v); localStorage.setItem("netops_term_highlight", v ? "1" : "0"); };              // token da sessão SFTP (painel de arquivos)

  useEffect(() => {
    document.title = `${(info.host || id)} · ${(method || "").toUpperCase()} — NetOps`;
  }, [info.host, id, method]);

  useEffect(() => {
    const term = new Terminal({
      fontFamily: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
      fontSize: 14, cursorBlink: true, scrollback: 10000, theme: THEME,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    registerTermLinks(term); // URLs e ip:porta clicáveis (abre em aba nova)
    term.open(hostRef.current);
    try { fit.fit(); } catch (e) {}

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const qs = new URLSearchParams({ method, cols: term.cols, rows: term.rows, auth: authToken() });
    if (port) qs.set("port", port);
    const ws = new WebSocket(`${proto}://${location.host}/api/term/host/${encodeURIComponent(id)}?${qs}`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    const enc = new TextEncoder();
    const sendResize = () => { if (ws.readyState === 1) ws.send(JSON.stringify({ resize: [term.cols, term.rows] })); };

    ws.onopen = () => { term.focus(); };
    // Realce estilo MobaXterm (IP/MAC/erros) só no texto sem cor própria; desligável no botão "Cores".
    const dec = new TextDecoder("utf-8");
    const hl = createHighlighter();
    let hlTimer = null;
    const flushHl = () => { hlTimer = null; const t = hl.flush(); if (t) term.write(t); };
    ws.onmessage = (e) => {
      if (typeof e.data !== "string") {
        if (!highlightRef.current) { const t = hl.flush(); if (t) term.write(t); term.write(new Uint8Array(e.data)); return; }
        const out = hl.feed(dec.decode(new Uint8Array(e.data), { stream: true }));
        if (out) term.write(out);
        clearTimeout(hlTimer);
        if (hl.pending) hlTimer = setTimeout(flushHl, 12);
        return;
      }
      try {
        const msg = JSON.parse(e.data);
        if (msg.status) {
          setStatus(msg.status); if (msg.host || msg.ip) setInfo((o) => ({ ...o, ...msg }));
          if (msg.status === "conectado") setSftp(msg.sftp || null);
          setVaultAsk(msg.status === "vault_locked");
        }
      } catch (err) { term.write(e.data); }
    };
    ws.onclose = (e) => {
      setVaultAsk(false);
      setSftp(null);
      if (e.code === 4403) {
        setStatus("desabilitado");
        term.write("\r\n\x1b[33mAcesso negado: faça login no console (ou o terminal está desligado: suba sem --read-only e com o terminal ligado).\x1b[0m\r\n");
      } else {
        setStatus((s) => (s === "erro" ? s : "desconectado"));
        term.write("\r\n\x1b[31m— sessão encerrada —\x1b[0m\r\n");
      }
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
  }, [id, method, port, gen]);

  // Fechou o popup: destrancou -> servidor relê a credencial (login automático); senão -> login manual.
  async function vaultClosed() {
    setVaultAsk(false);
    let st = {};
    try { st = await api.get("/vault/status"); } catch (e) {}
    refreshVault();
    const ws = wsRef.current;
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ vault: ["cache", "env"].includes(st.state) ? "retry" : "manual" }));
  }

  // Painel de arquivos à esquerda (como o MobaXterm): SEMPRE começa recolhido ao abrir um host (pedido do
  // usuário, 14/11/2026); abre pelo botão redondo da borda (igual ao do menu do NetOps) ou por "Arquivos" no topo.
  // Recolher só esconde: a pasta aberta continua. Largura lembrada.
  const [showFiles, setShowFiles] = useState(false);
  const [filesUsed, setFilesUsed] = useState(false);     // já foi aberto nesta janela (mantém montado)
  useEffect(() => { if (showFiles) setFilesUsed(true); }, [showFiles]);
  const [filesW, setFilesW] = useState(() => Number(localStorage.getItem("netops_hostterm_files_w")) || 380);
  const [dragW, setDragW] = useState(false);
  function startResize(e) {
    e.preventDefault();
    setDragW(true);
    const x0 = e.clientX, w0 = filesW;
    let w = w0;
    const move = (ev) => { w = Math.max(220, Math.min(innerWidth * 0.7, w0 + ev.clientX - x0)); setFilesW(w); };
    const up = () => { setDragW(false); localStorage.setItem("netops_hostterm_files_w", String(Math.round(w)));
      removeEventListener("pointermove", move); removeEventListener("pointerup", up); };
    addEventListener("pointermove", move); addEventListener("pointerup", up);
  }

  const badge = { conectado: "ok", conectando: "", desconectado: "warn", desabilitado: "danger", erro: "danger", vault_locked: "warn" }[status] || "";
  return html`<div class="hostterm-page">
    <div class="hostterm-bar">
      <b>${info.host || `host ${id}`}</b>
      <span class="mono">${info.ip || ""} · ${(method || "?").toUpperCase()}${port ? ":" + port : ""}${info.user ? " · " + info.user : ""}</span>
      <span class="badge ${badge}">${status === "vault_locked" ? "cofre trancado" : status}</span>
      <span class="spacer"></span>
      <button class=${"sm fm-toggle" + (highlight ? " on" : "")} onClick=${() => setHighlight(!highlight)}
        title="Realce de sintaxe (estilo MobaXterm): IPs e MACs em magenta, erros em vermelho, avisos em amarelo, OK em verde. Só no texto que chega sem cor.">
        <span class="term-hl-dot"></span> Cores</button>
      ${(method || "ssh") === "ssh" && html`<button class=${"sm fm-toggle" + (showFiles ? " on" : "")}
        title=${sftp ? "Painel de arquivos (SFTP) deste host" : "Arquivos: disponível com a sessão SSH conectada"}
        onClick=${() => setShowFiles(!showFiles)}><${ToolIcon} name="files" size=${14} /> Arquivos</button>`}
      ${(status === "desconectado" || status === "erro") &&
        html`<button class="sm" onClick=${() => { setStatus("conectando"); setGen((g) => g + 1); }}>Reconectar</button>`}
    </div>
    <div class="hostterm-body">
      ${filesUsed && (method || "ssh") === "ssh" && html`<div class="hostterm-files-wrap" style=${showFiles ? "" : "display:none"}>
          <${HostFilesPanel} token=${sftp} status=${status} width=${filesW} /></div>
        ${showFiles && html`<div class=${"hostterm-resizer" + (dragW ? " drag" : "")} onPointerDown=${startResize} title="Arraste para ajustar a largura"></div>`}`}
      ${(method || "ssh") === "ssh" && html`<button class="hostterm-files-toggle" style=${`left:${showFiles ? filesW - 12 : 6}px`}
        aria-label=${showFiles ? "Recolher arquivos" : "Mostrar arquivos"} title=${showFiles ? "Recolher arquivos" : "Mostrar arquivos (SFTP)"}
        onClick=${() => setShowFiles(!showFiles)}>${showFiles ? "‹" : "›"}</button>`}
      <div class="hostterm-host" ref=${hostRef}></div>
    </div>
    ${vaultAsk && html`<${UnlockModal} onClose=${vaultClosed} />`}
  </div>`;
}

// Painel SFTP do terminal: mesma conexão SSH (sem novo login). Pasta inicial = home do usuário no host.
// A pasta aberta fica na URL (?fpath=), em replace, para não poluir o Voltar da janela do terminal.
function HostFilesPanel({ token, status, width }) {
  const route = useRoute();
  const [home, setHome] = useState(null);
  const [err, setErr] = useState("");
  const [st, setSt] = useState(() => ({ path: route.params.fpath || "", q: "", sort: "", hidden: true, open: "" }));
  useEffect(() => {
    setErr(""); setHome(null);
    if (!token) return;
    api.get(`/files/info?src=${encodeURIComponent(token)}`)
      .then((i) => { setHome(i.home || "/"); setSt((s) => ({ ...s, path: s.path || i.home || "/" })); })
      .catch((e) => setErr(e.message || String(e)));
  }, [token]);
  useEffect(() => {
    if (!st.path) return;
    const u = new URL(location.href);
    const [h, q = ""] = u.hash.split("?");
    const p = new URLSearchParams(q); p.set("fpath", st.path);
    history.replaceState(null, "", h + "?" + p.toString());
  }, [st.path]);
  const setState = (patch) => setSt((s) => ({ ...s, ...patch }));
  const box = (msg) => html`<div class="hostterm-files" style=${`width:${width}px`}><div class="fm-msg-box">${msg}</div></div>`;
  if (!token) return box(status === "conectado"
    ? "Arquivos indisponíveis nesta sessão (gerenciador de arquivos desligado no console)."
    : status === "conectando" || status === "vault_locked" ? "Os arquivos aparecem aqui quando a sessão SSH conectar."
    : "Sessão SSH encerrada — reconecte para ver os arquivos.");
  if (err) return box(html`<span class="err">${err}</span>`);
  if (!home) return box("Abrindo SFTP…");
  return html`<div class="hostterm-files" style=${`width:${width}px`}>
    <${FileBrowser} src=${token} home=${home} state=${st} setState=${setState} compact />
  </div>`;
}
