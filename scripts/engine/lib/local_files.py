"""Local files of an installation that are born in the instance language (core/rules/i18n.md).

AGENTS.md (repo root) and memory/MEMORY.md are local (git-ignored, never overwritten by updates). They are
created from core/templates/<lang>/<NAME>.tmpl.md when it exists, else from core/templates/<NAME>.tmpl.md
(the legacy Portuguese template). `sync_language()` regenerates them in the chosen language ONLY while they
are still pristine (identical to what a template would generate): anything the user added is never touched.
"""
from __future__ import annotations

import os
from pathlib import Path

from lib import i18n

TEMPLATES = ("AGENTS", "MEMORY")
_TARGET = {"AGENTS": "AGENTS.md", "MEMORY": "memory/MEMORY.md"}
_LEGACY_PRISTINE = {"MEMORY": ["# Memória — NetOps\n\n", "# Memória — NetOps\n", ""]}


def _templates_dir(code_root: Path) -> Path:
    return code_root / "core" / "templates"


def template_path(code_root: Path, name: str, lang: str | None) -> Path | None:
    base = _templates_dir(code_root)
    code = i18n.normalize(lang) if lang else None
    for p in ([base / code / f"{name}.tmpl.md"] if code else []) + [base / f"{name}.tmpl.md"]:
        if p.is_file():
            return p
    return None


def render(code_root: Path, name: str, lang: str | None) -> str | None:
    """Template text without its leading <!-- ... --> maintainer comment."""
    p = template_path(code_root, name, lang)
    if p is None:
        return None
    text = p.read_text(encoding="utf-8")
    if text.lstrip().startswith("<!--") and "-->" in text:
        text = text.split("-->", 1)[1].lstrip("\n")
    return text


def _pristine_variants(code_root: Path, name: str) -> set[str]:
    out = set(_LEGACY_PRISTINE.get(name, []))
    for lang in [None] + i18n.codes():
        r = render(code_root, name, lang)
        if r is not None:
            out.add(r)
    return out


def sync_language(code_root: Path | str, data_root: Path | str, lang: str, *, agents: bool = True) -> dict:
    """Create/regenerate the local files in `lang` when missing or still pristine. Returns {name: action}.

    agents=False skips AGENTS.md (it lives in the code root: isolated data roots, e.g. tests, never touch it)."""
    code_root, data_root = Path(code_root), Path(data_root)
    out: dict[str, str] = {}
    for name in TEMPLATES:
        if name == "AGENTS" and not agents:
            out[name] = "skipped"
            continue
        dst = (code_root if name == "AGENTS" else data_root) / _TARGET[name]
        want = render(code_root, name, lang)
        if want is None:
            out[name] = "no_template"
            continue
        current = dst.read_text(encoding="utf-8") if dst.exists() else None
        if current == want:
            out[name] = "ok"
            continue
        if current is not None and current not in _pristine_variants(code_root, name):
            out[name] = "kept"            # customized by the user: never overwrite
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_text(want, encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
        out[name] = "written"
    return out
