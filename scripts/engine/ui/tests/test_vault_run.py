"""scripts/tools/secrets/run.py: referências nvault:// resolvidas só no processo filho, saída mascarada."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[4]
RUN = PROJECT / "scripts/tools/secrets/run.py"
SECRET = "tok-SUPER-secreto-123"


@pytest.fixture()
def vault_env(tmp_path):
    sys.path.insert(0, str(PROJECT / "scripts/engine"))
    from lib import pwvault, vault, vault_session
    from vault import cli
    (tmp_path / "network").mkdir()
    (tmp_path / "runs").mkdir()
    meta, key = vault.build_meta("senha-mestra-teste")
    cli._atomic_write(tmp_path / "network/credentials.yaml",
                      cli._set_vault_block("version: 1\n\ncredentials: {}\n", meta))
    data = pwvault.default_doc()
    data["items"]["coolify-producao"] = {"title": "Coolify", "template": "api", "values": {
        "URL": "https://coolify.example", "API key": vault.encrypt_value(key, SECRET)}}
    (tmp_path / "network/vault.yaml").write_text(pwvault.dump(data))
    vault_session.set_session_key(key, 900)
    env = {**os.environ, "NETOPS_UI_DATA_ROOT": str(tmp_path)}
    env.pop("NETOPS_USER", None)
    return tmp_path, env


def _run(args, env, cwd):
    return subprocess.run([sys.executable, str(RUN), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=60)


def test_env_file_reference_resolved_and_masked(vault_env):
    root, env = vault_env
    app = root / "app"; app.mkdir()
    (app / ".env").write_text("COOLIFY_TOKEN=nvault://coolify-producao/api-key\nBASE=nvault://coolify-producao/url\n"
                              "AUTH='Bearer {{nvault://coolify-producao/API key}}'\nPLAIN=x\n")
    code = ("import os,sys; t=os.environ['COOLIFY_TOKEN']; assert t=='%s'; "
            "assert os.environ['AUTH']=='Bearer %s'; print('BASE', os.environ['BASE']); "
            "print('vazou?', t); sys.stderr.write('err '+t+'\\n'); print('len', len(t))") % (SECRET, SECRET)
    r = _run(["run", "--", sys.executable, "-c", code], env, app)
    assert r.returncode == 0, r.stderr
    assert SECRET not in r.stdout + r.stderr
    assert "vazou? ***" in r.stdout and "err ***" in r.stderr
    assert "BASE https://coolify.example" in r.stdout and f"len {len(SECRET)}" in r.stdout
    assert SECRET not in (app / ".env").read_text()


def test_item_prefix_and_set(vault_env):
    root, env = vault_env
    code = "import os; print(os.environ['COOLIFY_URL']); assert os.environ['T']==os.environ['COOLIFY_API_KEY']"
    r = _run(["run", "--no-dotenv", "--item", "coolify-producao", "--prefix", "COOLIFY_",
              "--set", "T=coolify-producao/api-key", "--", sys.executable, "-c", code], env, root)
    assert r.returncode == 0, r.stderr
    assert "https://coolify.example" in r.stdout


def test_locked_vault_does_not_run_command(vault_env):
    root, env = vault_env
    from lib import vault_session
    vault_session.clear_session()
    marker = root / "ran"
    r = _run(["run", "--set", "T=nvault://coolify-producao/api-key", "--", "touch", str(marker)], env, root)
    assert r.returncode == 3 and "trancado" in r.stderr.lower()
    assert not marker.exists()


def test_bad_reference_and_list_check(vault_env):
    root, env = vault_env
    r = _run(["run", "--set", "T=nvault://nao-existe/x", "--", "true"], env, root)
    assert r.returncode == 2 and "não existe" in r.stderr
    out = _run(["list"], env, root)
    assert out.returncode == 0 and "nvault://coolify-producao/api-key" in out.stdout and SECRET not in out.stdout
    (root / ".env").write_text("A=nvault://coolify-producao/api-key\nB=nvault://coolify-producao/nada\n")
    chk = _run(["check"], env, root)
    assert chk.returncode == 2 and "OK    A" in chk.stdout and "ERRO  B" in chk.stdout


def test_console_user_needs_vault_use(vault_env):
    root, env = vault_env
    from lib import accessdb
    db = root / "runs/netops.db"
    accessdb.create_user(db, None, "Senha-forte-123", email="chefe@empresa.com.br", groups=["admin"])
    accessdb.create_user(db, None, "Senha-forte-123", email="leitor@empresa.com.br", groups=["leitura"])
    user = accessdb.login_username(db, "leitor@empresa.com.br")
    r = _run(["run", "--set", "T=nvault://coolify-producao/api-key", "--", "true"], {**env, "NETOPS_USER": user}, root)
    assert r.returncode == 4 and "vault.use" in r.stderr
    admin = accessdb.login_username(db, "chefe@empresa.com.br")
    ok = _run(["run", "--set", "T=nvault://coolify-producao/api-key", "--", "true"], {**env, "NETOPS_USER": admin}, root)
    assert ok.returncode == 0, ok.stderr
    assert accessdb.query_audit(db, action="vault.run")["items"][0]["target"] == "coolify-producao"


def test_masker_split_across_chunks():
    sys.path.insert(0, str(RUN.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("nvault_run", RUN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    m = mod.Masker(["abcdef"])
    out = m.feed(b"xx abc") + m.feed(b"def yy ab") + m.feed(b"Z") + m.flush()
    assert out == b"xx *** yy abZ"
