#!/usr/bin/env python3
"""Conectar o GitHub DO USUÁRIO (Minha conta → GitHub). ⚠ MEXE EM CREDENCIAL.

Fluxo padrão = login por dispositivo do próprio GitHub CLI, num PTY (mesma técnica de claude_auth.py):

    GH_CONFIG_DIR=<runs/users/<u>/gh> gh auth login --hostname github.com --git-protocol https --web --scopes ...

O `gh` imprime um código de uso único e o link https://github.com/login/device; a UI mostra os dois, o
usuário autoriza no navegador DELE e o `gh` termina sozinho gravando o token só na pasta dele. A senha
do GitHub nunca passa pelo NetOps. Depois lemos login/nome/e-mails (`gh api user`) p/ o github.json.

Protocolo do WebSocket /api/account/github/login (JSON):
  cliente -> servidor: {"type":"start"} | {"type":"cancel"}
  servidor -> cliente: {"type":"status","status":{...}}
                       {"type":"device","code":"XXXX-XXXX","url":"https://github.com/login/device"}
                       {"type":"log","text":"..."}
                       {"type":"done","ok":bool,"status":{...}}
                       {"type":"error","detail":"..."}
"""
from __future__ import annotations

import asyncio
import json
import os
import pty
import re
import signal

from fastapi import WebSocket, WebSocketDisconnect

import deps
from lib import github_identity as ghid

_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_78=>]")
_CODE = re.compile(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})")
_URL = re.compile(r"https://github\.com/login/device\S*")
_YESNO = re.compile(r"\(Y/n\)|\[Y/n\]", re.I)
_TOKENISH = re.compile(r"\b(gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
LOGIN_TIMEOUT = 15 * 60


def status(username: str) -> dict:
    return ghid.public(ghid.get_meta(deps.DATA_ROOT, username))


class GitHubLoginSession:
    """Conduz um `gh auth login --web` num PTY, com o GH_CONFIG_DIR do usuário."""

    def __init__(self, ws: WebSocket, username: str, on_done=None):
        self.ws, self.username, self.on_done = ws, username, on_done
        self.pid: int | None = None
        self.fd: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._buf = ""
        self._sent_code = False
        self._entered = False
        self._exited = asyncio.Event()

    async def _send(self, obj: dict) -> None:
        try:
            await self.ws.send_text(json.dumps(obj, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def run(self) -> None:
        await self._send({"type": "status", "status": status(self.username)})
        try:
            while True:
                try:
                    raw = await self.ws.receive_json()
                except Exception:   # noqa: BLE001 - socket caiu
                    return
                kind = raw.get("type") if isinstance(raw, dict) else None
                if kind == "start" and self.pid is None:
                    await self._spawn()
                elif kind == "cancel":
                    self._kill()
                    await self._send({"type": "done", "ok": False, "status": status(self.username)})
                    return
        finally:
            self._kill()
            try:
                await self.ws.close()
            except Exception:   # noqa: BLE001
                pass

    async def _spawn(self) -> None:
        gh = ghid.gh_bin()
        if not gh:
            await self._send({"type": "error", "detail": "GitHub CLI (gh) não está instalado no servidor."})
            return
        cfg = ghid.gh_dir(deps.DATA_ROOT, self.username)
        # Login novo sobrescreve o anterior da pasta (troca de conta).
        argv = [gh, "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web",
                "--scopes", ",".join(ghid.SCOPES),
                # token no hosts.yml DA PASTA do usuário (0700), nunca no chaveiro do sistema (compartilhado)
                "--insecure-storage"]
        env = ghid.base_env(cfg, deps.DATA_ROOT)
        env.pop("GH_PROMPT_DISABLED", None)   # o fluxo --web precisa do "Press Enter"
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(str(cfg))
                os.execvpe(argv[0], argv, env)
            except OSError:
                pass
            os._exit(127)
        self.pid, self.fd = pid, fd
        os.set_blocking(fd, False)
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(fd, self._on_readable)
        self._loop.create_task(self._watch())

    def _on_readable(self) -> None:
        if self.fd is None:
            return
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._detach()
            self._exited.set()
            return
        self._loop.create_task(self._translate(data.decode("utf-8", "replace")))

    def _write(self, text: str) -> None:
        if self.fd is not None:
            try:
                os.write(self.fd, text.encode())
            except OSError:
                pass

    async def _translate(self, chunk: str) -> None:
        # O prompt (survey) do gh pergunta a posição do cursor (ESC[6n) e TRAVA até o terminal responder.
        for _ in range(chunk.count("\x1b[6n")):
            self._write("\x1b[24;80R")
        text = _TOKENISH.sub("«token»", _ANSI.sub("", chunk))
        self._buf += text
        if not self._sent_code:
            m = _CODE.search(self._buf)
            if m:
                self._sent_code = True
                u = _URL.search(self._buf)
                await self._send({"type": "device", "code": m.group(1),
                                  "url": (u.group(0).rstrip(".") if u else "https://github.com/login/device")})
        if not self._entered and "Press Enter" in self._buf:
            self._entered = True
            self._write("\r")          # "abre" o navegador (GH_BROWSER=true) e começa a esperar a autorização
        if _YESNO.search(text):
            # "Authenticate Git with your GitHub credentials?" = sim: grava o helper só no gitconfig DA PASTA
            # (GIT_CONFIG_GLOBAL isolado). O survey do gh lê em modo raw: Enter = \r.
            self._write("Y\r")
        clean = "\n".join(line for line in (s.strip() for s in text.splitlines())
                          if line and not _CODE.search(line) and "Press Enter" not in line)
        if clean:
            await self._send({"type": "log", "text": clean[:500]})

    async def _watch(self) -> None:
        try:
            await asyncio.wait_for(self._exited.wait(), timeout=LOGIN_TIMEOUT)
        except asyncio.TimeoutError:
            await self._send({"type": "error", "detail": "tempo esgotado esperando a autorização no GitHub"})
        rc = None
        for _ in range(30):            # o gh sai logo depois do EOF; espera sem bloquear o loop
            rc = self._reap()
            if rc is not None or self.pid is None:
                break
            await asyncio.sleep(0.1)
        self._kill()
        ok, detail = False, ""
        if rc == 0:
            try:
                await asyncio.to_thread(ghid.refresh, deps.DATA_ROOT, self.username, "device", False)
                ok = True
            except ghid.GitHubError as e:
                detail = e.detail
        else:
            detail = "login não concluído"
        if ok and self.on_done:
            try:
                self.on_done(self.username)
            except Exception:   # noqa: BLE001
                pass
        if detail:
            await self._send({"type": "log", "text": detail})
        await self._send({"type": "done", "ok": ok, "status": status(self.username)})

    def _reap(self) -> int | None:
        if self.pid is None:
            return None
        try:
            pid, st = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.pid = None
            return None
        if pid:
            self.pid = None
            return os.waitstatus_to_exitcode(st)
        return None

    def _detach(self) -> None:
        if self.fd is not None and self._loop is not None:
            try:
                self._loop.remove_reader(self.fd)
            except Exception:   # noqa: BLE001
                pass

    def _kill(self) -> None:
        self._detach()
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                pass
            self.pid = None
