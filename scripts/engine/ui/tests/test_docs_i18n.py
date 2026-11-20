"""Human docs in two languages: `X.md` (English) and `X.pt-BR.md` (Portuguese) stay in parity."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import deps  # noqa: F401  (bootstraps scripts/engine on sys.path)

from update.common import distributed

ROOT = Path(__file__).resolve().parents[4]
PT_SUFFIX = ".pt-BR.md"
# Docs whose structure must match heading for heading. Others only need both files and the cross-links.
STRICT_HEADINGS = {"README.md"}
HEADING = re.compile(r"^#{1,3}\s+\S")
FENCE = re.compile(r"^\s*(```|~~~)")


def _repo_files() -> set[str]:
    """Tracked files plus new, not ignored ones (a doc pair may not be committed yet)."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True, capture_output=True, text=True).stdout
    return {line for line in out.splitlines() if line and (ROOT / line).is_file()}


def _pairs() -> list[tuple[str, str]]:
    files = _repo_files()
    return sorted((f[: -len(PT_SUFFIX)] + ".md", f) for f in files if f.endswith(PT_SUFFIX))


def _first_line(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _heading_count(path: Path) -> int:
    count, in_code = 0, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code and HEADING.match(line):
            count += 1
    return count


def test_readme_has_a_portuguese_version():
    assert ("README.md", "README.pt-BR.md") in _pairs()


def test_every_doc_pair_exists_and_cross_links():
    for en, pt in _pairs():
        en_path, pt_path = ROOT / en, ROOT / pt
        assert en_path.is_file(), f"{pt} has no English sibling {en}"
        en_name, pt_name = Path(en).name, Path(pt).name
        assert f"[Português]({pt_name})" in _first_line(en_path), f"{en}: first line must link to {pt_name}"
        assert f"[English]({en_name})" in _first_line(pt_path), f"{pt}: first line must link to {en_name}"


def test_strict_docs_have_the_same_headings():
    for en, pt in _pairs():
        if en in STRICT_HEADINGS:
            assert _heading_count(ROOT / en) == _heading_count(ROOT / pt), f"{en} and {pt} differ in headings"


def test_new_doc_versions_stay_out_of_the_package_for_old_updaters():
    """The updater already installed validates the package with ITS OWN list and rejects unknown root files
    (protected_path). So README.pt-BR.md lives only in git/GitHub; translations ship under core/locales/."""
    assert distributed("README.md") and not distributed("README.pt-BR.md")
    assert distributed("core/locales/en/common.json") and distributed("core/locales/_languages.yaml")
