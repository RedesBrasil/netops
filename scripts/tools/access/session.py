#!/usr/bin/env python3
"""ÚNICO script de acesso CLI a equipamentos (SSH/Telnet) — substitui os antigos ssh.py/telnet.py.

Modo PADRÃO = sessão persistente por host:
  exec --host-id N   → reusa a sessão VIVA do host N (sem novo login) ou abre uma; o shell remoto
                       mantém o estado entre chamadas. Vários hosts = uma sessão por host, todas
                       abertas ao mesmo tempo. Fecha sozinha após `access.session_idle_minutes`
                       (project-config.yaml / tela Configuração; padrão 5 min) sem comando.
  close --host-id N  → encerra a sessão do host (ou close --all).
  run                → lote isolado: conecta, roda, desconecta (sem reuso). Só p/ coleta pontual.
Na sessão persistente, um processo em background segura a conexão Netmiko e atende por um Unix
socket local (dir 0700, socket 0600). A credencial é resolvida só dentro do processo — nunca sai dele.
Python: `python3` (ou `python`) do sistema — o script entra sozinho no .venv do projeto.

Uso:
    python3 scripts/tools/access/session.py exec  --host-id 21 --command "/ip/address/print"
    python3 scripts/tools/access/session.py exec  --host-id 21 --command "/ip/arp/print"   # mesma sessão
    python3 scripts/tools/access/session.py list
    python3 scripts/tools/access/session.py close --host-id 21       # ou: close --all
    python3 scripts/tools/access/session.py open  --host-id 21       # SESSION_ID (reusa; --new força outra)
    python3 scripts/tools/access/session.py exec  --session <ID> --command "..."
    python3 scripts/tools/access/session.py run   --host-id 21 --command "a" --command "b" [--telnet]

Linux (vendor linux/proxmox/...): 1 autenticação + 1 shell persistente (bash, ou sh) num canal do
transporte SSH. TODOS os comandos da sessão (ou do `run`) rodam nesse MESMO shell: `export`, `cd`,
funções, `source` e venv persistem entre comandos — e ainda há exit code real e stderr separado
(sem PTY e sem parse de prompt: o fim de cada comando é detectado por marcador aleatório).
O stdin dos comandos é /dev/null (sem PTY: nada de prompt interativo). `exit`/`set -e` que mata o
shell: a sessão sobe um shell novo no mesmo login e avisa "estado do shell reiniciado".
`open --shell` força o shell interativo do Netmiko (PTY), para o raro comando que exige terminal.
Comandos que não terminam sozinhos (ping sem count, /tool torch): use `exec --timing`;
em timeout a sessão interrompe o comando (Ctrl-C / SIGINT nos filhos) e devolve o que leu, sem cair.

Regras: só hosts do inventário; mudança de config continua exigindo baseline + rollback
(workflow apply-config-change). Toda saída vai para runs/<ts>-session-<host>/session.log.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools (familias irmas)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()
from lib.inventory import NETOPS_ROOT, load_inventory, resolve_host  # noqa: E402

DEFAULT_IDLE_MINUTES = 5                                              # padrão: 5 min sem comando -> fecha
MAX_LIFETIME = int(os.environ.get("NETOPS_SESSION_MAX", "7200"))      # s de vida máxima
OPEN_TIMEOUT = 90                                                     # s esperando o login
CLIENT_SLACK = 30                                                     # s além do --timeout


_IDLE_CACHE: dict = {"mtime": None, "value": None}


def idle_timeout() -> int:
    """Segundos sem comando até a sessão fechar.

    Fonte: core/config/project-config.yaml -> access.session_idle_minutes (tela Configuração do
    console). Relido a cada volta do laço do servidor: mudar a config vale na hora, inclusive para as
    sessões já abertas. NETOPS_SESSION_IDLE (segundos) sobrepõe, para testes/uso pontual.
    """
    env = os.environ.get("NETOPS_SESSION_IDLE")
    if env:
        return max(10, int(float(env)))
    cfg_path = NETOPS_ROOT / "core" / "config" / "project-config.yaml"
    try:
        mtime = cfg_path.stat().st_mtime
    except OSError:
        return DEFAULT_IDLE_MINUTES * 60
    if _IDLE_CACHE["mtime"] != mtime:
        minutes = DEFAULT_IDLE_MINUTES
        try:
            import yaml  # noqa: PLC0415
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            val = (cfg.get("access") or {}).get("session_idle_minutes")
            if val not in (None, ""):
                minutes = float(val)
        except Exception:  # noqa: BLE001 — config inválida não derruba sessão: usa o padrão
            minutes = DEFAULT_IDLE_MINUTES
        _IDLE_CACHE.update(mtime=mtime, value=max(10, int(minutes * 60)))
    return _IDLE_CACHE["value"]


# ----------------------------------------------------------------- diretório dos sockets
def session_dir() -> Path:
    """Diretório privado do usuário. Recusa symlink/dono errado (evita sequestro em /tmp)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = Path(base) / f"netops-sessions-{os.getuid()}"
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        sys.exit(f"ERRO: {path} não é um diretório próprio seguro — remova-o e tente de novo.")
    os.chmod(path, 0o700)
    return path


def _paths(sid: str) -> tuple[Path, Path]:
    if not sid.replace("-", "").replace("_", "").isalnum():
        sys.exit(f"ERRO: SESSION_ID inválido: {sid!r}")
    d = session_dir()
    return d / f"{sid}.sock", d / f"{sid}.json"


def _canonical(host_ref: int | str) -> dict:
    hosts_data, _ = load_inventory(include_credentials=False)
    host, _ = resolve_host(host_ref, hosts_data, {}, decrypt=False)
    return host


# ----------------------------------------------------------------- protocolo (JSON, 1 req/conexão)
def _request(sid: str, payload: dict, timeout: float) -> dict:
    sock_path, _ = _paths(sid)
    if not sock_path.exists():
        raise FileNotFoundError(f"sessão '{sid}' não existe (expirou ou foi fechada) — rode `open` de novo")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(str(sock_path))
        except (ConnectionRefusedError, FileNotFoundError):
            _cleanup(sid)
            raise FileNotFoundError(f"sessão '{sid}' morreu — rode `open` de novo") from None
        s.sendall(json.dumps(payload).encode())
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            data = s.recv(65536)
            if not data:
                break
            chunks.append(data)
    return json.loads(b"".join(chunks) or b"{}")


def _cleanup(sid: str) -> None:
    for p in _paths(sid):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ----------------------------------------------------------------- shell persistente (Linux)
class ShellDied(Exception):
    """O shell remoto terminou (exit, set -e, kill) — o transporte SSH continua autenticado."""


class PersistentShell:
    """Um único bash/sh remoto, sem PTY, num canal do transporte SSH já autenticado.

    Cada comando é enviado em base64 e executado com `eval` no próprio shell (não em subshell),
    então variáveis, `cd`, funções e `source` persistem. O fim do comando é detectado por um
    marcador aleatório (impossível de colidir com a saída) que carrega o exit code; o stderr
    recebe um marcador próprio para sincronizar os dois fluxos.
    """

    START_CMD = "if command -v bash >/dev/null 2>&1; then exec bash -l; else exec sh -l; fi"
    START_TIMEOUT = 20

    def __init__(self, transport):
        self.transport = transport
        self.mark = f"__NETOPS_{secrets.token_hex(8)}__".encode()
        self.re_out = re.compile(re.escape(self.mark) + rb"(-?\d+)\n")
        self.chan = transport.open_session()
        self.chan.exec_command(self.START_CMD)
        self.pid = None
        # Handshake: descarta o que o .profile imprimir e aprende o PID do shell (para interromper).
        # Sem base64 no host, o shell não serve (PID "0" = recusa → canal exec por comando).
        self.chan.sendall(f"if command -v base64 >/dev/null 2>&1; then __p=$$; else __p=0; fi; "
                          f"printf '%s%s\\n' '{self.mark.decode()}' \"$__p\"; unset __p; "
                          f"printf '%s\\n' '{self.mark.decode()}' >&2\n".encode())
        out, _err, rc, done = self._collect(time.time() + self.START_TIMEOUT)
        if not done or rc is None or rc <= 1:
            self.close()
            raise RuntimeError(f"shell persistente não respondeu ao handshake: {out[-200:]!r}")
        self.pid = rc

    def alive(self) -> bool:
        return not self.chan.closed and not self.chan.exit_status_ready() and self.transport.is_active()

    def _collect(self, deadline: float):
        """Lê stdout/stderr até os dois marcadores (ou o prazo, ou o shell morrer)."""
        out, err = bytearray(), bytearray()
        got_out = got_err = False
        rc = None
        err_grace = None                       # após o marcador do stdout, espera o do stderr no máx. 2 s
        while True:
            busy = False
            if self.chan.recv_ready():
                out += self.chan.recv(65536); busy = True
            if self.chan.recv_stderr_ready():
                err += self.chan.recv_stderr(65536); busy = True
            if not got_out:
                m = self.re_out.search(out)
                if m:
                    got_out, rc = True, int(m.group(1))
                    del out[m.start():]
                    err_grace = time.time() + 2
            if not got_err:
                i = err.find(self.mark + b"\n")
                if i >= 0:
                    got_err = True
                    del err[i:]
            if got_out and (got_err or time.time() > err_grace):
                return bytes(out), bytes(err), rc, True
            if (self.chan.exit_status_ready() and not self.chan.recv_ready()
                    and not self.chan.recv_stderr_ready()):
                raise ShellDied(bytes(out), bytes(err), self.chan.recv_exit_status())
            if time.time() > deadline:
                return bytes(out), bytes(err), None, False
            if not busy:
                time.sleep(0.02)

    def _signal_children(self, sig: str) -> None:
        """Manda `sig` a todos os descendentes do shell (o shell em si fica vivo), por outro canal."""
        script = ('k(){ for c in $(pgrep -P "$1" 2>/dev/null); do k "$c" "$2"; '
                  'kill -"$2" "$c" 2>/dev/null; done; }; ' f"k {self.pid} {sig}")
        try:
            side = self.transport.open_session()
            side.exec_command(script)
            side.recv_exit_status()
            side.close()
        except Exception:  # noqa: BLE001
            pass

    def run(self, cmd: str, timeout: float) -> dict:
        b64 = base64.b64encode(cmd.encode()).decode()
        m = self.mark.decode()
        wrapper = (f"eval \"$(printf '%s' '{b64}' | base64 -d)\" </dev/null; "
                   f"printf '%s%s\\n' '{m}' \"$?\"; printf '%s\\n' '{m}' >&2\n")
        self.chan.sendall(wrapper.encode())
        out, err, rc, done = self._collect(time.time() + timeout)
        if done:
            return {"status": "ok", "output": out.decode(errors="replace"),
                    "stderr": err.decode(errors="replace"), "exit": rc}
        # Prazo esgotado: Ctrl-C nos filhos; se o shell não voltar, mata o shell (estado perdido).
        self._signal_children("INT")
        more_out, more_err, rc, done = self._collect(time.time() + 3)
        if not done:
            self._signal_children("KILL")
            more_out2, more_err2, rc, done = self._collect(time.time() + 3)
            more_out, more_err = more_out + more_out2, more_err + more_err2
        res = {"status": "timeout", "output": (out + more_out).decode(errors="replace"),
               "stderr": (err + more_err).decode(errors="replace"), "exit": rc}
        if not done:                              # loop em builtin etc.: shell irrecuperável
            self._signal_children("KILL")
            try:
                side = self.transport.open_session()
                side.exec_command(f"kill -KILL {self.pid} 2>/dev/null")
                side.recv_exit_status()
                side.close()
            except Exception:  # noqa: BLE001
                pass
            self.close()
            res["shell_died"] = True
        return res

    def close(self) -> None:
        try:
            if self.pid and not self.chan.closed:
                self.chan.sendall(b"exit 0\n")
                self.chan.shutdown_write()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.chan.close()
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------- servidor (processo em background)
class Session:
    def __init__(self, sid: str, host_ref: int | str, method: str, shell: bool):
        self.sid, self.host_ref, self.method, self.force_shell = sid, host_ref, method, shell
        self.conn = None
        self.exec_mode = False
        self.shell: PersistentShell | None = None
        self.shell_fallback = False      # host não aceitou o shell persistente: canal exec por comando
        self.shell_starts = 0
        self.started = time.time()
        self.last_used = time.time()
        self.count = 0
        host = _canonical(host_ref)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        self.log_dir = NETOPS_ROOT / "runs" / f"{ts}-session-{host.get('id', host['name'])}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "session.log"

    def log(self, text: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {text}\n")

    def connect(self) -> None:
        from lib.transport import open_cli
        from lib.vendor_map import netmiko_device_type
        hosts_data, creds_data = load_inventory()
        host, cred = resolve_host(self.host_ref, hosts_data, creds_data)   # decripta só aqui
        access = host.setdefault("access", {})
        if self.method == "telnet" and access.get("method") != "telnet":
            access.pop("port", None)              # porta do cadastro é a do SSH; Telnet usa a 23
        access["method"] = self.method
        self.host = host
        self.conn = open_cli(host, cred)
        if cred.get("secret"):
            try:
                self.conn.enable()
            except Exception:  # noqa: BLE001 — nem todo device tem enable
                pass
        del cred
        dtype = netmiko_device_type(host.get("vendor"), self.method)
        self.exec_mode = (dtype == "linux" and self.method == "ssh" and not self.force_shell)
        transport = self._transport()
        if transport is not None:
            transport.set_keepalive(30)          # NAT/firewall não derruba a sessão ociosa
        self.shell = None
        self.shell_starts = 0
        self.log(f"CONECTADO host={host['name']} ip={host.get('mgmt_ip')} method={self.method} "
                 f"device_type={dtype} modo={self.mode_name()}")
        if self.exec_mode:
            self._ensure_shell()

    def mode_name(self) -> str:
        if not self.exec_mode:
            return "shell"
        return "exec-por-comando" if self.shell_fallback else "shell-persistente"

    def _ensure_shell(self) -> bool:
        """Garante o shell persistente vivo. Devolve True se precisou (re)criar um que já existia."""
        if self.shell_fallback:
            return False
        if self.shell is not None and self.shell.alive():
            return False
        restarted = self.shell_starts > 0
        if self.shell is not None:
            self.shell.close()
        try:
            self.shell = PersistentShell(self._transport())
            self.shell_starts += 1
            self.log(f"shell persistente pid={self.shell.pid}" + (" (REINICIADO: estado anterior perdido)"
                                                                   if restarted else ""))
        except Exception as exc:  # noqa: BLE001 — shell restrito/sem base64: volta ao canal por comando
            self.shell, self.shell_fallback = None, True
            self.log(f"shell persistente indisponível ({exc}) — usando canal exec por comando (sem estado)")
        return restarted

    def _transport(self):
        pre = getattr(self.conn, "remote_conn_pre", None)
        get = getattr(pre, "get_transport", None)
        return get() if get else None

    def alive(self) -> bool:
        try:
            if self.exec_mode:
                t = self._transport()
                return bool(t and t.is_active())
            if self.method == "telnet" and self.conn:
                # is_alive() do Netmiko manda IAC NOP, e o RouterOS fecha a conexão: checa o socket sem escrever
                import select
                import socket as _socket
                sock = self.conn.remote_conn.get_socket()
                if select.select([sock], [], [], 0)[0]:
                    return bool(sock.recv(1, _socket.MSG_PEEK))
                return True
            return bool(self.conn and self.conn.is_alive())
        except Exception:  # noqa: BLE001
            return False

    # -- execução
    def _run_exec(self, cmd: str, timeout: float) -> dict:
        chan = self._transport().open_session()
        chan.exec_command(cmd)
        out, err, deadline = [], [], time.time() + timeout
        while True:
            busy = False
            if chan.recv_ready():
                out.append(chan.recv(65536)); busy = True
            if chan.recv_stderr_ready():
                err.append(chan.recv_stderr(65536)); busy = True
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if time.time() > deadline:
                chan.close()
                return {"status": "timeout", "output": b"".join(out).decode(errors="replace"),
                        "stderr": b"".join(err).decode(errors="replace"), "exit": None}
            if not busy:
                time.sleep(0.05)
        rc = chan.recv_exit_status()
        chan.close()
        return {"status": "ok", "output": b"".join(out).decode(errors="replace"),
                "stderr": b"".join(err).decode(errors="replace"), "exit": rc}

    def _run_persistent(self, cmd: str, timeout: float, timing: bool) -> dict:
        try:
            res = self.shell.run(cmd, timeout)
        except ShellDied as died:
            out, err, rc = died.args
            self.log(f"shell terminou durante o comando (exit {rc}) — o próximo comando sobe um shell novo")
            self.shell = None
            return {"status": "ok", "output": out.decode(errors="replace"),
                    "stderr": err.decode(errors="replace"), "exit": rc, "shell_ended": True}
        if res.pop("shell_died", False):
            self.log("shell irrecuperável após timeout — morto; o próximo comando sobe um shell novo")
            self.shell = None
            res["shell_ended"] = True
        if timing and res["status"] == "timeout":
            res["status"] = "interrompido"     # com --timing, esgotar o prazo é o esperado
        return res

    def _run_shell(self, cmd: str, timeout: float, expect: str | None, timing: bool) -> dict:
        from netmiko.exceptions import ReadTimeout
        if timing:
            return self._run_timing(cmd, timeout)
        kw = {"read_timeout": timeout}
        if expect:
            kw["expect_string"] = expect
        try:
            out = self.conn.send_command(cmd, **kw)
            status = "ok"
        except ReadTimeout:
            # Comando não terminou / prompt mudou: interrompe, recolhe o que veio e reaprende o prompt.
            self.conn.write_channel("\x03")
            time.sleep(1.5)
            out = self.conn.read_channel()
            status = "timeout"
        try:
            self.conn.set_base_prompt()          # prompt pode ter mudado (config mode, cd, ...)
        except Exception:  # noqa: BLE001
            status = "prompt-perdido" if status == "ok" else status
        return {"status": status, "output": out, "stderr": "", "exit": None}

    def _run_timing(self, cmd: str, timeout: float) -> dict:
        """Lê por tempo: termina quando o prompt volta e o canal fica quieto 2 s; no prazo, Ctrl-C."""
        self.conn.clear_buffer()
        self.conn.write_channel(cmd + self.conn.RETURN)
        prompt = self.conn.base_prompt
        buf, deadline, last_data = "", time.time() + timeout, time.time()
        status = "interrompido"   # ≠ timeout: com --timing, esgotar o prazo é o esperado
        while time.time() < deadline:
            data = self.conn.read_channel()
            if data:
                buf += data
                last_data = time.time()
            elif time.time() - last_data > 2 and prompt in (buf.rstrip().splitlines() or [""])[-1]:
                status = "ok"
                break
            else:
                time.sleep(0.1)
        if status != "ok":
            self.conn.write_channel("\x03")         # comando contínuo: interrompe e recolhe o resto
            time.sleep(1.5)
            buf += self.conn.read_channel()
        try:
            self.conn.set_base_prompt()
        except Exception:  # noqa: BLE001
            status = "prompt-perdido"
        return {"status": status, "output": buf, "stderr": "", "exit": None}

    def run(self, cmd: str, timeout: float, expect: str | None, timing: bool) -> dict:
        reconnected = False
        if not self.alive():
            self.log("conexão caiu — reconectando antes do comando")
            try:
                self.conn.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.connect()
            reconnected = True
        state_reset = reconnected and self.count > 0 and self.exec_mode
        t0 = time.time()
        try:
            if self.exec_mode:
                if self._ensure_shell():
                    state_reset = True
                if self.shell is not None:
                    res = self._run_persistent(cmd, timeout, timing)
                else:
                    res = self._run_exec(cmd, timeout)
                    if timing and res["status"] == "timeout":
                        res["status"] = "interrompido"
            else:
                res = self._run_shell(cmd, timeout, expect, timing)
        except Exception as exc:  # noqa: BLE001
            # Não reenvia: o comando pode ter sido aplicado. Quem chama decide.
            res = {"status": "erro", "output": "", "stderr": f"{type(exc).__name__}: {exc}", "exit": None}
        res["seconds"] = round(time.time() - t0, 2)
        res["reconnected"] = reconnected
        res["state_reset"] = state_reset
        self.count += 1
        self.last_used = time.time()
        self.log(f"$ {cmd}\n--- status={res['status']} exit={res['exit']} t={res['seconds']}s\n"
                 f"{res['output']}{('[stderr] ' + res['stderr']) if res['stderr'] else ''}\n")
        return res

    def close(self) -> None:
        if self.shell is not None:
            self.shell.close()
            self.shell = None
        try:
            if self.conn:
                self.conn.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self.log(f"FECHADO após {self.count} comando(s), {int(time.time() - self.started)} s")


def serve(sid: str, host_ref: int | str, method: str, shell: bool) -> int:
    """Processo filho: conecta, avisa o pai pelo stdout (READY/ERRO) e atende o socket."""
    sock_path, meta_path = _paths(sid)
    try:
        sess = Session(sid, host_ref, method, shell)
        sess.connect()
    except BaseException as exc:  # noqa: BLE001 — inclui SystemExit (cofre trancado etc.)
        print(f"ERRO {type(exc).__name__}: {exc}", flush=True)
        return 1

    os.umask(0o077)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    os.chmod(sock_path, 0o600)
    srv.listen(4)
    meta = {"session": sid, "host": sess.host["name"], "ip": sess.host.get("mgmt_ip"),
            "vendor": sess.host.get("vendor"), "method": method,
            "mode": sess.mode_name(), "pid": os.getpid(), "host_id": sess.host.get("id", sess.host["name"]),
            "shell_forced": bool(shell),
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "log": str(sess.log_path)}
    meta_path.write_text(json.dumps(meta))

    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    print(f"READY {json.dumps(meta)}", flush=True)
    devnull = os.open(os.devnull, os.O_RDWR)                # desacopla do terminal de quem abriu
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)

    srv.settimeout(5)
    try:
        while not stop["flag"]:
            now = time.time()
            idle_limit = idle_timeout()
            if now - sess.last_used > idle_limit:
                sess.log(f"idle-timeout ({idle_limit}s sem comando)"); break
            if now - sess.started > MAX_LIFETIME:
                sess.log(f"vida máxima ({MAX_LIFETIME}s)"); break
            try:
                client, _ = srv.accept()
            except socket.timeout:
                continue
            with client:                                     # 1 cliente por vez = 1 comando por vez
                client.settimeout(30)
                raw = b""
                try:
                    while True:
                        part = client.recv(65536)
                        if not part:
                            break
                        raw += part
                    req = json.loads(raw or b"{}")
                except (OSError, ValueError):
                    continue
                op = req.get("op")
                if op == "exec":
                    resp = sess.run(req["command"], float(req.get("timeout", 60)),
                                    req.get("expect"), bool(req.get("timing")))
                elif op == "ping":
                    resp = {"status": "ok", "alive": sess.alive(), "commands": sess.count,
                            "mode": sess.mode_name(), "idle_limit": idle_timeout(),
                            "idle": int(time.time() - sess.last_used)}
                elif op == "close":
                    resp, stop["flag"] = {"status": "ok"}, True
                else:
                    resp = {"status": "erro", "stderr": f"op desconhecida: {op}"}
                try:
                    client.settimeout(30)
                    client.sendall(json.dumps(resp).encode())
                except OSError:
                    pass
    finally:
        sess.close()
        srv.close()
        _cleanup(sid)
    return 0


# ----------------------------------------------------------------- comandos do cliente
def _fmt_idle() -> str:
    sec = idle_timeout()
    return f"{sec / 60:g} min" if sec >= 60 else f"{sec} s"


def _host_key(host: dict) -> str:
    hid = str(host.get("id", host["name"]))
    return "".join(c if c.isalnum() else "_" for c in hid)


def _find_session(host: dict, method: str, shell: bool) -> str | None:
    """SESSION_ID de uma sessão VIVA para este host/método (reuso), ou None."""
    want = str(host.get("id", host["name"]))
    for meta_file in sorted(session_dir().glob(f"{_host_key(host)}-*.json")):
        sid = meta_file.stem
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, ValueError):
            continue
        if (str(meta.get("host_id", meta.get("host"))) != want or meta.get("method") != method
                or bool(meta.get("shell_forced")) != bool(shell)):
            continue
        try:
            ping = _request(sid, {"op": "ping"}, timeout=10)
        except (OSError, ValueError, FileNotFoundError):
            _cleanup(sid)
            continue
        if ping.get("status") == "ok":
            return sid
    return None


def _spawn_session(host: dict, method: str, shell: bool) -> tuple[str | None, str]:
    """Sobe o processo da sessão em background. Devolve (sid, msg) — sid None em falha."""
    sid = f"{_host_key(host)}-{secrets.token_hex(3)}"
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_serve", sid,
         (f"id:{host['name']}" if isinstance(host["name"], int) else f"name:{host['name']}"), method,
         "1" if shell else "0"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True, text=True)
    deadline = time.time() + OPEN_TIMEOUT
    line = ""
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line or proc.poll() is not None:
            break
    if line.startswith("READY "):
        meta = json.loads(line[6:])
        return sid, (f"[sessão aberta {sid}] host={meta['host']} ip={meta['ip']} modo={meta['mode']} "
                     f"fecha após {_fmt_idle()} sem comando · log={meta['log']}")
    if proc.poll() is not None or line:
        try:                                   # mensagem de erro multilinha (ex.: cofre trancado + instrução)
            line += proc.stdout.read() or ""
        except Exception:  # noqa: BLE001
            pass
    proc.kill()
    return None, line.strip() or "timeout no login"


def acquire_session(host_ref, method: str, shell: bool, force_new: bool = False) -> tuple[str | None, str]:
    """Reusa a sessão viva do host ou abre uma (1 login por host). Trava por host contra corrida."""
    import fcntl  # noqa: PLC0415
    host = _canonical(host_ref)
    lock_path = session_dir() / f"{_host_key(host)}.lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not force_new:
            sid = _find_session(host, method, shell)
            if sid:
                return sid, f"[sessão reutilizada {sid}] host={host['name']} (sem novo login)"
        if method == "telnet":
            print("AVISO: Telnet trafega em texto puro. Prefira SSH sempre que possível.", file=sys.stderr)
        return _spawn_session(host, method, shell)


def cmd_open(args) -> int:
    host_ref = args.host_id if args.host_id is not None else args.host
    try:
        host = _canonical(host_ref)
    except Exception as exc:  # noqa: BLE001
        print(f"FALHA: host '{host_ref}' fora do inventário: {exc}", file=sys.stderr)
        return 1
    if _is_local(host):
        print("FALHA: o host Local não tem sessão persistente (root é por operação). Use exec/run --host-id "
              f"{host['name']} --command '...'", file=sys.stderr)
        return 2
    sid, msg = acquire_session(host_ref, "telnet" if args.telnet else "ssh", args.shell, args.new)
    if sid:
        print(sid)
        print(msg, file=sys.stderr)
        return 0
    print(f"FALHA ao abrir sessão em '{host_ref}': {msg}", file=sys.stderr)
    return 1


def _print_result(cmd: str, res: dict, multi: bool) -> int | None:
    """Imprime a saída de um comando. Devolve 3 se a sequência deve parar, o exit code se ≠0, ou None."""
    if multi:
        print(f"### {cmd}")
    out = res.get("output", "")
    if out:
        print(out, end="" if out.endswith("\n") else "\n", flush=True)
    if res.get("stderr"):
        print(res["stderr"], file=sys.stderr, end="" if res["stderr"].endswith("\n") else "\n")
    extra = " (reconectou antes)" if res.get("reconnected") else ""
    if res.get("state_reset"):
        extra += " (AVISO: shell novo — variáveis/cd anteriores foram perdidos)"
    if res.get("shell_ended"):
        extra += " (o shell terminou; o próximo comando abre outro no mesmo login)"
    print(f"[status={res.get('status')} exit={res.get('exit')} {res.get('seconds')}s{extra}]",
          file=sys.stderr)
    if res.get("status") not in ("ok", "interrompido"):
        return 3                                      # não segue a sequência às cegas
    return res.get("exit") or None


# --------------------------------------------------------------------------- host Local (este servidor)
def _is_local(host: dict) -> bool:
    return str((host.get("access") or {}).get("method", "")).lower() == "local"


def run_local(host: dict, commands: list[str], timeout: int, multi: bool) -> int:
    """Host Local = este servidor NetOps: SEM SSH. Cada comando roda como ROOT, uma operação por vez,
    pelo serviço netops-localadmin (su autenticado com a credencial do cofre; ver
    scripts/engine/localadmin/SKILL.md). Não há shell root persistente: `cd`/`export` não passam de
    um comando para o outro — junte-os num só (`cd /x && ...`). Para rodar SEM root, use o terminal/Bash."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine" / "localadmin"))
    import client  # noqa: PLC0415
    from common import LocalAdminError  # noqa: PLC0415
    log_dir = NETOPS_ROOT / "runs" / f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-session-{host['name']}"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = log_dir / "session.log"
    rc = 0
    with open(log_path, "a", encoding="utf-8") as log:
        os.chmod(log_path, 0o600)
        log.write(f"LOCAL host={host['name']} hostname={host.get('hostname')} (root por operação, sem SSH)\n")
        for cmd in commands:
            if multi:
                print(f"### {cmd}")
            chunks = []

            def out(d, chunks=chunks):
                chunks.append(d)
                sys.stdout.buffer.write(d)
                sys.stdout.flush()
            t0 = time.time()
            try:
                end = client.run(NETOPS_ROOT, script=cmd, cwd="/root", timeout=timeout,
                                 scope=os.environ.get("NETOPS_LOCAL_SCOPE", cmd)[:500], on_output=out)
            except LocalAdminError as e:
                print(f"[local] {e.code}: {e.detail}", file=sys.stderr)
                print(f"[status=erro exit=- {time.time() - t0:.2f}s local:{e.code}]", file=sys.stderr)
                log.write(f"$ {cmd}\n[erro {e.code}]\n")
                return 3
            text = b"".join(chunks).decode(errors="replace")
            if text and not text.endswith("\n"):
                print()
            log.write(f"$ {cmd}\n{text}\n[exit={end['exit_code']} uid={end['effective_uid']} op={end['operation_id']}]\n")
            status = "timeout" if end.get("timeout") else "ok"
            print(f"[status={status} exit={end['exit_code']} {end.get('duration_s')}s local uid=0 "
                  f"op={end['operation_id']}{' saída truncada' if end.get('truncated') else ''}]", file=sys.stderr)
            if end.get("timeout"):
                return 3
            if end["exit_code"]:
                rc = end["exit_code"]
    print(f"[log] {log_path}", file=sys.stderr)
    return rc


def cmd_exec(args) -> int:
    """Roda comando(s) numa sessão. Com --host-id/--host: reusa a sessão viva do host ou abre uma."""
    sid = args.session
    if sid is None:
        host_ref = args.host_id if args.host_id is not None else args.host
        try:
            host = _canonical(host_ref)
        except Exception as exc:  # noqa: BLE001
            print(f"FALHA: host '{host_ref}' fora do inventário: {exc}", file=sys.stderr)
            return 1
        if _is_local(host):
            if args.telnet or args.shell:
                print("FALHA: o host Local não usa SSH/Telnet nem shell interativo", file=sys.stderr)
                return 2
            return run_local(host, list(args.command), args.timeout, len(args.command) > 1)
        sid, msg = acquire_session(host_ref, "telnet" if args.telnet else "ssh", args.shell)
        if not sid:
            print(f"FALHA ao abrir sessão em '{host_ref}': {msg}", file=sys.stderr)
            return 1
        print(msg, file=sys.stderr)
    rc = 0
    for cmd in args.command:
        try:
            res = _request(sid, {"op": "exec", "command": cmd, "timeout": args.timeout,
                                 "expect": args.expect, "timing": args.timing},
                           timeout=args.timeout + CLIENT_SLACK)
        except (FileNotFoundError, OSError, ValueError) as exc:
            print(f"FALHA: {exc}", file=sys.stderr)
            return 4
        code = _print_result(cmd, res, len(args.command) > 1)
        if code == 3:
            return 3
        if code:
            rc = code
    return rc


def cmd_run(args) -> int:
    """Lote numa chamada só: conecta, roda os comandos em ordem e desconecta (sem processo em background).

    Substitui os antigos ssh.py/telnet.py. Mesmo comportamento do exec (modo exec no Linux, Ctrl-C em
    timeout, para no primeiro que falha) e mesmo log em runs/<ts>-session-<id>/session.log.
    """
    host_ref = args.host_id if args.host_id is not None else args.host
    commands = list(args.command or [])
    if args.commands_file:
        commands += [ln.strip() for ln in Path(args.commands_file).read_text().splitlines() if ln.strip()]
    if not commands:
        print("FALHA: informe ao menos um --command ou --commands-file", file=sys.stderr)
        return 2
    try:
        host = _canonical(host_ref)
    except Exception as exc:  # noqa: BLE001
        print(f"FALHA: host '{host_ref}' fora do inventário: {exc}", file=sys.stderr)
        return 1
    if _is_local(host):
        if args.telnet or args.shell:
            print("FALHA: o host Local não usa SSH/Telnet nem shell interativo", file=sys.stderr)
            return 2
        return run_local(host, commands, args.timeout, len(commands) > 1)
    method = "telnet" if args.telnet else "ssh"
    if method == "telnet":
        print("AVISO: Telnet trafega em texto puro. Prefira SSH sempre que possível.", file=sys.stderr)
    try:
        sess = Session(f"run-{secrets.token_hex(3)}", host_ref, method, args.shell)
        sess.connect()
    except BaseException as exc:  # noqa: BLE001 — inclui SystemExit (cofre trancado etc.)
        print(f"FALHA ao conectar em '{host.get('hostname') or host['name']}': {exc}", file=sys.stderr)
        return 1
    rc = 0
    try:
        for cmd in commands:
            code = _print_result(cmd, sess.run(cmd, args.timeout, args.expect, args.timing), len(commands) > 1)
            if code == 3:
                rc = 3
                break
            if code:
                rc = code
    finally:
        sess.close()
        print(f"[log] {sess.log_path}", file=sys.stderr)
    return rc


def cmd_list(_args) -> int:
    found = False
    for meta_file in sorted(session_dir().glob("*.json")):
        sid = meta_file.stem
        try:
            meta = json.loads(meta_file.read_text())
            ping = _request(sid, {"op": "ping"}, timeout=10)
        except (OSError, ValueError, FileNotFoundError):
            _cleanup(sid)
            continue
        found = True
        print(f"{sid}  host={meta['host']} ip={meta['ip']} modo={meta['mode']} "
              f"cmds={ping.get('commands')} ocioso={ping.get('idle')}s/{ping.get('idle_limit')}s vivo={ping.get('alive')}")
    if not found:
        print("(nenhuma sessão aberta)")
    return 0


def cmd_close(args) -> int:
    if args.all:
        sids = [p.stem for p in session_dir().glob("*.json")]
    elif args.session:
        sids = [args.session]
    else:
        host_ref = args.host_id if args.host_id is not None else args.host
        try:
            host = _canonical(host_ref)
        except Exception as exc:  # noqa: BLE001
            print(f"FALHA: host '{host_ref}' fora do inventário: {exc}", file=sys.stderr)
            return 1
        sids = [p.stem for p in session_dir().glob(f"{_host_key(host)}-*.json")]
        if not sids:
            print(f"(nenhuma sessão aberta para o host {host['name']})")
    for sid in sids:
        try:
            _request(sid, {"op": "close"}, timeout=30)
            print(f"[fechada] {sid}")
        except (OSError, ValueError, FileNotFoundError) as exc:
            _cleanup(sid)
            print(f"[{sid}] {exc}", file=sys.stderr)
    return 0


def main() -> int:
    if len(sys.argv) >= 6 and sys.argv[1] == "_serve":       # uso interno (processo filho)
        kind, _, ref = sys.argv[3].partition(":")          # preserva o tipo: ID inteiro x nome
        return serve(sys.argv[2], int(ref) if kind == "id" else ref, sys.argv[4], sys.argv[5] == "1")

    parser = argparse.ArgumentParser(description="Acesso a equipamentos do inventário (SSH/Telnet): "
                                                 "run = lote numa chamada; open/exec/close = sessão persistente.")
    sub = parser.add_subparsers(dest="action", required=True)

    p_run = sub.add_parser("run", help="Conecta, roda o(s) comando(s) e desconecta — numa chamada só")
    rsel = p_run.add_mutually_exclusive_group(required=True)
    rsel.add_argument("--host-id", type=int, help="ID inteiro do host no inventário")
    rsel.add_argument("--host", help="Nome único ou alias legado do host")
    p_run.add_argument("--command", action="append", help="Comando (pode repetir)")
    p_run.add_argument("--commands-file", help="Arquivo com um comando por linha")
    p_run.add_argument("--telnet", action="store_true", help="Usa Telnet (legado) em vez de SSH")
    p_run.add_argument("--shell", action="store_true",
                       help="Linux: shell interativo do Netmiko com PTY (só p/ comando que exige terminal; sem exit code)")
    p_run.add_argument("--timeout", type=float, default=60, help="Segundos por comando (padrão 60)")
    p_run.add_argument("--expect", help="Regex do prompt esperado (shell), se ele mudar")
    p_run.add_argument("--timing", action="store_true",
                       help="Shell: lê por tempo (comando contínuo/paginado: ping, torch)")

    p_open = sub.add_parser("open", help="Reusa a sessão viva do host ou abre uma (imprime o SESSION_ID)")
    sel = p_open.add_mutually_exclusive_group(required=True)
    sel.add_argument("--host-id", type=int, help="ID inteiro do host no inventário")
    sel.add_argument("--host", help="Nome único ou alias legado do host")
    p_open.add_argument("--telnet", action="store_true", help="Usa Telnet (legado) em vez de SSH")
    p_open.add_argument("--shell", action="store_true",
                        help="Linux: shell interativo do Netmiko com PTY (só p/ comando que exige terminal; sem exit code)")
    p_open.add_argument("--new", action="store_true", help="Abre outra sessão mesmo havendo uma viva")

    p_exec = sub.add_parser("exec", help="Roda comando(s) na sessão do host (reusa ou abre) — MODO PADRÃO")
    esel = p_exec.add_mutually_exclusive_group(required=True)
    esel.add_argument("--host-id", type=int, help="ID do host: reusa a sessão viva dele ou abre uma")
    esel.add_argument("--host", help="Nome único ou alias legado do host (idem)")
    esel.add_argument("--session", help="SESSION_ID explícito (de `open`)")
    p_exec.add_argument("--telnet", action="store_true", help="Com --host-id: sessão Telnet (legado)")
    p_exec.add_argument("--shell", action="store_true", help="Com --host-id: shell Netmiko com PTY")
    p_exec.add_argument("--command", action="append", required=True, help="Comando (pode repetir)")
    p_exec.add_argument("--timeout", type=float, default=60, help="Segundos por comando (padrão 60)")
    p_exec.add_argument("--expect", help="Regex do prompt esperado (shell), se ele mudar")
    p_exec.add_argument("--timing", action="store_true",
                        help="Shell: lê por tempo (comando contínuo/paginado: ping, torch)")

    sub.add_parser("list", help="Lista as sessões abertas")
    p_close = sub.add_parser("close", help="Fecha sessão(ões)")
    g = p_close.add_mutually_exclusive_group(required=True)
    g.add_argument("--session")
    g.add_argument("--host-id", type=int, help="Fecha a(s) sessão(ões) deste host")
    g.add_argument("--host", help="Idem, por nome/alias")
    g.add_argument("--all", action="store_true")

    args = parser.parse_args()
    return {"run": cmd_run, "open": cmd_open, "exec": cmd_exec, "list": cmd_list,
            "close": cmd_close}[args.action](args)


if __name__ == "__main__":
    raise SystemExit(main())
