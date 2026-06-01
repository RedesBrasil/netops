// Entrypoint: router hash-based + shell (sidebar/topbar/vault banner) + mount.
import { render } from "preact";
import { html, useState, useEffect, api } from "./ui.js";
import { ToastHost, startVaultPolling } from "./ui.js";
import { VaultBanner } from "./components.js";
import { HostsPage, GroupsPage } from "./pages/hosts.js";
import { CredentialsPage } from "./pages/credentials.js";
import { TopologyPage } from "./pages/topology.js";
import { MemoryPage } from "./pages/memory.js";
import { KnowledgePage } from "./pages/knowledge.js";
import { CatalogPage } from "./pages/catalog.js";
import { ReportsPage, RunsPage, SettingsPage } from "./pages/view.js";

const ROUTES = {
  hosts: { label: "Hosts", comp: HostsPage, group: "Inventário" },
  groups: { label: "Grupos", comp: GroupsPage, group: "Inventário" },
  credentials: { label: "Credenciais", comp: CredentialsPage, group: "Inventário" },
  topology: { label: "Topologia", comp: TopologyPage, group: "Inventário" },
  memory: { label: "Memória", comp: MemoryPage, group: "Conhecimento" },
  knowledge: { label: "Boas práticas / Configs", comp: KnowledgePage, group: "Conhecimento" },
  catalog: { label: "Workflows & Agentes", comp: CatalogPage, group: "Conhecimento" },
  reports: { label: "Relatórios", comp: ReportsPage, group: "Saída" },
  runs: { label: "Execuções", comp: RunsPage, group: "Saída" },
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

function Sidebar({ current }) {
  return html`<nav class="sidebar">
    ${ORDER.map((g) => html`<div key=${g}>
      <div class="group-label">${g}</div>
      ${Object.entries(ROUTES).filter(([, r]) => r.group === g).map(([key, r]) => html`
        <a key=${key} href=${"#" + key} class=${current === key ? "active" : ""}>${r.label}</a>`)}
    </div>`)}
  </nav>`;
}

function App() {
  const route = useHash();
  const [net, setNet] = useState("NetOps");
  const [theme, setTheme] = useState(localStorage.getItem("netops_theme") || "light");
  useEffect(() => { startVaultPolling(); api.get("/config/meta").then((m) => setNet(m.network_name)).catch(() => {}); }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("netops_theme", theme); }, [theme]);

  const Page = (ROUTES[route] || ROUTES.hosts).comp;
  return html`<div class="shell">
    <div class="topbar">
      <span class="brand">NetOps Console</span>
      <span class="net">· ${net}</span>
      <span class="spacer"></span>
      <button class="sm" onClick=${() => setTheme(theme === "light" ? "dark" : "light")}>
        ${theme === "light" ? "🌙 escuro" : "☀ claro"}</button>
    </div>
    <${Sidebar} current=${route} />
    <main class="content">
      <${VaultBanner} />
      <${Page} />
    </main>
    <${ToastHost} />
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
