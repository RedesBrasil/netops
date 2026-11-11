"""Reinício real do launcher em cópia integral fictícia; nenhum serviço real é tocado."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import deps
from update.common import PROTOCOL, REPOSITORY, STATE_DIR, distributed, private_dir, read_version, write_json
from update.release import build_package

PROJECT = Path(__file__).resolve().parents[4]


def read_supervisor(state):
    return json.loads((state / "supervisor.json").read_text())


def wait_for(fn, process, timeout=65):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Launcher de teste encerrou antes do esperado")
        try:
            result = fn()
            if result:
                return result
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.15)
    raise AssertionError("Timeout no processo isolado")


def test_launcher_update_then_failed_release_rolls_back(tmp_path):
    root = tmp_path / "installation"
    root.mkdir()
    # Somente caminhos distribuíveis, incluindo o código novo ainda não commitado.
    paths = subprocess.check_output(["git", "-C", str(PROJECT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]).split(b"\0")
    files = {}
    for raw in paths:
        if not raw:
            continue
        rel = raw.decode()
        if not distributed(rel):
            continue
        source = PROJECT / rel
        if not source.is_file() or source.is_symlink():
            continue
        content = source.read_bytes()
        if rel == "core/config/core-config.yaml":
            content = content.replace(f'  version: "{read_version(PROJECT)}"'.encode(), b'  version: "1.0.0"')
        mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
        files[rel] = {"raw": content, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content), "mode": mode}
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        dest.chmod(mode)
    # Reusa dependências somente leitura. Requirements iguais não trocam o venv neste teste.
    test_venv = PROJECT / ".venv" if (PROJECT / ".venv/bin/python3").exists() else Path(sys.prefix)
    (root / ".venv").symlink_to(test_venv, target_is_directory=True)
    for name in ("hosts", "topology"):
        shutil.copy(root / f"network/{name}.example.yaml", root / f"network/{name}.yaml")
    (root / "core/config/project-config.yaml").write_text("project:\n  network_name: Fixture Updates\n")
    (root / "memory").mkdir()
    (root / "memory/MEMORY.md").write_text("fixture preserved\n")
    original_hosts = (root / "network/hosts.yaml").read_bytes()
    state = private_dir(root / STATE_DIR)
    write_json(state / "installed.json", {"protocol": PROTOCOL, "repository": REPOSITORY, "version": "1.0.0",
                                           "files": {p: {k: v for k, v in i.items() if k != "raw"} for p, i in files.items()}})
    assets = tmp_path / "assets"
    assets.mkdir()
    ghbin = tmp_path / "bin"
    ghbin.mkdir()
    gh = ghbin / "gh"
    gh.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
base = Path(os.environ["NETOPS_FIXTURE_ASSETS"])
arg = next(a for a in sys.argv if a.startswith("repos/"))
if "/releases/assets/" in arg:
    sys.stdout.buffer.write((base / "release.tar.gz").read_bytes())
else:
    sys.stdout.write((base / "releases.json").read_text())
''')
    gh.chmod(0o755)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), PATH=str(ghbin) + os.pathsep + os.environ["PATH"],
               NETOPS_UI_HOME=str(home), NETOPS_UI_HOST="127.0.0.1", NETOPS_UI_PORT=str(port),
               NETOPS_UI_TERMINAL="0", NETOPS_UI_CLAUDE="0", NETOPS_UI_DATA_ROOT=str(root),
               NETOPS_FIXTURE_ASSETS=str(assets))
    for key in ("NETOPS_UPDATE_FROZEN", "NETOPS_UPDATE_MANAGED", "NETOPS_UPDATE_NONCE"):
        env.pop(key, None)
    with (tmp_path / "console.log").open("wb") as log:
        proc = subprocess.Popen(["bash", str(root / "scripts/engine/ui/start.sh")], cwd=root, env=env, stdout=log, stderr=log)
        try:
            wait_for(lambda: (state / "supervisor.json").exists(), proc)
            def get_meta():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config/meta", timeout=2) as response:
                    return json.load(response)
            assert get_meta()["version"] == "1.0.0"
            if os.environ.get("PLAYWRIGHT_MODULE"):
                browser_env = dict(os.environ, NETOPS_E2E_URL=f"http://127.0.0.1:{port}",
                                   NETOPS_UPDATE_TEST_ROOT=str(root))
                subprocess.run(["node", str(PROJECT / "scripts/engine/ui/tests/updates.browser.mjs")],
                               env=browser_env, check=True, timeout=90)
            # Cofre fictício: teste passa pela confirmação HTTP autenticada real.
            from lib import vault
            from vault import cli
            meta, _ = vault.build_meta("fixture-update-master")
            (root / "network/credentials.yaml").write_text(cli._set_vault_block("version: 1\ncredentials: {}\n", meta))
            (root / "network/credentials.yaml").chmod(0o600)
            def post_api(endpoint, body, token=None):
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/{endpoint}",
                    data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **({"X-Netops-Session": token} if token else {})})
                with urllib.request.urlopen(request, timeout=40) as response:
                    return json.load(response)
            for index, version in enumerate(("1.1.0", "1.2.0"), start=1):
                candidate = {p: dict(i) for p, i in files.items()}
                for rel in ("core/config/core-config.yaml", "scripts/engine/ui/server.py"):
                    content = candidate[rel]["raw"]
                    if rel.endswith(".yaml"):
                        content = content.replace(b'  version: "1.0.0"', f'  version: "{version}"'.encode())
                    elif index == 2:
                        content = b"raise RuntimeError('fixture broken release')\n"
                    candidate[rel].update(raw=content, size=len(content), sha256=hashlib.sha256(content).hexdigest())
                package = assets / "release.tar.gz"
                build_package(candidate, version, package)
                digest = "sha256:" + hashlib.sha256(package.read_bytes()).hexdigest()
                asset = {"id": index, "name": f"netops-{version}.tar.gz", "digest": digest, "size": package.stat().st_size}
                (assets / "releases.json").write_text(json.dumps([{"id": index, "tag_name": "v" + version, "body": "fixture", "assets": [asset]}]))
                wait_for(lambda: read_supervisor(state).get("server_pid") == json.loads((state / "ready.json").read_text())["pid"], proc)
                token = post_api("auth/login", {"master_password": "fixture-update-master"})["auth_token"]
                job = post_api("updates/apply", {"release_id": index, "confirm": True}, token)
                assert job["phase"] == "queued"
                expected = "completed" if index == 1 else "rolled_back"
                wait_for(lambda: json.loads((state / "job.json").read_text()).get("phase") == expected, proc)
                wait_for(lambda: get_meta()["version"] == "1.1.0", proc)
                assert (root / "network/hosts.yaml").read_bytes() == original_hosts
                assert (root / "memory/MEMORY.md").read_text() == "fixture preserved\n"
                assert (root / ".venv").resolve() == test_venv.resolve()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=35)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    assert proc.returncode == 0
