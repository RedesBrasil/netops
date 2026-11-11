"""GitHub privado via gh: autenticação fica no processo, nunca no navegador."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .common import MAX_PACKAGE, REPOSITORY, UpdateError, sha256, version_tuple


def _failure(stderr: bytes) -> UpdateError:
    text = stderr.decode("utf-8", errors="replace").lower()
    if "rate limit" in text or "http 429" in text:
        return UpdateError("rate_limit", "Limite do GitHub atingido. Tente novamente mais tarde.")
    if any(s in text for s in ("gh auth login", "http 401", "authentication", "not logged")):
        return UpdateError("github_auth", "Autentique gh no mesmo usuário e HOME do servidor: gh auth login --hostname github.com")
    if "http 403" in text or "http 404" in text:
        return UpdateError("github_access", "Sem acesso ao repositório privado RedesBrasil/netops ou à release solicitada.")
    return UpdateError("github_unavailable", "Não foi possível consultar o GitHub. Confira a conexão e tente novamente.")


def _api(endpoint: str, destination: Path, *, binary=False, limit=16 * 1024 * 1024, timeout=45):
    if not shutil.which("gh"):
        raise UpdateError("gh_missing", "Instale GitHub CLI (gh) e autentique no usuário que inicia o console.")
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    env.pop("GH_DEBUG", None)
    args = ["gh", "api", "--hostname", "github.com", endpoint]
    if binary:
        args += ["-H", "Accept: application/octet-stream"]
    with destination.open("xb") as output, tempfile.TemporaryFile() as errors:
        os.chmod(destination, 0o600)
        proc = subprocess.Popen(args, stdout=output, stderr=errors, env=env, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if destination.stat().st_size > limit:
                    raise UpdateError("github_too_large", "Resposta do GitHub excede o limite permitido.")
                if time.monotonic() >= deadline:
                    raise UpdateError("github_timeout", "O GitHub demorou para responder. Tente novamente.")
                time.sleep(0.05)
            if destination.stat().st_size > limit:
                raise UpdateError("github_too_large", "Resposta do GitHub excede o limite permitido.")
            if proc.returncode:
                errors.seek(0)
                raise _failure(errors.read(8192))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def api_json(endpoint: str):
    with tempfile.TemporaryDirectory(prefix="netops-gh-") as tmp:
        path = Path(tmp) / "response.json"
        _api(endpoint, path)
        try:
            return json.loads(path.read_bytes())
        except (ValueError, UnicodeError):
            raise UpdateError("github_invalid", "Resposta inválida do GitHub.") from None


def asset_name(version: str) -> str:
    version_tuple(version)
    return f"netops-{version.removeprefix('v')}.tar.gz"


def stable_releases() -> list[dict]:
    releases, page, seen = [], 1, set()
    while True:
        rows = api_json(f"repos/{REPOSITORY}/releases?per_page=100&page={page}")
        if not isinstance(rows, list):
            raise UpdateError("github_invalid", "Lista de releases inválida.")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), int) or row["id"] in seen:
                raise UpdateError("github_incomplete", "A lista de releases mudou durante a consulta. Verifique novamente.")
            seen.add(row["id"])
            if row.get("draft") or row.get("prerelease"):
                continue
            try:
                version = version_tuple(row.get("tag_name", ""))
            except UpdateError:
                continue
            tag = row["tag_name"]
            name = asset_name(tag)
            assets = [a for a in row.get("assets", []) if a.get("name") == name]
            asset = assets[0] if len(assets) == 1 else None
            digest = asset.get("digest", "") if asset else ""
            installable = bool(asset and isinstance(asset.get("id"), int)
                               and re.fullmatch(r"sha256:[a-f0-9]{64}", digest or "")
                               and 0 < asset.get("size", 0) <= MAX_PACKAGE)
            releases.append({
                "id": row["id"], "tag": tag, "version": ".".join(map(str, version)),
                "name": row.get("name") or tag, "published_at": row.get("published_at"),
                "changelog": row.get("body") or "Sem notas de versão.",
                "url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
                "installable": installable,
                "asset": {"id": asset["id"], "digest": digest, "size": asset["size"], "name": name} if installable else None,
            })
        if len(rows) < 100:
            break
        page += 1
    versions = [r["version"] for r in releases]
    if len(set(versions)) != len(versions):
        raise UpdateError("github_ambiguous", "Há releases estáveis com versões duplicadas. Corrija no GitHub antes de atualizar.")
    return sorted(releases, key=lambda r: version_tuple(r["version"]), reverse=True)


def download(release: dict, path: Path):
    asset = release.get("asset")
    if not release.get("installable") or not asset:
        raise UpdateError("no_package", "Esta release não tem um pacote oficial verificável.")
    _api(f"repos/{REPOSITORY}/releases/assets/{int(asset['id'])}", path,
         binary=True, limit=MAX_PACKAGE, timeout=300)
    if path.stat().st_size != asset["size"] or "sha256:" + sha256(path) != asset["digest"]:
        raise UpdateError("digest_mismatch", "O pacote baixado não corresponde ao digest publicado pelo GitHub.")
