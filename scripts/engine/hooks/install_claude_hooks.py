#!/usr/bin/env python3
"""Garante os hooks do NetOps em `.claude/settings.json` (idempotente, só stdlib).

Mescla o modelo `claude-settings.json` (desta pasta) no settings do projeto sem apagar
nada do usuário (tema, permissões, outros hooks). Entrada antiga que aponta para
`.claude/hooks/guard-netops.sh` é trocada pelo caminho atual. Chamado pelo `install.sh`;
pode rodar à mão:  python3 scripts/engine/hooks/install_claude_hooks.py [--root DIR] [--check]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "claude-settings.json"
MARKER = "guard-netops.sh"


def _commands(entry: dict) -> list[str]:
    return [h.get("command", "") for h in entry.get("hooks", []) if isinstance(h, dict)]


def merge(settings: dict, template: dict) -> tuple[dict, bool]:
    """Devolve (settings, mudou). Só toca nas entradas de hook do NetOps."""
    changed = False
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' em .claude/settings.json não é um objeto")
    for event, wanted_entries in template.get("hooks", {}).items():
        current = hooks.setdefault(event, [])
        if not isinstance(current, list):
            raise ValueError(f"'hooks.{event}' em .claude/settings.json não é uma lista")
        for wanted in wanted_entries:
            want_cmds = _commands(wanted)
            found = False
            for i, entry in enumerate(current):
                if not isinstance(entry, dict) or not any(MARKER in c for c in _commands(entry)):
                    continue
                found = True
                if entry != wanted:          # caminho antigo ou parâmetros desatualizados
                    current[i] = wanted
                    changed = True
            if not found and want_cmds:
                current.append(wanted)
                changed = True
    if "$schema" not in settings and "$schema" in template:
        settings = {"$schema": template["$schema"], **settings}
        changed = True
    return settings, changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=HERE.parents[2], help="raiz do NetOps")
    ap.add_argument("--check", action="store_true", help="só confere (exit 1 se faltar o hook)")
    args = ap.parse_args()
    target = args.root / ".claude" / "settings.json"
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    try:
        current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    except ValueError as exc:
        print(f"ERRO: {target} não é JSON válido ({exc}); corrija e rode de novo.", file=sys.stderr)
        return 2
    try:
        merged, changed = merge(current, template)
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    if args.check:
        print("hooks NetOps: " + ("DESATUALIZADOS/AUSENTES" if changed else "OK") + f" ({target})")
        return 1 if changed else 0
    if not changed:
        print(f"hooks NetOps já presentes em {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".settings.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(merged, out, indent=2, ensure_ascii=False)
        out.write("\n")
    if target.exists():
        os.chmod(tmp, target.stat().st_mode & 0o777)
    else:
        os.chmod(tmp, 0o644)
    os.replace(tmp, target)
    print(f"hooks NetOps gravados em {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
