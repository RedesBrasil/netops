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
    venv_py = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), *sys.argv])
