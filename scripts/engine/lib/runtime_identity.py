#!/usr/bin/env python3
"""Identidade operacional do NetOps: fonte única de conta, HOME, runtime e instância.

Desde o layout 2 o NetOps roda como uma conta Linux dedicada (`netops`), nunca como root:
console, supervisor, IA, subagentes, terminal, agendador e atualizador usam a mesma conta.
Root só provisiona o sistema (instalador/migração) e executa operações administrativas
locais autorizadas (backend Local, ver scripts/engine/localadmin/).

A configuração de cada instalação fica num arquivo ROOT-OWNED, fora do alcance da conta
operacional (ela não pode trocar a própria identidade nem apontar o serviço para outro lugar):

    /etc/netops/instances/<slug>.env      slug = caminho da instalação ("/opt/netops" -> "opt-netops")

    NETOPS_LAYOUT=2
    NETOPS_DIR=/opt/netops
    NETOPS_RUNTIME_USER=netops
    NETOPS_RUNTIME_HOME=/var/lib/netops
    NETOPS_INSTANCE_ID=<uuid4>            identificador persistente desta instalação (vínculo do host Local)
    NETOPS_UI_HOST=0.0.0.0                todos os IPs da máquina (padrão do instalador; vazio = 0.0.0.0)
    NETOPS_UI_PORT=8765
    NETOPS_UI_TERMINAL=1 / NETOPS_UI_CLAUDE=1 / NETOPS_UI_CLAUDE_PERSIST=1   opcionais

Sem esse arquivo a instalação é LEGADA (layout 1: console como root). O `start.sh` mantém o
comportamento antigo para ela e o instalador oferece a migração (scripts/engine/identity/).

O arquivo é lido também pelo `start.sh` em bash puro (mesmo formato: KEY=valor, sem aspas,
sem expansão). Este módulo só usa stdlib e nunca toca em segredos.

CLI:
    runtime_identity.py show  [--root DIR]          JSON com a identidade resolvida (ou layout 1)
    runtime_identity.py check [--root DIR]          exit 0 se o processo atual é a conta certa
    runtime_identity.py write --root DIR --user U --home H [--port P] [--host IP]   (root)
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import sys
import uuid
from pathlib import Path

CONF_DIR = Path(os.environ.get("NETOPS_IDENTITY_DIR", "/etc/netops/instances"))
LAYOUT = 2
DEFAULT_USER = "netops"
DEFAULT_HOME = "/var/lib/netops"
ADMIN_USER = "netops-admin"           # conta de elevação local (Adendo A §3)
UNIT_TEMPLATE = "netops-console@.service"
LOCALADMIN_UNIT_TEMPLATE = "netops-localadmin@.service"

_KEYS = ("NETOPS_LAYOUT", "NETOPS_DIR", "NETOPS_RUNTIME_USER", "NETOPS_RUNTIME_HOME",
         "NETOPS_INSTANCE_ID", "NETOPS_UI_HOST", "NETOPS_UI_PORT", "NETOPS_UI_TERMINAL",
         "NETOPS_UI_CLAUDE", "NETOPS_UI_CLAUDE_PERSIST")
_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@%+,-]*$")   # sem espaço, aspas, $, `, ; …
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


class IdentityError(Exception):
    pass


def slug(root) -> str:
    """'/opt/netops' -> 'opt-netops' (nome da instância no systemd e no /etc/netops)."""
    p = str(Path(root).resolve()).strip("/")
    s = re.sub(r"[^A-Za-z0-9]+", "-", p).strip("-")
    if not s:
        raise IdentityError("caminho de instalação inválido")
    return s


def config_path(root) -> Path:
    return CONF_DIR / f"{slug(root)}.env"


def unit_name(root) -> str:
    return f"netops-console@{slug(root)}.service"


def localadmin_unit(root) -> str:
    return f"netops-localadmin@{slug(root)}.service"


def parse_env(text: str) -> dict:
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in _KEYS:
            raise IdentityError(f"linha {n} inválida no arquivo de identidade")
        if not _VALUE_RE.match(value):
            raise IdentityError(f"valor inválido para {key}")
        out[key] = value
    return out


def _check_conf_file(path: Path) -> None:
    """O arquivo e os diretórios acima dele precisam ser root-owned e sem escrita por outros."""
    for p in (path, *path.parents):
        if p == Path("/"):
            break
        st = p.lstat()
        if p.is_symlink():
            raise IdentityError(f"{p} é link simbólico")
        if os.environ.get("NETOPS_IDENTITY_DIR"):      # testes: diretório temporário
            continue
        if st.st_uid != 0 or st.st_mode & 0o022:
            raise IdentityError(f"{p} precisa pertencer a root e não ser gravável por outros")


def load(root) -> dict | None:
    """Identidade da instalação em `root`, ou None se legada (layout 1)."""
    path = config_path(root)
    if not path.exists():
        return None
    _check_conf_file(path)
    env = parse_env(path.read_text(encoding="utf-8"))
    if env.get("NETOPS_LAYOUT") != str(LAYOUT):
        raise IdentityError("layout de identidade desconhecido")
    if Path(env.get("NETOPS_DIR", "")).resolve() != Path(root).resolve():
        raise IdentityError("arquivo de identidade aponta para outra instalação")
    user = env.get("NETOPS_RUNTIME_USER", "")
    if not _USER_RE.match(user) or user == "root":
        raise IdentityError("conta operacional inválida")
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        raise IdentityError(f"conta operacional {user} não existe")
    if pw.pw_uid == 0:
        raise IdentityError("conta operacional não pode ter UID 0")
    home = env.get("NETOPS_RUNTIME_HOME") or pw.pw_dir
    if Path(home).resolve() != Path(pw.pw_dir).resolve():
        raise IdentityError(f"HOME de {user} ({pw.pw_dir}) difere do configurado ({home})")
    return {
        "layout": LAYOUT,
        "root": str(Path(root).resolve()),
        "slug": slug(root),
        "user": user,
        "uid": pw.pw_uid,
        "gid": pw.pw_gid,
        "home": home,
        "runtime_dir": f"/run/user/{pw.pw_uid}",
        "instance_id": env.get("NETOPS_INSTANCE_ID", ""),
        "unit": unit_name(root),
        "localadmin_unit": localadmin_unit(root),
        "config": str(path),
        "ui": {k: env[k] for k in ("NETOPS_UI_HOST", "NETOPS_UI_PORT", "NETOPS_UI_TERMINAL",
                                    "NETOPS_UI_CLAUDE", "NETOPS_UI_CLAUDE_PERSIST") if k in env},
    }


def current_ok(ident: dict | None) -> tuple[bool, str]:
    """O processo atual é a identidade operacional certa?"""
    if ident is None:
        return True, "instalação legada (layout 1)"
    if os.geteuid() != ident["uid"]:
        who = pwd.getpwuid(os.geteuid()).pw_name
        return False, f"rodando como {who}; esta instalação roda como {ident['user']}"
    return True, f"rodando como {ident['user']}"


def instance_id(root) -> str:
    """ID persistente da instalação ('' se legada)."""
    try:
        ident = load(root)
    except IdentityError:
        return ""
    return (ident or {}).get("instance_id", "")


def write(root, user: str, home: str, port: str = "8765", host: str = "",
          keep_id: bool = True, extra: dict | None = None) -> Path:
    if os.geteuid() != 0 and not os.environ.get("NETOPS_IDENTITY_DIR"):
        raise IdentityError("só root grava a identidade da instalação")
    path = config_path(root)
    old = {}
    if path.exists() and keep_id:
        old = parse_env(path.read_text(encoding="utf-8"))
    env = {
        "NETOPS_LAYOUT": str(LAYOUT),
        "NETOPS_DIR": str(Path(root).resolve()),
        "NETOPS_RUNTIME_USER": user,
        "NETOPS_RUNTIME_HOME": home,
        "NETOPS_INSTANCE_ID": old.get("NETOPS_INSTANCE_ID") or str(uuid.uuid4()),
        "NETOPS_UI_PORT": str(port or old.get("NETOPS_UI_PORT") or "8765"),
    }
    if host or old.get("NETOPS_UI_HOST"):
        env["NETOPS_UI_HOST"] = host or old["NETOPS_UI_HOST"]
    for k in ("NETOPS_UI_TERMINAL", "NETOPS_UI_CLAUDE", "NETOPS_UI_CLAUDE_PERSIST"):
        if (extra or {}).get(k) is not None:
            env[k] = str(extra[k])
        elif k in old:
            env[k] = old[k]
    for k, v in env.items():
        if not _VALUE_RE.match(v):
            raise IdentityError(f"valor inválido para {k}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    body = ("# NetOps — identidade desta instalação (gerado por install.sh/migração; root-owned).\n"
            "# A conta operacional NÃO pode alterar este arquivo. Ver scripts/engine/lib/runtime_identity.py\n"
            + "".join(f"{k}={v}\n" for k, v in env.items()))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Identidade operacional do NetOps")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "check"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=str(Path(__file__).resolve().parents[3]))
    w = sub.add_parser("write")
    w.add_argument("--root", required=True)
    w.add_argument("--user", default=DEFAULT_USER)
    w.add_argument("--home", default=DEFAULT_HOME)
    w.add_argument("--port", default="8765")
    w.add_argument("--host", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "write":
            print(write(a.root, a.user, a.home, a.port, a.host))
            return 0
        ident = load(a.root)
        if a.cmd == "show":
            print(json.dumps(ident or {"layout": 1, "root": str(Path(a.root).resolve())}, indent=2))
            return 0
        ok, msg = current_ok(ident)
        print(msg)
        return 0 if ok else 1
    except IdentityError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
