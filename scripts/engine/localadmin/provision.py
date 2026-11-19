#!/usr/bin/env python3
"""Administração Local — provisionamento (SÓ ROOT; só stdlib; rode com `python3 -I`).

    sudo python3 -I scripts/engine/localadmin/provision.py install [--root DIR]
         cria `netops-admin` (senha aleatória, nunca exibida), sudoers, bloqueio de SSH, grava a
         senha no cofre (CRED_LOCAL_ADMIN), cadastra o host Local protegido e liga o serviço.
    ... rotate     nova senha: grava no cofre e aplica no sistema (também é a recuperação do cofre)
    ... disable    trava a conta (passwd -l) e marca a política como desativada
    ... enable     destrava e reativa
    ... rebind     revalida o vínculo após clone/restore (machine-id/hostname desta máquina)
    ... status     estado (sem segredos)

O cofre precisa da senha-mestra para gravar a credencial: usa a sessão destrancada da conta
operacional, ou NETOPS_MASTER_PASSWORD (instalação automatizada), ou pergunta no terminal.
"""
from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True   # root nunca grava __pycache__ na árvore da conta operacional

import argparse
import json
import os
import pwd
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import common  # noqa: E402
from common import ADMIN_USER, SSHD_DROPIN, SUDOERS  # noqa: E402
from lib import runtime_identity as rid  # noqa: E402

SUDOERS_BODY = f"""# NetOps — conta de elevação da administração Local (gerado por provision.py).
# A conta operacional `netops` NÃO tem sudo. Só quem autentica `su - {ADMIN_USER}` (senha no cofre
# do NetOps) chega aqui. Revogar: passwd -l {ADMIN_USER}  ou apagar este arquivo.
Defaults:{ADMIN_USER} !use_pty, !lecture, env_reset
{ADMIN_USER} ALL=(ALL:ALL) NOPASSWD: ALL
"""
SSHD_BODY = f"# NetOps: a conta de elevação local nunca entra por SSH (gerado por provision.py)\nDenyUsers {ADMIN_USER}\n"


def sh(*cmd, input_text=None, check=True, env=None) -> subprocess.CompletedProcess:
    r = subprocess.run(list(cmd), input=input_text, text=True, capture_output=True, env=env)
    if check and r.returncode:
        raise SystemExit(f"ERRO: {' '.join(cmd[:2])} falhou: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def _ident(root: Path) -> dict:
    ident = rid.load(root)
    if not ident:
        raise SystemExit("ERRO: instalação legada (layout 1). Migre antes: scripts/engine/identity/migrate.py")
    return ident


def _as_operational(ident: dict, argv: list, input_text=None, extra_env=None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": ident["home"],
           "USER": ident["user"], "LOGNAME": ident["user"], "LANG": "C.UTF-8",
           "XDG_RUNTIME_DIR": ident["runtime_dir"],
           "DBUS_SESSION_BUS_ADDRESS": f"unix:path={ident['runtime_dir']}/bus"}
    env.update(extra_env or {})
    return subprocess.run(["runuser", "-u", ident["user"], "--", *argv], input=input_text, text=True,
                          capture_output=True, env=env, cwd=ident["root"])


def ensure_account() -> bool:
    try:
        pw = pwd.getpwnam(ADMIN_USER)
        if pw.pw_uid == 0:
            raise SystemExit(f"ERRO: {ADMIN_USER} existe com UID 0 — conta incompatível; não vou reaproveitar")
        return False
    except KeyError:
        pass
    sh("useradd", "--system", "--create-home", "--home-dir", f"/var/lib/{ADMIN_USER}", "--shell", "/bin/bash",
       "--comment", "NetOps elevacao local", ADMIN_USER)
    os.chmod(f"/var/lib/{ADMIN_USER}", 0o700)
    return True


def write_sudoers() -> None:
    tmp = SUDOERS.with_name(".netops-admin.tmp")
    tmp.write_text(SUDOERS_BODY)
    os.chmod(tmp, 0o440)
    if shutil.which("visudo"):
        sh("visudo", "-cf", str(tmp))
    os.replace(tmp, SUDOERS)


def write_sshd() -> None:
    if SSHD_DROPIN.parent.is_dir():
        SSHD_DROPIN.write_text(SSHD_BODY)
        os.chmod(SSHD_DROPIN, 0o644)
        if shutil.which("sshd"):
            r = sh("sshd", "-t", check=False)
            if r.returncode:
                SSHD_DROPIN.unlink()
                print("  ! sshd -t recusou o drop-in; removido (SSH não alterado)")
                return
            for unit in ("ssh", "sshd"):
                if sh("systemctl", "reload", unit, check=False).returncode == 0:
                    break
    # sem sshd_config.d: a conta não tem chave nem senha conhecida; SSH por senha fica sem uso


def store_and_apply(ident: dict, root: Path) -> None:
    """Grava a senha nova no cofre (como a conta operacional) e só então aplica no sistema."""
    pw = secrets.token_urlsafe(32)
    extra = {}
    if os.environ.get("NETOPS_MASTER_PASSWORD"):
        extra["NETOPS_MASTER_PASSWORD"] = os.environ["NETOPS_MASTER_PASSWORD"]
    py = str(root / ".venv" / "bin" / "python3")
    cli = str(HERE / "cli.py")
    if sys.stdin.isatty() and not extra:
        # a senha-mestra é perguntada no /dev/tty pelo próprio cli.py; o stdin leva só a senha nova
        r = subprocess.run(["runuser", "-u", ident["user"], "--", "env", f"HOME={ident['home']}",
                            f"XDG_RUNTIME_DIR={ident['runtime_dir']}", py, cli, "store-credential", "--stdin"],
                           input=pw + "\n", text=True, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        r = _as_operational(ident, [py, cli, "store-credential", "--stdin"], input_text=pw + "\n", extra_env=extra)
    if r.returncode:
        raise SystemExit(f"ERRO: não gravei a credencial no cofre ({(r.stderr or r.stdout).strip()[-300:]}). "
                         "Nada foi alterado no sistema. Destranque o cofre e rode de novo.")
    sh("chpasswd", input_text=f"{ADMIN_USER}:{pw}\n")
    del pw
    print("  ✓ senha de netops-admin gerada, gravada no cofre (CRED_LOCAL_ADMIN) e aplicada — não exibida")


def ensure_host(ident: dict, root: Path) -> int:
    r = _as_operational(ident, [str(root / ".venv" / "bin" / "python3"), str(HERE / "cli.py"), "ensure-host"])
    if r.returncode:
        raise SystemExit(f"ERRO: não consegui cadastrar o host Local: {(r.stderr or r.stdout).strip()[-400:]}")
    return int(json.loads(r.stdout.strip().splitlines()[-1])["host_id"])


def write_policy(root: Path, host_id: int, enabled: bool) -> None:
    common.write_policy(root, {"ADMIN_USER": ADMIN_USER, "CREDENTIAL": common.CREDENTIAL, "HOST_ID": str(host_id),
                               "MACHINE_ID": common.machine_fingerprint(), "HOSTNAME": common.os_hostname(),
                               "ENABLED": "1" if enabled else "0"})


def enable_service(ident: dict) -> None:
    unit = ident["localadmin_unit"]
    _as_operational(ident, ["systemctl", "--user", "daemon-reload"])
    r = _as_operational(ident, ["systemctl", "--user", "enable", "--now", unit])
    if r.returncode:
        print(f"  ! não consegui ligar {unit}: {r.stderr.strip()[:200]}")
    else:
        _as_operational(ident, ["systemctl", "--user", "restart", unit])
        print(f"  ✓ serviço {unit} ativo")


def cmd_install(root: Path, a) -> int:
    ident = _ident(root)
    created = ensure_account()
    print(f"  ✓ conta {ADMIN_USER} {'criada' if created else 'já existe'}")
    write_sudoers()
    print(f"  ✓ {SUDOERS} (NOPASSWD só para {ADMIN_USER}; netops sem sudo)")
    write_sshd()
    host_id = ensure_host(ident, root)
    print(f"  ✓ host Local protegido no inventário (host {host_id})")
    write_policy(root, host_id, enabled=True)
    pol = common.load_policy(root)
    if a.no_credential:
        print("  ! credencial não gravada (--no-credential): rode `provision.py rotate` com o cofre destrancado")
    else:
        status = sh("passwd", "-S", ADMIN_USER, check=False).stdout.split()
        need = created or len(status) < 2 or status[1] in ("L", "NP") or a.force_rotate
        if need:
            store_and_apply(ident, root)
        else:
            print("  ✓ senha já definida (use `rotate` para trocar)")
    enable_service(ident)
    print(f"  ✓ política {common.policy_path(root)} (host {pol['HOST_ID']}, vínculo desta máquina)")
    return 0


def cmd_rotate(root: Path, _a) -> int:
    ident = _ident(root)
    ensure_account()
    store_and_apply(ident, root)
    sh("passwd", "-u", ADMIN_USER, check=False)
    return 0


def _set_enabled(root: Path, enabled: bool) -> int:
    pol = common.load_policy(root)
    if not pol:
        raise SystemExit("ERRO: administração Local não instalada (rode install)")
    sh("passwd", "-u" if enabled else "-l", ADMIN_USER, check=False)
    common.write_policy(root, {**pol, "ENABLED": "1" if enabled else "0"})
    print(f"  ✓ administração Local {'ativada' if enabled else 'desativada (conta travada)'}")
    return 0


def cmd_rebind(root: Path, _a) -> int:
    ident = _ident(root)
    pol = common.load_policy(root) or {}
    host_id = ensure_host(ident, root)
    write_policy(root, host_id, enabled=pol.get("ENABLED", "1") == "1")
    print(f"  ✓ vínculo refeito para esta máquina (host {host_id})")
    return 0


def cmd_status(root: Path, _a) -> int:
    pol = common.load_policy(root)
    try:
        acct = sh("passwd", "-S", ADMIN_USER, check=False).stdout.split()
    except FileNotFoundError:
        acct = []
    out = {"policy": pol, "account": acct[1] if len(acct) > 1 else "ausente",
           "sudoers": SUDOERS.exists(), "binding_problem": common.binding_problem(pol) if pol else "sem política"}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Provisionamento da administração Local (root)")
    ap.add_argument("cmd", choices=["install", "rotate", "disable", "enable", "rebind", "status"])
    ap.add_argument("--root", default=str(HERE.parents[2]))
    ap.add_argument("--no-credential", action="store_true")
    ap.add_argument("--force-rotate", action="store_true")
    a = ap.parse_args(argv)
    if os.geteuid() != 0:
        print("ERRO: rode como root: sudo python3 -I scripts/engine/localadmin/provision.py " + a.cmd, file=sys.stderr)
        return 2
    root = Path(a.root).resolve()
    fn = {"install": cmd_install, "rotate": cmd_rotate, "rebind": cmd_rebind, "status": cmd_status,
          "disable": lambda r, _a: _set_enabled(r, False), "enable": lambda r, _a: _set_enabled(r, True)}[a.cmd]
    return fn(root, a)


if __name__ == "__main__":
    raise SystemExit(main())
