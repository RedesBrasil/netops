#!/usr/bin/env python3
"""Gerenciador de arquivos do console: menu **Arquivos** (este servidor) e painel SFTP do terminal de host.

Duas fontes com a MESMA interface assíncrona (o router não sabe qual está usando):
  - LocalFS  — o sistema de arquivos do servidor NetOps, como o usuário do processo (root na instalação
               padrão). Sem jaula de diretório: é a "gerência completa" pedida (12/11/2026).
  - RemoteFS — SFTP sobre a MESMA conexão SSH do terminal de host aberto (services/host_term_svc.py
               registra a sessão em SFTP_SESSIONS). Sem segundo login; acaba quando o terminal fecha.

Proteções (o resto é confiança no operador logado):
  - caminhos sempre absolutos e normalizados (sem NUL, sem relativo);
  - apagar/mover a raiz ou uma pasta de sistema de 1º nível (/etc, /usr, ...) é recusado;
  - apagar NUNCA segue link simbólico (o link é removido, o alvo fica);
  - escrita atômica: upload e edição gravam num temporário na mesma pasta e só renomeiam no fim;
  - edição com controle de concorrência (mtime+tamanho que o editor abriu);
  - auditoria de toda ação de escrita/download em runs/files/audit.log (sem conteúdo).
"""
from __future__ import annotations

import asyncio
import os
import posixpath
import secrets
import shutil
import stat as st
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import deps

READ_TEXT_MAX = 5 * 1024 * 1024          # editor: até 5 MiB
CHUNK = 256 * 1024                         # leitura p/ download/zip
UPLOAD_TMP_PREFIX = ".netops-upload-"
TICKET_TTL = 120                           # seg que um link de download vale (uso único)

# Recusados como alvo de apagar/mover/renomear (o conteúdo deles continua gerenciável).
PROTECTED = frozenset({
    "/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib32", "/lib64", "/libx32", "/media",
    "/mnt", "/opt", "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var",
})


class FsError(Exception):
    status = 400
    code = "fs_error"


class NotFound(FsError):
    status, code = 404, "not_found"


class Exists(FsError):
    status, code = 409, "exists"


class Denied(FsError):
    status, code = 403, "denied"


class Changed(FsError):
    status, code = 409, "changed"


class Unsupported(FsError):
    status, code = 501, "unsupported"


# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #
def norm(path: str | None) -> str:
    """Caminho absoluto normalizado (estilo POSIX). Relativo/NUL/vazio = erro."""
    p = str(path or "")
    if not p or "\x00" in p:
        raise FsError("caminho vazio ou inválido")
    if not p.startswith("/"):
        raise FsError(f"use caminho absoluto (recebido: {p!r})")
    p = posixpath.normpath(p)
    return "/" + p.lstrip("/") if p.startswith("//") else p


def join(parent: str, name: str) -> str:
    name = str(name or "")
    if not name or name in (".", "..") or "/" in name or "\x00" in name:
        raise FsError(f"nome inválido: {name!r}")
    return norm(posixpath.join(norm(parent), name))


def check_mutable(path: str) -> str:
    p = norm(path)
    if p in PROTECTED:
        raise Denied(f"{p} é protegido: o NetOps não apaga, move nem renomeia a raiz nem pastas de sistema")
    return p


def perms_string(mode: int) -> str:
    return st.filemode(mode)


def _kind(mode: int) -> str:
    if st.S_ISDIR(mode):
        return "dir"
    if st.S_ISLNK(mode):
        return "link"
    if st.S_ISREG(mode):
        return "file"
    return "other"          # socket, fifo, dispositivo


def sort_entries(entries: list[dict]) -> list[dict]:
    """Pastas (e links p/ pasta) primeiro, depois por nome sem caixa."""
    return sorted(entries, key=lambda e: (not e.get("is_dir"), e["name"].lower(), e["name"]))


def unique_name(name: str, taken: set[str], suffix: str = "cópia") -> str:
    if name not in taken:
        return name
    stem, ext = (name, "")
    if not name.startswith(".") and "." in name:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    n = 1
    while True:
        cand = f"{stem} ({suffix}{'' if n == 1 else ' ' + str(n)}){ext}"
        if cand not in taken:
            return cand
        n += 1


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #
_audit_lock = threading.Lock()


def audit(source: str, action: str, detail: str, client: str = "?") -> None:
    try:
        d = Path(deps.NETOPS_ROOT) / "runs" / "files"
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{stamp}] {action} origem={source} cliente={client} {detail}".replace("\n", " ")
        with _audit_lock, (d / "audit.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Fonte local (este servidor)
# --------------------------------------------------------------------------- #
def _owner(uid: int) -> str:
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (KeyError, ImportError):
        return str(uid)


def _group(gid: int) -> str:
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except (KeyError, ImportError):
        return str(gid)


def _oserr(exc: OSError, path: str = "") -> FsError:
    import errno
    msg = f"{exc.strerror or exc}{': ' + path if path else ''}"
    if exc.errno == errno.ENOENT:
        return NotFound(msg)
    if exc.errno == errno.EEXIST or exc.errno == errno.ENOTEMPTY:
        return Exists(msg)
    if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return Denied(msg)
    return FsError(msg)


class LocalFS:
    kind = "local"
    label = "local"
    remote_copy = True

    def __init__(self):
        self._owners: dict[int, str] = {}
        self._groups: dict[int, str] = {}

    # ---- helpers síncronos (rodam em thread) ----
    def _entry(self, path: str, name: str) -> dict:
        ls = os.lstat(path)
        kind = _kind(ls.st_mode)
        e = {"name": name, "type": kind, "size": ls.st_size, "mtime": int(ls.st_mtime),
             "mode": st.S_IMODE(ls.st_mode), "perms": perms_string(ls.st_mode),
             "owner": self._owners.setdefault(ls.st_uid, _owner(ls.st_uid)),
             "group": self._groups.setdefault(ls.st_gid, _group(ls.st_gid)),
             "is_dir": kind == "dir"}
        if kind == "link":
            try:
                e["target"] = os.readlink(path)
                t = os.stat(path)
                e["is_dir"] = st.S_ISDIR(t.st_mode)
                e["target_size"] = t.st_size
            except OSError:
                e["broken"] = True
        return e

    def _list(self, path: str) -> dict:
        p = norm(path)
        try:
            if not os.path.isdir(p):
                if os.path.exists(p):
                    raise FsError(f"não é uma pasta: {p}")
                raise NotFound(f"pasta não existe: {p}")
            names = os.listdir(p)
        except OSError as exc:
            raise _oserr(exc, p) from exc
        out = []
        for n in names:
            try:
                out.append(self._entry(os.path.join(p, n), n))
            except OSError:
                out.append({"name": n, "type": "other", "size": 0, "mtime": 0, "mode": 0,
                            "perms": "?---------", "owner": "", "group": "", "is_dir": False, "broken": True})
        return {"path": p, "entries": sort_entries(out)}

    def _stat(self, path: str) -> dict:
        p = norm(path)
        try:
            e = self._entry(p, posixpath.basename(p) or "/")
        except OSError as exc:
            raise _oserr(exc, p) from exc
        e["path"] = p
        return e

    async def _run(self, fn, *a):
        return await asyncio.to_thread(fn, *a)

    # ---- interface ----
    async def home(self) -> str:
        return "/"

    async def list(self, path: str) -> dict:
        return await self._run(self._list, path)

    async def stat(self, path: str) -> dict:
        return await self._run(self._stat, path)

    async def exists(self, path: str) -> bool:
        return await self._run(os.path.lexists, norm(path))

    async def mkdir(self, path: str) -> None:
        def go():
            p = norm(path)
            try:
                os.mkdir(p)
            except OSError as exc:
                raise _oserr(exc, p) from exc
        await self._run(go)

    async def touch(self, path: str) -> None:
        def go():
            p = norm(path)
            try:
                fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                os.close(fd)
            except OSError as exc:
                raise _oserr(exc, p) from exc
        await self._run(go)

    async def rename(self, src: str, dst: str, overwrite: bool = False) -> None:
        def go():
            s, d = check_mutable(src), norm(dst)
            if d == s:
                return
            if d.startswith(s + "/"):
                raise FsError("não dá para mover uma pasta para dentro dela mesma")
            if os.path.lexists(d):
                if not overwrite:
                    raise Exists(f"já existe: {d}")
                if os.path.isdir(d) and not os.path.islink(d):
                    raise Exists(f"já existe uma pasta com esse nome: {d}")
            try:
                os.rename(s, d)
            except OSError as exc:
                import errno
                if exc.errno != errno.EXDEV:
                    raise _oserr(exc, s) from exc
                try:
                    shutil.move(s, d)          # outro sistema de arquivos: copia + apaga
                except OSError as exc2:
                    raise _oserr(exc2, s) from exc2
        await self._run(go)

    async def copy(self, src: str, dst: str) -> None:
        def go():
            s, d = norm(src), norm(dst)
            if d == s or d.startswith(s + "/"):
                raise FsError("não dá para copiar uma pasta para dentro dela mesma")
            if os.path.lexists(d):
                raise Exists(f"já existe: {d}")
            try:
                if os.path.isdir(s) and not os.path.islink(s):
                    shutil.copytree(s, d, symlinks=True)
                else:
                    shutil.copy2(s, d, follow_symlinks=False)
            except (OSError, shutil.Error) as exc:
                raise (_oserr(exc, s) if isinstance(exc, OSError) else FsError(str(exc))) from exc
        await self._run(go)

    async def delete(self, path: str) -> None:
        def go():
            p = check_mutable(path)
            try:
                if os.path.islink(p) or not os.path.isdir(p):
                    os.unlink(p)
                else:
                    shutil.rmtree(p)           # não segue links internos
            except OSError as exc:
                raise _oserr(exc, p) from exc
        await self._run(go)

    async def chmod(self, path: str, mode: int) -> None:
        def go():
            p = norm(path)
            try:
                os.chmod(p, mode, follow_symlinks=True)
            except OSError as exc:
                raise _oserr(exc, p) from exc
        await self._run(go)

    async def read_bytes(self, path: str, limit: int) -> tuple[bytes, dict]:
        def go():
            p = norm(path)
            try:
                info = os.stat(p)
                if st.S_ISDIR(info.st_mode):
                    raise FsError(f"é uma pasta: {p}")
                if info.st_size > limit:
                    raise FsError(f"arquivo grande demais para o editor ({info.st_size} bytes; limite {limit}) — baixe-o")
                with open(p, "rb") as fh:
                    data = fh.read(limit + 1)
            except OSError as exc:
                raise _oserr(exc, p) from exc
            if len(data) > limit:
                raise FsError("arquivo grande demais para o editor — baixe-o")
            return data, {"mtime": int(info.st_mtime), "size": info.st_size}
        return await self._run(go)

    async def write_bytes(self, path: str, data: bytes, expect: dict | None) -> dict:
        def go():
            p = norm(path)
            real = os.path.realpath(p)
            try:
                info = os.stat(real) if os.path.exists(real) else None
                if expect and info is not None and (int(info.st_mtime) != int(expect.get("mtime", -1))
                                                    or info.st_size != int(expect.get("size", -1))):
                    raise Changed("o arquivo mudou no disco desde que foi aberto")
                if expect and info is None:
                    raise Changed("o arquivo foi apagado desde que foi aberto")
                tmp = os.path.join(os.path.dirname(real), f".{os.path.basename(real)}.netops-{secrets.token_hex(4)}")
                with open(tmp, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                if info is not None:
                    os.chmod(tmp, st.S_IMODE(info.st_mode))
                    try:
                        os.chown(tmp, info.st_uid, info.st_gid)
                    except OSError:
                        pass
                os.replace(tmp, real)
                new = os.stat(real)
            except OSError as exc:
                raise _oserr(exc, p) from exc
            return {"mtime": int(new.st_mtime), "size": new.st_size}
        return await self._run(go)

    # ---- upload em partes ----
    def _tmp_for(self, target: str, uid: str) -> str:
        return os.path.join(os.path.dirname(target), f"{UPLOAD_TMP_PREFIX}{uid}")

    async def upload_chunk(self, path: str, uid: str, offset: int, data: bytes,
                           final: bool, overwrite: bool, mkdirs: bool) -> dict:
        def go():
            p = norm(path)
            if p in PROTECTED:
                raise Denied(f"{p} é protegido")
            parent = os.path.dirname(p)
            try:
                if mkdirs:
                    os.makedirs(parent, exist_ok=True)
                if offset == 0 and os.path.lexists(p) and not overwrite:
                    raise Exists(f"já existe: {p}")
                if os.path.isdir(p) and not os.path.islink(p):
                    raise Exists(f"já existe uma pasta com esse nome: {p}")
                tmp = self._tmp_for(p, uid)
                if offset == 0:
                    fh = open(tmp, "wb")
                else:
                    have = os.path.getsize(tmp) if os.path.exists(tmp) else -1
                    if have != offset:
                        raise FsError(f"parte fora de ordem (esperado {have}, recebido {offset}); reenvie o arquivo")
                    fh = open(tmp, "ab")
                with fh:
                    fh.write(data)
                if final:
                    if os.path.lexists(p) and not overwrite:
                        os.unlink(tmp)
                        raise Exists(f"já existe: {p}")
                    os.chmod(tmp, 0o644)
                    os.replace(tmp, p)
                    return {"done": True, "size": os.path.getsize(p)}
                return {"done": False, "received": offset + len(data)}
            except OSError as exc:
                raise _oserr(exc, p) from exc
        return await self._run(go)

    async def upload_abort(self, path: str, uid: str) -> None:
        def go():
            try:
                os.unlink(self._tmp_for(norm(path), uid))
            except OSError:
                pass
        await self._run(go)

    # ---- leitura em fluxo (download/zip) — chamadas SÍNCRONAS, usadas na thread do zip ----
    def sync_walk(self, root: str):
        """(caminho_absoluto, nome_relativo, tamanho, é_pasta) de tudo sob root (não segue links de pasta)."""
        root = norm(root)
        base = posixpath.basename(root) or "raiz"
        if not os.path.isdir(root) or os.path.islink(root):
            yield root, base, os.path.getsize(root), False
            return
        yield root, base, 0, True
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            rel = base if dirpath == root else posixpath.join(base, os.path.relpath(dirpath, root))
            for d in sorted(dirnames):
                full = os.path.join(dirpath, d)
                if os.path.islink(full):
                    continue
                yield full, posixpath.join(rel, d), 0, True
            for f in sorted(filenames):
                full = os.path.join(dirpath, f)
                try:
                    s = os.stat(full)              # link p/ arquivo: inclui o conteúdo
                except OSError:
                    continue
                if st.S_ISREG(s.st_mode):
                    yield full, posixpath.join(rel, f), s.st_size, False

    def sync_open(self, path: str):
        return open(path, "rb")

    async def iter_file(self, path: str):
        """Gerador assíncrono de blocos (download de 1 arquivo)."""
        fh = await self._run(open, norm(path), "rb")
        try:
            while True:
                chunk = await self._run(fh.read, CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            fh.close()


# --------------------------------------------------------------------------- #
# Fonte remota: SFTP sobre a conexão do terminal de host
# --------------------------------------------------------------------------- #
class RemoteSession:
    """Uma conexão SSH viva do terminal de host. O SFTP só é iniciado no 1º uso."""

    def __init__(self, conn, host: dict, user: str, loop):
        self.conn = conn
        self.host = host
        self.user = user
        self.loop = loop
        self.sftp = None
        self.error = ""
        self._lock = asyncio.Lock()

    @property
    def label(self) -> str:
        return f"host:{self.host.get('id')}({self.host.get('hostname', '')})"

    async def client(self):
        async with self._lock:
            if self.sftp is None:
                if self.error:
                    raise Unsupported(self.error)
                try:
                    self.sftp = await self.conn.start_sftp_client()
                except Exception as exc:  # noqa: BLE001 — servidor sem subsistema sftp
                    self.error = f"este host não oferece SFTP ({exc or type(exc).__name__})"
                    raise Unsupported(self.error) from exc
            return self.sftp

    def close(self):
        try:
            if self.sftp is not None:
                self.sftp.exit()
        except Exception:  # noqa: BLE001
            pass


SFTP_SESSIONS: dict[str, RemoteSession] = {}


def register_session(conn, host: dict, user: str) -> str:
    token = secrets.token_urlsafe(24)
    SFTP_SESSIONS[token] = RemoteSession(conn, host, user, asyncio.get_running_loop())
    return token


def unregister_session(token: str | None) -> None:
    s = SFTP_SESSIONS.pop(token or "", None)
    if s:
        s.close()


def _sftp_err(exc, path: str = "") -> FsError:
    import asyncssh
    if isinstance(exc, FsError):
        return exc
    if isinstance(exc, asyncssh.SFTPError):
        code = getattr(exc, "code", None)
        msg = f"{exc.reason or exc}{': ' + path if path else ''}"
        if code == asyncssh.FX_NO_SUCH_FILE:
            return NotFound(msg)
        if code == asyncssh.FX_PERMISSION_DENIED:
            return Denied(msg)
        if code == getattr(asyncssh, "FX_FILE_ALREADY_EXISTS", -1):
            return Exists(msg)
        if code == asyncssh.FX_OP_UNSUPPORTED:
            return Unsupported(msg)
        return FsError(msg)
    if isinstance(exc, (asyncssh.Error, OSError, EOFError, ConnectionError)):
        return FsError(f"conexão SFTP: {exc or type(exc).__name__}")
    return FsError(str(exc))


class RemoteFS:
    kind = "remote"

    def __init__(self, session: RemoteSession):
        self.s = session
        self.label = session.label

    async def _c(self):
        return await self.s.client()

    @staticmethod
    def _attrs_entry(name: str, attrs, longname: str = "") -> dict:
        mode = attrs.permissions or 0
        kind = _kind(mode) if mode else {1: "file", 2: "dir", 3: "link"}.get(getattr(attrs, "type", 0), "other")
        owner = attrs.owner or ""
        group = attrs.group or ""
        if (not owner or not group) and longname:
            parts = str(longname).split()
            if len(parts) >= 4:
                owner, group = owner or parts[2], group or parts[3]
        return {"name": name, "type": kind, "size": attrs.size or 0, "mtime": int(attrs.mtime or 0),
                "mode": st.S_IMODE(mode), "perms": perms_string(mode) if mode else "?---------",
                "owner": owner or str(attrs.uid if attrs.uid is not None else ""),
                "group": group or str(attrs.gid if attrs.gid is not None else ""),
                "is_dir": kind == "dir"}

    async def home(self) -> str:
        c = await self._c()
        try:
            return norm(await c.realpath("."))
        except Exception:  # noqa: BLE001
            return "/"

    async def list(self, path: str) -> dict:
        c = await self._c()
        p = norm(path)
        try:
            names = await c.readdir(p)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc
        out = []
        links = []
        for n in names:
            fn = n.filename if isinstance(n.filename, str) else n.filename.decode("utf-8", "replace")
            if fn in (".", ".."):
                continue
            e = self._attrs_entry(fn, n.attrs, n.longname if isinstance(n.longname, str) else "")
            out.append(e)
            if e["type"] == "link":
                links.append(e)

        async def resolve(e):
            full = posixpath.join(p, e["name"])
            try:
                e["target"] = await c.readlink(full)
            except Exception:  # noqa: BLE001
                pass
            try:
                t = await c.stat(full)
                e["is_dir"] = bool(t.permissions and st.S_ISDIR(t.permissions))
                e["target_size"] = t.size or 0
            except Exception:  # noqa: BLE001
                e["broken"] = True
        if links:
            await asyncio.gather(*(resolve(e) for e in links[:500]))
        return {"path": p, "entries": sort_entries(out)}

    async def stat(self, path: str) -> dict:
        c = await self._c()
        p = norm(path)
        try:
            e = self._attrs_entry(posixpath.basename(p) or "/", await c.lstat(p))
            if e["type"] == "link":
                t = await c.stat(p)
                e["is_dir"] = bool(t.permissions and st.S_ISDIR(t.permissions))
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc
        e["path"] = p
        return e

    async def exists(self, path: str) -> bool:
        c = await self._c()
        try:
            await c.lstat(norm(path))
            return True
        except Exception:  # noqa: BLE001
            return False

    async def mkdir(self, path: str) -> None:
        c = await self._c()
        p = norm(path)
        if await self.exists(p):
            raise Exists(f"já existe: {p}")
        try:
            await c.mkdir(p)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc

    async def _makedirs(self, path: str) -> None:
        c = await self._c()
        try:
            await c.makedirs(norm(path), exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, path) from exc

    async def touch(self, path: str) -> None:
        import asyncssh
        c = await self._c()
        p = norm(path)
        try:
            f = await c.open(p, asyncssh.FXF_WRITE | asyncssh.FXF_CREAT | asyncssh.FXF_EXCL)
            await f.close()
        except Exception as exc:  # noqa: BLE001
            if await self.exists(p):
                raise Exists(f"já existe: {p}") from exc
            raise _sftp_err(exc, p) from exc

    async def _replace(self, c, src: str, dst: str) -> None:
        """rename que sobrescreve: posix-rename (OpenSSH) ou remove+rename."""
        try:
            await c.posix_rename(src, dst)
            return
        except Exception:  # noqa: BLE001 — extensão ausente (MikroTik etc.)
            pass
        if await self.exists(dst):
            await c.remove(dst)
        await c.rename(src, dst)

    async def rename(self, src: str, dst: str, overwrite: bool = False) -> None:
        c = await self._c()
        s, d = check_mutable(src), norm(dst)
        if d == s:
            return
        if d.startswith(s + "/"):
            raise FsError("não dá para mover uma pasta para dentro dela mesma")
        try:
            if await self.exists(d):
                if not overwrite:
                    raise Exists(f"já existe: {d}")
                if (await self.stat(d))["type"] == "dir":
                    raise Exists(f"já existe uma pasta com esse nome: {d}")
                await self._replace(c, s, d)
            else:
                await c.rename(s, d)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, s) from exc

    async def copy(self, src: str, dst: str) -> None:
        c = await self._c()
        s, d = norm(src), norm(dst)
        if d == s or d.startswith(s + "/"):
            raise FsError("não dá para copiar uma pasta para dentro dela mesma")
        if await self.exists(d):
            raise Exists(f"já existe: {d}")
        try:
            # asyncssh usa a extensão copy-data quando o servidor tem; senão passa os bytes pelo NetOps.
            await c.copy(s, d, recurse=True, preserve=True)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, s) from exc

    async def delete(self, path: str) -> None:
        c = await self._c()
        p = check_mutable(path)
        try:
            a = await c.lstat(p)
            if a.permissions and st.S_ISDIR(a.permissions):
                await c.rmtree(p)
            else:
                await c.remove(p)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc

    async def chmod(self, path: str, mode: int) -> None:
        c = await self._c()
        p = norm(path)
        try:
            await c.chmod(p, mode)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc

    async def read_bytes(self, path: str, limit: int) -> tuple[bytes, dict]:
        c = await self._c()
        p = norm(path)
        try:
            a = await c.stat(p)
            if a.permissions and st.S_ISDIR(a.permissions):
                raise FsError(f"é uma pasta: {p}")
            if (a.size or 0) > limit:
                raise FsError(f"arquivo grande demais para o editor ({a.size} bytes; limite {limit}) — baixe-o")
            async with c.open(p, "rb") as f:
                data = await f.read(limit + 1)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc
        if len(data) > limit:
            raise FsError("arquivo grande demais para o editor — baixe-o")
        return data, {"mtime": int(a.mtime or 0), "size": a.size or 0}

    async def write_bytes(self, path: str, data: bytes, expect: dict | None) -> dict:
        c = await self._c()
        p = norm(path)
        try:
            try:
                a = await c.stat(p)
            except Exception:  # noqa: BLE001
                a = None
            if expect and a is not None and (int(a.mtime or 0) != int(expect.get("mtime", -1))
                                             or (a.size or 0) != int(expect.get("size", -1))):
                raise Changed("o arquivo mudou no host desde que foi aberto")
            if expect and a is None:
                raise Changed("o arquivo foi apagado desde que foi aberto")
            tmp = posixpath.join(posixpath.dirname(p), f".{posixpath.basename(p)}.netops-{secrets.token_hex(4)}")
            async with c.open(tmp, "wb") as f:
                await f.write(data)
            if a is not None and a.permissions:
                try:
                    await c.chmod(tmp, st.S_IMODE(a.permissions))
                except Exception:  # noqa: BLE001
                    pass
            await self._replace(c, tmp, p)
            n = await c.stat(p)
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc
        return {"mtime": int(n.mtime or 0), "size": n.size or 0}

    async def upload_chunk(self, path: str, uid: str, offset: int, data: bytes,
                           final: bool, overwrite: bool, mkdirs: bool) -> dict:
        c = await self._c()
        p = norm(path)
        if p in PROTECTED:
            raise Denied(f"{p} é protegido")
        tmp = posixpath.join(posixpath.dirname(p), f"{UPLOAD_TMP_PREFIX}{uid}")
        try:
            if mkdirs:
                await self._makedirs(posixpath.dirname(p))
            if offset == 0 and await self.exists(p) and not overwrite:
                raise Exists(f"já existe: {p}")
            if offset == 0:
                async with c.open(tmp, "wb") as f:
                    await f.write(data)
            else:
                have = (await c.stat(tmp)).size if await self.exists(tmp) else -1
                if have != offset:
                    raise FsError(f"parte fora de ordem (esperado {have}, recebido {offset}); reenvie o arquivo")
                async with c.open(tmp, "r+b") as f:
                    await f.write(data, offset)
            if final:
                if await self.exists(p):
                    if not overwrite:
                        await c.remove(tmp)
                        raise Exists(f"já existe: {p}")
                    await self._replace(c, tmp, p)
                else:
                    await c.rename(tmp, p)
                return {"done": True, "size": (await c.stat(p)).size or 0}
            return {"done": False, "received": offset + len(data)}
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc

    async def upload_abort(self, path: str, uid: str) -> None:
        try:
            c = await self._c()
            await c.remove(posixpath.join(posixpath.dirname(norm(path)), f"{UPLOAD_TMP_PREFIX}{uid}"))
        except Exception:  # noqa: BLE001
            pass

    # ---- leitura em fluxo ----
    async def iter_file(self, path: str):
        c = await self._c()
        p = norm(path)
        try:
            f = await c.open(p, "rb")
        except Exception as exc:  # noqa: BLE001
            raise _sftp_err(exc, p) from exc
        try:
            offset = 0
            while True:
                chunk = await f.read(CHUNK, offset)
                if not chunk:
                    break
                offset += len(chunk)
                yield chunk
        finally:
            await f.close()

    # Versões síncronas p/ a thread do zip: delegam ao loop do servidor.
    def _sync(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.s.loop).result(300)

    def sync_walk(self, root: str):
        c = self._sync(self._c())
        root = norm(root)
        base = posixpath.basename(root) or "raiz"
        a = self._sync(c.stat(root))
        if not (a.permissions and st.S_ISDIR(a.permissions)):
            yield root, base, a.size or 0, False
            return
        yield root, base, 0, True
        stack = [(root, base)]
        while stack:
            d, rel = stack.pop()
            try:
                names = self._sync(c.readdir(d))
            except Exception:  # noqa: BLE001
                continue
            for n in sorted(names, key=lambda x: str(x.filename)):
                fn = n.filename if isinstance(n.filename, str) else n.filename.decode("utf-8", "replace")
                if fn in (".", ".."):
                    continue
                full, r = posixpath.join(d, fn), posixpath.join(rel, fn)
                mode = n.attrs.permissions or 0
                if st.S_ISDIR(mode):
                    yield full, r, 0, True
                    stack.append((full, r))
                elif st.S_ISLNK(mode):
                    try:
                        t = self._sync(c.stat(full))
                    except Exception:  # noqa: BLE001
                        continue
                    if t.permissions and st.S_ISREG(t.permissions):
                        yield full, r, t.size or 0, False
                elif st.S_ISREG(mode):
                    yield full, r, n.attrs.size or 0, False

    def sync_open(self, path: str):
        fs = self

        class _Reader:
            def __init__(self):
                async def _open():          # sftp.open devolve um "awaitable", não uma coroutine
                    return await fs.s.sftp.open(path, "rb")
                self.f = fs._sync(_open())
                self.off = 0

            def read(self, n=CHUNK):
                data = fs._sync(self.f.read(n, self.off))
                self.off += len(data)
                return data

            def close(self):
                try:
                    fs._sync(self.f.close())
                except Exception:  # noqa: BLE001
                    pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()
        return _Reader()


# --------------------------------------------------------------------------- #
# Escolha da fonte
# --------------------------------------------------------------------------- #
_LOCAL = LocalFS()


def backend(src: str | None):
    if not src or src == "local":
        return _LOCAL
    s = SFTP_SESSIONS.get(src)
    if s is None:
        raise NotFound("sessão SFTP encerrada (o terminal do host foi fechado) — reabra o terminal")
    return RemoteFS(s)


# --------------------------------------------------------------------------- #
# Links de download (uso único) — o navegador baixa direto, sem carregar tudo na memória
# --------------------------------------------------------------------------- #
_tickets: dict[str, dict] = {}


def new_ticket(src: str, paths: list[str]) -> str:
    now = time.time()
    for k in [k for k, v in _tickets.items() if v["exp"] < now]:
        _tickets.pop(k, None)
    t = secrets.token_urlsafe(24)
    _tickets[t] = {"src": src, "paths": paths, "exp": now + TICKET_TTL}
    return t


def take_ticket(token: str) -> dict | None:
    t = _tickets.pop(token, None)
    if not t or t["exp"] < time.time():
        return None
    return t


# --------------------------------------------------------------------------- #
# ZIP em fluxo (várias pastas/arquivos): thread escreve, o loop entrega ao navegador
# --------------------------------------------------------------------------- #
class _QueueWriter:
    """Arquivo não-posicionável p/ o zipfile: cada write vira um bloco na fila (com contrapressão)."""

    def __init__(self, put):
        self._put = put
        self._buf = bytearray()
        self.pos = 0

    def write(self, b) -> int:
        self._buf += b
        self.pos += len(b)
        if len(self._buf) >= CHUNK:
            self._put(bytes(self._buf))
            self._buf.clear()
        return len(b)

    def tell(self) -> int:
        return self.pos

    def flush(self) -> None:
        if self._buf:
            self._put(bytes(self._buf))
            self._buf.clear()

    def seekable(self) -> bool:
        return False


async def zip_stream(fs, paths: list[str]):
    """Gerador assíncrono de um .zip com todos os caminhos (pastas recursivas)."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=16)
    stop = threading.Event()
    DONE = object()

    def put(item):
        if stop.is_set():
            raise RuntimeError("download cancelado")
        asyncio.run_coroutine_threadsafe(q.put(item), loop).result()

    def produce():
        try:
            w = _QueueWriter(put)
            with zipfile.ZipFile(w, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1,
                                 allowZip64=True) as zf:
                used: set[str] = set()
                for root in paths:
                    for full, rel, size, is_dir in fs.sync_walk(root):
                        if stop.is_set():
                            return
                        arc = rel
                        if not is_dir and arc in used:
                            arc = posixpath.join(posixpath.dirname(arc),
                                                 unique_name(posixpath.basename(arc), {posixpath.basename(u) for u in used}))
                        used.add(arc)
                        zi = zipfile.ZipInfo(arc + ("/" if is_dir else ""),
                                             date_time=time.localtime(time.time())[:6])
                        if is_dir:
                            zi.external_attr = (0o40755 << 16) | 0x10
                            zf.writestr(zi, b"")
                            continue
                        zi.compress_type = zipfile.ZIP_DEFLATED
                        zi.external_attr = 0o100644 << 16
                        zi.file_size = size
                        try:
                            with fs.sync_open(full) as src, zf.open(zi, "w", force_zip64=size > 2**31) as dst:
                                while True:
                                    data = src.read(CHUNK)
                                    if not data:
                                        break
                                    dst.write(data)
                        except (OSError, FsError) as exc:
                            zf.writestr(arc + ".ERRO.txt", f"não foi possível ler {full}: {exc}\n")
            w.flush()
        except Exception as exc:  # noqa: BLE001
            if not stop.is_set():
                try:
                    put(exc)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if not stop.is_set():
                try:
                    put(DONE)
                except Exception:  # noqa: BLE001
                    pass

    th = threading.Thread(target=produce, daemon=True, name="netops-zip")
    th.start()
    try:
        while True:
            item = await q.get()
            if item is DONE:
                break
            if isinstance(item, Exception):
                break                       # zip incompleto: o navegador acusa erro no arquivo
            yield item
    finally:
        stop.set()
        while not q.empty():               # destrava o produtor se ele estiver esperando espaço
            q.get_nowait()
