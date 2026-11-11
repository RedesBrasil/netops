#!/usr/bin/env python3
"""Ditado por voz: config da Cloudflare (Workers AI) e POST de transcrição.

Passa pelo middleware http normal (sessão + Origin + read-only). O token nunca é devolvido.
"""
from __future__ import annotations

from fastapi import APIRouter, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services import audio_svc

router = APIRouter(tags=["audio"])


def _err(e: audio_svc.AudioError) -> JSONResponse:
    return JSONResponse({"detail": e.detail}, status_code=e.status)


class AudioCfg(BaseModel):
    account_id: str | None = None
    token: str | None = None


@router.get("/audio/config")
def get_cfg():
    return audio_svc.status()


@router.put("/audio/config")
async def put_cfg(body: AudioCfg):
    try:
        return await audio_svc.save(body.account_id, body.token)
    except audio_svc.AudioError as e:
        return _err(e)


@router.delete("/audio/config")
def del_cfg():
    return audio_svc.remove()


@router.post("/audio/transcribe")
async def transcribe(audio: UploadFile):
    try:
        try:
            raw = await audio.read(audio_svc.MAX_AUDIO_BYTES + 1)
        finally:
            await audio.close()
        return {"transcription": await audio_svc.transcribe(raw)}
    except audio_svc.AudioError as e:
        return _err(e)


@router.post("/audio/test")
async def test_cfg():
    try:
        return await audio_svc.verify()
    except audio_svc.AudioError as e:
        return _err(e)
