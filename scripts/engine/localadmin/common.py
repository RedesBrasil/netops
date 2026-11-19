"""Administração Local — constantes, política instalada e vínculo do host Local (só stdlib).

Modelo (plano 2026-11-19, Adendo A):
  * a conta operacional (`netops`) nunca tem sudo; a elevação é feita autenticando
    `su - netops-admin` num PTY privado com a senha guardada no cofre (`cred_local_admin`);
    `netops-admin` tem `NOPASSWD: ALL` em /etc/sudoers.d/netops-admin (a única autenticação
    é o `su`);
  * quem conduz o `su` é o serviço `netops-localadmin@<slug>` (daemon.py), fora da árvore de
    processos da IA; console, CLI e IA pedem operações por socket UNIX 0600;
  * a política instalada é ROOT-OWNED: /etc/netops/instances/<slug>.local
      ADMIN_USER=netops-admin
      CREDENTIAL=cred_local_admin
      HOST_ID=<id do host Local no inventário>
      MACHINE_ID=<sha256 de /etc/machine-id>   vínculo: clone/restore em outra máquina bloqueia
      HOSTNAME=<hostname do SO>
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from lib import runtime_identity as rid  # noqa: E402

ADMIN_USER = rid.ADMIN_USER
CREDENTIAL = "CRED_LOCAL_ADMIN"
LOCAL_HOSTNAME = "NETOPS-LOCAL"
SUDOERS = Path("/etc/sudoers.d/netops-admin")
SSHD_DROPIN = Path("/etc/ssh/sshd_config.d/90-netops-admin.conf")

# Erros estruturados (plano §6.4). Mensagens sem segredo, prontas para o humano.
ERRORS = {
    "local_access_disabled": "Administração Local desativada neste servidor.",
    "backend_unavailable": "Backend Local indisponível (serviço netops-localadmin parado ou não instalado).",
    "vault_locked": "Cofre trancado: destranque com `python3 scripts/engine/vault/cli.py unlock` (humano).",
    "credential_missing": "Credencial do admin local ausente no cofre: rode `sudo scripts/engine/localadmin/provision.py rotate`.",
    "binding_mismatch": "Vínculo do host Local inconsistente (clone/restore?): revalide com `sudo scripts/engine/localadmin/provision.py rebind`.",
    "authentication_failed": "A senha do admin local foi recusada pelo sistema. Não haverá nova tentativa automática; rode `sudo scripts/engine/localadmin/provision.py rotate`.",
    "authentication_cooldown": "Autenticação local recusada há pouco; aguardando antes de tentar de novo (sem retentativa automática).",
    "authorization_denied": "Seu usuário não tem a permissão `server.admin` para administração Local.",
    "busy": "Limite de operações administrativas simultâneas atingido.",
    "timeout": "A operação excedeu o tempo limite (o efeito parcial precisa ser verificado; não houve rollback).",
    "verification_failed": "Não foi possível confirmar o UID efetivo root da operação.",
    "bad_request": "Pedido inválido.",
}


class LocalAdminError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail or ERRORS.get(code, code)
        super().__init__(f"{code}: {self.detail}")


def machine_fingerprint() -> str:
    try:
        raw = Path("/etc/machine-id").read_text().strip()
    except OSError:
        raw = ""
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def os_hostname() -> str:
    return socket.gethostname()


def policy_path(root) -> Path:
    return rid.CONF_DIR / f"{rid.slug(root)}.local"


_POLICY_KEYS = ("ADMIN_USER", "CREDENTIAL", "HOST_ID", "MACHINE_ID", "HOSTNAME", "ENABLED")
_VAL = re.compile(r"^[A-Za-z0-9_.:-]*$")


def load_policy(root) -> dict | None:
    p = policy_path(root)
    if not p.exists():
        return None
    rid._check_conf_file(p)
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        if k not in _POLICY_KEYS or not _VAL.match(v):
            raise LocalAdminError("binding_mismatch", "política local inválida")
        out[k] = v
    return out


def write_policy(root, values: dict) -> Path:
    p = policy_path(root)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    for k, v in values.items():
        if k not in _POLICY_KEYS or not _VAL.match(str(v)):
            raise ValueError(f"valor inválido em {k}")
    body = ("# NetOps — política da administração Local (root-owned; ver scripts/engine/localadmin/common.py)\n"
            + "".join(f"{k}={values[k]}\n" for k in _POLICY_KEYS if k in values))
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, p)
    return p


def binding_problem(policy: dict) -> str:
    """'' se o vínculo bate com esta máquina; senão o motivo."""
    if policy.get("MACHINE_ID") != machine_fingerprint():
        return "machine-id diferente do vinculado"
    if policy.get("HOSTNAME") != os_hostname():
        return "hostname do sistema diferente do vinculado"
    return ""


def socket_path(root, uid: int | None = None) -> Path:
    uid = os.getuid() if uid is None else uid
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    return Path(base) / "netops" / f"localadmin-{rid.slug(root)}.sock"


def is_local_host(host: dict) -> bool:
    return str((host.get("access") or {}).get("method", "")).lower() == "local"
