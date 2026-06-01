#!/usr/bin/env python3
"""Diff de configuração — compara dois arquivos de config (ex.: baseline x proposta).

Usado pelo `tester`/`planner` para revisar exatamente o que uma mudança altera, e pelo
`executor` para comparar o estado antes/depois de uma mudança.

Uso:
    python scripts/analysis/config_diff.py --before baseline.txt --after proposta.txt
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path


def diff(before: Path, after: Path) -> tuple[str, int, int]:
    """Retorna (diff_unificado, linhas_adicionadas, linhas_removidas)."""
    a = before.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    b = after.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    lines = list(difflib.unified_diff(a, b, fromfile=str(before), tofile=str(after), lineterm=""))
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    return "\n".join(lines), added, removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara dois arquivos de configuração.")
    parser.add_argument("--before", required=True, help="Arquivo de config 'antes' (baseline)")
    parser.add_argument("--after", required=True, help="Arquivo de config 'depois' (proposta)")
    args = parser.parse_args()

    before, after = Path(args.before), Path(args.after)
    for f in (before, after):
        if not f.exists():
            print(f"ERRO: arquivo não encontrado: {f}", file=sys.stderr)
            return 1

    text, added, removed = diff(before, after)
    if not text:
        print("Sem diferenças entre os arquivos.")
        return 0
    print(text)
    print(f"\n--- Resumo: +{added} linha(s), -{removed} linha(s) ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
