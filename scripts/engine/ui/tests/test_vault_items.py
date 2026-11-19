"""Cofre de senhas (network/vault.yaml): campos, templates, itens, cofre trancado/aberto."""
from __future__ import annotations

import yaml


def _init_vault(env, master="senha-mestra-teste"):
    import deps
    from lib import vault, vault_session
    from vault import cli
    meta, key = vault.build_meta(master)
    cli._atomic_write(deps.CREDS_FILE, cli._set_vault_block("version: 1\n\ncredentials: {}\n", meta))
    vault_session.set_session_key(key, 900)
    return key


def _rev(client):
    return client.get("/api/vault/items").json()["rev"]


def _item(client, **kw):
    body = {"title": "Portal Claro", "template": "login",
            "values": [{"field": "URL", "value": "https://claro.example"},
                       {"field": "Usuário", "value": "fulano"},
                       {"field": "Senha", "value": "s3gr3d0"}]} | kw
    return client.post("/api/vault/items", json=body, headers={"If-Match": _rev(client)})


def test_defaults_without_file(client, env):
    d = client.get("/api/vault/items").json()
    assert d["items"] == []
    assert {t["id"] for t in d["templates"]} == {"login", "api"}
    assert {f["name"]: f["kind"] for f in d["fields"]}["Senha"] == "secret"
    assert not (env / "network/vault.yaml").exists()


def test_create_item_encrypts_secret_and_lists_masked(client, env):
    key = _init_vault(env)
    r = _item(client)
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    assert iid == "portal-claro"
    path = env / "network/vault.yaml"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    raw = path.read_text()
    assert "s3gr3d0" not in raw and "enc.v1:" in raw and "https://claro.example" in raw
    data = yaml.safe_load(raw)
    from lib import vault
    assert vault.decrypt_value(key, data["items"][iid]["values"]["Senha"]) == "s3gr3d0"
    listed = client.get("/api/vault/items").json()["items"][0]
    vals = {v["field"]: v for v in listed["values"]}
    assert vals["Senha"] == {"field": "Senha", "kind": "secret", "set": True}
    assert vals["URL"]["value"] == "https://claro.example"
    assert "s3gr3d0" not in client.get("/api/vault/items").text


def test_locked_shows_text_hides_secret_and_blocks_writes(client, env):
    _init_vault(env)
    iid = _item(client).json()["id"]
    from lib import vault_session
    vault_session.clear_session()
    listed = client.get("/api/vault/items")
    assert listed.status_code == 200 and "fulano" in listed.text
    assert client.post(f"/api/vault/items/{iid}/reveal", json={"field": "Senha"}).status_code == 423
    r = client.put(f"/api/vault/items/{iid}", headers={"If-Match": _rev(client)},
                   json={"title": "Portal Claro", "template": "login",
                         "values": [{"field": "Usuário", "value": "x"}, {"field": "Senha", "value": "nova"}]})
    assert r.status_code == 423
    # só texto, mantendo o segredo (value=None): funciona trancado
    r = client.put(f"/api/vault/items/{iid}", headers={"If-Match": _rev(client)},
                   json={"title": "Portal Claro 2", "template": "login",
                         "values": [{"field": "Usuário", "value": "beltrano"}, {"field": "Senha", "value": None}]})
    assert r.status_code == 200, r.text
    vals = {v["field"]: v for v in r.json()["values"]}
    assert vals["Senha"]["set"] is True and vals["Usuário"]["value"] == "beltrano"


def test_reveal_unlocked(client, env):
    _init_vault(env)
    iid = _item(client).json()["id"]
    r = client.post(f"/api/vault/items/{iid}/reveal", json={"field": "senha"})
    assert r.status_code == 200 and r.json()["values"] == {"Senha": "s3gr3d0"}
    allv = client.post(f"/api/vault/items/{iid}/reveal", json={}).json()["values"]
    assert allv["Senha"] == "s3gr3d0" and allv["URL"] == "https://claro.example"


def test_required_validated_on_backend(client, env):
    _init_vault(env)
    r = _item(client, values=[{"field": "URL", "value": "https://x"}])
    assert r.status_code == 422
    assert "Usuário" in r.text and "Senha" in r.text


def test_uninitialized_vault_secret_409(client, env):
    r = _item(client)
    assert r.status_code == 409 and r.json()["error"] == "vault_uninitialized"


def test_template_creates_reusable_field_and_kind_conversion(client, env):
    _init_vault(env)
    r = client.post("/api/vault/templates", headers={"If-Match": _rev(client)},
                    json={"label": "Cloudflare", "fields": [
                        {"field": "URL", "required": True, "visible": True},
                        {"field": "Zone ID", "kind": "text", "visible": True},
                        {"field": "api key", "required": True}]})
    assert r.status_code == 201, r.text
    cat = r.json()
    tpl = next(t for t in cat["templates"] if t["id"] == "cloudflare")
    assert [f["field"] for f in tpl["fields"]] == ["URL", "Zone ID", "API key"]   # reaproveita "API key"
    assert {f["name"]: f["kind"] for f in cat["fields"]}["Zone ID"] == "text"
    it = client.post("/api/vault/items", headers={"If-Match": _rev(client)},
                     json={"title": "CF", "template": "cloudflare", "values": [
                         {"field": "URL", "value": "https://api.cloudflare.com"},
                         {"field": "Zone ID", "value": "abc123"}, {"field": "API key", "value": "k"}]})
    assert it.status_code == 201, it.text
    # Zone ID vira segredo: o valor gravado passa a ser cifrado
    r = client.patch("/api/vault/fields/Zone ID", headers={"If-Match": _rev(client)}, json={"kind": "secret"})
    assert r.status_code == 200, r.text
    raw = (env / "network/vault.yaml").read_text()
    assert "abc123" not in raw
    assert client.post("/api/vault/items/cf/reveal", json={"field": "Zone ID"}).json()["values"]["Zone ID"] == "abc123"


def test_field_rename_cascades_and_delete_in_use_blocked(client, env):
    _init_vault(env)
    iid = _item(client).json()["id"]
    r = client.patch("/api/vault/fields/Senha", headers={"If-Match": _rev(client)}, json={"name": "Senha web"})
    assert r.status_code == 200, r.text
    login = next(t for t in r.json()["templates"] if t["id"] == "login")
    assert "Senha web" in [f["field"] for f in login["fields"]]
    assert client.post(f"/api/vault/items/{iid}/reveal", json={"field": "Senha web"}).json()["values"]["Senha web"] == "s3gr3d0"
    assert client.delete("/api/vault/fields/Senha web", headers={"If-Match": _rev(client)}).status_code == 409


def test_delete_template_keeps_items(client, env):
    _init_vault(env)
    iid = _item(client).json()["id"]
    assert client.delete("/api/vault/templates/login", headers={"If-Match": _rev(client)}).status_code == 200
    it = client.get(f"/api/vault/items/{iid}").json()
    assert "template" not in it and it["template_label"] == "Login"


def test_stale_rev_conflict(client, env):
    _init_vault(env)
    old = _rev(client)
    _item(client)
    r = client.post("/api/vault/items", headers={"If-Match": old},
                    json={"title": "Outro", "values": [{"field": "URL", "value": "x"}]})
    assert r.status_code == 409


def test_change_password_reencrypts_vault_yaml(env):
    import deps
    from lib import pwvault, vault
    old_key = _init_vault(env)
    path = deps.NETWORK_DIR / "vault.yaml"
    data = pwvault.default_doc()
    data["items"]["x"] = {"title": "X", "values": {"Senha": vault.encrypt_value(old_key, "abc"), "URL": "u"}}
    path.write_text(pwvault.dump(data))
    _, new_key = vault.build_meta("outra-senha")
    text, n = pwvault.reencrypt_file(path, old_key, new_key)
    assert n == 1
    assert vault.decrypt_value(new_key, yaml.safe_load(text)["items"]["x"]["values"]["Senha"]) == "abc"


def test_permissions_mapped():
    from services import authz
    assert authz.required_perm("GET", "/vault/items") == "vault.view"
    assert authz.required_perm("GET", "/vault/catalog") == "vault.view"
    assert authz.required_perm("POST", "/vault/items/x/reveal") == "vault.reveal"
    assert authz.required_perm("PUT", "/vault/items/x") == "vault.edit"
    assert authz.required_perm("POST", "/vault/templates") == "vault.templates"
    assert authz.required_perm("DELETE", "/vault/fields/URL") == "vault.templates"
    assert authz.required_perm("POST", "/vault/unlock") == authz.ANY
