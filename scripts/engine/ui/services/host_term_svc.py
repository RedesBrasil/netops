#!/usr/bin/env python3
"""Terminal web para HOSTS do inventário — SSH (asyncssh) e Telnet (telnetlib3).

Ponte navegador (xterm.js) <-> equipamento, rodando no loop do uvicorn (sem thread por sessão).

Segurança:
  - Só conecta em host de network/hosts.yaml, e só por um método de acesso CADASTRADO nele
    (access principal + extra_access); o cliente manda ID + método (+ porta), nunca IP livre.
  - A credencial é resolvida AQUI, no servidor (cofre destrancado); senha/secret NUNCA vão ao
    navegador. Sem credencial ou cofre trancado -> o terminal pede usuário/senha (não grava).
  - Log de auditoria (quem/qual host/método/quando/duração) em runs/<ts>-terminal-<id>/session.log.
    As teclas NÃO são gravadas (senhas digitadas iriam junto).

Protocolo de quadros (igual ao /api/term):
  cliente -> servidor: BINÁRIO = teclas; TEXTO JSON {"resize":[cols,rows]}
  servidor -> cliente: BINÁRIO = saída do terminal; TEXTO JSON {"status": "...", ...}
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import deps

TERMINAL_METHODS = ("ssh", "telnet")
DEFAULT_PORTS = {"ssh": 22, "telnet": 23}
TERM_TYPE = "xterm-256color"
CONNECT_TIMEOUT = 20
MAX_AUTH_ATTEMPTS = 3
AUTOLOGIN_WINDOW = 30          # seg em que o Telnet procura os prompts de login/senha
MAX_DIM = 1000

_ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-Za-z]|\x1b[=>]")
_LOGIN_PROMPT = re.compile(r"(login|username|user name|user)\s*:\s*$", re.I)
_PASS_PROMPT = re.compile(r"pass(word|code)?\s*:\s*$", re.I)


class Closed(Exception):
    """O navegador fechou a janela (ou Ctrl-C/Ctrl-D num prompt local)."""


class TargetError(Exception):
    """Host/método inválido para o terminal (vira mensagem + close 4404)."""


# --------------------------------------------------------------------------- #
# Inventário: métodos de acesso de terminal e credencial
# --------------------------------------------------------------------------- #
def access_entries(host: dict) -> list[dict]:
    """Métodos de terminal do host resolvido, em ordem de prioridade: [{method, port, credential}].

    Principal (access + credential) primeiro, depois extra_access. Só ssh/telnet; sem duplicata
    (método+porta). extra_access sem credential herda a credencial do host."""
    principal = host.get("access") or {}
    items = [{"method": principal.get("method") or "ssh", "port": principal.get("port"),
              "credential": host.get("credential")}]
    for extra in host.get("extra_access") or []:
        if isinstance(extra, dict):
            items.append({"method": extra.get("method"), "port": extra.get("port"),
                          "credential": extra.get("credential") or host.get("credential")})
    out, seen = [], set()
    for item in items:
        method = str(item["method"] or "").lower()
        if method not in TERMINAL_METHODS:
            continue
        try:
            port = int(item["port"] or DEFAULT_PORTS[method])
        except (TypeError, ValueError):
            port = DEFAULT_PORTS[method]
        if (method, port) in seen:
            continue
        seen.add((method, port))
        out.append({"method": method, "port": port, "credential": item["credential"]})
    return out


def pick_entry(entries: list[dict], method: str | None, port: int | None) -> dict:
    method = (method or "").lower() or None
    for entry in entries:
        if (method is None or entry["method"] == method) and (port is None or entry["port"] == port):
            return entry
    raise TargetError(f"método {method or '?'}{':' + str(port) if port else ''} não está cadastrado neste host")


def _host_ref(host_id: str):
    return int(host_id) if str(host_id).isdigit() else host_id


def resolve_target(host_id: str, method: str | None, port: int | None) -> tuple[dict, dict, dict, str]:
    """(host, entry, cred, aviso). cred pode vir vazio/parcial (sem credencial ou cofre trancado)."""
    from lib.inventory import lookup_ci, resolve_host, resolve_secret
    from services.credentials_svc import load_creds
    from services.inventory_svc import load_hosts
    hosts_data, _ = load_hosts()          # caminhos do console (deps.*: respeita DATA_ROOT/testes)
    creds_data, _ = load_creds()
    try:
        host, _ = resolve_host(_host_ref(host_id), hosts_data, {}, decrypt=False)
    except Exception as exc:  # noqa: BLE001 — id inexistente/ambíguo
        raise TargetError(f"host '{host_id}' não está no inventário") from exc
    if not host.get("mgmt_ip"):
        raise TargetError("host sem IP de gerência (mgmt_ip)")
    entry = pick_entry(access_entries(host), method, port)

    cred, note = {}, ""
    name = entry.get("credential")
    raw = (lookup_ci(creds_data.get("credentials") or {}, name) or {}) if name else {}
    if not raw:
        note = "host sem credencial cadastrada" if not name else f"credencial '{name}' não encontrada"
    for key in ("username", "password", "secret", "key_file"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            continue
        try:
            cred[key] = resolve_secret(value)     # decripta só aqui, em memória
        except Exception:  # noqa: BLE001 — VaultLocked/VaultError: pede no terminal
            note = "cofre trancado — informe a senha manualmente"
    return host, entry, cred, note


# --------------------------------------------------------------------------- #
# WebSocket: fila única de eventos (teclas/resize/close) para prompts e ponte
# --------------------------------------------------------------------------- #
class WsIO:
    def __init__(self, ws, cols: int, rows: int):
        self.ws = ws
        self.cols, self.rows = cols, rows
        self.queue: asyncio.Queue = asyncio.Queue()
        self.on_resize = None
        self._task = asyncio.create_task(self._pump())

    async def _pump(self):
        from fastapi import WebSocketDisconnect
        try:
            while True:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    self.queue.put_nowait(msg["bytes"])
                    continue
                text = msg.get("text")
                if not text:
                    continue
                try:
                    ctrl = json.loads(text)
                except ValueError:
                    self.queue.put_nowait(text.encode("utf-8"))
                    continue
                size = ctrl.get("resize") if isinstance(ctrl, dict) else None
                if isinstance(size, list) and len(size) == 2:
                    try:
                        self.cols = max(1, min(MAX_DIM, int(size[0])))
                        self.rows = max(1, min(MAX_DIM, int(size[1])))
                    except (TypeError, ValueError):
                        continue
                    if self.on_resize:
                        try:
                            self.on_resize(self.cols, self.rows)
                        except Exception:  # noqa: BLE001
                            pass
        except (WebSocketDisconnect, RuntimeError):
            pass
        self.queue.put_nowait(None)

    async def read(self) -> bytes:
        data = await self.queue.get()
        if data is None:
            self.queue.put_nowait(None)   # mantém o "fechado" para quem ler depois
            raise Closed()
        return data

    async def write(self, data: bytes | str) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        await self.ws.send_bytes(data)

    async def status(self, status: str, **extra) -> None:
        await self.ws.send_text(json.dumps({"status": status, **extra}))

    async def info(self, text: str, color: str = "36") -> None:
        await self.write(f"\x1b[{color}m{text}\x1b[0m\r\n")

    async def prompt(self, label: str, echo: bool) -> str:
        """Lê uma linha digitada no xterm (edição mínima: backspace; Ctrl-C/D cancela)."""
        await self.write(label)
        buf = bytearray()
        while True:
            data = await self.read()
            for byte in data:
                if byte in (13, 10):
                    await self.write("\r\n")
                    return buf.decode("utf-8", "replace")
                if byte in (3, 4):
                    await self.write("^C\r\n")
                    raise Closed()
                if byte in (8, 127):
                    if buf:
                        buf.pop()
                        if echo:
                            await self.write("\b \b")
                elif byte == 27:
                    break                     # sequência de escape (setas etc.): ignora o resto
                elif byte >= 32:
                    buf.append(byte)
                    if echo:
                        await self.write(bytes([byte]))

    def close(self):
        self._task.cancel()


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #
class AuditLog:
    def __init__(self, host: dict, entry: dict, client: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        self.dir = Path(deps.NETOPS_ROOT) / "runs" / f"{ts}-terminal-{host.get('id', host.get('name'))}"
        self.started = time.time()
        self.prefix = f"host={host.get('id', host.get('name'))} ({host.get('hostname', '')}) " \
                      f"ip={host.get('mgmt_ip')} {entry['method']}:{entry['port']} cliente={client}"

    def write(self, text: str) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with (self.dir / "session.log").open("a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] {text} | {self.prefix}\n")
        except OSError:
            pass

    def duration(self) -> str:
        return f"{int(time.time() - self.started)}s"


# --------------------------------------------------------------------------- #
# SSH (asyncssh)
# --------------------------------------------------------------------------- #
def _ssh_algs() -> dict:
    """Padrão moderno primeiro + legados no fim (equipamento antigo: group1/group14-sha1, cbc, ssh-rsa/dss)."""
    from asyncssh.encryption import get_default_encryption_algs, get_encryption_algs
    from asyncssh.kex import get_default_kex_algs, get_kex_algs
    from asyncssh.mac import get_default_mac_algs, get_mac_algs
    from asyncssh.public_key import get_default_public_key_algs, get_public_key_algs

    def merge(default, every):
        default = list(default)
        algs = default + [a for a in every if a not in default and not a.startswith(b"gss-")]
        return [a.decode("ascii") for a in algs]

    return {
        "kex_algs": merge(get_default_kex_algs(), get_kex_algs()),
        "encryption_algs": merge(get_default_encryption_algs(), get_encryption_algs()),
        "mac_algs": merge(get_default_mac_algs(), get_mac_algs()),
        "server_host_key_algs": merge(get_default_public_key_algs(), get_public_key_algs()),
    }


async def run_ssh(io: WsIO, host: dict, entry: dict, cred: dict, audit: AuditLog) -> None:
    import asyncssh

    ip, port = host["mgmt_ip"], entry["port"]
    user = cred.get("username") or ""
    password = cred.get("password")
    key_file = cred.get("key_file")
    auto = bool(user and (password or key_file))
    conn = None
    for attempt in range(1, MAX_AUTH_ATTEMPTS + 1):
        if not user:
            user = (await io.prompt("login as: ", echo=True)).strip()
            if not user:
                continue
        if password is None and not key_file:
            password = await io.prompt(f"{user}@{ip}'s password: ", echo=False)
        await io.info(f"Conectando em {user}@{ip}:{port} (SSH){' — autenticação automática' if auto else ''}…")
        try:
            conn = await asyncssh.connect(
                ip, port, username=user, password=password or None,
                client_keys=[key_file] if key_file else (), agent_path=None, config=(),
                known_hosts=None, keepalive_interval=30, connect_timeout=CONNECT_TIMEOUT,
                **_ssh_algs())
            break
        except asyncssh.PermissionDenied:
            audit.write(f"AUTH FALHOU tentativa={attempt} usuario={user} auto={auto}")
            await io.info("Acesso negado (usuário/senha)." + (" Informe as credenciais." if auto else ""), "31")
            if auto:
                user = ""       # credencial cadastrada falhou: pede tudo de novo
            password, key_file, auto = None, None, False
        except (OSError, asyncio.TimeoutError, asyncssh.Error) as exc:
            audit.write(f"ERRO conexão: {type(exc).__name__}: {exc}")
            await io.info(f"Falha ao conectar: {exc or type(exc).__name__}", "31")
            await io.status("erro")
            return
    del password
    if conn is None:
        await io.info("Muitas tentativas — encerrado.", "31")
        await io.status("erro")
        return

    async with conn:
        proc = await conn.create_process(term_type=TERM_TYPE, term_size=(io.cols, io.rows),
                                         encoding=None, stderr=asyncssh.STDOUT)
        fp = ""
        try:
            key = conn.get_server_host_key()
            fp = key.get_fingerprint() if key else ""
        except Exception:  # noqa: BLE001
            pass
        audit.write(f"CONECTADO usuario={user} hostkey={fp}")
        await io.status("conectado", user=user)
        io.on_resize = lambda c, r: proc.change_terminal_size(c, r)

        async def pump_out():
            while True:
                data = await proc.stdout.read(65536)
                if not data:
                    return
                await io.write(data)

        async def pump_in():
            while True:
                proc.stdin.write(await io.read())

        await _bridge(pump_out(), pump_in())
        proc.close()


# --------------------------------------------------------------------------- #
# Telnet (telnetlib3)
# --------------------------------------------------------------------------- #
async def run_telnet(io: WsIO, host: dict, entry: dict, cred: dict, audit: AuditLog) -> None:
    import telnetlib3
    from telnetlib3.telopt import NAWS

    ip, port = host["mgmt_ip"], entry["port"]
    user, password = cred.get("username") or "", cred.get("password")
    auto = bool(user and password)
    await io.info(f"Conectando em {ip}:{port} (Telnet){' — login automático' if auto else ''}…")
    try:
        reader, writer = await asyncio.wait_for(telnetlib3.open_connection(
            ip, port, encoding=False, term=TERM_TYPE, cols=io.cols, rows=io.rows,
            connect_minwait=0.05, connect_maxwait=1.0), CONNECT_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        audit.write(f"ERRO conexão: {type(exc).__name__}: {exc}")
        await io.info(f"Falha ao conectar: {exc or type(exc).__name__}", "31")
        await io.status("erro")
        return
    audit.write(f"CONECTADO usuario={user or '(manual)'} auto={auto}")
    await io.status("conectado", user=user)

    def resize(cols, rows):
        proto = getattr(writer, "_protocol", None)
        if proto is not None and hasattr(proto, "_extra"):
            proto._extra["cols"], proto._extra["rows"] = cols, rows
        if writer.local_option.enabled(NAWS):
            writer._send_naws()
    io.on_resize = resize

    def send_line(text: str):
        writer.write(text.encode("utf-8") + b"\r\n")

    state = {"user": not auto, "pass": not auto, "tail": "", "until": time.time() + AUTOLOGIN_WINDOW}

    def autologin(data: bytes):
        if state["pass"] or time.time() > state["until"]:
            return
        tail = (state["tail"] + _ANSI.sub(b"", data).decode("utf-8", "replace"))[-200:]
        state["tail"] = tail
        line = tail.rstrip(" \x00").splitlines()[-1] if tail.strip() else ""
        if not state["user"] and _LOGIN_PROMPT.search(line):
            send_line(user)
            state["user"], state["tail"] = True, ""
        elif _PASS_PROMPT.search(line):
            send_line(password)
            state["user"] = state["pass"] = True
            state["tail"] = ""

    async def pump_out():
        while True:
            data = await reader.read(65536)
            if not data:
                return
            await io.write(data)
            autologin(data)

    async def pump_in():
        while True:
            data = await io.read()
            state["until"] = 0 if state["user"] else state["until"]   # digitou após o login: para o automático
            if not writer.outbinary:
                # NVT: Enter = CR LF (RouterOS exige; Cisco/Linux aceitam). xterm manda só CR.
                data = re.sub(rb"\r(?!\n)", b"\r\n", data)
            writer.write(data)

    try:
        await _bridge(pump_out(), pump_in())
    finally:
        writer.close()


# --------------------------------------------------------------------------- #
async def _bridge(out_coro, in_coro) -> None:
    t_out, t_in = asyncio.create_task(out_coro), asyncio.create_task(in_coro)
    done, pending = await asyncio.wait({t_out, t_in}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc and not isinstance(exc, Closed):
            raise exc


async def serve(ws, host_id: str, method: str | None, port: int | None, cols: int, rows: int) -> None:
    """Sessão completa: resolve o alvo, autentica (auto ou manual), faz a ponte e audita."""
    io = WsIO(ws, cols, rows)
    audit = None
    try:
        try:
            host, entry, cred, note = await asyncio.to_thread(resolve_target, host_id, method, port)
        except TargetError as exc:
            await io.info(f"[netops] {exc}", "31")
            await io.status("erro", error=str(exc))
            return
        client = getattr(ws.client, "host", "?") if ws.client else "?"
        audit = AuditLog(host, entry, client)
        audit.write("ABERTO")
        await io.status("conectando", host=host.get("hostname") or str(host.get("id")),
                        ip=host["mgmt_ip"], method=entry["method"], port=entry["port"])
        if note:
            await io.info(f"[netops] {note}", "33")
        runner = run_ssh if entry["method"] == "ssh" else run_telnet
        try:
            await runner(io, host, entry, cred, audit)
        finally:
            cred.clear()
        await io.status("desconectado")
    except Closed:
        pass
    except Exception as exc:  # noqa: BLE001 — erro inesperado: mostra no terminal em vez de cair calado
        if audit:
            audit.write(f"ERRO {type(exc).__name__}: {exc}")
        try:
            await io.info(f"[netops] erro: {exc or type(exc).__name__}", "31")
            await io.status("erro")
        except Exception:  # noqa: BLE001
            pass
    finally:
        if audit:
            audit.write(f"FECHADO duração={audit.duration()}")
        io.close()
