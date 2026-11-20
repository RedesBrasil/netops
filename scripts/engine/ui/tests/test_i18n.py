"""Translations (core/rules/i18n.md): catalogs, API endpoints, per-user and instance language,
request language (X-Netops-Lang) and local files born in the chosen language."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[4]
MASTER = "senha-mestra-teste-123"


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    from lib import vault
    monkeypatch.setattr(vault, "ARGON2_DEFAULTS", {"iterations": 1, "memory_cost": 1024, "lanes": 1, "length": 32})


def _client():
    from app import create_app
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _admin(env):
    import yaml
    import deps
    from lib import vault
    meta, _ = vault.build_meta(MASTER)
    f = env / "network" / "credentials.yaml"
    data = (yaml.safe_load(f.read_text()) if f.exists() else {}) or {}
    data["vault"] = meta
    f.write_text(yaml.safe_dump(data))
    deps._vault_init_cache.clear()
    c = _client()
    r = c.post("/api/auth/login", json={"master_password": MASTER, "email": "admin@empresa.com"})
    assert r.status_code == 200, r.text
    c.headers["X-Netops-Session"] = r.json()["auth_token"]
    return c


# ----------------------------------------------------------------- catalogs
def test_lib_t_fallback_plural_and_placeholders():
    from lib import i18n
    assert i18n.normalize("pt") == "pt-BR" and i18n.normalize("en_US") == "en" and i18n.normalize("xx") is None
    assert i18n.t("common.save", "en") == "Save" and i18n.t("common.save", "pt-BR") == "Salvar"
    assert i18n.t("nav.archived", "en", count=3) == "Archived (3)"
    assert i18n.t("no.such.key", "en") == "no.such.key"
    assert i18n.t("errors.unknown_language", "en", lang="zz") == "Unsupported language: zz"
    assert i18n.plural_category("pt-BR", 0) == "one" and i18n.plural_category("en", 0) == "other"


def test_python_t_calls_use_keys_that_exist_in_english():
    """Every literal i18n.t("ns.key") / _t("ns.key") in scripts/ exists in core/locales/en (or as _one/_other)."""
    from lib import i18n
    en = i18n.raw_catalog("en")
    pat = re.compile(r"""\b(?:i18n\.t|_t|tr)\(\s*["']([a-z][a-z0-9_]*(?:\.[a-z0-9_-]+)+)["']\s*[,)]""")
    missing = []
    for f in (REPO / "scripts").rglob("*.py"):
        if "node_modules" in f.parts or "/tests/" in str(f):
            continue
        for m in pat.finditer(f.read_text(encoding="utf-8", errors="replace")):
            k = m.group(1)
            if k not in en and f"{k}_one" not in en and f"{k}_other" not in en:
                missing.append(f"{f.relative_to(REPO)}: {k}")
    assert missing == []


def test_catalogs_are_valid_json_and_complete_languages_match_english():
    from lib import i18n
    en = i18n.raw_catalog("en")
    for lang in i18n.languages():
        for f in (REPO / "core" / "locales" / lang["code"]).glob("*.json"):
            json.loads(f.read_text(encoding="utf-8"))
        if lang["status"] == "complete":
            assert set(i18n.raw_catalog(lang["code"])) == set(en), lang["code"]


# ----------------------------------------------------------------- API
def test_i18n_endpoints_are_open_and_merge_english(env):
    c = _admin(env)
    bare = _client()
    idx = bare.get("/api/i18n").json()
    assert {x["code"] for x in idx["languages"]} >= {"en", "pt-BR"}
    assert idx["instance"] is None and idx["default"] == "pt-BR"     # pre-i18n installs behave as pt-BR
    cat = bare.get("/api/i18n/en").json()
    assert cat["lang"] == "en" and cat["messages"]["common.save"] == "Save"
    assert bare.get("/api/i18n/pt").json()["lang"] == "pt-BR"
    assert bare.get("/api/i18n/xx").status_code == 404
    assert c.get("/api/auth/me").json()["locale"] == ""


def test_request_language_header_translates_api_messages(env):
    c = _admin(env)
    r = c.put("/api/auth/locale", json={"locale": "xx"}, headers={"X-Netops-Lang": "en"})
    assert r.status_code == 422 and r.json()["detail"] == "Unsupported language: xx"
    r = c.put("/api/auth/locale", json={"locale": "xx"}, headers={"X-Netops-Lang": "pt-BR"})
    assert r.json()["detail"] == "Idioma não suportado: xx"


def test_user_locale_is_per_user(env):
    c = _admin(env)
    r = c.put("/api/auth/locale", json={"locale": "en"})
    assert r.status_code == 200 and r.json()["locale"] == "en"
    me = c.get("/api/auth/me").json()
    assert me["locale"] == "en" and me["instance_language"] is None
    assert c.put("/api/auth/locale", json={"locale": ""}).json()["effective"] == "pt-BR"
    assert c.get("/api/auth/me").json()["locale"] == ""


def test_permission_labels_follow_the_request_language(env):
    c = _admin(env)
    cat = c.get("/api/auth/me", headers={"X-Netops-Lang": "en"}).json()["catalog"]
    assert next(p for p in cat if p["key"] == "hosts.view")["label"] == "View hosts, host groups and maps"
    cat = c.get("/api/auth/me", headers={"X-Netops-Lang": "pt-BR"}).json()["catalog"]
    assert next(p for p in cat if p["key"] == "hosts.view")["label"] == "Ver hosts, grupos de host e mapas"


def test_instance_language_admin_only_and_written_to_project_config(env):
    import yaml
    c = _admin(env)
    assert c.put("/api/config/language", json={"language": "zz"}).status_code == 422
    r = c.put("/api/config/language", json={"language": "en"})
    assert r.status_code == 200 and r.json()["language"] == "en"
    cfg = yaml.safe_load((env / "core/config/project-config.yaml").read_text())
    assert cfg["instance"]["language"] == "en"
    assert "project" in cfg                                    # the rest of the file is kept
    assert _client().get("/api/i18n").json()["instance"] == "en"
    assert c.get("/api/config/meta").json()["language"] == "en"
    # no header: API messages now default to the instance language
    r = c.put("/api/auth/locale", json={"locale": "xx"})
    assert r.json()["detail"] == "Unsupported language: xx"


def test_language_routes_are_mapped():
    from services import authz
    assert authz.required_perm("GET", "/i18n") is authz.ANY
    assert authz.required_perm("GET", "/i18n/pt-BR") is authz.ANY
    assert authz.required_perm("PUT", "/config/language") == "config"
    assert authz.required_perm("PUT", "/auth/locale") is authz.ANY


# ----------------------------------------------------------------- local files
def test_local_files_regenerated_only_while_pristine(tmp_path):
    from lib import local_files
    code = tmp_path / "code"
    (code / "core/templates/en").mkdir(parents=True)
    (code / "core/templates/AGENTS.tmpl.md").write_text("<!-- modelo\n-->\n# Regras\n", encoding="utf-8")
    (code / "core/templates/en/AGENTS.tmpl.md").write_text("<!-- template\n-->\n# Rules\n", encoding="utf-8")
    (code / "core/templates/MEMORY.tmpl.md").write_text("<!-- m -->\n# Memória — NetOps\n\n", encoding="utf-8")
    (code / "core/templates/en/MEMORY.tmpl.md").write_text("<!-- m -->\n# Memory — NetOps\n\n", encoding="utf-8")
    (code / "AGENTS.md").write_text("# Regras\n", encoding="utf-8")            # pristine pt (installer)
    (code / "memory").mkdir()
    (code / "memory/MEMORY.md").write_text("# Memória — NetOps\n\n", encoding="utf-8")
    out = local_files.sync_language(code, code, "en")
    assert out == {"AGENTS": "written", "MEMORY": "written"}
    assert (code / "AGENTS.md").read_text() == "# Rules\n"
    assert (code / "memory/MEMORY.md").read_text() == "# Memory — NetOps\n\n"
    (code / "memory/MEMORY.md").write_text("# Memory — NetOps\n\n- my note\n", encoding="utf-8")
    out = local_files.sync_language(code, code, "pt-BR")
    assert out == {"AGENTS": "written", "MEMORY": "kept"}
    assert "my note" in (code / "memory/MEMORY.md").read_text()
    assert local_files.sync_language(code, code, "pt-BR", agents=False)["AGENTS"] == "skipped"


def test_real_templates_exist_for_every_complete_language():
    from lib import i18n, local_files
    for lang in i18n.codes():
        for name in local_files.TEMPLATES:
            assert local_files.template_path(REPO, name, lang) is not None, (lang, name)


def test_existing_install_gets_pt_br_on_startup(env):
    """Pre-i18n install (vault/users, no instance.language) is pinned to pt-BR when the console starts."""
    import yaml
    _admin(env)                                   # vault + admin = configured installation
    from app import create_app
    with TestClient(create_app(), base_url="http://127.0.0.1"):
        pass                                      # runs the startup events
    cfg = yaml.safe_load((env / "core/config/project-config.yaml").read_text())
    assert cfg["instance"]["language"] == "pt-BR"


def test_fresh_install_language_is_left_to_first_access(env):
    import yaml
    from app import create_app
    with TestClient(create_app(), base_url="http://127.0.0.1"):
        pass
    cfg = yaml.safe_load((env / "core/config/project-config.yaml").read_text()) or {}
    assert "instance" not in cfg
