#!/usr/bin/env python3
"""Gerenciador de arquivos — menu Arquivos (este servidor) e painel SFTP do terminal de host.

`src` escolhe a fonte: `local` (padrão) = o servidor NetOps; qualquer outro valor = token da sessão
SFTP que o terminal de host recebeu ao conectar (services/host_term_svc.py). Toda a lógica fica em
services/files_svc.py; aqui só HTTP, gate e auditoria.

Gate: mesmo nível de confiança do terminal web (`deps.files_enabled()`): login + terminal ligado +
`NETOPS_UI_FILES` != 0. Escrita ainda passa pelo middleware (Origin, --read-only, manutenção).
Download: `GET /files/download-link` devolve um link de USO ÚNICO (`/api/files/dl/<ticket>`, 120 s) que o
navegador baixa direto — streaming, sem carregar o arquivo inteiro na memória da aba. Esse caminho é o
único liberado sem o header de sessão (app.py); o ticket só é emitido para quem está logado.
"""
from __future__ import annotations

import posixpath
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import deps
from services import files_svc as fsvc

router = APIRouter(tags=["files"])

MAX_UPLOAD_CHUNK = 32 * 1024 * 1024


class FilesDisabled(Exception):
    pass


def _gate() -> None:
    if not deps.files_enabled():
        raise FilesDisabled()


def _client(request: Request) -> str:
    return getattr(request.client, "host", "?") if request.client else "?"


def _err(exc: fsvc.FsError) -> JSONResponse:
    return JSONResponse({"error": exc.code, "detail": str(exc)}, status_code=exc.status)


def _disabled() -> JSONResponse:
    return JSONResponse({"error": "files_disabled", "detail":
                         "Gerenciador de arquivos desligado (exige o terminal web ligado — start.sh — "
                         "e NETOPS_UI_FILES diferente de 0)."}, status_code=403)


async def _do(fn):
    try:
        _gate()
        return await fn()
    except FilesDisabled:
        return _disabled()
    except fsvc.FsError as exc:
        return _err(exc)


# --------------------------------------------------------------------------- #
class PathBody(BaseModel):
    src: str = "local"
    path: str


class PathsBody(BaseModel):
    src: str = "local"
    paths: list[str] = Field(min_length=1, max_length=5000)


class RenameBody(BaseModel):
    src: str = "local"
    path: str
    name: str


class PasteBody(BaseModel):
    src: str = "local"
    op: str = Field(pattern="^(copy|move)$")
    paths: list[str] = Field(min_length=1, max_length=5000)
    dest: str
    overwrite: bool = False


class ChmodBody(BaseModel):
    src: str = "local"
    path: str
    mode: str = Field(pattern="^[0-7]{3,4}$")


class WriteBody(BaseModel):
    src: str = "local"
    path: str
    content: str
    mtime: int | None = None
    size: int | None = None
    create: bool = False


# --------------------------------------------------------------------------- #
@router.get("/files/info")
async def files_info(src: str = "local"):
    """Pasta inicial da fonte (local = /; SFTP = home do usuário) e descrição."""
    async def go():
        fs = fsvc.backend(src)
        out = {"src": src, "kind": fs.kind, "home": await fs.home(), "label": fs.label}
        if fs.kind == "local":
            import getpass
            import socket
            out.update(hostname=socket.gethostname(), user=getpass.getuser())
        if fs.kind == "remote":
            h = fs.s.host
            out.update(host_id=h.get("id"), hostname=h.get("hostname", ""), user=fs.s.user)
        return out
    return await _do(go)


@router.get("/files/list")
async def files_list(path: str = Query(...), src: str = "local"):
    async def go():
        fs = fsvc.backend(src)
        data = await fs.list(path)
        p = data["path"]
        data["parent"] = None if p == "/" else (posixpath.dirname(p) or "/")
        return data
    return await _do(go)


@router.get("/files/stat")
async def files_stat(path: str = Query(...), src: str = "local"):
    return await _do(lambda: fsvc.backend(src).stat(path))


@router.post("/files/mkdir")
async def files_mkdir(body: PathBody, request: Request):
    async def go():
        fs = fsvc.backend(body.src)
        await fs.mkdir(body.path)
        fsvc.audit(fs.label, "MKDIR", fsvc.norm(body.path), _client(request))
        return {"ok": True, "path": fsvc.norm(body.path)}
    return await _do(go)


@router.post("/files/touch")
async def files_touch(body: PathBody, request: Request):
    async def go():
        fs = fsvc.backend(body.src)
        await fs.touch(body.path)
        fsvc.audit(fs.label, "NOVO-ARQUIVO", fsvc.norm(body.path), _client(request))
        return {"ok": True, "path": fsvc.norm(body.path)}
    return await _do(go)


@router.post("/files/rename")
async def files_rename(body: RenameBody, request: Request):
    async def go():
        fs = fsvc.backend(body.src)
        src = fsvc.norm(body.path)
        dst = fsvc.join(posixpath.dirname(src) or "/", body.name)
        await fs.rename(src, dst)
        fsvc.audit(fs.label, "RENOMEAR", f"{src} -> {dst}", _client(request))
        return {"ok": True, "path": dst}
    return await _do(go)


@router.post("/files/paste")
async def files_paste(body: PasteBody, request: Request):
    """Copiar/mover vários itens para `dest`. Copiar para a mesma pasta cria "nome (cópia)".
    Mover com nome repetido: erro no item (ou sobrescreve arquivo, com overwrite)."""
    async def go():
        fs = fsvc.backend(body.src)
        dest = fsvc.norm(body.dest)
        listing = await fs.list(dest)
        taken = {e["name"] for e in listing["entries"]}
        results = []
        for raw in body.paths:
            try:
                src = fsvc.norm(raw)
                name = posixpath.basename(src)
                if body.op == "copy":
                    name = fsvc.unique_name(name, taken)
                    dst = fsvc.join(dest, name)
                    await fs.copy(src, dst)
                else:
                    dst = fsvc.join(dest, name)
                    if dst == src:
                        results.append({"path": src, "dest": dst, "ok": True, "skipped": True})
                        continue
                    await fs.rename(src, dst, overwrite=body.overwrite)
                taken.add(name)
                fsvc.audit(fs.label, "COPIAR" if body.op == "copy" else "MOVER", f"{src} -> {dst}", _client(request))
                results.append({"path": src, "dest": dst, "ok": True})
            except fsvc.FsError as exc:
                results.append({"path": raw, "ok": False, "error": str(exc), "code": exc.code})
        return {"results": results, "ok": all(r["ok"] for r in results)}
    return await _do(go)


@router.post("/files/delete")
async def files_delete(body: PathsBody, request: Request):
    async def go():
        fs = fsvc.backend(body.src)
        results = []
        for raw in body.paths:
            try:
                await fs.delete(raw)
                fsvc.audit(fs.label, "APAGAR", fsvc.norm(raw), _client(request))
                results.append({"path": raw, "ok": True})
            except fsvc.FsError as exc:
                results.append({"path": raw, "ok": False, "error": str(exc), "code": exc.code})
        return {"results": results, "ok": all(r["ok"] for r in results)}
    return await _do(go)


@router.post("/files/chmod")
async def files_chmod(body: ChmodBody, request: Request):
    async def go():
        fs = fsvc.backend(body.src)
        await fs.chmod(body.path, int(body.mode, 8))
        fsvc.audit(fs.label, "CHMOD", f"{body.mode} {fsvc.norm(body.path)}", _client(request))
        return await fs.stat(body.path)
    return await _do(go)


@router.get("/files/read")
async def files_read(path: str = Query(...), src: str = "local"):
    """Conteúdo p/ o editor (até 5 MiB). Binário: devolve binary=true sem o conteúdo."""
    async def go():
        fs = fsvc.backend(src)
        data, meta = await fs.read_bytes(path, fsvc.READ_TEXT_MAX)
        if b"\x00" in data[:8192]:
            return {"path": fsvc.norm(path), "binary": True, **meta}
        try:
            text, enc = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, enc = data.decode("latin-1"), "latin-1"
        return {"path": fsvc.norm(path), "binary": False, "content": text, "encoding": enc, **meta}
    return await _do(go)


@router.put("/files/write")
async def files_write(body: WriteBody, request: Request):
    async def go():
        fs = fsvc.backend(body.src)
        p = fsvc.norm(body.path)
        if body.create and await fs.exists(p):
            raise fsvc.Exists(f"já existe: {p}")
        expect = None if body.create or body.mtime is None else {"mtime": body.mtime, "size": body.size}
        meta = await fs.write_bytes(p, body.content.encode("utf-8"), expect)
        fsvc.audit(fs.label, "EDITAR", f"{p} ({meta['size']} bytes)", _client(request))
        return {"ok": True, "path": p, **meta}
    return await _do(go)


@router.put("/files/upload")
async def files_upload(request: Request, path: str = Query(...), uid: str = Query(..., pattern=r"^[A-Za-z0-9_-]{8,64}$"),
                       offset: int = Query(0, ge=0), final: bool = False, overwrite: bool = False,
                       src: str = "local", mkdirs: bool = True):
    """Upload em partes: corpo cru (sem multipart), até 32 MiB por parte. Grava num temporário
    `.netops-upload-<uid>` na pasta de destino e só renomeia na última parte (final=1)."""
    async def go():
        fs = fsvc.backend(src)
        buf = bytearray()
        async for piece in request.stream():
            buf += piece
            if len(buf) > MAX_UPLOAD_CHUNK:
                raise fsvc.FsError("parte grande demais (máx. 32 MiB)")
        try:
            out = await fs.upload_chunk(path, uid, offset, bytes(buf), final, overwrite, mkdirs)
        except fsvc.FsError:
            if offset == 0 or final:
                await fs.upload_abort(path, uid)
            raise
        if out.get("done"):
            fsvc.audit(fs.label, "UPLOAD", f"{fsvc.norm(path)} ({out.get('size')} bytes)", _client(request))
        return out
    return await _do(go)


@router.delete("/files/upload")
async def files_upload_abort(path: str = Query(...), uid: str = Query(..., pattern=r"^[A-Za-z0-9_-]{8,64}$"),
                             src: str = "local"):
    async def go():
        await fsvc.backend(src).upload_abort(path, uid)
        return {"ok": True}
    return await _do(go)


@router.get("/files/download-plan")
async def files_download_plan(path: list[str] = Query(...), src: str = "local"):
    """Expande pastas em arquivos p/ baixar SEM zip: [{rel, path, size, is_dir}] (rel começa no nome
    do item selecionado). O navegador pede um link por arquivo, na hora de baixar (o ticket vale 120 s)."""
    async def go():
        import asyncio
        fs = fsvc.backend(src)
        items: list[dict] = []
        for p in [fsvc.norm(x) for x in path][:5000]:
            walked = await asyncio.to_thread(lambda q=p: list(fs.sync_walk(q)))
            for full, rel, size, is_dir in walked:
                items.append({"rel": rel, "path": full, "size": size, "is_dir": is_dir})
                if len(items) > 20000:
                    raise fsvc.FsError("mais de 20.000 itens — baixe como .zip")
        return {"items": items, "files": sum(1 for i in items if not i["is_dir"]),
                "bytes": sum(i["size"] for i in items)}
    return await _do(go)


@router.get("/files/download-link")
async def files_download_link(path: list[str] = Query(...), src: str = "local"):
    """Link de uso único (120 s). 1 arquivo = o próprio arquivo; pasta(s) ou vários = .zip em fluxo."""
    async def go():
        fs = fsvc.backend(src)
        paths = [fsvc.norm(p) for p in path][:5000]
        st0 = await fs.stat(paths[0])          # valida já (erro aparece antes de abrir o download)
        single = len(paths) == 1 and not st0["is_dir"]
        if single and st0["type"] == "other":
            raise fsvc.FsError("não é um arquivo comum")
        t = fsvc.new_ticket(src, paths)
        name = posixpath.basename(paths[0]) or "raiz"
        if not single:
            name = (name if len(paths) == 1 else (posixpath.basename(posixpath.dirname(paths[0])) or "arquivos")) + ".zip"
        return {"url": f"/api/files/dl/{t}", "name": name, "zip": not single}
    return await _do(go)


def _disposition(name: str) -> str:
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@router.get("/files/dl/{ticket}")
async def files_dl(ticket: str, request: Request):
    """Download pelo link de uso único (sem header de sessão — o ticket é a autorização)."""
    try:
        _gate()
    except FilesDisabled:
        return _disabled()
    t = fsvc.take_ticket(ticket)
    if not t:
        return JSONResponse({"error": "expired", "detail": "link de download expirado ou já usado"}, status_code=410)
    try:
        fs = fsvc.backend(t["src"])
        paths = t["paths"]
        st0 = await fs.stat(paths[0])
        if len(paths) == 1 and not st0["is_dir"]:
            name = posixpath.basename(paths[0])
            fsvc.audit(fs.label, "DOWNLOAD", paths[0], _client(request))
            if fs.kind == "local":
                return FileResponse(paths[0], filename=name, media_type="application/octet-stream")
            size = st0.get("target_size", st0["size"]) if st0["type"] == "link" else st0["size"]
            return StreamingResponse(fs.iter_file(paths[0]), media_type="application/octet-stream",
                                     headers={"Content-Disposition": _disposition(name),
                                              "Content-Length": str(size)})
        base = posixpath.basename(paths[0]) or "raiz"
        name = (base if len(paths) == 1 else (posixpath.basename(posixpath.dirname(paths[0])) or "arquivos")) + ".zip"
        fsvc.audit(fs.label, "DOWNLOAD-ZIP", " ".join(paths), _client(request))
        return StreamingResponse(fsvc.zip_stream(fs, paths), media_type="application/zip",
                                 headers={"Content-Disposition": _disposition(name)})
    except fsvc.FsError as exc:
        return _err(exc)
