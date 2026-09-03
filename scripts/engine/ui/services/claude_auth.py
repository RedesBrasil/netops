#!/usr/bin/env python3
"""Login/logout do agente `claude` a partir da aba Claude Code. ⚠ MEXE EM CREDENCIAL.

Por que este arquivo existe: `/login` é um comando da **TUI** do Claude Code — ele não
existe no protocolo do `claude-agent-sdk`, então nunca aparece na lista de slash da aba e
digitá-lo no chat não faz nada (vira só mais um texto pro modelo). Aqui reimplementamos o
fluxo com o que o CLI expõe FORA da TUI:

    claude auth status --json    # estado atual (headless, seguro)
    claude auth login            # OAuth: imprime a URL e espera o código colado
    claude auth logout

O `auth login` é interativo (só fala com um TTY), então rodamos num **PTY** — mesma
técnica de routers/terminal.py — e traduzimos a conversa para JSON no WebSocket: o
servidor manda a URL, o humano abre no navegador dele e cola o código de volta.

⚠ O HOME É O QUE IMPORTA. As credenciais vivem em `$HOME/.claude/.credentials.json` do
processo que roda o `claude`. A aba Claude Code lança o agente via SDK com
`env={**os.environ, ...}` (ver claude_svc._options), ou seja **o HOME do servidor**.
Logo o login TEM de rodar com esse mesmo env, senão grava a credencial em outro store.
É exatamente a pegadinha do console NetOps: o servidor sobe como root (HOME=/root) e o
terminal web DROPA para `netops` (HOME=/opt/netops) — logar pelo terminal não loga a aba,
são dois cofres diferentes. Rodando aqui, o login cai no mesmo store do agente, e por
tabela nas mesmas conversas de `$HOME/.claude/projects/`.

Segredo: o código OAuth colado é credencial. Desligamos o eco do PTY e ainda redigimos
qualquer eco residual antes de devolver a saída pra tela. Ele nunca é logado.

Protocolo do WebSocket /api/claude/login (JSON nos dois sentidos):
  cliente -> servidor:
    {"type":"start","mode":"claudeai"|"console"}   inicia o fluxo (spawna o `claude auth login`)
    {"type":"code","code":"..."}                   entrega o código colado do navegador
    {"type":"cancel"}                              aborta e mata o subprocesso
  servidor -> cliente:
    {"type":"status","status":{...}}               estado inicial (mesmo shape de status())
    {"type":"url","url":"https://..."}             URL p/ abrir no navegador
    {"type":"awaiting_code"}                       o CLI está pedindo o código
    {"type":"log","text":"..."}                    saída do CLI (limpa de ANSI, redigida)
    {"type":"done","ok":bool,"status":{...}}       fim do fluxo (status() é a autoridade)
    {"type":"error","detail":"..."}
"""
from __future__ import annotations

import asyncio
import json
import os
import pty
import pwd
import re
import signal
import subprocess
import termios

from fastapi import WebSocket, WebSocketDisconnect

import deps
from services import claude_svc

# Limpeza de ANSI. A URL vem embrulhada num hyperlink OSC-8 (`ESC ] 8 ; ; <url> BEL`),
# então o OSC sai PRIMEIRO — o que sobra é a URL em texto puro que o CLI também imprime.
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_ESC = re.compile(r"\x1b[@-Z\\-_]")
_URL = re.compile(r"https://[^\s'\"<>]+")
_ASK_CODE = re.compile(r"paste\s+(the\s+)?code", re.I)
_OUTCOME = re.compile(r"login\s+(failed|success)", re.I)

_LOGIN_TIMEOUT = 15 * 60   # o humano precisa ir no navegador; teto generoso
_STATUS_TIMEOUT = 30


def _clean(text: str) -> str:
    return _ESC.sub("", _CSI.sub("", _OSC.sub("", text)))


def _env() -> dict:
    """Env do subprocesso — o MESMO do agente (claude_svc._options), logo o mesmo HOME.

    `IS_SANDBOX=1` acompanha o do agente: o console costuma subir como root em container, e o
    `claude` recusa algumas operações sob root sem essa declaração de ambiente isolado.
    NO_COLOR/TERM=dumb só enxugam a saída p/ o parser; não mudam o store nem o fluxo.
    """
    return {**os.environ, "IS_SANDBOX": "1", "NO_COLOR": "1", "FORCE_COLOR": "0", "TERM": "dumb"}


def _store() -> dict:
    """Onde a credencial vai parar — o par (usuário, HOME) do processo do servidor.

    Exposto na UI de propósito: é a resposta pra "loguei no terminal e a aba continua
    deslogada". Só metadado de caminho; nenhum segredo sai daqui.
    """
    home = os.path.expanduser("~")
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        user = str(os.getuid())
    return {"user": user, "home": home, "credentials": os.path.join(home, ".claude", ".credentials.json")}


def _first_json(text: str) -> dict | None:
    """Extrai o primeiro objeto JSON da saída (o CLI às vezes prefixa avisos)."""
    clean = _clean(text)
    start, end = clean.find("{"), clean.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(clean[start:end + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _run(args: list[str], timeout: int = _STATUS_TIMEOUT) -> subprocess.CompletedProcess | None:
    cli = claude_svc.claude_path()
    if not cli:
        return None
    try:
        return subprocess.run(  # noqa: S603 - argv fixo, sem shell
            [cli, *args], env=_env(), cwd=str(deps.NETOPS_ROOT),
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def status() -> dict:
    """Estado da autenticação do `claude` que a aba usa. Nunca devolve token/segredo."""
    if not claude_svc.claude_path():
        return {"available": False, "loggedIn": False,
                "detail": "binário `claude` não encontrado no PATH do servidor"}
    proc = _run(["auth", "status", "--json"])
    if proc is None:
        return {"available": True, "loggedIn": False, "store": _store(),
                "detail": "falha ao executar `claude auth status`"}
    data = _first_json(proc.stdout) or _first_json(proc.stderr)
    if data is None:
        return {"available": True, "loggedIn": False, "store": _store(),
                "detail": _clean(proc.stderr or proc.stdout).strip()[:300] or "resposta ininteligível"}
    data["available"] = True
    data["store"] = _store()
    return data


def logout() -> dict:
    """Desloga e devolve o estado resultante."""
    _run(["auth", "logout"])
    return status()


class ClaudeLoginSession:
    """Conduz um `claude auth login` num PTY, falando JSON com a UI."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.pid: int | None = None
        self.fd: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._code: str | None = None      # p/ redigir eco residual
        self._asked = False
        self._pending_code = False         # código entregue, esperando o veredito do CLI
        self._url_sent = False
        self._url = ""
        self._buf = ""
        self._exited = asyncio.Event()

    # ------------------------------------------------------------------ envio
    async def _send(self, obj: dict) -> None:
        try:
            await self.ws.send_text(json.dumps(obj, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass

    def _redact(self, text: str) -> str:
        return text.replace(self._code, "«código»") if self._code else text

    # ------------------------------------------------------------- ciclo de vida
    async def run(self) -> None:
        await self._send({"type": "status", "status": status()})
        try:
            await self._ws_pump()
        finally:
            self._kill()
            try:
                await self.ws.close()
            except Exception:
                pass

    async def _ws_pump(self) -> None:
        while True:
            try:
                raw = await self.ws.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                return
            except Exception:
                return
            if not isinstance(raw, dict):
                continue
            kind = raw.get("type")
            if kind == "start":
                if self.pid is None:
                    await self._spawn(raw.get("mode"))
            elif kind == "code":
                self._write_code(raw.get("code") or "")
            elif kind == "cancel":
                self._kill()
                await self._send({"type": "done", "ok": False, "status": status()})
                return

    async def _spawn(self, mode: str | None) -> None:
        cli = claude_svc.claude_path()
        if not cli:
            await self._send({"type": "error", "detail": "binário `claude` não encontrado no PATH"})
            return
        argv = [cli, "auth", "login", "--console" if mode == "console" else "--claudeai"]
        env, cwd = _env(), str(deps.NETOPS_ROOT)
        # Estado zerado: um "tentar de novo" na mesma conexão não pode herdar o desfecho anterior.
        self._exited = asyncio.Event()
        self._code = None
        self._asked = self._pending_code = self._url_sent = False
        self._url = self._buf = ""

        pid, fd = pty.fork()
        if pid == 0:  # filho: vira o `claude auth login`
            try:
                os.chdir(cwd)
            except OSError:
                pass
            try:
                os.execvpe(argv[0], argv, env)
            except OSError:
                pass
            os._exit(127)

        self.pid, self.fd = pid, fd
        self._noecho(fd)   # o código colado NÃO volta pela saída
        os.set_blocking(fd, False)
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(fd, self._on_readable)
        self._loop.create_task(self._watch())

    @staticmethod
    def _noecho(fd: int) -> None:
        try:
            attrs = termios.tcgetattr(fd)
            attrs[3] &= ~termios.ECHO          # lflag
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except (termios.error, OSError):
            pass

    def _write_code(self, code: str) -> None:
        code = code.strip()
        if not code or self.fd is None:
            return
        self._code = code
        self._pending_code = True
        try:
            os.write(self.fd, (code + "\n").encode("utf-8"))
        except OSError:
            pass

    # ------------------------------------------------------------- leitura do PTY
    def _on_readable(self) -> None:
        """Callback do event loop: lê o PTY e agenda a tradução (não pode ser async)."""
        if self.fd is None:
            return
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:                      # EOF: o subprocesso terminou
            self._detach()
            self._exited.set()
            return
        self._loop.create_task(self._translate(data.decode("utf-8", "replace")))

    async def _translate(self, chunk: str) -> None:
        text = self._redact(_clean(chunk))
        self._buf += text
        # A URL só interessa uma vez (o CLI a imprime duas: hyperlink + texto).
        if not self._url_sent:
            for u in _URL.findall(self._buf):
                if "oauth" in u or "authorize" in u:
                    self._url_sent = True
                    self._url = u
                    await self._send({"type": "url", "url": u})
                    break
        if _ASK_CODE.search(text):            # primeiro pedido do código
            self._asked = True
            await self._send({"type": "awaiting_code"})
        stripped = text.strip()
        if stripped and not (self._url and self._url in stripped):   # não repete a URL no log
            await self._send({"type": "log", "text": stripped})

        if _OUTCOME.search(text):     # "Login successful/failed": desfecho — o CLI não sai sozinho
            self._pending_code = False
            self._exited.set()
        elif self._pending_code and stripped:
            # O CLI reclamou do código (ex.: "Invalid code. Please make sure the full code was
            # copied.") e segue esperando — mas NÃO reimprime o "Paste code here", ele só
            # redesenha a linha. Sem re-armar aqui, a UI ficaria travada num fluxo ainda vivo.
            self._pending_code = False
            await self._send({"type": "awaiting_code"})

    async def _watch(self) -> None:
        """Espera o fim (EOF/desfecho impresso) e dá o veredito — `status()` é a autoridade."""
        try:
            await asyncio.wait_for(self._exited.wait(), timeout=_LOGIN_TIMEOUT)
        except asyncio.TimeoutError:
            await self._send({"type": "error", "detail": "tempo esgotado no login"})
        await asyncio.sleep(0.5)   # deixa o CLI gravar ~/.claude/.credentials.json
        self._kill()
        st = status()
        await self._send({"type": "done", "ok": bool(st.get("loggedIn")), "status": st})

    # ------------------------------------------------------------------ limpeza
    def _detach(self) -> None:
        if self.fd is None or self._loop is None:
            return
        try:
            self._loop.remove_reader(self.fd)
        except Exception:
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
