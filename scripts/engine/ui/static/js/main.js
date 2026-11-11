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
import { UpdatesControl } from "./pages/updates.js";
import { TerminalPage } from "./pages/terminal.js";
import { ClaudeCodePage, ClaudeProvider, ChatDock, useClaude } from "./pages/claude.js";

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
  reports: { label: "Relatórios", comp: ReportsPage, group: "Saída" },
  runs: { label: "Execuções", comp: RunsPage, group: "Saída" },
  backups: { label: "Backups", comp: BackupsPage, group: "Saída" },
  scripts: { label: "Scripts", comp: ScriptsPage, group: "Sistema" },
  claude: { label: "Claude Code", comp: ClaudeCodePage, group: "Sistema", flag: "claude_enabled" },
  terminal: { label: "Terminal", comp: TerminalPage, group: "Sistema", flag: "terminal_enabled" },
  settings: { label: "Configuração", comp: SettingsPage, group: "Sistema" },
};
const ORDER = ["Inventário", "Conhecimento", "Saída", "Sistema"];

function useHash() {
  const readHash = () => {
    const value = location.hash.slice(1) || "hosts";
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

function Sidebar({ current, meta }) {
  const visible = ([, r]) => !r.flag || meta[r.flag];
  return html`<nav class="sidebar">
    ${ORDER.map((g) => html`<div key=${g}>
      <div class="group-label">${g}</div>
      ${Object.entries(ROUTES).filter(([, r]) => r.group === g).filter(visible).map(([key, r]) => html`
        <a key=${key} href=${"#" + key} class=${current === key ? "active" : ""}>${r.label}</a>`)}
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
  const route = hash.startsWith("claude/") ? "claude" : hash;
  const claude = useClaude();
  const [meta, setMeta] = useState({ network_name: "NetOps" });
  const [theme, setTheme] = useState(localStorage.getItem("netops_theme") || "light");
  useEffect(() => { startVaultPolling(); api.get("/config/meta").then(setMeta).catch(() => {}); }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("netops_theme", theme); }, [theme]);

  async function doLogout() {
    const sid = authToken();
    try { await api.post("/auth/logout"); } catch (e) {}
    if (authToken() !== sid) return;
    clearAuthToken();
    onLogout && onLogout();
  }

  const Page = (ROUTES[route] || ROUTES.hosts).comp;
  // Chat encaixado à direita: só fora da página cheia (#claude) e com conversa viva.
  const dockVisible = route !== "claude" && !!(claude && claude.hasSession);
  return html`<div class=${"shell" + (dockVisible ? " has-dock" : "")}>
    <div class="topbar">
      <span class="brand">NetOps Console</span>
      <span class="net">· ${meta.network_name}</span>
      <span class="spacer"></span>
      <${UpdatesControl} />
      <button class="sm" onClick=${() => setTheme(theme === "light" ? "dark" : "light")}>
        ${theme === "light" ? "🌙 escuro" : "☀ claro"}</button>
      ${showLogout && html`<button class="sm" onClick=${doLogout}>Sair</button>`}
    </div>
    <${Sidebar} current=${route} meta=${meta} />
    <main class=${"content" + (route === "maps" ? " maps-content" : "")}>
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
