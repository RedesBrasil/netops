#!/usr/bin/env python3
"""Token de uso único do PRIMEIRO ACESSO ao console (só stdlib).

Instalação nova = console escutando em todos os IPs, sem cofre e sem usuário. Até alguém concluir o
assistente (#setup), quem chegasse primeiro viraria admin. O token fecha essa janela: o instalador
gera um (`users/cli.py setup-link`), imprime a URL `#setup?token=...` e só quem tem o token conclui.

Arquivo: <dados>/runs/setup/token.json (0600, da conta operacional), com o SHA-256 do token (nunca o
valor) e a validade. Gerar de novo invalida o anterior. Concluir o assistente apaga o arquivo.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

DEFAULT_TTL = 24 * 3600
TOKEN_REL = Path("runs") / "setup" / "token.json"
REQUEST_REL = Path("runs") / "setup" / "finish-request"


def token_path(data_root) -> Path:
    return Path(data_root) / TOKEN_REL


def request_path(data_root) -> Path:
    """Gatilho da unidade root netops-setup-finish-<slug>.path (o conteúdo não importa)."""
    return Path(data_root) / REQUEST_REL


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(data_root, ttl: int = DEFAULT_TTL) -> str:
    """Gera um token novo (invalida o anterior) e devolve o valor. Só o hash vai para o disco."""
    token = secrets.token_urlsafe(24)
    path = token_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(".token.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"sha256": _digest(token), "exp": int(time.time()) + int(ttl)}, f)
    os.replace(tmp, path)
    return token


def _load(data_root) -> dict | None:
    path = token_path(data_root)
    try:
        if path.is_symlink():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def exists(data_root) -> bool:
    """Há um token gerado (válido ou expirado). Liga o modo de primeiro acesso mesmo em loopback."""
    return _load(data_root) is not None


def state(data_root) -> str:
    """'none' | 'valid' | 'expired'."""
    data = _load(data_root)
    if data is None:
        return "none"
    return "valid" if int(data.get("exp") or 0) > time.time() else "expired"


def check(data_root, token: str | None) -> bool:
    """Confere o token (tempo constante) e a validade."""
    data = _load(data_root)
    if not data or not token or not isinstance(token, str) or len(token) > 200:
        return False
    if int(data.get("exp") or 0) <= time.time():
        return False
    return hmac.compare_digest(str(data.get("sha256") or ""), _digest(token))


def consume(data_root) -> None:
    """Apaga o token (assistente concluído)."""
    try:
        token_path(data_root).unlink()
    except FileNotFoundError:
        pass


def request_finish(data_root) -> Path:
    """Escreve o gatilho da etapa root (fixar o cofre no sudo + senha do host Local)."""
    path = request_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(".finish-request.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{int(time.time())}\n")
    os.replace(tmp, path)
    return path
