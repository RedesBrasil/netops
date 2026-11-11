"""Pacote, snapshot verificado e journal de aplicação/rollback. Somente stdlib."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
from pathlib import Path

from .common import (
    MAX_FILES, MAX_PACKAGE, MAX_UNPACKED, PROTOCOL, REPOSITORY, STATE_DIR,
    UpdateError, atomic_bytes, customizable, distributed, private_dir, read_json,
    read_version, safe_relative, sha256, target_path, version_tuple, write_json,
)

MANIFEST = "manifest.json"
REQUIRED = {"core/config/core-config.yaml", "requirements.txt", "scripts/engine/ui/start.sh",
            "scripts/engine/ui/server.py", "scripts/engine/ui/app.py", "scripts/engine/update/supervisor.py"}


def validate_manifest(manifest: dict) -> dict:
    if (not isinstance(manifest, dict) or manifest.get("protocol") != PROTOCOL
            or manifest.get("repository") != REPOSITORY or manifest.get("migrations")):
        raise UpdateError("incompatible_package", "Pacote ou migração incompatível com este atualizador.")
    version_tuple(manifest.get("version", ""))
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise UpdateError("invalid_manifest", "Manifesto sem inventário válido.")
    total = 0
    for rel, info in files.items():
        if not distributed(rel):
            raise UpdateError("protected_path", "Pacote tenta substituir arquivo protegido: " + rel)
        if (not isinstance(info, dict) or not re.fullmatch(r"[a-f0-9]{64}", info.get("sha256", ""))
                or type(info.get("size")) is not int or info["size"] < 0
                or info.get("mode") not in (0o644, 0o755)):
            raise UpdateError("invalid_manifest", "Metadados de arquivo inválidos: " + rel)
        total += info["size"]
        for parent in Path(rel).parents:
            if parent.as_posix() in files:
                raise UpdateError("invalid_manifest", "Arquivo e diretório ocupam o mesmo caminho.")
    if total > MAX_UNPACKED or not REQUIRED.issubset(files):
        raise UpdateError("invalid_manifest", "Pacote incompleto ou acima do limite descomprimido.")
    return manifest


def unpack(package: Path, stage: Path, expected_version: str) -> dict:
    if package.stat().st_size > MAX_PACKAGE:
        raise UpdateError("package_too_large", "Pacote excede o limite permitido.")
    private_dir(stage)
    try:
        with tarfile.open(package, "r:gz") as archive:
            members, total = {}, 0
            for member in archive:
                if not member.isfile() or member.name in members:
                    raise UpdateError("unsafe_package", "Pacote contém links, entradas especiais ou duplicatas.")
                safe_relative(member.name)
                total += member.size
                if len(members) >= MAX_FILES + 1 or total > MAX_UNPACKED + 4 * 1024 * 1024:
                    raise UpdateError("package_too_large", "Pacote descomprimido excede o limite.")
                members[member.name] = member
            metadata = members.get(MANIFEST)
            if metadata is None or metadata.size > 4 * 1024 * 1024:
                raise UpdateError("invalid_manifest", "Manifesto ausente ou muito grande.")
            manifest = validate_manifest(json.load(archive.extractfile(metadata)))
            if manifest["version"] != expected_version:
                raise UpdateError("version_mismatch", "Versão do pacote diverge da release selecionada.")
            if set(members) != {MANIFEST} | {"files/" + rel for rel in manifest["files"]}:
                raise UpdateError("invalid_manifest", "Conteúdo do pacote diverge do manifesto.")
            for rel, info in manifest["files"].items():
                member = members["files/" + rel]
                if member.size != info["size"] or member.mode != info["mode"]:
                    raise UpdateError("invalid_package", "Tamanho ou permissão inválida no pacote.")
                raw = archive.extractfile(member).read(info["size"] + 1)
                if hashlib.sha256(raw).hexdigest() != info["sha256"]:
                    raise UpdateError("digest_mismatch", "Hash de arquivo diverge do manifesto.")
                dest = target_path(stage, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                atomic_bytes(dest, raw, info["mode"])
            if read_version(stage) != expected_version:
                raise UpdateError("version_mismatch", "Versão central diverge do manifesto.")
            return manifest
    except (tarfile.TarError, ValueError, UnicodeError, KeyError, TypeError):
        raise UpdateError("invalid_package", "Pacote ou manifesto inválido.") from None


def git_files(root: Path, revision="HEAD") -> dict:
    result = subprocess.run(["git", "-C", str(root), "ls-tree", "-rz", revision],
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise UpdateError("unknown_installation", "Sem manifesto instalado ou referência Git confiável.")
    files = {}
    for entry in result.stdout.split(b"\x00"):
        if not entry:
            continue
        meta, rawpath = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        rel = rawpath.decode("utf-8")
        if not distributed(rel):
            continue
        if kind != "blob" or mode not in ("100644", "100755"):
            raise UpdateError("unsafe_git", "Distribuição Git contém entrada não suportada: " + rel)
        raw = subprocess.run(["git", "-C", str(root), "cat-file", "blob", oid],
                             capture_output=True, timeout=30, check=True).stdout
        files[rel] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
                      "mode": 0o755 if mode == "100755" else 0o644, "raw": raw}
    return files


def installed_manifest(root: Path) -> dict:
    stored = read_json(root / STATE_DIR / "installed.json")
    if stored is not None:
        return validate_manifest(stored)
    files = git_files(root)
    return {"protocol": PROTOCOL, "repository": REPOSITORY, "version": read_version(root),
            "files": {p: {k: v for k, v in item.items() if k != "raw"} for p, item in files.items()}}


def fingerprint(path: Path):
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise UpdateError("local_conflict", "Um caminho gerenciado não é um arquivo regular.")
    return {"sha256": sha256(path), "mode": stat.S_IMODE(path.stat().st_mode), "size": path.stat().st_size}


def same_file(current, expected) -> bool:
    if current is None or expected is None:
        return current is expected
    return (current["sha256"] == expected["sha256"] and current["size"] == expected["size"]
            and bool(current["mode"] & 0o111) == bool(expected["mode"] & 0o111))


def plan_files(root: Path, old: dict, new: dict) -> tuple[list, list]:
    changes, preserved = [], []
    for rel in sorted(set(old["files"]) | set(new["files"])):
        if not distributed(rel):
            continue
        previous, incoming = old["files"].get(rel), new["files"].get(rel)
        current = fingerprint(target_path(root, rel))
        if previous is None:
            if current is not None and not same_file(current, incoming):
                raise UpdateError("local_conflict", "Novo arquivo colide com conteúdo local: " + rel)
        elif not same_file(current, previous):
            if customizable(rel):
                preserved.append(rel)
                continue
            raise UpdateError("modified_engine", "Motor alterado localmente; preserve ou revise antes de atualizar: " + rel)
        if incoming is None and customizable(rel):
            preserved.append(rel)
            continue
        if not same_file(current, incoming):
            changes.append({"path": rel, "before": current, "after": incoming})
    return changes, preserved


SNAPSHOT_EXCLUDE = {STATE_DIR, ".netops-venvs", ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def snapshot(root: Path, data_root: Path, directory: Path) -> dict:
    """Arquivos privados são apenas bytes opacos. Nunca segue links ou imprime conteúdo."""
    private_dir(directory)
    if data_root != root and data_root in root.parents:
        raise UpdateError("unsafe_data_root", "O diretório externo de dados não pode conter a instalação.")
    records, total = [], 0
    sources = [("installation", root)]
    if data_root != root and root not in data_root.parents:
        sources.append(("data", data_root))
    def unreadable(_error):
        raise UpdateError("snapshot_unreadable", "Um diretório não pôde ser incluído no backup. Atualização cancelada.")

    for label, source in sources:
        for folder, dirs, names in os.walk(source, followlinks=False, onerror=unreadable):
            base = Path(folder)
            for name in dirs:
                path = base / name
                if path.is_symlink() and name not in SNAPSHOT_EXCLUDE:
                    records.append({"source": label, "path": path.relative_to(source).as_posix(), "link": os.readlink(path)})
            dirs[:] = [d for d in dirs if d not in SNAPSHOT_EXCLUDE and not (base / d).is_symlink()]
            for name in names:
                path = base / name
                st = path.lstat()
                rel = path.relative_to(source).as_posix()
                if stat.S_ISLNK(st.st_mode):
                    records.append({"source": label, "path": rel, "link": os.readlink(path)})
                    continue
                if not stat.S_ISREG(st.st_mode):
                    raise UpdateError("snapshot_special_file", "Snapshot encontrou um arquivo especial; encerre o processo que o mantém aberto.")
                total += st.st_size
                records.append({"source": label, "path": rel, "size": st.st_size,
                                "mode": stat.S_IMODE(st.st_mode), "sha256": sha256(path)})
    if shutil.disk_usage(directory).free < total + 64 * 1024 * 1024:
        raise UpdateError("disk_space", "Espaço insuficiente para snapshot verificado. Nenhum arquivo foi substituído.")
    locations = dict(sources)
    for record in records:
        if "link" in record:
            continue
        src = locations[record["source"]] / record["path"]
        dest = directory / record["source"] / record["path"]
        private_dir(dest.parent)
        with src.open("rb") as reader, dest.open("xb") as writer:
            os.chmod(dest, 0o600)
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        if sha256(dest) != record["sha256"] or fingerprint(src) != {k: record[k] for k in ("sha256", "mode", "size")}:
            raise UpdateError("snapshot_changed", "Arquivo mudou durante o backup; atualização cancelada.")
    manifest = {"created_at": int(time.time()), "files": records, "bytes": total}
    write_json(directory / "snapshot.json", manifest)
    return manifest


def status(root: Path, phase: str, **fields):
    state = root / STATE_DIR
    job = read_json(state / "job.json", {})
    job.update(fields, phase=phase, updated_at=int(time.time()))
    write_json(state / "job.json", job)


def prepare(root: Path, data_root: Path, package: Path, version: str, job_id: str) -> dict:
    if version_tuple(version) <= version_tuple(read_version(root)):
        raise UpdateError("not_newer", "A versão selecionada não é superior à instalada.")
    jobdir = private_dir(root / STATE_DIR / "jobs" / job_id)
    status(root, "validating")
    new = unpack(package, jobdir / "stage", version)
    old = installed_manifest(root)
    changes, preserved = plan_files(root, old, new)
    status(root, "backup", preserved=preserved)
    snapshot(root, data_root, jobdir / "backup")
    status(root, "preparing")
    candidate = None
    if old["files"].get("requirements.txt") != new["files"].get("requirements.txt"):
        candidate = root / ".netops-venvs" / job_id
        private_dir(candidate.parent)
        # Bibliotecas não contêm dados privados. O terminal de privilégio reduzido
        # também precisa atravessar o caminho do venv selecionado por .venv.
        os.chmod(candidate.parent, 0o755)
        result = subprocess.run([str(root / ".venv/bin/python3"), "-m", "venv", str(candidate)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        if result.returncode:
            raise UpdateError("venv_failed", "Falha ao preparar ambiente Python. O ambiente atual não foi modificado.")
        result = subprocess.run([str(candidate / "bin/python3"), "-m", "pip", "install", "--disable-pip-version-check",
                                 "-r", str(jobdir / "stage/requirements.txt")], cwd=jobdir / "stage",
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
        if result.returncode:
            raise UpdateError("dependencies_failed", "Falha ao instalar dependências no novo ambiente. Ambiente atual preservado.")
        result = subprocess.run([str(candidate / "bin/python3"), "-m", "pip", "check"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if result.returncode:
            raise UpdateError("dependencies_failed", "O novo ambiente contém dependências incompatíveis.")
    python = candidate / "bin/python3" if candidate else root / ".venv/bin/python3"
    # O bootstrap de importações será validado também pela prontidão HTTP depois da troca.
    if not python.exists():
        raise UpdateError("venv_missing", "Interpretador Python indisponível para iniciar a versão candidata.")
    venv = root / ".venv"
    if not venv.exists():
        raise UpdateError("venv_missing", "Ambiente .venv ausente.")
    original_link = os.readlink(venv) if venv.is_symlink() else None
    journal = {"job_id": job_id, "phase": "prepared", "old": old, "new": new,
               "changes": changes, "preserved": preserved, "candidate": str(candidate) if candidate else None,
               "venv_link": original_link, "venv_backup": str(jobdir / "original-venv"),
               "old_installed": read_json(root / STATE_DIR / "installed.json")}
    write_json(root / STATE_DIR / "journal.json", journal)
    return journal


def apply(root: Path, journal: dict):
    jobdir = root / STATE_DIR / "jobs" / journal["job_id"]
    for rel, info in journal["new"]["files"].items():
        if fingerprint(target_path(jobdir / "stage", rel)) != info:
            raise UpdateError("staging_changed", "Pacote em staging mudou após a verificação.")
    for change in journal["changes"]:
        if fingerprint(target_path(root, change["path"])) != change["before"]:
            raise UpdateError("changed_during_update", "Arquivo mudou antes da aplicação; atualização cancelada.")
    journal["phase"] = "applying"
    write_json(root / STATE_DIR / "journal.json", journal)
    status(root, "applying")
    for change in journal["changes"]:
        dest = target_path(root, change["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if change["after"] is None:
            dest.unlink()
        else:
            atomic_bytes(dest, (jobdir / "stage" / change["path"]).read_bytes(), change["after"]["mode"])
    if journal["candidate"]:
        venv = root / ".venv"
        if venv.is_symlink():
            venv.unlink()
        else:
            venv.rename(journal["venv_backup"])
        os.symlink(journal["candidate"], venv, target_is_directory=True)
    journal["phase"] = "restarting"
    write_json(root / STATE_DIR / "journal.json", journal)
    status(root, "restarting")


def rollback(root: Path, journal: dict):
    status(root, "rolling_back")
    jobdir = root / STATE_DIR / "jobs" / journal["job_id"]
    if journal["phase"] != "prepared":
        for change in reversed(journal["changes"]):
            dest = target_path(root, change["path"])
            before = change["before"]
            if before is None:
                if dest.exists():
                    if fingerprint(dest) != change["after"]:
                        raise UpdateError("rollback_conflict", "Conteúdo mudou após a aplicação; backup retido para recuperação manual.")
                    dest.unlink()
            else:
                actual = fingerprint(dest)
                if actual is not None and actual != before and not same_file(actual, change["after"]):
                    raise UpdateError("rollback_conflict", "Arquivo alterado por outro processo. Snapshot retido para recuperação manual.")
                source = jobdir / "backup/installation" / change["path"]
                if not source.is_file() or sha256(source) != before["sha256"]:
                    raise UpdateError("rollback_backup", "Snapshot não passou na verificação de recuperação.")
                dest.parent.mkdir(parents=True, exist_ok=True)
                atomic_bytes(dest, source.read_bytes(), before["mode"])
        if journal["candidate"]:
            venv, saved = root / ".venv", Path(journal["venv_backup"])
            if venv.is_symlink() and os.readlink(venv) == journal["candidate"]:
                venv.unlink()
            if not venv.exists():
                if journal["venv_link"] is not None:
                    os.symlink(journal["venv_link"], venv, target_is_directory=True)
                elif saved.exists():
                    saved.rename(venv)
                else:
                    raise UpdateError("rollback_venv", "Ambiente anterior não foi encontrado.")
    installed = root / STATE_DIR / "installed.json"
    if journal.get("old_installed") is not None:
        write_json(installed, journal["old_installed"])
    else:
        installed.unlink(missing_ok=True)
    journal["phase"] = "rolled_back"
    write_json(root / STATE_DIR / "journal.json", journal)
    status(root, "rolled_back", detail="Atualização não confirmada. Código e ambiente anteriores restaurados.",
           backup=str(jobdir / "backup"))


def commit(root: Path, journal: dict):
    write_json(root / STATE_DIR / "installed.json", journal["new"])
    journal["phase"] = "completed"
    write_json(root / STATE_DIR / "journal.json", journal)
    status(root, "completed", version=journal["new"]["version"], preserved=journal["preserved"],
           backup=str(root / STATE_DIR / "jobs" / journal["job_id"] / "backup"),
           detail="Atualização concluída e verificada. Dados locais preservados.")
