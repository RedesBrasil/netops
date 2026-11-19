"""Backend `su` em PTY privado (só stdlib). Roda DENTRO do serviço netops-localadmin.

Fluxo de uma operação:
  1. fork de `/bin/su - netops-admin -c <linha>` num PTY novo, ambiente mínimo (LANG=C, PATH fixo);
  2. espera o prompt de senha; confere que o ECO do PTY está desligado (senão aborta) e envia a
     senha (vinda do cofre, só em memória). A fase de autenticação NUNCA é repassada a ninguém;
  3. a linha executada por `netops-admin` é `sudo -n -H -- /bin/bash --noprofile --norc -c PRELUDE`,
     que imprime um marcador com nonce + `id -u` (UID efetivo verificado = 0) e só então executa
     o comando com `env -i` (ambiente limpo; nada da conta operacional chega ao root) e `timeout`
     do lado root (o processo root morre no prazo mesmo que o chamador não consiga sinalizá-lo);
  4. a saída depois do marcador é a saída do comando (limitada); o exit code é o do comando.

Senha nunca vai para argv, env, arquivo, log ou saída. Uma falha de autenticação NÃO é
retentada automaticamente (evita lockout); o chamador recebe `authentication_failed`.
"""
from __future__ import annotations

import os
import pty
import re
import secrets
import select
import shlex
import signal
import termios
import time

from common import ADMIN_USER, LocalAdminError

SU = "/bin/su"
ROOT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
PROMPT_RE = re.compile(rb"(?i)(password|senha|contrase\S*a|passwort|mot de passe)[^\n:]*:\s*$")
AUTH_FAIL_RE = re.compile(rb"(?i)(authentication failure|falha de autentica|incorrect password|"
                          rb"sorry|permission denied|account.*(expired|locked)|must change|new password)")
AUTH_TIMEOUT = 20
MAX_OUTPUT = 4 * 1024 * 1024


def _child_env() -> dict:
    return {"PATH": ROOT_PATH, "LANG": "C", "LC_ALL": "C", "TERM": "dumb", "HOME": "/"}


def _command_line(nonce: str, inner: str, redirect: str = "") -> str:
    """Linha passada a `su -c` (executada por netops-admin). O marcador vai para o stderr (= PTY),
    assim o stdout pode ser redirecionado para um canal binário (modo SFTP). O redirecionamento
    é feito ANTES do sudo, que fecha os descritores >= 3."""
    prelude = (f"printf '\\036NETOPS-BEGIN-%s-%s\\n' {nonce} \"$(id -u)\" >&2; " + inner)
    return "exec sudo -n -H -- /bin/bash --noprofile --norc -c " + shlex.quote(prelude) + redirect


def build_exec(argv: list[str] | None, script: str | None, cwd: str, timeout: int) -> str:
    env = (f"env -i PATH={ROOT_PATH} HOME=/root USER=root LOGNAME=root LANG=C.UTF-8 TERM=dumb "
           f"SHELL=/bin/bash")
    if argv:
        cmd = shlex.join(argv)
    else:
        cmd = "/bin/bash --noprofile --norc -c " + shlex.quote(script or "")
    return (f"cd {shlex.quote(cwd)} || exit 125; exec timeout --kill-after=10 {int(timeout)} "
            f"{env} {cmd}")


class SuProcess:
    """Um `su` autenticado. Uso: p = SuProcess(pw, line_builder); p.authenticate(); p.stream()."""

    def __init__(self, password: str, inner: str, pass_fds: tuple = (), redirect: str = ""):
        self.nonce = secrets.token_hex(8)
        self.line = _command_line(self.nonce, inner, redirect)
        self.password = password.encode()
        self.pass_fds = pass_fds
        self.pid = None
        self.fd = None
        self.uid_verified = None

    def start(self):
        pid, fd = pty.fork()
        if pid == 0:                                  # filho
            try:
                for f in self.pass_fds:
                    os.set_inheritable(f, True)
                os.execve(SU, [SU, "-", ADMIN_USER, "-c", self.line], _child_env())
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd

    def _read(self, timeout: float) -> bytes | None:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return b""
        try:
            return os.read(self.fd, 65536)
        except OSError:
            return None

    def authenticate(self) -> bytes:
        """Envia a senha no prompt; devolve o que veio DEPOIS do marcador (início da saída)."""
        self.start()
        buf, sent, deadline = b"", False, time.monotonic() + AUTH_TIMEOUT
        marker = re.compile(rb"\x1eNETOPS-BEGIN-" + self.nonce.encode() + rb"-(\d+)\r?\n")
        while time.monotonic() < deadline:
            d = self._read(0.5)
            if d is None:
                break
            buf += d
            m = marker.search(buf)
            if m:
                self.uid_verified = int(m.group(1))
                self.password = b""
                if self.uid_verified != 0:
                    self.kill()
                    raise LocalAdminError("verification_failed")
                return buf[m.end():]
            if not sent and PROMPT_RE.search(buf):
                attrs = termios.tcgetattr(self.fd)
                if attrs[3] & termios.ECHO:          # sem garantia de eco desligado: aborta
                    self.kill()
                    raise LocalAdminError("backend_unavailable", "PTY com eco ligado na autenticação")
                os.write(self.fd, self.password + b"\n")
                self.password = b""
                sent = True
                buf = b""
                continue
            if sent and AUTH_FAIL_RE.search(buf):
                self.kill()
                raise LocalAdminError("authentication_failed")
            if len(buf) > 65536:
                break
        self.kill()
        if sent:
            raise LocalAdminError("authentication_failed")
        raise LocalAdminError("backend_unavailable", "o `su` não pediu senha como esperado (PAM/política?)")

    def stream(self, first: bytes, deadline: float, on_chunk):
        """Repassa a saída (após o marcador) até o fim; devolve (exit_code, truncated, timed_out)."""
        total, truncated = 0, False

        def emit(d):
            nonlocal total, truncated
            if not d:
                return
            if total + len(d) > MAX_OUTPUT:
                d = d[:max(0, MAX_OUTPUT - total)]
                truncated = True
            total += len(d)
            if d:
                on_chunk(d)

        emit(first)
        timed_out = False
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                self.kill()
                break
            d = self._read(0.5)
            if d is None:
                break
            emit(d)
        code = self.wait()
        return code, truncated, timed_out

    def wait(self) -> int:
        if not self.pid:
            try:
                os.close(self.fd)
            except (OSError, TypeError):
                pass
            return -1
        try:
            _, st = os.waitpid(self.pid, 0)
            return os.waitstatus_to_exitcode(st)
        except ChildProcessError:
            return -1
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass

    def kill(self):
        """Encerra o `su` (real uid = conta operacional, então ela pode sinalizá-lo); o `su`
        repassa o sinal ao filho root. O `timeout` do lado root é a garantia final."""
        if not self.pid:
            return
        for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 0)):
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                return
            t = time.monotonic() + grace
            while time.monotonic() < t:
                try:
                    if os.waitpid(self.pid, os.WNOHANG)[0]:
                        self.pid = None
                        return
                except ChildProcessError:
                    self.pid = None
                    return
                time.sleep(0.1)
