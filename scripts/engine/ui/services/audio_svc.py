#!/usr/bin/env python3
"""Transcrição de áudio (ditado) via Cloudflare Workers AI — config + chamada ao modelo.

Config em `runs/claude/audio-transcription.json` (0600, git-ignorado): {"account_id", "token"}.
O token fica em texto puro 0600 — independe do cofre (o cofre é só das credenciais dos hosts).
NUNCA volta ao navegador nem vai para log.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading

import httpx

import deps
from lib import i18n

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


def _unseal(value: str) -> str:
    """Token salvo em texto puro (0600). O cofre é só p/ credenciais de hosts; versões antigas
    gravavam `enc.v1:` — migra p/ texto puro na primeira leitura possível."""
    if not value.startswith("enc.v1:"):
        return value
    try:
        from lib import vault, vault_session  # noqa: PLC0415
        plain = vault.decrypt_value(vault_session.get_session_key(), value)
    except Exception:
        raise AudioError(409, i18n.t("api_audio.token_old_format")) from None
    with _LOCK:
        d = _load()
        d["token"] = plain
        _save(d)
    return plain


def _ogg_info(content: bytes) -> tuple[float, int]:
    """(duração em s, nº de páginas) lidos dos cabeçalhos Ogg — só metadados, sem decodificar."""
    try:
        i = content.find(b"OpusHead")
        preskip = int.from_bytes(content[i + 10:i + 12], "little") if i >= 0 else 0
        last = content.rfind(b"OggS")
        gran = int.from_bytes(content[last + 6:last + 14], "little", signed=True)
        return max(0.0, (gran - preskip) / 48000), content.count(b"OggS")
    except Exception:
        return 0.0, 0


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
                    raise AudioError(422, i18n.t("api_audio.cannot_list_accounts"))
                if not r.is_success:
                    raise AudioError(502, i18n.t("api_audio.list_accounts_failed"))
                d = r.json()
                out += [{"id": a.get("id"), "name": a.get("name") or ""} for a in d.get("result") or []
                        if isinstance(a, dict) and _ID_RE.fullmatch(a.get("id") or "")]
                info = d.get("result_info") or {}
                if page >= int(info.get("total_pages") or 1):
                    break
                page += 1
    except httpx.TimeoutException:
        raise AudioError(504, i18n.t("api_audio.cf_timeout")) from None
    except (httpx.RequestError, ValueError):
        raise AudioError(502, i18n.t("api_audio.cf_connect_failed")) from None
    return out


async def save(account_id: str | None, token: str | None) -> dict:
    """token vazio preserva o salvo. Sem account_id (e sem um salvo), descobre pela Cloudflare:
    1 conta = salva sozinho; várias = devolve {needs_account, accounts} SEM salvar."""
    tok = (token or "").strip()
    aid = (account_id or "").strip()
    if aid and not _ID_RE.fullmatch(aid):
        raise AudioError(422, i18n.t("api_audio.bad_account_id"))
    if tok and not aid:
        accounts = await list_accounts(tok)
        if not accounts:
            raise AudioError(422, i18n.t("api_audio.no_accounts"))
        if len(accounts) > 1:
            return {**status(), "needs_account": True, "accounts": accounts}
        aid = accounts[0]["id"]
    with _LOCK:
        d = _load()
        if aid:
            if d.get("account_id") and d["account_id"] != aid and not tok:
                raise AudioError(422, i18n.t("api_audio.new_account_token"))
            d["account_id"] = aid
        if tok:
            d["token"] = tok
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
        raise AudioError(400, i18n.t("api_audio.not_configured"))
    return aid, _unseal(tok)


def audio_kind(content: bytes) -> str:
    """Formato pelo cabeçalho: Ogg/Opus (opus-recorder, Firefox), WebM (Chrome/Android), MP4 (Safari/iOS)."""
    if content.startswith(b"OggS") and b"OpusHead" in content[:128]:
        return "ogg"
    if content.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if content[4:8] == b"ftyp":
        return "mp4"
    return ""


def _info(content: bytes) -> str:
    if audio_kind(content) == "ogg":
        dur, pages = _ogg_info(content)
        return i18n.t("api_audio.ogg_info", seconds=f"{dur:.1f}", kb=len(content) // 1024, pages=pages)
    return f"{audio_kind(content)}, {len(content) // 1024} KB"


async def transcribe(content: bytes) -> str:
    aid, token = credentials()
    if not content:
        raise AudioError(400, i18n.t("api_audio.empty"))
    if len(content) > MAX_AUDIO_BYTES:
        raise AudioError(413, i18n.t("api_audio.too_large"))
    kind = audio_kind(content)
    if not kind:
        raise AudioError(415, i18n.t("api_audio.bad_type"))
    if len(content) < 1024:   # só cabeçalho, sem nenhum quadro de áudio: não gasta chamada na Cloudflare
        _debug_keep(content)
        raise AudioError(422, i18n.t("api_audio.no_audio", kind=kind, size=len(content)))
    url = f"https://api.cloudflare.com/client/v4/accounts/{aid}/ai/run/{MODEL}"
    payload = {"audio": base64.b64encode(content).decode("ascii"), "task": "transcribe", "language": "pt"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise AudioError(504, i18n.t("api_audio.transcription_timeout")) from None
    except httpx.RequestError:
        raise AudioError(502, i18n.t("api_audio.cf_connect_failed")) from None
    if r.status_code in (401, 403):
        raise AudioError(502, i18n.t("api_audio.check_permissions"))
    if r.status_code == 429:
        raise AudioError(429, i18n.t("api_audio.rate_limited"))
    if not r.is_success:
        _debug_keep(content)
        raise AudioError(502, i18n.t("api_audio.process_failed", status=r.status_code, errors=_cf_errors(r),
                                     info=_info(content)))
    try:
        data = r.json()
    except ValueError:
        raise AudioError(502, i18n.t("api_audio.bad_response")) from None
    if not isinstance(data, dict) or data.get("success") is not True:
        raise AudioError(502, i18n.t("api_audio.transcription_failed"))
    res = data.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("text"), str):
        raise AudioError(502, i18n.t("api_audio.no_transcription"))
    text = res["text"].strip()
    if not text:
        _debug_keep(content)
        raise AudioError(422, i18n.t("api_audio.no_speech", info=_info(content)))
    return text


def _cf_errors(r) -> str:
    """Códigos/mensagens de erro da Cloudflare (sanitizados, sem token nem áudio)."""
    try:
        errs = r.json().get("errors") or []
        txt = "; ".join(f"{e.get('code')}: {str(e.get('message'))[:160]}" for e in errs if isinstance(e, dict))
        return f" — {txt}" if txt else ""
    except Exception:
        return ""


DEBUG_FILE = deps.RUNS_DIR / "claude" / "audio-debug-last-empty.ogg"


def _debug_keep(content: bytes) -> None:
    """DIAGNÓSTICO TEMPORÁRIO: guarda só o ÚLTIMO áudio que voltou sem texto (0600, sobrescrito).
    Remover depois de achar a causa do "sem fala" na gravação do navegador."""
    try:
        fd = os.open(DEBUG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
    except OSError:
        pass


async def verify() -> dict:
    """Confere que o token da conta está ativo (não consome franquia nem testa acesso ao modelo)."""
    aid, token = credentials()
    url = f"https://api.cloudflare.com/client/v4/accounts/{aid}/tokens/verify"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise AudioError(504, i18n.t("api_audio.cf_timeout")) from None
    except httpx.RequestError:
        raise AudioError(502, i18n.t("api_audio.cf_connect_failed")) from None
    if r.status_code in (400, 401, 403):
        raise AudioError(502, i18n.t("api_audio.token_invalid"))
    if not r.is_success:
        raise AudioError(502, i18n.t("api_audio.verify_failed"))
    try:
        active = r.json().get("result", {}).get("status") == "active"
    except (ValueError, AttributeError):
        active = False
    if not active:
        raise AudioError(502, i18n.t("api_audio.token_inactive"))
    return {"ok": True}
