"""Projetos da aba Claude Code: registro (nome + pasta), navegação de pastas e `cwd` do agente.

Sem agente real: `_options()` só monta as opções; a retomada pós-restart é lida do arquivo de anotação.
"""
import pytest

import deps
from services import claude_svc, projects_svc as P


@pytest.fixture
def pasta(tmp_path_factory):
    # FORA do tmp_path: nos testes HTTP o NETOPS_ROOT é o tmp_path, e pasta dentro do NetOps é proibida.
    d = tmp_path_factory.mktemp("projetos") / "meu-site"
    d.mkdir()
    return d


# ------------------------------------------------------------------ registro
def test_criar_lista_e_slug(pasta):
    p = P.create("  Meu   Site  ", str(pasta))
    assert p["id"] == "meu-site" and p["name"] == "Meu Site"
    assert p["path"] == str(pasta.resolve()) and p["exists"] is True
    assert [x["id"] for x in P.list_projects()] == ["meu-site"]
    assert P.get("meu-site")["path"] == p["path"]
    assert P.path_of("meu-site") == p["path"]


def test_slug_colide_ganha_sufixo_e_acentos(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    assert P.create("Cálculo", str(a))["id"] == "calculo"
    assert P.create("Calculo", str(b))["id"] == "calculo-2"


def test_nome_new_nao_vira_id_reservado(pasta):
    assert P.create("new", str(pasta))["id"] != "new"


@pytest.mark.parametrize("nome,caminho,codigo", [
    ("", "/tmp", "empty_name"),
    ("x", "", "bad_path"),
    ("x", "relativo/pasta", "bad_path"),
    ("x", "/caminho/que/nao/existe/xyz", "path_not_found"),
])
def test_validacoes(nome, caminho, codigo):
    with pytest.raises(P.ProjectError) as e:
        P.create(nome, caminho)
    assert e.value.code == codigo


def test_arquivo_nao_e_pasta(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(P.ProjectError) as e:
        P.create("x", str(f))
    assert e.value.code == "not_a_dir"


def test_recusa_pasta_duplicada_e_a_do_netops(pasta):
    P.create("um", str(pasta))
    with pytest.raises(P.ProjectError) as e:
        P.create("dois", str(pasta))
    assert e.value.code == "duplicate_path" and e.value.status == 409
    with pytest.raises(P.ProjectError) as e:
        P.create("netops", str(deps.NETOPS_ROOT))
    assert e.value.code == "forbidden_path"


def test_renomear_mantem_id_e_remover_nao_apaga_a_pasta(pasta):
    P.create("Antigo", str(pasta))
    r = P.rename("antigo", "Novo nome")
    assert r["id"] == "antigo" and r["name"] == "Novo nome"
    assert P.delete("antigo") is True
    assert P.delete("antigo") is False
    assert P.get("antigo") is None
    assert pasta.is_dir()                     # só o registro some
    with pytest.raises(P.ProjectError):
        P.rename("antigo", "x")


def test_pasta_que_sumiu_nao_e_usada_pelo_agente(tmp_path):
    d = tmp_path / "efemera"
    d.mkdir()
    P.create("efemera", str(d))
    d.rmdir()
    assert P.get("efemera")["exists"] is False
    assert P.path_of("efemera") is None


def test_id_invalido_nunca_vira_caminho():
    for ruim in ("../etc", "a/b", "", "NEW", "new", "x" * 80, "a b"):
        assert P.get(ruim) is None


# ------------------------------------------------------------------ navegador de pastas
def test_browse_lista_so_pastas_e_esconde_ocultas(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "A").mkdir()
    (tmp_path / ".oculta").mkdir()
    (tmp_path / "arquivo.txt").write_text("x")
    r = P.browse(str(tmp_path))
    assert [d["name"] for d in r["dirs"]] == ["A", "b"]
    assert r["parent"] == str(tmp_path.parent)
    assert ".oculta" in [d["name"] for d in P.browse(str(tmp_path), hidden=True)["dirs"]]


def test_browse_raiz_nao_tem_pai():
    assert P.browse("/")["parent"] is None


def test_browse_inexistente_da_erro():
    with pytest.raises(P.ProjectError) as e:
        P.browse("/nao/existe/mesmo")
    assert e.value.code == "path_not_found"


# ------------------------------------------------------------------ cwd do agente
def test_padrao_continua_sendo_o_netops():
    s = claude_svc.ClaudeWebSession(persist=True)
    assert s._cwd == str(deps.NETOPS_ROOT) and s._is_project is False
    assert s._options().cwd == str(deps.NETOPS_ROOT)


def test_projeto_roda_na_pasta_dele(pasta):
    s = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))
    assert s._is_project is True
    assert s._options().cwd == str(pasta)


def test_anotacao_de_retomada_guarda_a_pasta_so_para_projetos(pasta):
    proj = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))
    proj.sid, proj._tracked, proj._busy = "p1", True, True
    proj._track()
    net = claude_svc.ClaudeWebSession(persist=True)
    net.sid, net._tracked, net._busy = "n1", True, True
    net._track()
    data = claude_svc._resume_load()
    assert data["p1"]["cwd"] == str(pasta)
    assert "cwd" not in data["n1"]            # formato antigo intacto p/ a aba Claude Code


def test_sessao_viva_so_vale_na_propria_pasta(pasta, tmp_path):
    sid = "11111111-1111-4111-8111-111111111111"
    s = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))
    claude_svc._LIVE[sid] = s
    try:
        assert claude_svc.project_session_exists(sid, str(pasta)) is True
        assert claude_svc.project_session_exists(sid, str(tmp_path)) is False   # outro projeto
        assert claude_svc.project_session_exists(sid) is False                  # nem a aba Claude Code
    finally:
        claude_svc._LIVE.pop(sid, None)


# ------------------------------------------------------------------ HTTP
@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setattr(deps.STATE, "enable_claude", True)
    return client


def test_http_exige_a_aba_claude_ligada(client):
    assert client.get("/api/projects").status_code == 403
    assert client.post("/api/projects", json={"name": "x", "path": "/tmp"}).status_code == 403


def test_http_crud_de_projeto(api, pasta):
    r = api.post("/api/projects", json={"name": "Site", "path": str(pasta)})
    assert r.status_code == 200 and r.json()["id"] == "site"
    assert api.get("/api/projects").json()["projects"][0]["path"] == str(pasta.resolve())
    assert api.get("/api/projects/site").json()["name"] == "Site"
    assert api.patch("/api/projects/site", json={"name": "Outro"}).json()["name"] == "Outro"
    assert api.delete("/api/projects/site").status_code == 204
    assert api.get("/api/projects/site").status_code == 404
    assert pasta.is_dir()


def test_http_erros_de_validacao(api, pasta):
    r = api.post("/api/projects", json={"name": "x", "path": "/nao/existe/mesmo"})
    assert r.status_code == 404 and r.json()["error"] == "path_not_found"
    api.post("/api/projects", json={"name": "a", "path": str(pasta)})
    r = api.post("/api/projects", json={"name": "b", "path": str(pasta)})
    assert r.status_code == 409 and r.json()["error"] == "duplicate_path"


def test_http_browse_nao_e_confundido_com_id(api, tmp_path):
    raiz = tmp_path / "raiz-browse"          # o tmp_path também guarda as pastas da fixture `env`
    (raiz / "sub").mkdir(parents=True)
    r = api.get("/api/projects/browse", params={"path": str(raiz)})
    assert r.status_code == 200 and [d["name"] for d in r.json()["dirs"]] == ["sub"]
    assert api.get("/api/projects/browse", params={"path": "/nao/existe"}).status_code == 404


def test_http_sessoes_do_projeto_usam_a_pasta_dele(api, pasta, monkeypatch):
    api.post("/api/projects", json={"name": "Site", "path": str(pasta)})
    seen = []
    monkeypatch.setattr(claude_svc, "list_project_sessions",
                        lambda limit=60, cwd=None: seen.append(cwd) or [{"id": "s1"}])
    assert api.get("/api/projects/site/sessions").json() == {"sessions": [{"id": "s1", "owner": "", "owner_name": ""}]}
    assert seen == [str(pasta.resolve())]
    assert api.get("/api/projects/nao-existe/sessions").status_code == 404


def test_http_project_invalido_nunca_cai_no_netops(api, monkeypatch):
    """?project= desconhecido = 404. Cair calado na pasta do NetOps misturaria as conversas."""
    sid = "11111111-1111-4111-8111-111111111111"
    chamadas = []
    monkeypatch.setattr(claude_svc, "session_items", lambda *a, **k: chamadas.append(a) or [])
    monkeypatch.setattr(claude_svc, "delete_project_session", lambda *a, **k: chamadas.append(a))
    for r in (api.get(f"/api/claude/sessions/{sid}/messages", params={"project": "fantasma"}),
              api.get(f"/api/claude/sessions/{sid}", params={"project": "fantasma"}),
              api.put(f"/api/claude/sessions/{sid}/title", params={"project": "fantasma"}, json={"title": "x"}),
              api.delete(f"/api/claude/sessions/{sid}", params={"project": "fantasma"})):
        assert r.status_code == 404 and r.json()["error"] == "project_not_found"
    assert chamadas == []


def test_http_sessao_com_project_repassa_a_pasta(api, pasta, monkeypatch):
    api.post("/api/projects", json={"name": "Site", "path": str(pasta)})
    sid = "11111111-1111-4111-8111-111111111111"
    vistos = []
    monkeypatch.setattr(claude_svc, "session_items", lambda s, cwd=None: vistos.append(cwd) or [])
    api.get(f"/api/claude/sessions/{sid}/messages", params={"project": "site"})
    api.get(f"/api/claude/sessions/{sid}/messages")
    assert vistos == [str(pasta.resolve()), None]      # sem project = NetOps, como sempre


def test_http_upload_de_projeto_devolve_caminho_absoluto(api, pasta, monkeypatch, tmp_path):
    api.post("/api/projects", json={"name": "Site", "path": str(pasta)})
    from routers import claude as router
    monkeypatch.setattr(router, "UPLOAD_DIR", tmp_path / "up")
    monkeypatch.setattr(deps, "NETOPS_ROOT", tmp_path)
    r = api.post("/api/claude/upload", params={"project": "site"}, files={"file": ("a.txt", b"oi")})
    assert r.status_code == 200 and r.json()["path"] == str(tmp_path / "up" / "a.txt")
    r = api.post("/api/claude/upload", files={"file": ("b.txt", b"oi")})
    assert r.json()["path"] == "up/b.txt"              # sem projeto: relativo à raiz, como antes


def test_ws_project_inexistente_fecha_4404_sem_subir_agente(api, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setattr(claude_svc, "is_available", lambda: True)
    monkeypatch.setattr(deps, "host_origin_allowed", lambda *a, **k: True)
    monkeypatch.setattr(claude_svc, "attach_or_create", lambda **k: pytest.fail("agente não pode subir"))
    monkeypatch.setattr(claude_svc, "ClaudeWebSession", lambda *a, **k: pytest.fail("agente não pode subir"))
    with pytest.raises(WebSocketDisconnect) as e:
        with api.websocket_connect("/api/claude?project=fantasma") as ws:
            ws.receive_text()
    assert e.value.code == 4404


# ------------------------------------------------------------------ conta do agente em projeto
def _settings(tmp_path, monkeypatch, env_local, env_user=None):
    """Aponta os settings do user e do NetOps para um tmp (nunca lê a conta real)."""
    import json
    from services import claude_models
    home, root = tmp_path / "home", tmp_path / "root"
    for d in (home / ".claude", root / ".claude"):
        d.mkdir(parents=True)
    (root / ".claude" / "settings.local.json").write_text(json.dumps({"env": env_local}))
    if env_user is not None:
        (home / ".claude" / "settings.json").write_text(json.dumps({"env": env_user}))
    monkeypatch.setenv("HOME", str(home))
    for k in [k for k in __import__("os").environ if k.startswith("ANTHROPIC_") or k == "CLAUDE_CODE_OAUTH_TOKEN"]:
        monkeypatch.delenv(k)
    monkeypatch.setattr(deps, "NETOPS_ROOT", root)
    return claude_models


def test_token_nunca_e_copiado_para_o_agente_do_projeto(tmp_path, monkeypatch):
    """Modelo VS Code: a conta vale em qualquer pasta por estar no nível do usuário; o console não
    injeta ANTHROPIC_*/CLAUDE_CODE_OAUTH_TOKEN dos settings do NetOps no env de um agente com shell."""
    m = _settings(tmp_path, monkeypatch, {"ANTHROPIC_AUTH_TOKEN": "tok", "CLAUDE_CODE_OAUTH_TOKEN": "o"})
    assert not hasattr(m, "provider_env")
    pasta = tmp_path / "proj"
    pasta.mkdir()
    env = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))._options().env
    assert "ANTHROPIC_AUTH_TOKEN" not in env and "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert env["IS_SANDBOX"] == "1"


def test_aviso_quando_a_conta_esta_so_nos_settings_do_netops(tmp_path, monkeypatch):
    m = _settings(tmp_path, monkeypatch, {"ANTHROPIC_AUTH_TOKEN": "tok"})
    assert m.account_only_in_netops() is True
    m = _settings(tmp_path / "b", monkeypatch, {"ANTHROPIC_AUTH_TOKEN": "tok"}, {"ANTHROPIC_BASE_URL": "http://gw"})
    assert m.account_only_in_netops() is False          # conta no nível do usuário: projeto acha
    m = _settings(tmp_path / "c", monkeypatch, {"FOO": "x"})
    assert m.account_only_in_netops() is False          # OAuth normal (~/.claude/.credentials.json)


def test_http_lista_traz_o_aviso_de_conta(api, monkeypatch):
    from services import claude_models
    monkeypatch.setattr(claude_models, "account_only_in_netops", lambda: True)
    assert api.get("/api/projects").json()["account_warning"] is True


# ------------------------------------------------------------------ pastas proibidas
@pytest.mark.parametrize("caminho", ["/", "/etc", "/etc/ssh", "/usr", "/proc/1", "/root", "/opt", "/var"])
def test_pasta_do_sistema_nao_vira_projeto(caminho):
    with pytest.raises(P.ProjectError) as e:
        P.create("x", caminho)
    assert e.value.code == "forbidden_path"


def test_netops_dentro_ou_acima_nao_vira_projeto(tmp_path, monkeypatch):
    root = tmp_path / "base" / "netops"
    (root / "scripts").mkdir(parents=True)
    monkeypatch.setattr(deps, "NETOPS_ROOT", root)
    for d in (root, root / "scripts", tmp_path / "base"):
        with pytest.raises(P.ProjectError) as e:
            P.create("x", str(d))
        assert e.value.code == "forbidden_path"


def test_pasta_oculta_do_home_nao_vira_projeto(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / "proj").mkdir()
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(P.ProjectError) as e:
        P.create("x", str(home / ".claude"))
    assert e.value.code == "forbidden_path"
    with pytest.raises(P.ProjectError):
        P.create("x", str(home))
    assert P.create("ok", str(home / "proj"))["id"] == "ok"


def test_symlink_para_pasta_proibida_e_recusado(pasta):
    link = pasta.parent / "atalho"
    link.symlink_to("/etc")
    with pytest.raises(P.ProjectError) as e:
        P.create("x", str(link))
    assert e.value.code == "forbidden_path"


def test_registro_editado_a_mao_para_pasta_proibida_nao_e_usado(pasta, monkeypatch):
    P.create("Site", str(pasta))
    items = P._load()
    items[0]["path"] = "/etc"
    P._save(items)
    assert P.path_of("site") is None                # o agente nunca roda lá


# ------------------------------------------------------------------ pasta nova + confiança
def test_pasta_nova_e_criada_vazia_e_confiavel(pasta):
    base = pasta.parent
    p = P.create("App", str(base), new_folder="app-novo")
    assert p["path"] == str((base / "app-novo").resolve()) and (base / "app-novo").is_dir()
    assert p["trusted"] is True
    with pytest.raises(P.ProjectError) as e:
        P.create("App2", str(base), new_folder="app-novo")
    assert e.value.code == "exists"
    for ruim in ("../fora", "a/b", ".oculta", "com espaço", ""):
        with pytest.raises(P.ProjectError):
            P.create("x", str(base), new_folder=ruim or "/")


def test_pasta_nova_em_lugar_proibido_nao_cria_nada():
    with pytest.raises(P.ProjectError) as e:
        P.create("x", "/etc", new_folder="netops-teste-nao-deve-existir")
    assert e.value.code == "forbidden_path"
    import os
    assert not os.path.exists("/etc/netops-teste-nao-deve-existir")


def test_pasta_existente_com_config_executavel_nasce_restrita(pasta):
    (pasta / ".claude").mkdir()
    (pasta / ".claude" / "settings.json").write_text('{"hooks": {}}')
    (pasta / "CLAUDE.md").write_text("x")
    p = P.create("Site", str(pasta))
    assert p["trusted"] is False
    assert p["config"] == {"exec": [".claude/settings.json"], "info": ["CLAUDE.md"]}
    assert P.is_trusted(p["path"]) is False
    assert P.set_trusted("site", True)["trusted"] is True and P.is_trusted(p["path"]) is True


def test_confiar_na_criacao_e_pasta_sem_config(pasta, tmp_path_factory):
    (pasta / ".mcp.json").write_text("{}")
    assert P.create("Site", str(pasta), trust=True)["trusted"] is True
    limpa = tmp_path_factory.mktemp("limpa")
    assert P.create("Limpa", str(limpa))["trusted"] is True   # nada que execute: não precisa perguntar


def test_modo_restrito_so_carrega_os_settings_do_usuario(pasta):
    (pasta / ".mcp.json").write_text("{}")
    p = P.create("Site", str(pasta))
    s = claude_svc.ClaudeWebSession(persist=True, cwd=p["path"])
    assert s._options().setting_sources == ["user"]
    P.set_trusted("site", True)
    assert s._options().setting_sources == ["user", "project", "local"]
    # pasta fora do registro (projeto removido) = restrito; NetOps continua com tudo
    assert claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta.parent))._options().setting_sources == ["user"]
    assert claude_svc.ClaudeWebSession(persist=True)._options().setting_sources == ["user", "project", "local"]


def _matchers(opts):
    return [h for m in opts.hooks["PreToolUse"] for h in m.hooks]


def test_guarda_do_netops_vale_so_em_projeto(pasta):
    proj = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))
    net = claude_svc.ClaudeWebSession(persist=True)
    assert proj._hook_netops_guard in _matchers(proj._options())
    assert net._hook_netops_guard not in _matchers(net._options())   # no NetOps o hook vem do settings.json


def test_guarda_bloqueia_alteracao_sem_backup(pasta, monkeypatch, tmp_path):
    import asyncio
    root = tmp_path / "nt"
    (root / "scripts" / "engine" / "hooks").mkdir(parents=True)
    (root / "scripts" / "engine" / "hooks" / "guard-netops.sh").write_text(
        'cat >/dev/null; echo "BLOQUEADO: falta change.py begin" >&2; exit 2\n')
    monkeypatch.setattr(deps, "NETOPS_ROOT", root)
    s = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))
    cmd = {"tool_input": {"command": "python3 /opt/netops/scripts/tools/access/session.py run --host-id 2 --command '/ip address add'"}}
    out = asyncio.run(s._hook_netops_guard(cmd, None, None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "change.py begin" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert asyncio.run(s._hook_netops_guard({"tool_input": {"command": "ls"}}, None, None)) == {}


def test_guarda_que_nao_roda_bloqueia(pasta, monkeypatch, tmp_path):
    import asyncio
    monkeypatch.setattr(deps, "NETOPS_ROOT", tmp_path / "sem-guard")
    s = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))
    out = asyncio.run(s._hook_netops_guard({"tool_input": {"command": "x session.py run --host-id 1"}}, None, None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"     # sem guarda = não mexe em equipamento


def test_http_criar_com_pasta_nova_e_confiar(api, pasta):
    r = api.post("/api/projects", json={"name": "Novo", "path": str(pasta.parent), "new_folder": "novo-app"})
    assert r.status_code == 200 and r.json()["trusted"] is True
    assert api.patch("/api/projects/novo", json={"trusted": False}).json()["trusted"] is False
    assert api.patch("/api/projects/novo", json={}).status_code == 400
    assert api.post("/api/projects", json={"name": "x", "path": "/etc"}).json()["error"] == "forbidden_path"


def test_http_browse_informa_se_pode_e_a_config(api, pasta):
    (pasta / ".mcp.json").write_text("{}")
    d = api.get("/api/projects/browse", params={"path": str(pasta)}).json()
    assert d["allowed"] is True and d["config"]["exec"] == [".mcp.json"]
    d = api.get("/api/projects/browse", params={"path": "/etc"}).json()
    assert d["allowed"] is False and d["reason"]


def test_pasta_base_padrao_com_barra_no_fim_e_criada(tmp_path_factory, monkeypatch):
    """Bug 18/11: "/opt/projetos/" (com barra) não criava a base e dava "Essa pasta não existe"."""
    base = tmp_path_factory.mktemp("b") / "projetos"
    monkeypatch.setattr(P, "DEFAULT_BASE", str(base))
    p = P.create("Testes", str(base) + "/", new_folder="testes")
    assert p["path"] == str((base / "testes").resolve()) and p["trusted"] is True


# ------------------------------------------------------------------ ordem e arquivados (por usuário)
def test_ordem_e_arquivados_sao_por_usuario(tmp_path_factory):
    base = tmp_path_factory.mktemp("ord")
    for n in ("a", "b", "c"):
        (base / n).mkdir()
        P.create(n.upper(), str(base / n))
    assert [p["id"] for p in P.list_for("ana")] == ["a", "b", "c"]          # sem ordem salva: alfabética
    P.set_order("ana", ["c", "a", "fantasma", "c"])                          # id desconhecido/duplicado é ignorado
    assert [p["id"] for p in P.list_for("ana")] == ["c", "a", "b"]           # sem posição (b) vai p/ o fim
    assert [p["id"] for p in P.list_for("bia")] == ["a", "b", "c"]           # outro usuário não muda
    assert P.set_archived("ana", "a", True)["archived"] is True
    assert [p["id"] for p in P.list_for("ana") if p["archived"]] == ["a"]
    assert not any(p["archived"] for p in P.list_for("bia"))
    P.set_archived("ana", "a", False)
    assert not any(p["archived"] for p in P.list_for("ana"))
    with pytest.raises(P.ProjectError):
        P.set_archived("ana", "nao-existe", True)
    with pytest.raises(P.ProjectError):
        P.set_order("ana", "c,a")


def test_remover_projeto_limpa_ordem_e_arquivados(tmp_path_factory):
    base = tmp_path_factory.mktemp("rm")
    (base / "x").mkdir(); (base / "y").mkdir()
    P.create("X", str(base / "x")); P.create("Y", str(base / "y"))
    P.set_order("ana", ["y", "x"]); P.set_archived("ana", "x", True)
    P.delete("x")
    assert P._user_prefs(P._prefs_all(), "ana") == {"order": ["y"], "archived": []}


def test_http_ordem_e_arquivar(api, pasta, tmp_path_factory):
    outra = tmp_path_factory.mktemp("o") / "outra"
    outra.mkdir()
    api.post("/api/projects", json={"name": "Site", "path": str(pasta)})
    api.post("/api/projects", json={"name": "Outra", "path": str(outra)})
    assert [p["id"] for p in api.put("/api/projects/order", json={"ids": ["site", "outra"]}).json()["projects"]] == ["site", "outra"]
    assert [p["id"] for p in api.get("/api/projects").json()["projects"]] == ["site", "outra"]
    assert api.put("/api/projects/site/archived", json={"archived": True}).json()["archived"] is True
    assert api.get("/api/projects/site").json()["archived"] is True
    assert api.put("/api/projects/nao-existe/archived", json={"archived": True}).status_code == 404


# ------------------------------------------------------------------ arquivos do projeto (presos à pasta)
@pytest.fixture
def pfs(pasta):
    import asyncio
    from services import files_svc
    (pasta / "src").mkdir()
    (pasta / "src" / "a.txt").write_text("oi")
    fora = pasta.parent / "fora"
    fora.mkdir()
    (fora / "segredo.txt").write_text("x")
    (pasta / "link-arq").symlink_to(fora / "segredo.txt")
    (pasta / "link-dir").symlink_to(fora)
    P.create("Site", str(pasta))
    fs = files_svc.backend("project:site")
    run = lambda c: asyncio.run(c)
    return fs, run, pasta, fora, files_svc


def test_fonte_do_projeto_comeca_e_fica_na_pasta(pfs):
    fs, run, pasta, fora, fsvc = pfs
    root = str(pasta.resolve())
    assert run(fs.home()) == root and fs.kind == "project"
    assert {e["name"] for e in run(fs.list(root))["entries"]} >= {"src", "link-arq", "link-dir"}
    data, _ = run(fs.read_bytes(root + "/src/a.txt", 100))
    assert data == b"oi"
    for bad in ("/etc", str(fora), root + "/..", root + "/link-dir"):
        with pytest.raises(fsvc.Denied):
            run(fs.list(bad))
    with pytest.raises(fsvc.Denied):
        run(fs.read_bytes(root + "/link-arq", 100))          # link p/ fora não vaza conteúdo
    with pytest.raises(fsvc.Denied):
        run(fs.read_bytes("/etc/hostname", 100))


def test_fonte_do_projeto_escrita_presa_a_pasta(pfs):
    fs, run, pasta, fora, fsvc = pfs
    root = str(pasta.resolve())
    run(fs.mkdir(root + "/novo"))
    run(fs.write_bytes(root + "/novo/b.txt", b"x", None))
    assert (pasta / "novo" / "b.txt").read_text() == "x"
    for op in (lambda: fs.mkdir(str(fora) + "/z"), lambda: fs.mkdir(root + "/link-dir/z"),
               lambda: fs.write_bytes(root + "/link-arq", b"hack", None),
               lambda: fs.chmod(root + "/link-arq", 0o777),
               lambda: fs.copy(root + "/src/a.txt", str(fora) + "/a.txt"),
               lambda: fs.rename(root + "/src/a.txt", str(fora) + "/a.txt"),
               lambda: fs.delete(root), lambda: fs.rename(root, root + "-x")):
        with pytest.raises(fsvc.Denied):
            run(op())
    assert (fora / "segredo.txt").read_text() == "x"
    run(fs.delete(root + "/link-arq"))                    # apagar o link apaga só o link
    assert (fora / "segredo.txt").exists() and not (pasta / "link-arq").exists()


def test_zip_do_projeto_nao_inclui_arquivo_de_fora(pfs):
    fs, run, pasta, fora, fsvc = pfs
    names = [rel for _f, rel, _s, _d in fs.sync_walk(str(pasta.resolve()))]
    assert any(n.endswith("src/a.txt") for n in names) and not any("link-arq" in n for n in names)


def test_fonte_de_projeto_inexistente_ou_proibido():
    from services import files_svc
    with pytest.raises(files_svc.NotFound):
        files_svc.backend("project:nao-existe")


def test_http_arquivos_do_projeto(api, pasta, monkeypatch):
    monkeypatch.setattr(deps, "files_enabled", lambda: True)
    (pasta / "a.txt").write_text("oi")
    api.post("/api/projects", json={"name": "Site", "path": str(pasta)})
    i = api.get("/api/files/info", params={"src": "project:site"}).json()
    assert i["root"] == str(pasta.resolve()) and i["home"] == i["root"] and i["kind"] == "project"
    r = api.get("/api/files/list", params={"src": "project:site", "path": i["root"]})
    assert "a.txt" in [e["name"] for e in r.json()["entries"]]
    assert api.get("/api/files/list", params={"src": "project:site", "path": "/etc"}).status_code == 403
    assert api.get("/api/files/read", params={"src": "project:site", "path": "/etc/hostname"}).status_code == 403


# ------------------------------------------------------------------ base padrão no HOME da conta (layout 2)
# Bug 21/11 (instalação do zero): a base era /opt/projetos. A conta `netops` não escreve em /opt, então
# instalação migrada/atualizada sem esse passo de root quebrava em "criar pasta nova". Agora a base é
# ~/projects da conta do console, que fica em /var/lib/netops (um _DENY_TREE): subpasta visível do HOME pode.
def test_home_da_conta_em_var_lib_libera_subpasta_visivel(monkeypatch):
    monkeypatch.setenv("HOME", "/var/lib/netops")
    assert P.deny_reason("/var/lib/netops/projects") is None
    assert P.deny_reason("/var/lib/netops/projects/meu-site") is None
    assert P.deny_reason("/var/lib/netops/.claude") is not None          # oculta do HOME: nunca
    assert P.deny_reason("/var/lib/netops/.claude/projects") is not None
    assert P.deny_reason("/var/lib/netops") is not None                   # o próprio HOME: não
    assert P.deny_reason("/var/lib/mysql") is not None                    # resto de /var/lib continua proibido
    assert P.deny_reason("/var/lib") is not None
    assert P.deny_reason("/etc/netops") is not None


def test_base_padrao_e_criada_sozinha_no_home_sem_root(tmp_path_factory, monkeypatch):
    """Simula a conta netops: HOME próprio, base ~/projects ainda não existe; o console cria (750) e o projeto."""
    home = tmp_path_factory.mktemp("var-lib") / "netops"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    base = home / "projects"
    monkeypatch.setattr(P, "DEFAULT_BASE", str(base))
    p = P.create("Meu Site", str(base), new_folder="meu-site")
    assert p["path"] == str((base / "meu-site").resolve()) and p["trusted"] is True
    assert (base.stat().st_mode & 0o777) == 0o750
    assert P.path_of(p["id"]) == p["path"]                                # o agente pode rodar nela


def test_base_padrao_sem_permissao_da_erro_claro(tmp_path_factory, monkeypatch):
    """Base num pai sem escrita (ex.: /opt para a conta netops) = erro mkdir_failed, nunca exceção crua."""
    import os
    if os.geteuid() == 0:
        pytest.skip("root escreve em qualquer pasta")
    pai = tmp_path_factory.mktemp("opt")
    pai.chmod(0o555)
    try:
        monkeypatch.setattr(P, "DEFAULT_BASE", str(pai / "projetos"))
        with pytest.raises(P.ProjectError) as e:
            P.create("x", str(pai / "projetos"), new_folder="x")
        assert e.value.code == "mkdir_failed"
    finally:
        pai.chmod(0o755)


def test_http_lista_informa_a_base_padrao(api, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_BASE", "/var/lib/netops/projects")
    assert api.get("/api/projects").json()["default_base"] == "/var/lib/netops/projects"


def test_base_padrao_nao_fica_mais_em_opt():
    assert not P.DEFAULT_BASE.startswith("/opt/") and P.DEFAULT_BASE.endswith("/projects")
