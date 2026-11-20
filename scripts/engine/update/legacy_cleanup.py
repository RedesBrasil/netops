"""Remove files renamed in 2.6.1 that the updater had to keep.

The updater never deletes a removed file inside a customizable folder (agents/, workflows/, scripts/tools/...).
After the English renames (PADRAO.md -> STANDARD.md, diagnostics/atendimento/ -> support-monitor/...), the old
copies would stay beside the new ones. This deletes an old file ONLY when its sha256 is identical to a published
version (legacy_files.json, built from the release tags). A file the user edited is never touched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

LIST = Path(__file__).with_name("legacy_files.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root: Path) -> list[str]:
    root = Path(root)
    try:
        known = json.loads(LIST.read_text(encoding="utf-8")).get("files") or {}
    except (OSError, ValueError):
        return []
    removed = []
    for rel, hashes in known.items():
        path = root / rel
        try:
            if path.is_symlink() or not path.is_file() or _sha(path) not in set(hashes):
                continue
            path.unlink()
            removed.append(rel)
        except OSError:
            continue
    # old folders left empty (only __pycache__) go too
    for rel in {str(Path(r).parent) for r in removed}:
        d = root / rel
        try:
            cache = d / "__pycache__"
            if cache.is_dir() and not cache.is_symlink():
                for f in cache.iterdir():
                    if f.is_file() and f.suffix == ".pyc":
                        f.unlink()
                cache.rmdir()
            d.rmdir()
        except OSError:
            pass
    return removed
