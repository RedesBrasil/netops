#!/usr/bin/env python3
"""Atualiza ícones locais a partir de um commit explícito, sem executar código remoto.

Uso: python3 scripts/engine/ui/vendor_icons.py
Requer Pillow somente para gerar as miniaturas de manutenção, não em execução.
"""
from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

REPOSITORY = "https://github.com/RedesBrasil/network-icons"
COMMIT = "3bfe4c177ea78b91846517bd1a6964da3e3f55d3"
BASE = f"https://raw.githubusercontent.com/RedesBrasil/network-icons/{COMMIT}/"
DESTINATION = Path(__file__).resolve().parent / "static" / "icons" / "network"


def download(name: str, limit: int) -> bytes:
    with urlopen(BASE + name, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"arquivo excede limite: {name}")
    return data


def main():
    from PIL import Image
    catalog_bytes = download("catalog.json", 65536)
    catalog = json.loads(catalog_bytes)
    if not isinstance(catalog, list) or not 0 < len(catalog) <= 100:
        raise ValueError("catálogo inválido")
    seen = set()
    assets = []
    for icon in catalog:
        ident = icon["id"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", ident) or ident in seen or icon["file"] != ident + ".png":
            raise ValueError("ID ou caminho de ícone inválido")
        seen.add(ident)
        content = download(icon["file"], 8 * 1024 * 1024)
        if hashlib.sha256(content).hexdigest() != icon["sha256"]:
            raise ValueError(f"checksum divergente: {ident}")
        with Image.open(BytesIO(content)) as image:
            if image.format != "PNG" or image.size != (icon["width"], icon["height"]):
                raise ValueError(f"imagem divergente: {ident}")
            thumbnail = image.convert("RGBA")
            thumbnail.thumbnail((128, 128), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            thumbnail.save(buffer, format="PNG", optimize=True)
        assets.append((icon["file"], content, buffer.getvalue()))
    # Só substitui a biblioteca depois de validar todos os arquivos baixados.
    (DESTINATION / "thumbnails").mkdir(parents=True, exist_ok=True)
    (DESTINATION / "catalog.json").write_bytes(catalog_bytes)
    for name, original, thumbnail in assets:
        (DESTINATION / name).write_bytes(original)
        (DESTINATION / "thumbnails" / name).write_bytes(thumbnail)
    files = [("catalog.json", catalog_bytes)]
    files += [(name, content) for name, content, _ in assets]
    files += [("thumbnails/" + name, thumbnail) for name, _, thumbnail in assets]
    (DESTINATION / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files))
    print(f"{len(assets)} ícones verificados e miniaturas em {DESTINATION}")


if __name__ == "__main__":
    main()
