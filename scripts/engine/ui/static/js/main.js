// Entrypoint: router hash-based + shell (sidebar/topbar/vault banner) + mount.
import { render } from "preact";
import { html, useState, useEffect, api } from "./ui.js";
import { ToastHost, startVaultPolling } from "./ui.js";
import { LoginScreen } from "./components.js";
import { authToken, setOnAuthChange, setOnUnauthorized, clearAuthToken } from "./api.js";
import { HostsPage, GroupsPage } from "./pages/hosts.js";
import { CredentialsPage } from "./pages/credentials.js";
import { MapsPage } from "./pages/maps.js";
import { MemoryPage } from "./pages/memory.js";
import { BestPracticesPage, ConfigsPage } from "./pages/knowledge.js";
import { WorkflowsPage, AgentsPage } from "./pages/catalog.js";
import { ScriptsPage } from "./pages/scripts.js";
import { ReportsPage, RunsPage, SettingsPage } from "./pages/view.js";
import { BackupsPage } from "./pages/backups.js";
import { SchedulesPage } from "./pages/schedules.js";
import { UpdatesControl } from "./pages/updates.js";
import { TerminalPage } from "./pages/terminal.js";
import { HostTermPage } from "./pages/host-term.js";
import { FilesPage } from "./pages/files.js";
import { ClaudeCodePage, ClaudeTopbarControls, ClaudeStatusDot, ClaudeSessionTitle, ClaudeProvider, ChatDock, useClaude } from "./pages/claude.js";

const ROUTES = {
  hosts: { label: "Hosts", comp: HostsPage, group: "Inventário" },
  groups: { label: "Grupos", comp: GroupsPage, group: "Inventário" },
  credentials: { label: "Credenciais", comp: CredentialsPage, group: "Inventário" },
  maps: { label: "Mapas", comp: MapsPage, group: "Inventário" },
  memory: { label: "Memória", comp: MemoryPage, group: "Conhecimento" },
  practices: { label: "Boas práticas", comp: BestPracticesPage, group: "Conhecimento" },
  configs: { label: "Configurações", comp: ConfigsPage, group: "Conhecimento" },
  workflows: { label: "Workflows", comp: WorkflowsPage, group: "Conhecimento" },
  agents: { label: "Agentes", comp: AgentsPage, group: "Conhecimento" },
  scripts: { label: "Scripts / Skills", comp: ScriptsPage, group: "Conhecimento" },
  reports: { label: "Relatórios", comp: ReportsPage, group: "Saída" },
  runs: { label: "Execuções", comp: RunsPage, group: "Saída" },
  backups: { label: "Backups", comp: BackupsPage, group: "Saída" },
  schedules: { label: "Tarefas agendadas", comp: SchedulesPage, group: "Sistema", badge: "schedules" },
  claude: { label: "Claude Code", comp: ClaudeCodePage, group: "Sistema", flag: "claude_enabled" },
  terminal: { label: "Terminal", comp: TerminalPage, group: "Sistema", flag: "terminal_enabled" },
  files: { label: "Arquivos", comp: FilesPage, group: "Sistema", flag: "files_enabled" },
  settings: { label: "Configuração", comp: SettingsPage, group: "Sistema" },
};
const ORDER = ["Inventário", "Conhecimento", "Saída", "Sistema"];

function useHash() {
  const readHash = () => {
    const value = location.hash.slice(1).split("?")[0] || "hosts";
    if (value !== "topology") return value;
    // Links antigos abrem Mapas, sem carregar a página removida.
    history.replaceState(null, "", "#maps");
    return "maps";
  };
  const [hash, setHash] = useState(readHash);
  useEffect(() => {
    const on = () => setHash(readHash());
    addEventListener("hashchange", on); return () => removeEventListener("hashchange", on);
  }, []);
  return hash;
}

// Contador de notificações não lidas das tarefas agendadas (badge no menu). Polling leve +
// recarga imediata quando a página de tarefas marca algo como lido (evento netops:schedules).
function useScheduleBadge() {
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () => api.get("/schedules/notifications").then((d) => alive && setN(d.unread || 0)).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    addEventListener("netops:schedules", load); addEventListener("focus", load);
    return () => { alive = false; clearInterval(t); removeEventListener("netops:schedules", load); removeEventListener("focus", load); };
  }, []);
  return { schedules: n };
}

function Sidebar({ current, meta, open, onNavigate }) {
  const visible = ([, r]) => !r.flag || meta[r.flag];
  const badges = useScheduleBadge();
  return html`<nav class=${"sidebar" + (open ? " open" : "")} onClick=${(e) => { if (e.target.closest("a")) onNavigate(); }}>
    ${ORDER.map((g) => html`<div key=${g}>
      <div class="group-label">${g}</div>
      ${Object.entries(ROUTES).filter(([, r]) => r.group === g).filter(visible).map(([key, r]) => html`
        <a key=${key} href=${"#" + key} class=${current === key ? "active" : ""}>${r.label}${r.badge && badges[r.badge] > 0
          ? html`<span class="nav-badge" title="execuções com resultado não lido">${badges[r.badge]}</span>` : ""}</a>`)}
    </div>`)}
  </nav>`;
}

// A sessão do Claude vive AQUI, acima do roteador: o ClaudeProvider é montado uma vez e
// não desmonta ao trocar de rota, então a conversa (WS + turno) sobrevive à navegação.
function App({ onLogout, showLogout }) {
  return html`<${ClaudeProvider}><${Shell} onLogout=${onLogout} showLogout=${showLogout} /><//>`;
}

function Shell({ onLogout, showLogout }) {
  const hash = useHash();
  const route = hash.split("/")[0];
  const claude = useClaude();
  const [meta, setMeta] = useState({ network_name: "NetOps" });
  const [navOpen, setNavOpen] = useState(false);     // gaveta de navegação (mobile)
  const [collapsed, setCollapsed] = useState(localStorage.getItem("netops_sidebar") === "0");  // barra lateral escondida (desktop)
  useEffect(() => { localStorage.setItem("netops_sidebar", collapsed ? "0" : "1"); }, [collapsed]);
  const [moreOpen, setMoreOpen] = useState(false);   // folha de ações do topo (mobile)
  const [theme, setTheme] = useState(localStorage.getItem("netops_theme") || "light");
  useEffect(() => { startVaultPolling(); api.get("/config/meta").then(setMeta).catch(() => {}); }, []);
  useEffect(() => { document.title = meta.network_name ? `NetOps · ${meta.network_name}` : "NetOps"; }, [meta.network_name]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme; localStorage.setItem("netops_theme", theme);
    // PWA: cor da barra de título/status acompanha o tema (--surface).
    const m = document.querySelector('meta[name="theme-color"]'); if (m) m.content = theme === "dark" ? "#1a212b" : "#1b78c2";
  }, [theme]);

  async function doLogout() {
    const sid = authToken();
    try { await api.post("/auth/logout"); } catch (e) {}
    if (authToken() !== sid) return;
    clearAuthToken();
    onLogout && onLogout();
  }

  // Terminal de host abre numa janela própria: tela cheia, sem barra lateral/topo.
  if (route === "hostterm") return html`<${HostTermPage} /><${ToastHost} />`;
  const Page = (ROUTES[route] || ROUTES.hosts).comp;
  // Chat encaixado à direita: só fora da página cheia (#claude) e com conversa viva.
  const dockVisible = route !== "claude" && !!(claude && claude.hasSession);
  return html`<div class=${"shell" + (dockVisible ? " has-dock" : "") + (collapsed ? " nav-collapsed" : "")}>
    <div class="topbar">
      <button class="sm mob-only nav-toggle" aria-label="Menu" onClick=${() => { setMoreOpen(false); setNavOpen(!navOpen); }}>☰</button>
      ${route === "claude"
        ? html`<${ClaudeSessionTitle} />`
        : html`<span class="brand">NetOps Console</span><span class="net">· ${meta.network_name}</span>`}
      <div id="topbar-slot" class="topbar-slot"></div>
      ${route === "claude" && html`<${ClaudeStatusDot} />`}
      <button class="sm mob-only more-toggle" aria-label="Ações" onClick=${() => { setNavOpen(false); setMoreOpen(!moreOpen); }}>⋯</button>
      <div class=${"topbar-actions" + (moreOpen ? " open" : "")}
        onClick=${(e) => { if (e.target.closest("button") && !e.target.closest(".keep-open")) setMoreOpen(false); }}>
        ${route === "claude" && html`<${ClaudeTopbarControls} />`}
        <div class="keep-open"><${UpdatesControl} part="version" /></div>
        <button class="sm" onClick=${() => setTheme(theme === "light" ? "dark" : "light")}>
          ${theme === "light" ? "🌙 escuro" : "☀ claro"}</button>
        ${showLogout && html`<button class="sm" onClick=${doLogout}>Sair</button>`}
      </div>
    </div>
    ${(navOpen || moreOpen) && html`<div class="mob-backdrop" onClick=${() => { setNavOpen(false); setMoreOpen(false); }}></div>`}
    <${Sidebar} current=${route} meta=${meta} open=${navOpen} onNavigate=${() => setNavOpen(false)} />
    <button class="sidebar-toggle" aria-label=${collapsed ? "Mostrar barra lateral" : "Esconder barra lateral"}
      title=${collapsed ? "Mostrar barra lateral" : "Esconder barra lateral"} onClick=${() => setCollapsed(!collapsed)}>${collapsed ? "›" : "‹"}</button>
    <main class=${"content" + (route === "maps" ? " maps-content" : "") + (route === "files" ? " files-content" : "")}>
      <${Page} />
    </main>
    ${dockVisible && html`<${ChatDock} />`}
    <${ToastHost} />
  </div>`;
}

// Gate de login: checa /auth/status; mostra a tela de login se exigido e não autenticado.
function Root() {
  const [gate, setGate] = useState("loading");   // "loading" | "login" | "app"
  const [authRequired, setAuthRequired] = useState(false);
  const [migration, setMigration] = useState(null);

  useEffect(() => {
    let generation = 0;
    let retry;
    async function check() {
      clearTimeout(retry);
      const current = ++generation;
      const sentAuth = authToken();
      try {
        const meta = await api.get("/config/meta");
        if (current !== generation) return;
        if (meta.host_migration?.blocking) {
          setMigration({ ...meta.host_migration, version: meta.version });
          retry = setTimeout(check, 1000);
          return;
        }
        setMigration(null);
        const s = await api.get("/auth/status");
        if (current !== generation) return;
        if (sentAuth !== authToken()) return check();
        setAuthRequired(!!s.auth_required);
        setGate(s.auth_required && !s.authenticated ? "login" : "app");
      } catch (e) {
        if (current === generation) setGate("app");
      }
    }
    setOnUnauthorized(() => { generation++; setGate("login"); });
    setOnAuthChange(check);
    check();
    return () => { generation++; clearTimeout(retry); setOnAuthChange(null); setOnUnauthorized(null); };
  }, []);

  if (migration) return html`<div class="boot"><section role=${migration.phase === "failed" ? "alert" : "status"} aria-live="polite">
    <h1>${migration.phase === "failed" ? "Migração de IDs bloqueada" : "Preparando o NetOps"}</h1>
    <p>Versão instalada: v${migration.version}</p><p>${migration.detail}</p>
    ${migration.phase === "failed" && html`<p>O código instalado foi mantido. Os dados não serão descartados nem substituídos para contornar o erro.</p>`}
    <button onClick=${() => location.reload()}>Verificar novamente</button>
  </section></div>`;
  if (gate === "loading") return html`<div class="boot">Carregando NetOps Console…</div>`;
  if (gate === "login") return html`<${LoginScreen} onAuthed=${() => { setAuthRequired(true); setGate("app"); }} />`;
  return html`<${App} onLogout=${() => setGate("login")} showLogout=${authRequired} />`;
}

render(html`<${Root} />`, document.getElementById("app"));

// PWA: service worker (só em contexto seguro: HTTPS ou localhost). Falha aqui nunca afeta o console.
if ("serviceWorker" in navigator) {
  addEventListener("load", () => { navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {}); });
}
