"""Re-executa o script no Python do `.venv` do projeto, se houver.

Faz `python3 scripts/foo.py …` funcionar mesmo quando as dependências (netmiko,
librouteros, etc.) estão instaladas só no venv. Chame `ensure_venv()` o mais cedo
possível em scripts CLI — antes de importar libs externas.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_venv() -> None:
    venv_dir = Path(__file__).resolve().parents[2] / ".venv"
    venv_py = venv_dir / "bin" / "python"
    # Já estamos DENTRO do venv? sys.prefix aponta pro diretório do venv quando ele está
    # ativo. NÃO comparar executáveis com .resolve(): o python do venv costuma ser só um
    # symlink pro interpretador do sistema, então ambos resolveriam pro MESMO binário e o
    # re-exec nunca dispararia (era o bug: rodar com `python3` ficava sem as deps do venv).
    if Path(sys.prefix).resolve() == venv_dir.resolve():
        return
    if venv_py.exists():
        os.execv(str(venv_py), [str(venv_py), *sys.argv])
