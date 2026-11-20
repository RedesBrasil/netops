#!/usr/bin/env python3
"""Diff de configuração — compara dois arquivos de config (ex.: baseline x proposta).

Usado pelo `tester`/`planner` para revisar exatamente o que uma mudança altera, e pelo
`executor` para comparar o estado antes/depois de uma mudança.

Uso:
    python3 scripts/tools/analysis/config_diff.py --before baseline.txt --after proposta.txt
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto
from lib import i18n  # noqa: E402


def diff(before: Path, after: Path) -> tuple[str, int, int]:
    """Retorna (diff_unificado, linhas_adicionadas, linhas_removidas)."""
    a = before.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    b = after.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    lines = list(difflib.unified_diff(a, b, fromfile=str(before), tofile=str(after), lineterm=""))
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    return "\n".join(lines), added, removed


def main() -> int:
    parser = argparse.ArgumentParser(description=i18n.t("cli_analysis.diff_description"))
    parser.add_argument("--before", required=True, help=i18n.t("cli_analysis.help_before"))
    parser.add_argument("--after", required=True, help=i18n.t("cli_analysis.help_after"))
    args = parser.parse_args()

    before, after = Path(args.before), Path(args.after)
    for f in (before, after):
        if not f.exists():
            print(i18n.t("cli_analysis.file_not_found", path=f), file=sys.stderr)
            return 1

    text, added, removed = diff(before, after)
    if not text:
        print(i18n.t("cli_analysis.no_differences"))
        return 0
    print(text)
    print("\n" + i18n.t("cli_analysis.diff_summary", added=added, removed=removed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
