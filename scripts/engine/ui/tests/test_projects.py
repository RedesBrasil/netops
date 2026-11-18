"""Projetos da aba Claude Code: registro (nome + pasta), navegação de pastas e `cwd` do agente.

Sem agente real: `_options()` só monta as opções; a retomada pós-restart é lida do arquivo de anotação.
"""
import pytest

import deps
from services import claude_svc, projects_svc as P


@pytest.fixture
def pasta(tmp_path):
    d = tmp_path / "meu-site"
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
    assert e.value.code == "is_netops"


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
    assert api.get("/api/projects/site/sessions").json() == {"sessions": [{"id": "s1", "owner": ""}]}
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
    monkeypatch.setattr(deps, "NETOPS_ROOT", root)
    return claude_models


def test_provider_env_pega_so_conta_e_modelo_e_local_vence_user(tmp_path, monkeypatch):
    m = _settings(tmp_path, monkeypatch,
                  {"ANTHROPIC_AUTH_TOKEN": "tok-local", "ANTHROPIC_BASE_URL": "http://gw", "FOO": "x", "ANTHROPIC_MODEL": ""},
                  {"ANTHROPIC_AUTH_TOKEN": "tok-user", "CLAUDE_CODE_OAUTH_TOKEN": "oauth", "PATH": "/x"})
    assert m.provider_env() == {"ANTHROPIC_AUTH_TOKEN": "tok-local", "ANTHROPIC_BASE_URL": "http://gw",
                                "CLAUDE_CODE_OAUTH_TOKEN": "oauth"}      # sem FOO/PATH, sem valor vazio


def test_agente_de_projeto_recebe_a_conta_e_o_do_netops_nao_muda(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, {"ANTHROPIC_AUTH_TOKEN": "tok", "ANTHROPIC_BASE_URL": "http://gw"})
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    pasta = tmp_path / "proj"
    pasta.mkdir()
    proj = claude_svc.ClaudeWebSession(persist=True, cwd=str(pasta))._options().env
    assert proj["ANTHROPIC_AUTH_TOKEN"] == "tok" and proj["ANTHROPIC_BASE_URL"] == "http://gw"
    assert proj["IS_SANDBOX"] == "1"
    net = claude_svc.ClaudeWebSession(persist=True)._options().env
    assert "ANTHROPIC_AUTH_TOKEN" not in net      # NetOps: o CLI já lê os settings da própria pasta
