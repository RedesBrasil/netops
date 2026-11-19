#!/usr/bin/env python3
"""Serviço da administração Local (netops-localadmin@<slug>.service). Ver SKILL.md desta pasta.

Escuta num socket UNIX 0600 em $XDG_RUNTIME_DIR/netops/ e atende pedidos JSON (uma linha):
  {"op": "status"}
  {"op": "exec", "user": "<usuário do console>", "operation_id": "...", "argv": [...] | "script": "...",
   "cwd": "/root", "timeout": 600, "scope": "texto livre do pedido"}
  {"op": "sftp", "user": "...", "client": "console"}  -> devolve, por SCM_RIGHTS, um socket ligado a
                                                          um `sftp-server` rodando como root
Respostas: linhas JSON {"type": "out", "data": "<base64>"} ... {"type": "end", ...} ou {"type": "error"}.

Por que um serviço separado: a senha de `netops-admin` só existe na memória DESTE processo, que
não é descendente da IA nem do console (ptrace_scope=1 impede que processos da IA a inspecionem).
Limite documentado: com o cofre destrancado, outro processo da MESMA conta pode usar o cofre;
o mesmo UID não é fronteira forte (plano §4.3).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pwd
import socket
import struct
import sys
import syslog
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import common  # noqa: E402
from common import CREDENTIAL, LocalAdminError  # noqa: E402
from lib import runtime_identity as rid  # noqa: E402
import su_backend  # noqa: E402

MAX_CONCURRENT = 2
MAX_TIMEOUT = 3 * 3600
DEFAULT_TIMEOUT = 900
AUTH_COOLDOWN = 120          # após falha de autenticação, nada de nova tentativa por 2 min
SFTP_CANDIDATES = ("/usr/lib/openssh/sftp-server", "/usr/libexec/openssh/sftp-server",
                   "/usr/lib/ssh/sftp-server", "/usr/libexec/sftp-server", "/usr/lib/misc/sftp-server")


class State:
    def __init__(self, root: Path):
        self.root = root
        self.sem = threading.BoundedSemaphore(MAX_CONCURRENT)
        self.last_auth_fail = 0.0
        self.audit_path = root / "runs" / "localadmin" / "audit.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(st: State, event: dict) -> None:
    """Auditoria interna (JSONL 0600) + journal/syslog (evidência fora da árvore da aplicação)."""
    event = {"ts": _now(), **event}
    try:
        st.audit_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(st.audit_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass
    try:
        syslog.openlog("netops-localadmin", syslog.LOG_PID, syslog.LOG_AUTHPRIV)
        brief = {k: event.get(k) for k in ("op", "operation_id", "user", "result", "exit_code", "uid")}
        syslog.syslog(syslog.LOG_NOTICE, json.dumps(brief, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- estado / pré-condições
def _inventory():
    from lib import inventory  # noqa: PLC0415  (venv: yaml)
    return inventory


def preconditions(st: State, need_password: bool = True) -> dict:
    """Os 4 estados do plano §6.6 (capacidade, identidade, cofre) + o host Local."""
    info = {"capability": False, "binding": False, "vault": "locked", "credential": False, "host": None}
    try:
        policy = common.load_policy(st.root)
    except (LocalAdminError, rid.IdentityError) as e:
        raise LocalAdminError("binding_mismatch", str(e))
    if not policy or policy.get("ENABLED", "1") != "1":
        raise LocalAdminError("local_access_disabled")
    info["capability"] = True
    problem = common.binding_problem(policy)
    if problem:
        raise LocalAdminError("binding_mismatch", f"{common.ERRORS['binding_mismatch']} ({problem})")
    inv = _inventory()
    hosts, creds = inv.load_inventory()
    try:
        host, cred = inv.resolve_host(int(policy["HOST_ID"]), hosts, creds, decrypt=False)
    except Exception:  # noqa: BLE001
        raise LocalAdminError("binding_mismatch", "host Local do inventário não encontrado")
    if not common.is_local_host(host) or (host.get("credential") or "").lower() != CREDENTIAL.lower():
        raise LocalAdminError("binding_mismatch", "o host Local do inventário não aponta para a credencial do admin local")
    if (host.get("local_instance") or "") != rid.instance_id(st.root):
        raise LocalAdminError("binding_mismatch", "host Local vinculado a outra instalação")
    info["binding"] = True
    info["host"] = {"id": host.get("id"), "hostname": host.get("hostname")}
    if not cred.get("password"):
        raise LocalAdminError("credential_missing")
    info["credential"] = True
    from lib import vault, vault_session  # noqa: PLC0415
    try:
        vault_session.get_session_key()
        info["vault"] = "unlocked"
    except vault.VaultError:
        if need_password:
            raise LocalAdminError("vault_locked")
        return info
    if need_password:
        try:
            info["_password"] = inv.resolve_secret(cred["password"])
        except vault.VaultError:
            raise LocalAdminError("vault_locked")
        if cred.get("username") and cred["username"] != policy.get("ADMIN_USER", common.ADMIN_USER):
            raise LocalAdminError("binding_mismatch", "credencial do admin local com usuário inesperado")
    return info


def authorize(st: State, user: str) -> str:
    """`server.admin` do usuário do console. Sem usuários cadastrados = administrador local."""
    from lib import accessdb  # noqa: PLC0415
    db = st.root / "runs" / "netops.db"
    if not db.exists() or not accessdb.has_users(db):
        return user or "admin-local"
    if not user:
        raise LocalAdminError("authorization_denied", "pedido sem usuário do console (NETOPS_USER)")
    eff = accessdb.effective(db, user)
    if not eff or "server.admin" not in eff["permissions"]:
        raise LocalAdminError("authorization_denied")
    return eff["username"]


def _cooldown(st: State):
    if time.monotonic() - st.last_auth_fail < AUTH_COOLDOWN and st.last_auth_fail:
        raise LocalAdminError("authentication_cooldown")


# --------------------------------------------------------------------------- operações
def op_status(st: State, req: dict, conn) -> None:
    try:
        info = preconditions(st, need_password=False)
        info.pop("_password", None)
        ready = info["vault"] == "unlocked"
        _send(conn, {"type": "end", "ok": True, "ready": ready, **info,
                     "detail": "" if ready else common.ERRORS["vault_locked"]})
    except LocalAdminError as e:
        _send(conn, {"type": "end", "ok": True, "ready": False, "code": e.code, "detail": e.detail})


def _validate_exec(req: dict) -> tuple[list | None, str | None, str, int]:
    argv, script = req.get("argv"), req.get("script")
    if bool(argv) == bool(script):
        raise LocalAdminError("bad_request", "informe argv OU script")
    if argv is not None and (not isinstance(argv, list) or not all(isinstance(a, str) and "\x00" not in a for a in argv)):
        raise LocalAdminError("bad_request", "argv precisa ser lista de strings")
    if script is not None and (not isinstance(script, str) or "\x00" in script or len(script) > 256 * 1024):
        raise LocalAdminError("bad_request", "script inválido")
    cwd = req.get("cwd") or "/root"
    if not isinstance(cwd, str) or not cwd.startswith("/") or "\x00" in cwd or "\n" in cwd:
        raise LocalAdminError("bad_request", "cwd precisa ser caminho absoluto")
    try:
        timeout = int(req.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        raise LocalAdminError("bad_request", "timeout inválido")
    return argv, script, cwd, max(5, min(MAX_TIMEOUT, timeout))


def op_exec(st: State, req: dict, conn) -> None:
    op_id = str(req.get("operation_id") or uuid.uuid4())
    argv, script, cwd, timeout = _validate_exec(req)
    user = authorize(st, str(req.get("user") or ""))
    base = {"op": "exec", "operation_id": op_id, "user": user, "cwd": cwd, "timeout": timeout,
            "scope": str(req.get("scope") or "")[:500],
            "command": (" ".join(argv) if argv else f"<script {len(script)} bytes>")[:1000]}
    if not st.sem.acquire(blocking=False):
        raise LocalAdminError("busy")
    t0 = time.time()
    try:
        _cooldown(st)
        info = preconditions(st)
        password = info.pop("_password")
        audit(st, {**base, "result": "started", "host": info["host"]})
        proc = su_backend.SuProcess(password, su_backend.build_exec(argv, script, cwd, timeout))
        del password
        try:
            first = proc.authenticate()
        except LocalAdminError as e:
            if e.code == "authentication_failed":
                st.last_auth_fail = time.monotonic()
            raise
        _send(conn, {"type": "start", "operation_id": op_id, "effective_uid": proc.uid_verified})
        code, truncated, timed_out = proc.stream(
            first, time.monotonic() + timeout + 15,
            lambda d: _send(conn, {"type": "out", "data": base64.b64encode(d).decode()}))
        if code == 124 or timed_out:
            timed_out = True
        end = {"type": "end", "ok": code == 0 and not timed_out, "operation_id": op_id, "exit_code": code,
               "effective_uid": proc.uid_verified, "timeout": timed_out, "truncated": truncated,
               "duration_s": round(time.time() - t0, 2)}
        _send(conn, end)
        audit(st, {**base, "result": "timeout" if timed_out else ("ok" if code == 0 else "error"),
                   "exit_code": code, "uid": proc.uid_verified, "duration_s": end["duration_s"],
                   "truncated": truncated})
    except LocalAdminError as e:
        audit(st, {**base, "result": e.code})
        raise
    finally:
        st.sem.release()


def _sftp_server() -> str:
    for p in SFTP_CANDIDATES:
        if os.path.exists(p):
            return p
    raise LocalAdminError("backend_unavailable", "sftp-server do OpenSSH não encontrado (instale openssh-sftp-server)")


def op_sftp(st: State, req: dict, conn) -> None:
    """Abre um `sftp-server` como root e devolve o canal por SCM_RIGHTS (modo root dos Arquivos).
    A sessão termina quando o console fecha o canal (expira por inatividade lá: 5 min)."""
    user = authorize(st, str(req.get("user") or ""))
    base = {"op": "sftp", "operation_id": str(uuid.uuid4()), "user": user, "client": str(req.get("client") or "")}
    if req.get("client") != "console":
        raise LocalAdminError("authorization_denied", "o modo root dos Arquivos é exclusivo do console")
    if not st.sem.acquire(blocking=False):
        raise LocalAdminError("busy")
    try:
        _cooldown(st)
        info = preconditions(st)
        password = info.pop("_password")
        server = _sftp_server()
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        fd = theirs.fileno()
        proc = su_backend.SuProcess(password, f"exec {server} -e -l INFO", pass_fds=(fd,),
                                    redirect=f" <&{fd} >&{fd}")
        del password
        try:
            proc.authenticate()
        except LocalAdminError as e:
            if e.code == "authentication_failed":
                st.last_auth_fail = time.monotonic()
            ours.close(); theirs.close()
            raise
        theirs.close()
        socket.send_fds(conn, [json.dumps({"type": "end", "ok": True, "effective_uid": proc.uid_verified}).encode() + b"\n"],
                        [ours.fileno()])
        ours.close()
        audit(st, {**base, "result": "opened", "uid": proc.uid_verified, "host": info["host"]})
        threading.Thread(target=_reap, args=(st, proc, base), daemon=True).start()
    except LocalAdminError as e:
        audit(st, {**base, "result": e.code})
        raise
    finally:
        st.sem.release()


def _reap(st: State, proc, base: dict) -> None:
    while proc._read(1.0) is not None:   # drena o PTY (stderr do sftp-server) até o fim
        pass
    code = proc.wait()
    audit(st, {**base, "result": "closed", "exit_code": code})


# --------------------------------------------------------------------------- socket
def _send(conn, obj: dict) -> None:
    conn.sendall(json.dumps(obj, ensure_ascii=False).encode() + b"\n")


def _peer_uid(conn) -> int:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def handle(st: State, conn) -> None:
    try:
        if _peer_uid(conn) != os.getuid():
            _send(conn, {"type": "error", "code": "authorization_denied", "detail": "processo de outra conta"})
            return
        conn.settimeout(30)
        raw = b""
        while not raw.endswith(b"\n") and len(raw) < 512 * 1024:
            chunk = conn.recv(65536)
            if not chunk:
                break
            raw += chunk
        conn.settimeout(None)
        req = json.loads(raw.decode() or "{}")
        ops = {"status": op_status, "exec": op_exec, "sftp": op_sftp}
        fn = ops.get(req.get("op"))
        if not fn:
            raise LocalAdminError("bad_request", "operação desconhecida")
        fn(st, req, conn)
    except LocalAdminError as e:
        try:
            _send(conn, {"type": "error", "code": e.code, "detail": e.detail})
        except OSError:
            pass
    except (ValueError, OSError) as e:
        try:
            _send(conn, {"type": "error", "code": "bad_request", "detail": type(e).__name__})
        except OSError:
            pass
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    ident = rid.load(root)
    if not ident:
        print("ERRO: instalação legada (layout 1): administração Local exige o layout 2", file=sys.stderr)
        return 2
    ok, msg = rid.current_ok(ident)
    if not ok:
        print(f"ERRO: {msg}", file=sys.stderr)
        return 2
    os.umask(0o077)
    st = State(root)
    path = common.socket_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        path.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    os.chmod(path, 0o600)
    srv.listen(16)
    print(f"netops-localadmin: escutando em {path} (conta {pwd.getpwuid(os.getuid()).pw_name})", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(st, conn), daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(main())
