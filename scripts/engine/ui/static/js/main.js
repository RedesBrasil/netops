// Entrypoint: router hash-based + shell (sidebar/topbar/vault banner) + mount.
import { render } from "preact";
import { html, useState, useEffect, api } from "./ui.js";
import { ToastHost, startVaultPolling, refreshMe, useMe, can, permLabel, meStore } from "./ui.js";
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
import { InboxPage } from "./pages/inbox.js";
import { InboxBell, useInboxSummary } from "./inbox.js";
import { UpdatesControl } from "./pages/updates.js";
import { TerminalPage } from "./pages/terminal.js";
import { HostTermPage } from "./pages/host-term.js";
import { DashboardPage } from "./pages/dashboard.js";
import { FilesPage } from "./pages/files.js";
import { UsersPage, AccessGroupsPage } from "./pages/users.js";
import { AuditPage } from "./pages/audit.js";
import { AccountPage } from "./pages/account.js";
import { ClaudeCodePage, ClaudeTopbarControls, ClaudeStatusDot, ClaudeSessionTitle, ClaudeProvider, ChatDock, useClaude } from "./pages/claude.js";
import { ProjectsPage, useProjects, useProjectDrag } from "./pages/projects.js";
import { isClaudeChatHash } from "./claude-sessions.js";

// perm = permissão exigida (services/authz.py / lib/accessdb.PERMISSIONS); hidden = fora do menu.
const ROUTES = {
  hosts: { label: "Hosts", comp: HostsPage, group: "Inventário", perm: "hosts.view" },
  groups: { label: "Grupos", comp: GroupsPage, group: "Inventário", perm: "hosts.view" },
  credentials: { label: "Credenciais", comp: CredentialsPage, group: "Inventário", perm: "credentials.view" },
  maps: { label: "Mapas", comp: MapsPage, group: "Inventário", perm: "hosts.view" },
  memory: { label: "Memória", comp: MemoryPage, group: "Conhecimento", perm: "knowledge.view" },
  practices: { label: "Boas práticas", comp: BestPracticesPage, group: "Conhecimento", perm: "knowledge.view" },
  configs: { label: "Configurações", comp: ConfigsPage, group: "Conhecimento", perm: "knowledge.view" },
  workflows: { label: "Workflows", comp: WorkflowsPage, group: "Conhecimento", perm: "knowledge.view" },
  agents: { label: "Agentes", comp: AgentsPage, group: "Conhecimento", perm: "knowledge.view" },
  scripts: { label: "Scripts / Skills", comp: ScriptsPage, group: "Conhecimento", perm: "scripts.view" },
  // Central de Avisos: alertas/avisos/pedidos de aprovação (tarefas agendadas, scripts, agentes). Também no sino do topo.
  inbox: { label: "Central de Avisos", comp: InboxPage, group: "Saída", badge: "inbox", perm: "inbox.view" },
  reports: { label: "Relatórios", comp: ReportsPage, group: "Saída", perm: "knowledge.view" },
  runs: { label: "Execuções", comp: RunsPage, group: "Saída", perm: "knowledge.view" },
  backups: { label: "Backups", comp: BackupsPage, group: "Saída", perm: "backups.view" },
  dashboard: { label: "Painel", comp: DashboardPage, group: "Sistema", perm: "dashboard.view" },
  schedules: { label: "Tarefas agendadas", comp: SchedulesPage, group: "Sistema", badge: "schedules", perm: "schedules.view" },
  claude: { label: "Claude Code", comp: ClaudeCodePage, group: "Sistema", flag: "claude_enabled", perm: "claude.use" },
  // Sem `group`: não vira item fixo da sidebar. Os itens do grupo "Projetos" são os projetos cadastrados (ver Sidebar).
  projects: { label: "Projetos", comp: ProjectsPage, flag: "claude_enabled", perm: "claude.use" },
  terminal: { label: "Terminal", comp: TerminalPage, group: "Sistema", flag: "terminal_enabled", perm: "server.terminal" },
  files: { label: "Arquivos", comp: FilesPage, group: "Sistema", flag: "files_enabled", perm: "server.files" },
  settings: { label: "Configuração", comp: SettingsPage, group: "Sistema", perm: "config" },
  users: { label: "Usuários", comp: UsersPage, group: "Sistema", perm: "users.manage" },
  "access-groups": { label: "Grupos de acesso", comp: AccessGroupsPage, group: "Sistema", perm: "users.manage" },
  audit: { label: "Auditoria", comp: AuditPage, group: "Sistema", perm: "audit.view" },
  account: { label: "Minha conta", comp: AccountPage, group: "Sistema", hidden: true },
};
const ORDER = ["Inventário", "Conhecimento", "Saída", "Projetos", "Sistema"];

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
function useScheduleBadge(enabled) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const load = () => api.get("/schedules/notifications").then((d) => alive && setN(d.unread || 0)).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    addEventListener("netops:schedules", load); addEventListener("focus", load);
    return () => { alive = false; clearInterval(t); removeEventListener("netops:schedules", load); removeEventListener("focus", load); };
  }, [enabled]);
  return n;
}

// Contadores dos itens do menu (badge vermelho): tarefas agendadas + Central de Avisos.
function useNavBadges(me) {
  const schedules = useScheduleBadge(can("schedules.view", me));
  const inbox = useInboxSummary(can("inbox.view", me)).badge || 0;
  return { schedules, inbox };
}

// Menu: some o que o servidor não liga (flag) e o que o grupo do usuário não permite (perm).
const routeVisible = (r, meta, me) => !r.hidden && (!r.flag || meta[r.flag]) && can(r.perm, me);
function firstAllowed(meta, me) {
  const hit = Object.entries(ROUTES).find(([, r]) => routeVisible(r, meta, me));
  return hit ? hit[0] : "account";
}

function Sidebar({ current, hash = "", meta, me, open, onNavigate }) {
  const visible = ([, r]) => routeVisible(r, meta, me);
  const badges = useNavBadges(me);
  const showProjects = !!meta.claude_enabled && can("claude.use", me);   // grupo Projetos = quem usa o Claude
  const allProjects = useProjects(showProjects);
  const projects = allProjects.filter((p) => !p.archived);          // arquivados: só em #projects?arquivados=1
  const nArchived = allProjects.length - projects.length;
  const projDrag = useProjectDrag(projects);
  const projSeg = current === "projects" ? (hash.split("?")[0].split("/")[1] || "") : "";   // projeto (ou "new") aberto agora
  // Grupos abertos pelo usuário (persistido). Padrão: lista vazia = todos os grupos recolhidos.
  const [openGroups, setOpenGroups] = useState(() => {
    try { return JSON.parse(localStorage.getItem("netops_nav_groups") || "[]"); } catch { return []; }
  });
  const toggleGroup = (g) => setOpenGroups((cur) => {
    const next = cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g];
    localStorage.setItem("netops_nav_groups", JSON.stringify(next));
    return next;
  });
  const groups = ORDER.filter((g) => g === "Projetos" ? showProjects : Object.values(ROUTES).some((r) => r.group === g && routeVisible(r, meta, me)));
  return html`<nav class=${"sidebar" + (open ? " open" : "")} onClick=${(e) => { if (e.target.closest("a")) onNavigate(); }}>
    ${groups.map((g) => html`<div key=${g} class=${"nav-group" + (openGroups.includes(g) ? " is-open" : "")}>
      <button type="button" class="group-label group-toggle" aria-expanded=${openGroups.includes(g)}
        onClick=${() => toggleGroup(g)}>
        <span class="group-chevron">${openGroups.includes(g) ? "▾" : "▸"}</span>${g}
        ${(() => {   // grupo recolhido: mostra a soma dos contadores dos itens dele (não some da vista)
          if (openGroups.includes(g)) return "";
          const n = Object.values(ROUTES).filter((r) => r.group === g && r.badge && routeVisible(r, meta, me)).reduce((a, r) => a + (badges[r.badge] || 0), 0);
          return n > 0 ? html`<span class="nav-badge">${n}</span>` : "";
        })()}
      </button>
      ${openGroups.includes(g) && html`<div class="nav-children">
      ${g === "Projetos" && html`
        ${projects.map((p) => html`<a key=${p.id} href=${"#projects/" + p.id} title=${p.path + " — segure e arraste para reordenar"}
          ...${projDrag.props(p.id)} class=${(projSeg === p.id ? "active" : "") + projDrag.cls(p.id)}>${p.name}</a>`)}
        <a href="#projects/new" class=${"needs-projects-manage" + (projSeg === "new" ? " active" : "")}>＋ Novo projeto</a>
        ${nArchived > 0 && html`<a href="#projects?arquivados=1" class="nav-sub">🗄 Arquivados (${nArchived})</a>`}`}
      ${openGroups.includes(g) && Object.entries(ROUTES).filter(([, r]) => r.group === g).filter(visible).map(([key, r]) => html`
        <a key=${key} href=${"#" + key} class=${current === key ? "active" : ""}>${r.label}${r.badge && badges[r.badge] > 0
          ? html`<span class="nav-badge" title=${r.badge === "inbox" ? "não lidas + aguardando aprovação" : "execuções com resultado não lido"}>${badges[r.badge]}</span>` : ""}</a>`)}
      </div>`}
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
  const me = useMe();
  let route = hash.split("/")[0];
  const claude = useClaude();
  const [meta, setMeta] = useState({ network_name: "NetOps" });
  const [navOpen, setNavOpen] = useState(false);     // gaveta de navegação (mobile)
  const [collapsed, setCollapsed] = useState(localStorage.getItem("netops_sidebar") === "0");  // barra lateral escondida (desktop)
  useEffect(() => { localStorage.setItem("netops_sidebar", collapsed ? "0" : "1"); }, [collapsed]);
  const [moreOpen, setMoreOpen] = useState(false);   // folha de ações do topo (mobile)
  const [theme, setTheme] = useState(localStorage.getItem("netops_theme") || "light");
  useEffect(() => { startVaultPolling(); api.get("/config/meta").then(setMeta).catch(() => {}); }, []);
  // Esconde botões de ação sem permissão: a página marca o botão com `needs-<perm>` (ponto vira hífen,
  // ex.: needs-hosts-edit) e aqui vira display:none p/ cada permissão que o usuário NÃO tem.
  // É só conforto visual — quem bloqueia é o backend (403).
  useEffect(() => {
    let st = document.getElementById("netops-perm-style");
    if (!st) { st = document.createElement("style"); st.id = "netops-perm-style"; document.head.appendChild(st); }
    const missing = (me?.catalog || []).map((p) => p.key).filter((k) => !can(k, me));
    st.textContent = missing.map((k) => `.needs-${k.replace(/\./g, "-")}{display:none!important}`).join("\n");
  }, [me]);
  const inboxN = useInboxSummary(can("inbox.view", me)).badge || 0;
  useEffect(() => {   // (N) no título da aba do navegador = avisos pendentes da Central
    document.title = (inboxN ? `(${inboxN}) ` : "") + (meta.network_name ? `NetOps · ${meta.network_name}` : "NetOps");
  }, [meta.network_name, inboxN]);
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
  // Senha provisória: só a troca de senha até resolver (o backend devolve 403 no resto).
  const forced = !!(me && me.must_change_password);
  if (forced) route = "account";
  // Rota vazia/desconhecida -> primeira tela que o usuário pode ver (nem todo grupo vê Hosts).
  if (!ROUTES[route] && me) route = firstAllowed(meta, me);
  const target = ROUTES[route] || ROUTES.hosts;
  const denied = me && !forced && !can(target.perm, me);
  const Page = target.comp;
  // Chat encaixado à direita: só fora da página cheia (#claude) e com conversa viva.
  const isChat = isClaudeChatHash("#" + hash);   // #claude[/…] ou #projects/<proj>/<id|new>
  const dockVisible = !isChat && !!(claude && claude.hasSession) && can("claude.use", me);
  return html`<div class=${"shell" + (dockVisible ? " has-dock" : "") + (collapsed ? " nav-collapsed" : "")}>
    <div class="topbar">
      <button class="sm mob-only nav-toggle" aria-label="Menu" onClick=${() => { setMoreOpen(false); setNavOpen(!navOpen); }}>☰</button>
      ${isChat
        ? html`<${ClaudeSessionTitle} />`
        : html`<span class="brand">NetOps Console</span><span class="net">· ${meta.network_name}</span>`}
      <div id="topbar-slot" class="topbar-slot"></div>
      ${isChat && html`<${ClaudeStatusDot} />`}
      <div class="mob-only ib-slot"><${InboxBell} /></div>
      <button class="sm mob-only more-toggle" aria-label="Ações" onClick=${() => { setNavOpen(false); setMoreOpen(!moreOpen); }}>⋯</button>
      <div class=${"topbar-actions" + (moreOpen ? " open" : "")}
        onClick=${(e) => { if (e.target.closest("button") && !e.target.closest(".keep-open")) setMoreOpen(false); }}>
        ${isChat && html`<${ClaudeTopbarControls} />`}
        <div class="keep-open"><${UpdatesControl} part="version" /></div>
        <button class="sm" onClick=${() => setTheme(theme === "light" ? "dark" : "light")}>
          ${theme === "light" ? "🌙 escuro" : "☀ claro"}</button>
        ${me && showLogout && html`<a class="user-chip" href="#account" title=${"Minha conta — " + (me.email || me.username) + " — grupos: " + (me.groups || []).join(", ")}>👤 ${me.display_name || me.username}</a>`}
        <div class="desk-only ib-slot"><${InboxBell} /></div>
        ${showLogout && html`<button class="sm" onClick=${doLogout}>Sair</button>`}
      </div>
    </div>
    ${(navOpen || moreOpen) && html`<div class="mob-backdrop" onClick=${() => { setNavOpen(false); setMoreOpen(false); }}></div>`}
    <${Sidebar} current=${route} hash=${hash} meta=${meta} me=${me} open=${navOpen} onNavigate=${() => setNavOpen(false)} />
    <button class="sidebar-toggle" aria-label=${collapsed ? "Mostrar barra lateral" : "Esconder barra lateral"}
      title=${collapsed ? "Mostrar barra lateral" : "Esconder barra lateral"} onClick=${() => setCollapsed(!collapsed)}>${collapsed ? "›" : "‹"}</button>
    <main class=${"content" + (route === "maps" ? " maps-content" : "") + (route === "files" ? " files-content" : "")}>
      ${denied ? html`<div class="card forbidden-card"><h2>Sem permissão</h2>
          <p>Seu grupo de acesso não libera <b>${target.label}</b> (${permLabel(target.perm, me)}).</p>
          <p>Peça a um administrador para incluir você num grupo com essa permissão. <a href=${"#" + firstAllowed(meta, me)}>Voltar</a></p></div>`
        : forced ? html`<${AccountPage} forced=${true} />` : html`<${Page} />`}
    </main>
    ${dockVisible && html`<${ChatDock} />`}
    <${ToastHost} />
  </div>`;
}

// Gate de login: checa /auth/status; mostra a tela de login se exigido e não autenticado.
function Root() {
  const [gate, setGate] = useState("loading");   // "loading" | "login" | "app"
  const [authRequired, setAuthRequired] = useState(false);
  const [multiuser, setMultiuser] = useState(false);
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
        setMultiuser(!!s.multiuser);
        const needLogin = s.auth_required && !s.authenticated;
        if (!needLogin) await refreshMe();
        else meStore.set(null);
        if (current !== generation) return;
        setGate(needLogin ? "login" : "app");
      } catch (e) {
        if (current === generation) setGate("app");
      }
    }
    setOnUnauthorized(() => { generation++; meStore.set(null); setGate("login"); });
    // 403 password_change_required (senha provisória): relê o /auth/me -> o shell mostra a troca.
    const onPw = () => { refreshMe(); };
    addEventListener("netops:password-change", onPw);
    setOnAuthChange(check);
    check();
    return () => { generation++; clearTimeout(retry); setOnAuthChange(null); setOnUnauthorized(null); removeEventListener("netops:password-change", onPw); };
  }, []);

  if (migration) return html`<div class="boot"><section role=${migration.phase === "failed" ? "alert" : "status"} aria-live="polite">
    <h1>${migration.phase === "failed" ? "Migração de IDs bloqueada" : "Preparando o NetOps"}</h1>
    <p>Versão instalada: v${migration.version}</p><p>${migration.detail}</p>
    ${migration.phase === "failed" && html`<p>O código instalado foi mantido. Os dados não serão descartados nem substituídos para contornar o erro.</p>`}
    <button onClick=${() => location.reload()}>Verificar novamente</button>
  </section></div>`;
  if (gate === "loading") return html`<div class="boot">Carregando NetOps Console…</div>`;
  if (gate === "login") return html`<${LoginScreen} multiuser=${multiuser}
    onAuthed=${async () => { setAuthRequired(true); await refreshMe(); setMultiuser(true); setGate("app"); }} />`;
  return html`<${App} onLogout=${() => setGate("login")} showLogout=${authRequired} />`;
}

render(html`<${Root} />`, document.getElementById("app"));

// PWA: service worker (só em contexto seguro: HTTPS ou localhost). Falha aqui nunca afeta o console.
if ("serviceWorker" in navigator) {
  addEventListener("load", () => { navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {}); });
}
