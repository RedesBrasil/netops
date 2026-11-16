#!/usr/bin/env python3
"""Prepara pacote de uma revisão limpa. Publicação explícita fica no workflow de release."""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from update import releases
from update.common import PROTOCOL, REPOSITORY, UpdateError, read_version, sha256, version_tuple
from update.engine import git_files, validate_manifest


def release_notes(text: str, version: str) -> str:
    match = re.search(r"^## \[" + re.escape(version) + r"\] - \d{4}-\d{2}-\d{2}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match or len(match[1].strip()) < 20:
        raise UpdateError("missing_changelog", "CHANGELOG.md precisa de uma seção não vazia para a versão selecionada.")
    return match[1].strip() + "\n"


# Atualizadores já instalados (até 2.3.1) só aceitam CLAUDE.md na lista de arquivos distribuídos e
# recusam o pacote inteiro (protected_path) se ele trouxer AGENTS.md. Não entra no pacote até que
# a base instalada seja >= 2.4.0 (que aceita AGENTS.md); remover esta entrada na release seguinte.
LEGACY_HOLDBACK = {"AGENTS.md"}


def build_package(files: dict, version: str, destination: Path) -> dict:
    files = {p: i for p, i in files.items() if p not in LEGACY_HOLDBACK}
    manifest = {"protocol": PROTOCOL, "repository": REPOSITORY, "version": version,
                "migrations": [], "files": {p: {k: v for k, v in info.items() if k != "raw"}
                                             for p, info in files.items()}}
    validate_manifest(manifest)
    with tarfile.open(destination, "w:gz") as archive:
        contents = {"manifest.json": (json.dumps(manifest, sort_keys=True).encode(), 0o644)}
        contents.update({"files/" + p: (info["raw"], info["mode"]) for p, info in files.items()})
        for name, (raw, mode) in sorted(contents.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode, member.mtime = len(raw), mode, 0
            archive.addfile(member, io.BytesIO(raw))
    return manifest


def prepare_release(root: Path, output: Path) -> dict:
    # Toda versão deve ser escolhida depois desta consulta, nunca de um cache local.
    stable = releases.stable_releases()
    version = read_version(root)
    if stable and version_tuple(version) <= version_tuple(stable[0]["version"]):
        raise UpdateError("not_newer", "Incremente a versão acima da última release estável: " + stable[0]["tag"])
    if subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD"], check=False).returncode:
        raise UpdateError("dirty_tree", "A revisão de release precisa estar commitada e sem alterações rastreadas.")
    files = git_files(root)
    if "CHANGELOG.md" not in files:
        raise UpdateError("missing_changelog", "CHANGELOG.md precisa estar na revisão publicada.")
    notes = release_notes(files["CHANGELOG.md"]["raw"].decode(), version)
    # Referências locais não autorizam reutilizar uma tag remota já existente.
    tags = releases.api_json(f"repos/{REPOSITORY}/git/matching-refs/tags/v{version}")
    exact = [row for row in tags if row.get("ref") == "refs/tags/v" + version]
    if exact:
        local = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, check=True).stdout.decode().strip()
        tagged = subprocess.run(["git", "-C", str(root), "rev-parse", f"refs/tags/v{version}^{{commit}}"], capture_output=True, check=False)
        if tagged.returncode or tagged.stdout.decode().strip() != local:
            raise UpdateError("tag_conflict", "A tag remota já existe em outra revisão. Nunca mova uma tag publicada.")
    if output == root or root in output.parents:
        raise UpdateError("unsafe_output", "Gere o pacote em um diretório novo fora da instalação.")
    output.mkdir(parents=True, exist_ok=False)
    package = output / releases.asset_name(version)
    manifest = build_package(files, version, package)
    (output / "SHA256SUMS").write_text(f"{sha256(package)}  {package.name}\n", encoding="utf-8")
    (output / "release-notes.md").write_text(notes, encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Consulta releases e prepara pacote verificado de HEAD, sem publicar.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", required=True, type=Path, help="Diretório novo, fora do repositório.")
    args = parser.parse_args()
    try:
        manifest = prepare_release(args.root.resolve(), args.output.resolve())
        print(f"Pacote {manifest['version']} preparado em {args.output}. Nenhuma release foi publicada.")
        return 0
    except (UpdateError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
