#!/usr/bin/env python3
"""Translations for the console (lib/i18n.py): language list, catalogs, user and instance language.

- GET /i18n           -> languages offered, instance language, effective default (open: login/first access use it)
- GET /i18n/{lang}    -> merged catalog (English base + language) for the frontend's t()
- PUT /auth/locale    -> the user's own language (Minha conta -> Idioma); "" = follow the instance
- PUT /config/language -> instance language (admin, "config")
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import deps
from lib import accessdb, i18n
from services import authz

router = APIRouter(tags=["i18n"])

USER_LOCALE_KEY = "locale:"      # accessdb meta table: locale:<username> = code


def user_locale(username: str | None) -> str:
    if not username or not deps.has_users():
        return ""
    try:
        return i18n.normalize(accessdb.meta_get(deps.db_file(), USER_LOCALE_KEY + username)) or ""
    except Exception:  # noqa: BLE001
        return ""


class LocaleBody(BaseModel):
    model_config = {"extra": "forbid"}
    locale: str = Field(default="", max_length=20)


class LanguageBody(BaseModel):
    model_config = {"extra": "forbid"}
    language: str = Field(min_length=2, max_length=20)


@router.get("/i18n")
def i18n_index() -> dict:
    inst = i18n.instance_language(deps.DATA_ROOT)
    return {"languages": i18n.languages(), "instance": inst,
            "default": inst or i18n.LEGACY_DEFAULT, "source": i18n.SOURCE_LANG}


@router.get("/i18n/{lang}")
def i18n_catalog(lang: str):
    code = i18n.normalize(lang)
    if not code:
        return JSONResponse({"error": "unknown_language", "detail": i18n.t("errors.unknown_language", lang=lang)},
                            status_code=404)
    return JSONResponse({"lang": code, "messages": i18n.catalog(code)},
                        headers={"Cache-Control": "no-cache"})


@router.put("/auth/locale")
def set_my_locale(body: LocaleBody, request: Request):
    p = authz.request_principal(request)
    if not deps.has_users() or p.legacy:
        return JSONResponse({"error": "no_user", "detail": i18n.t("errors.locale_no_user")}, status_code=409)
    code = i18n.normalize(body.locale) if body.locale else ""
    if body.locale and not code:
        return JSONResponse({"error": "unknown_language", "detail": i18n.t("errors.unknown_language", lang=body.locale)},
                            status_code=422)
    accessdb.meta_set(deps.db_file(), USER_LOCALE_KEY + p.username, code)
    return {"ok": True, "locale": code, "effective": code or i18n.instance_language(deps.DATA_ROOT)
            or i18n.LEGACY_DEFAULT}


@router.put("/config/language")
def set_instance_language(body: LanguageBody):
    code = i18n.normalize(body.language)
    if not code:
        return JSONResponse({"error": "unknown_language", "detail": i18n.t("errors.unknown_language",
                                                                            lang=body.language)}, status_code=422)
    i18n.write_instance_language(code, deps.DATA_ROOT)
    from lib import local_files  # noqa: PLC0415
    files = local_files.sync_language(deps.NETOPS_ROOT, deps.DATA_ROOT, code, agents=deps.DATA_ROOT == deps.NETOPS_ROOT)
    return {"ok": True, "language": code, "files": files}
