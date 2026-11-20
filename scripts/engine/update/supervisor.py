#!/usr/bin/env python3
"""Supervisor efêmero do launcher. A execução usa uma cópia privada e imutável."""
from __future__ import annotations

import argparse
import json
import urllib.request
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from update.common import (STATE_DIR, TERMINAL_STATES, UpdateError, installation_lock,
                           atomic_bytes, private_dir, read_json, read_version, write_json)
from update import engine, releases


def freeze(root: Path):
    if os.environ.get("NETOPS_UPDATE_FROZEN") == "1":
        return
    runtime = private_dir(root / STATE_DIR / "runtime" / uuid.uuid4().hex)
    shutil.copytree(Path(__file__).resolve().parent, runtime / "update",
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.environ["NETOPS_UPDATE_FROZEN"] = "1"
    os.execv(sys.executable, [sys.executable, str(runtime / "update/supervisor.py"), *sys.argv[1:]])


def stop_server(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def launch(root: Path, args: list[str], *, recovering=False):
    state = private_dir(root / STATE_DIR)
    nonce = uuid.uuid4().hex
    ready = state / "ready.json"
    ready.unlink(missing_ok=True)
    env = dict(os.environ, NETOPS_UPDATE_MANAGED="1", NETOPS_UPDATE_NONCE=nonce,
               NETOPS_UPDATE_RECOVERING="1" if recovering else "0")
    child = subprocess.Popen([str(root / ".venv/bin/python3"), str(root / "scripts/engine/ui/server.py"), *args],
                             cwd=root, env=env)
    return child, nonce


def wait_ready(root: Path, child, nonce: str, version: str, args: list[str], timeout=45):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    bind, _ = parser.parse_known_args(args)
    # bind curinga (0.0.0.0/::) escuta em todos os IPs: a conferência conecta pelo loopback
    h = {"0.0.0.0": "127.0.0.1", "::": "::1", "*": "127.0.0.1", "": "127.0.0.1"}.get(bind.host, bind.host)
    host = f"[{h}]" if ":" in h else h
    url = f"http://{host}:{bind.port}/api/config/meta"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return False
        try:
            receipt = read_json(root / STATE_DIR / "ready.json", {})
            if receipt.get("nonce") == nonce and receipt.get("version") == version and receipt.get("pid") == child.pid:
                with opener.open(url, timeout=2) as response:
                    meta = json.load(response)
                if meta.get("boot_id") == nonce and meta.get("version") == version:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(0.15)
    return False


def run(root: Path, args: list[str]) -> int:
    stopping = False

    def terminate(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    state = private_dir(root / STATE_DIR)
    with installation_lock(root):
        previous = read_json(state / "ready.json", {})
        if isinstance(previous.get("pid"), int) and previous["pid"] > 0:
            try:
                os.kill(previous["pid"], 0)
            except ProcessLookupError:
                pass
            except PermissionError:
                raise UpdateError("orphan_server", "Há um processo anterior sem acesso para verificar. Encerre o console anterior antes de recuperar.") from None
            else:
                raise UpdateError("orphan_server", "Um servidor anterior ainda está vivo. Encerre essa instância antes de reiniciar ou recuperar.")
        if read_json(state / "job.json", {}).get("phase") == "recovery_failed":
            print("ERRO: recuperação pendente. Consulte scripts/engine/update/SKILL.md.", file=sys.stderr)
            return 1
        journal = read_json(state / "journal.json")
        if journal and journal.get("phase") not in TERMINAL_STATES:
            try:
                engine.rollback(root, journal)
            except Exception:
                engine.status(root, "recovery_failed", detail="Recuperação pendente. Preserve .netops-update e consulte o procedimento manual.")
                return 1
        job = read_json(state / "job.json", {})
        if job and job.get("phase") not in TERMINAL_STATES:
            engine.status(root, "failed", detail="Execução anterior foi interrompida antes da aplicação. Instalação preservada.")
        (state / "request.json").unlink(missing_ok=True)
        child, nonce = launch(root, args)
        if not wait_ready(root, child, nonce, read_version(root), args):
            stop_server(child)
            return 1
        write_json(state / "supervisor.json", {"pid": os.getpid(), "server_pid": child.pid})
        try:
            while not stopping and child.poll() is None:
                request = read_json(state / "request.json")
                if request is None:
                    time.sleep(0.2)
                    continue
                (state / "request.json").unlink()
                journal = None
                server_stopped = False
                try:
                    job_id = request["job_id"]
                    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
                        raise UpdateError("invalid_job", "Identificador de atualização inválido.")
                    all_releases = releases.stable_releases()
                    release = all_releases[0] if all_releases else None
                    if not release or release["id"] != request["release_id"] or release["asset"] != request["asset"]:
                        raise UpdateError("release_changed", "A release foi alterada. Verifique atualizações novamente.")
                    engine.status(root, "downloading")
                    jobdir = private_dir(state / "jobs" / job_id)
                    package = jobdir / "release.tar.gz"
                    releases.download(release, package)
                    journal = engine.prepare(root, Path(request["data_root"]), package, release["version"], job_id)
                    if stopping:
                        raise UpdateError("cancelled", "Atualização cancelada antes da aplicação.")
                    atomic_bytes(state / "recovery-supervisor", (str(Path(__file__).resolve()) + "\n").encode())
                    stop_server(child)
                    server_stopped = True
                    engine.apply(root, journal)
                    child, nonce = launch(root, args, recovering=True)
                    if not wait_ready(root, child, nonce, release["version"], args):
                        stop_server(child)
                        raise UpdateError("readiness_failed", "A nova versão não iniciou corretamente.")
                    engine.commit(root, journal)
                    (state / "recovery-supervisor").unlink(missing_ok=True)
                    # O servidor já pronto consulta o estado em disco antes de liberar escritas.
                except Exception as exc:
                    if journal:
                        stop_server(child)
                        try:
                            engine.rollback(root, journal)
                        except Exception:
                            engine.status(root, "recovery_failed", detail="Rollback incompleto. Snapshot retido; recuperação manual necessária.")
                            return 1
                    else:
                        engine.status(root, "failed", detail=exc.detail if isinstance(exc, UpdateError) else
                                      "Falha na preparação. Nenhum dado foi substituído.")
                    if server_stopped or child.poll() is not None:
                        child, nonce = launch(root, args)
                        if not wait_ready(root, child, nonce, read_version(root), args):
                            stop_server(child)
                            engine.status(root, "recovery_failed", detail="O console anterior não iniciou. Snapshot retido para recuperação manual.")
                            return 1
                (state / "recovery-supervisor").unlink(missing_ok=True)
                write_json(state / "supervisor.json", {"pid": os.getpid(), "server_pid": child.pid})
            return 0 if stopping else child.returncode or 0
        finally:
            stop_server(child)
            (state / "supervisor.json").unlink(missing_ok=True)
            (state / "ready.json").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Launcher gerenciado do NetOps.")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("server_args", nargs=argparse.REMAINDER)
    opts = parser.parse_args()
    root = opts.root.resolve()
    freeze(root)
    args = opts.server_args
    if args[:1] == ["--"]:
        args = args[1:]
    try:
        return run(root, args)
    except UpdateError as exc:
        print("ERRO: " + exc.detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
