#!/usr/bin/env python3
"""Primeiro acesso (#setup): status, conclusão do assistente e etapa root. Ver services/setup_svc.py."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib.accessdb import AccessError
from services import setup_svc

router = APIRouter(tags=["setup"])


class CompleteBody(BaseModel):
    model_config = {"extra": "forbid"}
    token: str = Field(min_length=1, max_length=200)
    language: str = Field(min_length=2, max_length=10)
    name: Optional[str] = Field(default="", max_length=80)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


def _err(exc) -> JSONResponse:
    return JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=exc.status)


@router.get("/setup/status")
def setup_status() -> dict:
    """Alcançável sem sessão: diz se o assistente está pendente (nunca devolve o token)."""
    return setup_svc.status()


@router.post("/setup/complete")
def setup_complete(body: CompleteBody, request: Request):
    try:
        return setup_svc.complete(token=body.token, language=body.language, name=body.name or "",
                                  email=body.email, password=body.password,
                                  ip=request.client.host if request.client else "",
                                  user_agent=request.headers.get("user-agent", ""))
    except setup_svc.SetupError as exc:
        return _err(exc)
    except AccessError as exc:
        return _err(exc)


@router.get("/setup/finish")
def setup_finish_status() -> dict:
    """Etapa root (sudo pelo cofre + senha do host Local): pendente, concluída ou falhou."""
    return setup_svc.finish_status()


@router.post("/setup/finish")
def setup_finish_retry() -> dict:
    """Dispara de novo a etapa root (precisa do cofre destrancado)."""
    return setup_svc.request_finish()
