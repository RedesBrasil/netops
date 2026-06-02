// Entrypoint: router hash-based + shell (sidebar/topbar/vault banner) + mount.
import { render } from "preact";
import { html, useState, useEffect, api } from "./ui.js";
import { ToastHost, startVaultPolling } from "./ui.js";
import { LoginScreen } from "./components.js";
import { setOnUnauthorized, clearAuthToken } from "./api.js";
import { HostsPage, GroupsPage } from "./pages/hosts.js";
import { CredentialsPage } from "./pages/credentials.js";
import { TopologyPage } from "./pages/topology.js";
import { MemoryPage } from "./pages/memory.js";
import { BestPracticesPage, ConfigsPage } from "./pages/knowledge.js";
import { WorkflowsPage, AgentsPage } from "./pages/catalog.js";
import { ReportsPage, RunsPage, SettingsPage } from "./pages/view.js";
import { TerminalPage } from "./pages/terminal.js";
import { ClaudeCodePage } from "./pages/claude.js";

const ROUTES = {
  hosts: { label: "Hosts", comp: HostsPage, group: "Inventário" },
  groups: { label: "Grupos", comp: GroupsPage, group: "Inventário" },
  credentials: { label: "Credenciais", comp: CredentialsPage, group: "Inventário" },
  topology: { label: "Topologia", comp: TopologyPage, group: "Inventário" },
  memory: { label: "Memória", comp: MemoryPage, group: "Conhecimento" },
  practices: { label: "Boas práticas", comp: BestPracticesPage, group: "Conhecimento" },
  configs: { label: "Configurações", comp: ConfigsPage, group: "Conhecimento" },
  workflows: { label: "Workflows", comp: WorkflowsPage, group: "Conhecimento" },
  agents: { label: "Agentes", comp: AgentsPage, group: "Conhecimento" },
  reports: { label: "Relatórios", comp: ReportsPage, group: "Saída" },
  runs: { label: "Execuções", comp: RunsPage, group: "Saída" },
  claude: { label: "Claude Code", comp: ClaudeCodePage, group: "Sistema", flag: "claude_enabled" },
  terminal: { label: "Terminal", comp: TerminalPage, group: "Sistema", flag: "terminal_enabled" },
  settings: { label: "Configuração", comp: SettingsPage, group: "Sistema" },
};
const ORDER = ["Inventário", "Conhecimento", "Saída", "Sistema"];

function useHash() {
  const [hash, setHash] = useState(location.hash.slice(1) || "hosts");
  useEffect(() => {
    const on = () => setHash(location.hash.slice(1) || "hosts");
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

function App({ onLogout, showLogout }) {
  const route = useHash();
  const [meta, setMeta] = useState({ network_name: "NetOps" });
  const [theme, setTheme] = useState(localStorage.getItem("netops_theme") || "light");
  useEffect(() => { startVaultPolling(); api.get("/config/meta").then(setMeta).catch(() => {}); }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("netops_theme", theme); }, [theme]);

  async function doLogout() {
    try { await api.post("/auth/logout"); } catch (e) {}
    clearAuthToken();
    onLogout && onLogout();
  }

  const Page = (ROUTES[route] || ROUTES.hosts).comp;
  return html`<div class="shell">
    <div class="topbar">
      <span class="brand">NetOps Console</span>
      <span class="net">· ${meta.network_name}</span>
      <span class="spacer"></span>
      <button class="sm" onClick=${() => setTheme(theme === "light" ? "dark" : "light")}>
        ${theme === "light" ? "🌙 escuro" : "☀ claro"}</button>
      ${showLogout && html`<button class="sm" onClick=${doLogout}>Sair</button>`}
    </div>
    <${Sidebar} current=${route} meta=${meta} />
    <main class="content">
      <${Page} />
    </main>
    <${ToastHost} />
  </div>`;
}

// Gate de login: checa /auth/status; mostra a tela de login se exigido e não autenticado.
function Root() {
  const [gate, setGate] = useState("loading");   // "loading" | "login" | "app"
  const [authRequired, setAuthRequired] = useState(false);

  async function check() {
    try {
      const s = await api.get("/auth/status");
      setAuthRequired(!!s.auth_required);
      setGate(s.auth_required && !s.authenticated ? "login" : "app");
    } catch (e) {
      setGate("app");   // sem status (ex.: token inválido) — o App expõe o erro nos toasts
    }
  }
  useEffect(() => { setOnUnauthorized(() => setGate("login")); check(); }, []);

  if (gate === "loading") return html`<div class="boot">Carregando NetOps Console…</div>`;
  if (gate === "login") return html`<${LoginScreen} onAuthed=${() => { setAuthRequired(true); setGate("app"); }} />`;
  return html`<${App} onLogout=${() => setGate("login")} showLogout=${authRequired} />`;
}

render(html`<${Root} />`, document.getElementById("app"));
