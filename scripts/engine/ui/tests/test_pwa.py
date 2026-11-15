"""PWA: manifest, service worker, página offline e ícones são servidos corretamente."""
from __future__ import annotations

import json
import re
import struct


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manifest_valido_e_icones_existem(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest+json" in r.headers["content-type"] or "application/json" in r.headers["content-type"]
    m = r.json()
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["scope"] == "/"
    assert m["name"] and m["short_name"]
    purposes = {(i["sizes"], i.get("purpose")) for i in m["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("192x192", "maskable"), ("512x512", "maskable")} <= purposes
    for icon in m["icons"]:
        resp = client.get(icon["src"])
        assert resp.status_code == 200, icon["src"]
        if icon["type"] == "image/png":
            w, h = (int(x) for x in icon["sizes"].split("x"))
            assert _png_size(resp.content) == (w, h), icon["src"]
    for sc in m["shortcuts"]:
        assert sc["url"].startswith("/#")


def test_service_worker_na_raiz_sem_cache_e_sem_api(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-cache"          # navegador sempre revalida o worker
    body = r.text
    assert '"/api/"' in body                                  # nunca intercepta a API
    assert "/offline.html" in body
    assert client.get("/offline.html").status_code == 200


def test_index_referencia_manifest_e_icones(client):
    html = client.get("/").text
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'name="theme-color"' in html
    assert re.search(r'rel="apple-touch-icon" href="(/icons/pwa/apple-touch-icon\.png)"', html)
    assert client.get("/icons/pwa/apple-touch-icon.png").status_code == 200


def test_pwa_assets_publicos_com_login_ativo(env, monkeypatch):
    """Manifest/sw/ícones são buscados pelo navegador sem sessão: não podem exigir login."""
    import deps
    from fastapi.testclient import TestClient
    from app import create_app
    monkeypatch.setattr(deps, "auth_required", lambda: True)
    c = TestClient(create_app())
    for path in ("/manifest.webmanifest", "/sw.js", "/offline.html", "/icons/pwa/icon-192.png"):
        assert c.get(path).status_code == 200, path
