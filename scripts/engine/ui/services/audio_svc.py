#!/usr/bin/env python3
"""Transcrição de áudio (ditado) via Cloudflare Workers AI — config + chamada ao modelo.

Config em `runs/claude/audio-transcription.json` (0600, git-ignorado): {"account_id", "token"}.
O token é cifrado com o cofre (`enc.v1:`) quando a chave da sessão está disponível; senão fica em
texto puro 0600 (mesmo regime do credentials.yaml). NUNCA volta ao navegador nem vai para log.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading

import httpx

import deps

_FILE = deps.RUNS_DIR / "claude" / "audio-transcription.json"
_LOCK = threading.Lock()
MODEL = "@cf/openai/whisper-large-v3-turbo"
MAX_AUDIO_BYTES = 4 * 1024 * 1024
_ID_RE = re.compile(r"[0-9a-fA-F]{32}")


class AudioError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _load() -> dict:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.chmod(tmp, 0o600)
    tmp.replace(_FILE)


def _seal(token: str) -> str:
    try:
        from lib import vault, vault_session  # noqa: PLC0415
        return vault.encrypt_value(vault_session.get_session_key(), token)
    except Exception:  # cofre trancado/não iniciado: texto puro 0600
        return token


def _unseal(value: str) -> str:
    from lib import vault, vault_session  # noqa: PLC0415
    if not vault.is_encrypted(value):
        return value
    try:
        return vault.decrypt_value(vault_session.get_session_key(), value)
    except Exception:
        raise AudioError(423, "Cofre trancado: destrave o cofre para usar a transcrição.") from None


def status() -> dict:
    d = _load()
    ok = bool(d.get("token")) and bool(_ID_RE.fullmatch(d.get("account_id") or ""))
    out = {"configured": ok, "has_token": bool(d.get("token"))}
    if d.get("account_id"):
        out["account_id"] = d["account_id"]
    return out


async def list_accounts(token: str) -> list[dict]:
    """Contas visíveis ao token (GET /accounts, todas as páginas)."""
    out, page = [], 1
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            while page <= 20:
                r = await client.get("https://api.cloudflare.com/client/v4/accounts",
                                     params={"per_page": 50, "page": page},
                                     headers={"Authorization": f"Bearer {token}"})
                if r.status_code in (400, 401, 403):
                    raise AudioError(422, "Não consegui listar as contas com este token. Confira o token; se ele for "
                                          "válido, adicione a permissão Account → Account Settings → Read ou informe o Account ID.")
                if not r.is_success:
                    raise AudioError(502, "A Cloudflare não conseguiu listar as contas.")
                d = r.json()
                out += [{"id": a.get("id"), "name": a.get("name") or ""} for a in d.get("result") or []
                        if isinstance(a, dict) and _ID_RE.fullmatch(a.get("id") or "")]
                info = d.get("result_info") or {}
                if page >= int(info.get("total_pages") or 1):
                    break
                page += 1
    except httpx.TimeoutException:
        raise AudioError(504, "A Cloudflare demorou demais para responder.") from None
    except (httpx.RequestError, ValueError):
        raise AudioError(502, "Não foi possível conectar à Cloudflare.") from None
    return out


async def save(account_id: str | None, token: str | None) -> dict:
    """token vazio preserva o salvo. Sem account_id (e sem um salvo), descobre pela Cloudflare:
    1 conta = salva sozinho; várias = devolve {needs_account, accounts} SEM salvar."""
    tok = (token or "").strip()
    aid = (account_id or "").strip()
    if aid and not _ID_RE.fullmatch(aid):
        raise AudioError(422, "Account ID inválido: use 32 caracteres hexadecimais.")
    if tok and not aid:
        accounts = await list_accounts(tok)
        if not accounts:
            raise AudioError(422, "O token não enxerga nenhuma conta. Informe o Account ID manualmente.")
        if len(accounts) > 1:
            return {**status(), "needs_account": True, "accounts": accounts}
        aid = accounts[0]["id"]
    with _LOCK:
        d = _load()
        if aid:
            if d.get("account_id") and d["account_id"] != aid and not tok:
                raise AudioError(422, "Ao trocar de conta, informe também o token da nova conta.")
            d["account_id"] = aid
        if tok:
            d["token"] = _seal(tok)
        _save(d)
    return status()


def remove() -> dict:
    with _LOCK:
        try:
            _FILE.unlink()
        except FileNotFoundError:
            pass
    return status()


def credentials() -> tuple[str, str]:
    d = _load()
    aid, tok = d.get("account_id") or "", d.get("token") or ""
    if not tok or not _ID_RE.fullmatch(aid):
        raise AudioError(400, "Configure o Account ID e o token da Cloudflare.")
    return aid, _unseal(tok)


async def transcribe(content: bytes) -> str:
    aid, token = credentials()
    if not content:
        raise AudioError(400, "A gravação está vazia.")
    if len(content) > MAX_AUDIO_BYTES:
        raise AudioError(413, "O áudio excede o tamanho permitido.")
    if not content.startswith(b"OggS") or b"OpusHead" not in content[:128]:
        raise AudioError(415, "Envie um áudio no formato OGG/Opus.")
    url = f"https://api.cloudflare.com/client/v4/accounts/{aid}/ai/run/{MODEL}"
    payload = {"audio": base64.b64encode(content).decode("ascii"), "task": "transcribe", "language": "pt"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise AudioError(504, "A transcrição demorou demais. Tente novamente.") from None
    except httpx.RequestError:
        raise AudioError(502, "Não foi possível conectar à Cloudflare.") from None
    if r.status_code in (401, 403):
        raise AudioError(502, "Confira o token, a conta e as permissões do Workers AI.")
    if r.status_code == 429:
        raise AudioError(429, "Limite de uso da Cloudflare atingido. Tente mais tarde.")
    if not r.is_success:
        raise AudioError(502, "A Cloudflare não conseguiu processar o áudio.")
    try:
        data = r.json()
    except ValueError:
        raise AudioError(502, "Resposta inválida da Cloudflare.") from None
    if not isinstance(data, dict) or data.get("success") is not True:
        raise AudioError(502, "A Cloudflare informou uma falha na transcrição.")
    res = data.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("text"), str):
        raise AudioError(502, "A resposta da Cloudflare não incluiu a transcrição.")
    text = res["text"].strip()
    if not text:
        raise AudioError(422, "Não foi possível identificar fala no áudio.")
    return text


async def verify() -> dict:
    """Confere que o token da conta está ativo (não consome franquia nem testa acesso ao modelo)."""
    aid, token = credentials()
    url = f"https://api.cloudflare.com/client/v4/accounts/{aid}/tokens/verify"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise AudioError(504, "A Cloudflare demorou demais para responder.") from None
    except httpx.RequestError:
        raise AudioError(502, "Não foi possível conectar à Cloudflare.") from None
    if r.status_code in (400, 401, 403):
        raise AudioError(502, "Token inválido para esta conta. Confira o token e o Account ID.")
    if not r.is_success:
        raise AudioError(502, "A Cloudflare não conseguiu verificar o token.")
    try:
        active = r.json().get("result", {}).get("status") == "active"
    except (ValueError, AttributeError):
        active = False
    if not active:
        raise AudioError(502, "O token não está ativo.")
    return {"ok": True}
