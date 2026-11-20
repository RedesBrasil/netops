#!/usr/bin/env python3
"""NetOps — permissões da conta operacional (root, só stdlib, `python3 -I -B`).

    sudo python3 -I -B scripts/engine/privileges/provision.py install --root /opt/netops [--trust-creds]
    sudo python3 -I -B scripts/engine/privileges/provision.py status  --root /opt/netops
    sudo python3 -I -B scripts/engine/privileges/provision.py pin     --root /opt/netops
    sudo python3 -I -B scripts/engine/privileges/provision.py remove  --root /opt/netops

O que `install` deixa pronto (idempotente; o install.sh chama em toda instalação/reparo):
  1. Rede SEM root e sem cofre, para qualquer conta:
     - net.ipv4.ping_group_range na faixa de GIDs mapeada (em CT não privilegiado o padrão do
       Debian "0 2147483647" é recusado e o ping fica só para root) -> /etc/sysctl.d/60-netops-ping.conf;
     - capabilities de arquivo (não setuid) em nmap/nping/tcpdump/mtr-packet/arping/fping/arp-scan...
       (/usr/local/sbin/netops-netcaps), reaplicadas após todo apt (/etc/apt/apt.conf.d/80netops-netcaps)
       e por um timer systemd (outras distros); wrappers /usr/local/bin/nmap|nping com --privileged.
  2. `sudo` COMPLETO da conta operacional, mas SÓ com o cofre destrancado:
     /etc/sudoers.d/netops-cofre + linha pam_exec em /etc/pam.d/sudo -> /usr/local/sbin/netops-sudo-cofre,
     que confere a sessão do cofre a cada chamada contra o verificador fixado pelo root
     (/etc/netops/vault-verifier.d/<slug>.pin). A conta não tem senha: cofre trancado = sudo negado.
  3. "sudo automático" no shell da conta (aba Claude e terminal): apt/systemctl/nft/docker... viram
     root sozinhos com o cofre destrancado (/usr/local/share/netops/auto-sudo.bash, carregado no topo
     do ~/.bashrc).

`--trust-creds`: só numa instalação NOVA (o install.sh acabou de criar o cofre): fixa o verificador lido
do credentials.yaml sem exigir o cofre destrancado. Fora disso, `pin` exige o cofre destrancado (a chave
da sessão precisa abrir o verificador), porque o credentials.yaml pertence à conta operacional.
Ver SKILL.md.
"""
from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True   # root nunca grava __pycache__ na árvore da conta operacional

import argparse
import importlib.machinery
import importlib.util
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = HERE / "files"
sys.path.insert(0, str(HERE.parent))
from lib import runtime_identity as rid  # noqa: E402

ETC = Path("/etc/netops")
CONF = ETC / "privileges.conf"
PIN_DIR = ETC / "vault-verifier.d"
OLD_PIN = ETC / "vault-verifier.pin"            # formato da 1ª versão (um pin só)
SYSCTL = Path("/etc/sysctl.d/60-netops-ping.conf")
APT_HOOK = Path("/etc/apt/apt.conf.d/80netops-netcaps")
SUDOERS = Path("/etc/sudoers.d/netops-cofre")
PAM_SUDO = Path("/etc/pam.d/sudo")
PAM_BACKUP = ETC / "pam.d-sudo.orig"
SBIN = Path("/usr/local/sbin")
SHARE = Path("/usr/local/share/netops")
UNIT_DIR = Path("/etc/systemd/system")
MARK = "netops-sudo-cofre"
BASHRC_BEGIN = "# >>> netops auto-sudo >>>"
BASHRC_END = "# <<< netops auto-sudo <<<"

PAM_LINE = f"auth [success=done default=ignore] pam_exec.so quiet {SBIN}/netops-sudo-cofre"
INSTALLED = {  # origem em files/ -> destino, modo
    "netops-netcaps": (SBIN / "netops-netcaps", 0o755),
    "netops-sudo-cofre": (SBIN / "netops-sudo-cofre", 0o755),
    "netops-setup-finish": (SBIN / "netops-setup-finish", 0o755),   # etapa root do primeiro acesso
    "auto-sudo.bash": (SHARE / "auto-sudo.bash", 0o644),
    "nmap": (Path("/usr/local/bin/nmap"), 0o755),
    "nping": (Path("/usr/local/bin/nping"), 0o755),
}
APT_BODY = ("// NetOps: reaplica as capabilities das ferramentas de rede depois de cada instalação/atualização.\n"
            'DPkg::Post-Invoke { "[ -x /usr/local/sbin/netops-netcaps ] && /usr/local/sbin/netops-netcaps || true"; };\n')
UNIT_SERVICE = """[Unit]
Description=NetOps: capabilities das ferramentas de rede (ping/nmap/tcpdump sem root)

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/netops-netcaps
"""
UNIT_TIMER = """[Unit]
Description=NetOps: reaplica as capabilities das ferramentas de rede (após atualização de pacotes)

[Timer]
OnBootSec=1min
OnUnitActiveSec=1h

[Install]
WantedBy=timers.target
"""


def sudoers_body(user: str) -> str:
    return (f"# NetOps (gerado por scripts/engine/privileges/provision.py): a conta {user} tem sudo COMPLETO,\n"
            "# mas só enquanto o cofre estiver destrancado. Ela não tem senha; quem libera é o PAM\n"
            f"# (/etc/pam.d/sudo -> {SBIN}/netops-sudo-cofre), que confere o cofre a CADA chamada\n"
            "# (timestamp_timeout=0: trancou = sudo some na hora).\n"
            f"Defaults:{user} timestamp_timeout=0, !lecture, passwd_tries=1, !requiretty\n"
            f"{user} ALL=(ALL:ALL) ALL\n")


def bashrc_block() -> str:
    return (f"{BASHRC_BEGIN}\n"
            "# NetOps: comandos de administração viram root sozinhos com o cofre destrancado. Fica ANTES do teste\n"
            "# de shell interativo, para a aba Claude (Claude Code) também carregar. Gerado por provision.py.\n"
            f"[ -r {SHARE}/auto-sudo.bash ] && . {SHARE}/auto-sudo.bash\n"
            f"{BASHRC_END}\n")


# --------------------------------------------------------------------------- utilitários
def sh(*cmd, check=False, input_text=None) -> subprocess.CompletedProcess:
    r = subprocess.run(list(cmd), text=True, capture_output=True, input=input_text)
    if check and r.returncode:
        raise SystemExit(f"ERRO: {' '.join(cmd[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def ok(msg):
    print(f"  ✓ {msg}")


def warn(msg):
    print(f"  ! {msg}")


def write_root(path: Path, body: str, mode: int) -> bool:
    """Grava arquivo do root de forma atômica; devolve True se mudou."""
    if path.exists() and path.read_text(encoding="utf-8", errors="replace") == body:
        os.chown(path, 0, 0)
        os.chmod(path, mode)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(body, encoding="utf-8")
    os.chown(tmp, 0, 0)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return True


def cofre_module():
    path = str(FILES / "netops-sudo-cofre")
    loader = importlib.machinery.SourceFileLoader("netops_sudo_cofre", path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def ident_of(root: Path) -> dict:
    ident = rid.load(root)
    if not ident:
        raise SystemExit("ERRO: instalação legada (console como root). Migre antes: scripts/engine/identity/migrate.py")
    return ident


def ping_range() -> str:
    """Faixa de GIDs que o kernel aceita aqui (CT não privilegiado: só a faixa mapeada)."""
    try:
        lines = Path("/proc/self/gid_map").read_text().split("\n")
        for ln in lines:
            parts = ln.split()
            if len(parts) == 3 and parts[0] == "0":
                return f"0 {min(int(parts[2]) - 1, 2147483647)}"
    except (OSError, ValueError):
        pass
    return "0 2147483647"


# --------------------------------------------------------------------------- passos
def step_conf(user: str) -> None:
    if CONF.exists():
        cur = [ln.split("=", 1)[1].strip() for ln in CONF.read_text().splitlines()
               if ln.startswith("NETOPS_RUNTIME_USER=")]
        if cur and cur[0] != user:
            raise SystemExit(f"ERRO: {CONF} já é da conta {cur[0]} (esta instalação usa {user}).")
    write_root(CONF, "# NetOps: conta operacional cujo sudo depende do cofre (gerado por privileges/provision.py)\n"
                     f"NETOPS_RUNTIME_USER={user}\n", 0o644)
    ETC.chmod(0o755)
    ok(f"{CONF}")


def step_ping() -> None:
    rng = ping_range()
    write_root(SYSCTL, "# NetOps: ping/ping6 sem root para todos (socket ICMP datagram, sem raw).\n"
                       "# Em CT não privilegiado o padrão do Debian (0 2147483647) é recusado: usa a faixa mapeada.\n"
                       f"net.ipv4.ping_group_range = {rng}\n", 0o644)
    r = sh("sysctl", "-w", f"net.ipv4.ping_group_range={rng}")
    if r.returncode:
        warn(f"não apliquei ping_group_range agora ({r.stderr.strip()[:120]}); vale no próximo boot")
    else:
        ok(f"ping sem root (ping_group_range = {rng})")


def step_files() -> None:
    for src, (dst, mode) in INSTALLED.items():
        body = (FILES / src).read_text(encoding="utf-8")
        if dst.exists() and "NetOps" not in dst.read_text(encoding="utf-8", errors="replace"):
            warn(f"{dst} já existe e não é do NetOps: mantido (sem {src})")
            continue
        write_root(dst, body, mode)
    SHARE.chmod(0o755)
    ok("scripts do sistema em /usr/local (netcaps, sudo-cofre, setup-finish, auto-sudo, wrappers nmap/nping)")


def step_netcaps() -> None:
    if Path("/etc/apt").is_dir():
        write_root(APT_HOOK, APT_BODY, 0o644)
    if Path("/run/systemd/system").is_dir():
        changed = write_root(UNIT_DIR / "netops-netcaps.service", UNIT_SERVICE, 0o644)
        changed |= write_root(UNIT_DIR / "netops-netcaps.timer", UNIT_TIMER, 0o644)
        if changed:
            sh("systemctl", "daemon-reload")
        sh("systemctl", "enable", "--now", "netops-netcaps.timer")
    if not shutil.which("setcap") and not Path("/usr/sbin/setcap").exists():
        warn("setcap ausente (pacote libcap2-bin/libcap): ferramentas raw (nmap -sS, tcpdump) seguem só com root")
        return
    sh(str(SBIN / "netops-netcaps"))
    r = sh(str(SBIN / "netops-netcaps"), "--check")
    n = sum(1 for ln in r.stdout.splitlines() if "cap_net" in ln)
    ok(f"capabilities de rede em {n} binário(s) (reaplicadas após apt e pelo timer netops-netcaps)")


def step_sudo(user: str) -> None:
    if not shutil.which("visudo") and not Path("/usr/sbin/visudo").exists():
        warn("sudo ausente: instale o pacote sudo e rode de novo")
        return
    body = sudoers_body(user)
    tmp = Path(f"/etc/netops/.sudoers.{os.getpid()}")
    tmp.write_text(body)
    tmp.chmod(0o440)
    r = sh("visudo", "-cf", str(tmp))
    tmp.unlink()
    if r.returncode:
        raise SystemExit(f"ERRO: sudoers gerado inválido: {r.stdout.strip()} {r.stderr.strip()}")
    write_root(SUDOERS, body, 0o440)
    if not PAM_SUDO.exists():
        raise SystemExit(f"ERRO: {PAM_SUDO} não existe (sudo sem PAM?)")
    text = PAM_SUDO.read_text()
    if MARK not in text:
        if not PAM_BACKUP.exists():
            write_root(PAM_BACKUP, text, 0o644)
        lines = text.splitlines(keepends=True)
        idx = next((i for i, ln in enumerate(lines)
                    if ln.lstrip().startswith(("auth", "@include common-auth", "-auth"))), len(lines))
        lines.insert(idx, PAM_LINE + "\n")
        write_root(PAM_SUDO, "".join(lines), 0o644)
    r = sh("visudo", "-c")
    if r.returncode:
        raise SystemExit(f"ERRO: visudo -c falhou depois da mudança: {r.stdout.strip()[-300:]}")
    ok(f"sudo de {user} liberado só com o cofre destrancado (PAM + {SUDOERS})")


def step_bashrc(user: str) -> None:
    pw = pwd.getpwnam(user)
    home = Path(pw.pw_dir)
    rc = home / ".bashrc"
    for name in (".bashrc", ".profile"):
        skel = Path("/etc/skel") / name
        if not (home / name).exists() and skel.exists():
            shutil.copyfile(skel, home / name)
            os.chown(home / name, pw.pw_uid, pw.pw_gid)
    text = rc.read_text(encoding="utf-8", errors="replace") if rc.exists() else ""
    if BASHRC_BEGIN in text:
        pre, rest = text.split(BASHRC_BEGIN, 1)
        post = rest.split(BASHRC_END, 1)[1].lstrip("\n") if BASHRC_END in rest else ""
        text = pre + post
    # versão manual antiga (linha solta, sem marcadores)
    text = "\n".join(ln for ln in text.splitlines()
                     if "auto-sudo.bash" not in ln and "viram root sozinhos" not in ln
                     and "para a aba Claude também carregar" not in ln) + "\n"
    new = bashrc_block() + "\n" + text.lstrip("\n")
    tmp = rc.with_name(f".bashrc.tmp.{os.getpid()}")
    tmp.write_text(new, encoding="utf-8")
    os.chown(tmp, pw.pw_uid, pw.pw_gid)
    os.chmod(tmp, 0o644)
    os.replace(tmp, rc)
    ok(f"sudo automático no shell de {user} ({rc})")


def _pin_path(root: Path) -> Path:
    return PIN_DIR / f"{rid.slug(root)}.pin"


def step_pin(root: Path, user: str, trust_creds: bool) -> None:
    PIN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(PIN_DIR, 0, 0)
    PIN_DIR.chmod(0o700)
    dst = _pin_path(root)
    mod = cofre_module()
    if OLD_PIN.exists() and not dst.exists():
        os.replace(OLD_PIN, dst)
    elif OLD_PIN.exists():
        OLD_PIN.unlink()
    try:
        value = mod.verifier_from_creds(str(root))
    except (SystemExit, OSError):       # sem credentials.yaml (instalação nova: cofre nasce no 1º acesso)
        ok("sudo pelo cofre: fica pronto ao concluir o primeiro acesso no console (cofre ainda não criado)")
        return
    if dst.exists() and dst.read_text().strip() == value:
        ok(f"verificador do cofre fixado ({dst})")
        return
    try:
        key, _ = mod.session_key(pwd.getpwnam(user).pw_uid)
        if not mod.fernet_ok(key, value):
            raise SystemExit("ERRO: o verificador do credentials.yaml não confere com o cofre destrancado — "
                             "não fixei (credentials.yaml alterado?)")
        how = "conferido com o cofre destrancado"
    except (OSError, ValueError):
        if not (trust_creds and not dst.exists()):
            warn("cofre trancado: sudo fica negado até fixar o verificador. Destranque e rode: "
                 f"sudo python3 -I -B {HERE}/provision.py pin --root {root}")
            return
        how = "instalação nova (cofre recém-criado)"
    write_root(dst, value + "\n", 0o600)
    ok(f"verificador do cofre fixado ({dst}; {how})")


# --------------------------------------------------------------------------- comandos
def cmd_install(root: Path, a) -> int:
    ident = ident_of(root)
    user = ident["user"]
    print(f"Permissões da conta {user} ({root})...")
    step_conf(user)
    step_ping()
    step_files()
    step_netcaps()
    step_sudo(user)
    step_bashrc(user)
    step_pin(root, user, a.trust_creds)
    print("Pronto: rede sem root; com o cofre destrancado, root por `sudo` ou direto (apt/systemctl/nft...).")
    return 0


def cmd_pin(root: Path, a) -> int:
    ident = ident_of(root)
    step_pin(root, ident["user"], False)
    return 0 if _pin_path(root).exists() else 1


def cmd_status(root: Path, a) -> int:
    ident = ident_of(root)
    user = ident["user"]
    rc = Path(pwd.getpwnam(user).pw_dir) / ".bashrc"
    items = {
        "privileges.conf": CONF.exists(),
        "ping_group_range": SYSCTL.exists(),
        "netcaps": (SBIN / "netops-netcaps").exists(),
        "apt hook": APT_HOOK.exists() or not Path("/etc/apt").is_dir(),
        "sudoers": SUDOERS.exists(),
        "pam": PAM_SUDO.exists() and MARK in PAM_SUDO.read_text(),
        "auto-sudo (.bashrc)": rc.exists() and BASHRC_BEGIN in rc.read_text(errors="replace"),
        "verificador fixado": _pin_path(root).exists(),
    }
    for k, v in items.items():
        print(f"  {'✓' if v else '✗'} {k}")
    print("  " + sh(str(SBIN / "netops-sudo-cofre"), "--check").stdout.strip()
          if (SBIN / "netops-sudo-cofre").exists() else "  ✗ netops-sudo-cofre ausente")
    return 0 if all(items.values()) else 1


def cmd_remove(root: Path, a) -> int:
    ident = ident_of(root)
    user = ident["user"]
    if PAM_SUDO.exists() and MARK in PAM_SUDO.read_text():
        write_root(PAM_SUDO, "".join(ln for ln in PAM_SUDO.read_text().splitlines(keepends=True) if MARK not in ln), 0o644)
    for p in (SUDOERS, APT_HOOK, SYSCTL, CONF, _pin_path(root), OLD_PIN):
        if p.exists():
            p.unlink()
    if Path("/run/systemd/system").is_dir():
        sh("systemctl", "disable", "--now", "netops-netcaps.timer")
    for p in (UNIT_DIR / "netops-netcaps.service", UNIT_DIR / "netops-netcaps.timer"):
        if p.exists():
            p.unlink()
    for _src, (dst, _mode) in INSTALLED.items():
        if dst.exists() and "NetOps" in dst.read_text(errors="replace"):
            dst.unlink()
    rc = Path(pwd.getpwnam(user).pw_dir) / ".bashrc"
    if rc.exists() and BASHRC_BEGIN in rc.read_text():
        pre, rest = rc.read_text().split(BASHRC_BEGIN, 1)
        rc.write_text(pre + (rest.split(BASHRC_END, 1)[1].lstrip("\n") if BASHRC_END in rest else ""))
    print("Removido (capabilities já aplicadas nos binários ficam até a próxima atualização do pacote).")
    return 0


def main(argv=None) -> int:
    if os.geteuid() != 0:
        raise SystemExit("ERRO: rode como root (sudo python3 -I -B ...)")
    ap = argparse.ArgumentParser(description="Permissões da conta operacional do NetOps (root)")
    ap.add_argument("cmd", choices=["install", "status", "pin", "remove"])
    ap.add_argument("--root", default=str(HERE.parents[2]))
    ap.add_argument("--trust-creds", action="store_true",
                    help="instalação nova: fixa o verificador do credentials.yaml sem exigir o cofre destrancado")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    return {"install": cmd_install, "status": cmd_status, "pin": cmd_pin, "remove": cmd_remove}[a.cmd](root, a)


if __name__ == "__main__":
    sys.exit(main())
