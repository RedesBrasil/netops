#!/usr/bin/env python3
"""Migração de uma instalação LEGADA (console como root, layout 1) para a conta dedicada `netops`
(layout 2). SÓ ROOT; só stdlib; rode com `python3 -I`. Ver SKILL.md desta pasta.

    sudo python3 -I scripts/engine/identity/migrate.py plan     [--root /opt/netops]   (dry-run; não muda nada)
    sudo python3 -I scripts/engine/identity/migrate.py apply    [--root ...] [--yes]
    sudo python3 -I scripts/engine/identity/migrate.py status   [--root ...]
    sudo python3 -I scripts/engine/identity/migrate.py rollback [--root ...]           (antes do commit)
    sudo python3 -I scripts/engine/identity/migrate.py commit   [--root ...]           (após validar + reboot)

O que o `apply` faz, em ordem, registrando cada passo num journal (para rollback):
  1. baseline em /var/backups/netops-migration/<id>/ (root, 0700): dono/modo de cada entrada da pasta,
     cópia consistente do SQLite (API de backup), inventário/credenciais cifradas/config, cron e unidade antigos;
  2. para o console root desta pasta (unidade de sistema ou transitória) e o despachante do cron desta pasta;
  3. conta `netops` com HOME /var/lib/netops (linger), perfil da IA desta instalação copiado de /root/.claude
     (memória automática e conversas: projects/<slug>*; settings.json se não houver) — o login da IA NÃO é
     copiado (faça /login na aba); o cache do cofre root não é transferido (destranque de novo);
  4. dono de TUDO em <root> -> netops (sem seguir links, sem atravessar montagens);
  5. identidade /etc/netops/instances/<slug>.env, unidades de usuário, serviço ligado, console no ar como netops;
  6. despachante do agendador no crontab de netops; agente `claude` instalado para netops.
Depois: valide (HTTP, aba Claude, tarefas), reinicie a máquina e rode `commit`. Antes do commit, `rollback`
devolve dono/serviço/cron antigos sem apagar dados novos (o banco NÃO é restaurado às cegas).
A administração Local (netops-admin + host Local) é etapa própria: provision.py install (cofre destrancado).
"""
from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True   # root nunca grava __pycache__ na árvore da conta operacional

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lib import runtime_identity as rid  # noqa: E402

BACKUP_BASE = Path("/var/backups/netops-migration")
OP_USER, OP_HOME = rid.DEFAULT_USER, rid.DEFAULT_HOME
CRON_FILE = Path("/etc/cron.d/netops-scheduler")
SYSTEM_UNIT = Path("/etc/systemd/system/netops-console.service")
ROOT_CLAUDE = Path("/root/.claude")


def sh(*cmd, check=True, input_text=None, env=None, cwd=None) -> subprocess.CompletedProcess:
    r = subprocess.run(list(cmd), capture_output=True, text=True, input=input_text, env=env, cwd=cwd)
    if check and r.returncode:
        raise SystemExit(f"ERRO: {' '.join(map(str, cmd))[:120]} -> {(r.stderr or r.stdout).strip()[:400]}")
    return r


def say(msg: str) -> None:
    print(msg, flush=True)


def claude_slug(path) -> str:
    """Como o Claude Code nomeia a pasta do projeto: caminho com / e . trocados por '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


# --------------------------------------------------------------------------- inventário
def supervisors(root: Path) -> list[dict]:
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            args = (d / "cmdline").read_bytes().split(b"\0")
            uid = d.stat().st_uid
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in args if a]
        if len(args) > 3 and args[1].endswith("update/supervisor.py") and "--root" in args:
            i = args.index("--root")
            if i + 1 < len(args) and Path(args[i + 1]).resolve() == root:
                host = args[args.index("--host") + 1] if "--host" in args else ""
                port = args[args.index("--port") + 1] if "--port" in args else ""
                cg = ""
                try:
                    cg = (d / "cgroup").read_text().strip().split("/")[-1]
                except OSError:
                    pass
                out.append({"pid": int(d.name), "uid": uid, "host": host, "port": port, "unit": cg,
                            "flags": [a for a in args if a.startswith("--enable") or a in ("--read-only",)]})
    return out


def cron_lines(root: Path) -> list[str]:
    if not CRON_FILE.exists():
        return []
    return [ln for ln in CRON_FILE.read_text().splitlines() if f"--data-root {root} " in ln + " " or f"{root}/scripts/engine/scheduler" in ln]


def walk_entries(root: Path):
    """Todas as entradas sob root, sem seguir links e sem atravessar montagens."""
    dev = root.lstat().st_dev
    yield root, root.lstat()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep = []
        for name in dirnames:
            p = Path(dirpath) / name
            try:
                st = p.lstat()
            except OSError:
                continue
            yield p, st
            if stat.S_ISDIR(st.st_mode) and st.st_dev == dev:
                keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            p = Path(dirpath) / name
            try:
                yield p, p.lstat()
            except OSError:
                continue


def inventory(root: Path) -> dict:
    sups = supervisors(root)
    pw = None
    try:
        pw = pwd.getpwnam(OP_USER)
    except KeyError:
        pass
    owners, foreign, mounts, count = {}, [], [], 0
    dev = root.lstat().st_dev
    for p, st in walk_entries(root):
        count += 1
        owners[st.st_uid] = owners.get(st.st_uid, 0) + 1
        if st.st_dev != dev:
            mounts.append(str(p))
        elif pw and st.st_uid not in (0, pw.pw_uid):
            foreign.append(str(p))
    slug = claude_slug(root)
    profile = sorted(str(p) for p in (ROOT_CLAUDE / "projects").glob(slug + "*")) if (ROOT_CLAUDE / "projects").is_dir() else []
    free = shutil.disk_usage(root).free
    return {
        "root": str(root), "slug": rid.slug(root), "identity_file": str(rid.config_path(root)),
        "layout": 2 if rid.config_path(root).exists() else 1,
        "supervisors": sups, "system_unit": str(SYSTEM_UNIT) if SYSTEM_UNIT.exists() and str(root) in SYSTEM_UNIT.read_text() else "",
        "cron_lines": cron_lines(root),
        "account": {"exists": bool(pw), "uid": pw.pw_uid if pw else None, "home": pw.pw_dir if pw else None},
        "owners": {pwd.getpwuid(u).pw_name if _uid_exists(u) else str(u): n for u, n in owners.items()},
        "entries": count, "foreign_owned": foreign[:20], "foreign_count": len(foreign), "mounts": mounts[:20],
        "update_journal": _update_pending(root),
        "claude_profile": profile, "claude_settings": (ROOT_CLAUDE / "settings.json").exists(),
        "projects_file": str(root / "runs" / "claude" / "projects.json") if (root / "runs" / "claude" / "projects.json").exists() else "",
        "free_bytes": free, "has_systemd": Path("/run/systemd/system").is_dir(),
        "other_instances_shared_account": _other_instances(root),
    }


def _update_pending(root: Path) -> bool:
    """Atualização/recuperação EM ANDAMENTO = journal fora dos estados finais (mesma regra do supervisor:
    update/common.py TERMINAL_STATES). Journal concluído/revertido antigo não bloqueia."""
    p = root / ".netops-update" / "journal.json"
    if not p.exists():
        return False
    try:
        phase = json.loads(p.read_text()).get("phase")
    except (OSError, ValueError):
        return True
    return phase not in {"completed", "failed", "rolled_back", "recovery_failed"}


def _uid_exists(u: int) -> bool:
    try:
        pwd.getpwuid(u)
        return True
    except KeyError:
        return False


def _other_instances(root: Path) -> list[str]:
    out = set()
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            args = [a.decode(errors="replace") for a in (d / "cmdline").read_bytes().split(b"\0") if a]
        except OSError:
            continue
        if len(args) > 3 and args[1].endswith("update/supervisor.py") and "--root" in args:
            r = args[args.index("--root") + 1]
            if Path(r).resolve() != root:
                out.add(r)
    return sorted(out)


def blockers(inv: dict) -> list[str]:
    b = []
    if inv["layout"] == 2:
        b.append("já migrada (layout 2)")
    if not inv["has_systemd"]:
        b.append("systemd ausente")
    if inv["update_journal"]:
        b.append("atualização/recuperação pendente (.netops-update/journal.json): termine-a antes")
    if inv["account"]["exists"] and inv["account"]["uid"] == 0:
        b.append("conta netops com UID 0")
    if inv["account"]["exists"] and inv["account"]["home"] not in (str(inv["root"]), OP_HOME):
        b.append(f"conta netops com HOME inesperado ({inv['account']['home']})")
    if inv["free_bytes"] < 2 * 1024 ** 3:
        b.append("menos de 2 GiB livres")
    if any(s["uid"] != 0 for s in inv["supervisors"]):
        b.append("há console desta pasta rodando com outra conta")
    return b


# --------------------------------------------------------------------------- journal
def journal_path(root: Path) -> Path:
    return BACKUP_BASE / f"{rid.slug(root)}.current"


def load_journal(root: Path) -> dict | None:
    p = journal_path(root)
    if not p.exists():
        return None
    return json.loads((Path(p.read_text().strip()) / "journal.json").read_text())


def save_journal(j: dict) -> None:
    d = Path(j["dir"])
    tmp = d / "journal.json.tmp"
    tmp.write_text(json.dumps(j, indent=2, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    os.replace(tmp, d / "journal.json")


def step(j: dict, name: str, **info) -> None:
    j["steps"].append({"step": name, "at": datetime.now().isoformat(timespec="seconds"), **info})
    save_journal(j)
    say(f"  ✓ {name}")


# --------------------------------------------------------------------------- baseline
def baseline(root: Path, inv: dict) -> dict:
    mid = datetime.now().strftime("%Y%m%d-%H%M%S")
    d = BACKUP_BASE / f"{rid.slug(root)}-{mid}"
    BACKUP_BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(BACKUP_BASE, 0o700)
    d.mkdir(mode=0o700)
    meta = d / "ownership.jsonl"
    with open(meta, "w") as f:
        os.chmod(meta, 0o600)
        for p, st in walk_entries(root):
            f.write(json.dumps([str(p), st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)]) + "\n")
    files = d / "files"
    files.mkdir(mode=0o700)
    for rel in ("network", "core/config", "runs/claude/projects.json", "runs/schedules", ".claude/settings.json",
                ".netops-update/installed.json"):
        src = root / rel
        if src.is_dir():
            shutil.copytree(src, files / rel, symlinks=True, ignore=shutil.ignore_patterns("*.log", "runs"))
        elif src.exists():
            (files / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, files / rel)
    db = root / "runs" / "netops.db"
    if db.exists():
        (files / "runs").mkdir(exist_ok=True)
        src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        dst = sqlite3.connect(str(files / "runs" / "netops.db"))
        src.backup(dst)
        dst.close(); src.close()
    for p in (CRON_FILE, SYSTEM_UNIT, Path("/etc/default/netops-console")):
        if p.exists():
            shutil.copy2(p, d / p.name)
    if subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True).returncode == 0:
        (d / "git-state.txt").write_text(sh("git", "-C", str(root), "status", "--porcelain=v1", "-b", check=False).stdout
                                         + "\nHEAD " + sh("git", "-C", str(root), "rev-parse", "HEAD", check=False).stdout)
    sums = []
    for p in sorted(d.rglob("*")):
        if p.is_file():
            sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(d)}")
    (d / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    (d / "RESTAURAR.txt").write_text(
        "Rollback (antes do commit): sudo python3 -I <root>/scripts/engine/identity/migrate.py rollback --root "
        f"{root}\nownership.jsonl = [caminho, uid, gid, modo] de cada entrada antes da migração.\n"
        "files/ = cópia de network/, core/config, banco (API de backup do SQLite) e configs.\n")
    for p in d.rglob("*"):
        os.chmod(p, 0o700 if p.is_dir() else 0o600)
    j = {"id": mid, "dir": str(d), "root": str(root), "state": "baseline", "inventory": inv, "steps": []}
    save_journal(j)
    journal_path(root).write_text(str(d) + "\n")
    os.chmod(journal_path(root), 0o600)
    return j


# --------------------------------------------------------------------------- passos
def stop_legacy(root: Path, j: dict) -> None:
    inv = j["inventory"]
    if inv["system_unit"]:
        sh("systemctl", "disable", "--now", "netops-console.service", check=False)
    for s in supervisors(root):
        unit = s["unit"]
        if unit.endswith(".service") and unit not in ("netops-console.service",):
            sh("systemctl", "stop", unit, check=False)
        try:
            os.kill(s["pid"], 15)
        except ProcessLookupError:
            pass
    for _ in range(40):
        if not supervisors(root):
            break
        time.sleep(1)
    for s in supervisors(root):
        os.kill(s["pid"], 9)
    step(j, "console root parado", supervisors=inv["supervisors"])
    lines = cron_lines(root)
    if lines and CRON_FILE.exists():
        keep = [ln for ln in CRON_FILE.read_text().splitlines() if ln not in lines]
        if any(ln.strip() and not ln.startswith(("#", "SHELL=", "PATH=", "CRON_TZ=", "MAILTO=")) for ln in keep):
            CRON_FILE.write_text("\n".join(keep) + "\n")
        else:
            CRON_FILE.unlink()
    step(j, "despachante root do agendador retirado", lines=lines)


def as_op(argv: list, cwd=None, input_text=None, check=True) -> subprocess.CompletedProcess:
    uid = pwd.getpwnam(OP_USER).pw_uid
    env = {"PATH": f"{OP_HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
           "HOME": OP_HOME, "USER": OP_USER, "LOGNAME": OP_USER, "LANG": "C.UTF-8",
           "XDG_RUNTIME_DIR": f"/run/user/{uid}", "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}
    return sh("runuser", "-u", OP_USER, "--", *argv, env=env, cwd=cwd, input_text=input_text, check=check)


REQUIRED_PKGS = {"apt": ["dbus-user-session", "sudo", "openssh-sftp-server"],
                 "dnf": ["dbus", "sudo", "openssh-server"], "yum": ["dbus", "sudo", "openssh-server"],
                 "zypper": ["dbus-1", "sudo", "openssh-server"], "pacman": ["dbus", "sudo", "openssh"]}


def ensure_packages(j: dict) -> None:
    """Pacotes que o layout 2 exige (bus do usuário, sudo p/ netops-admin, sftp-server p/ Arquivos root).
    Roda ANTES de parar o console: falhar aqui não derruba nada."""
    pm = next((m for m in ("apt", "dnf", "yum", "zypper", "pacman") if shutil.which("apt-get" if m == "apt" else m)), None)
    if not pm:
        raise SystemExit("ERRO: gerenciador de pacotes não reconhecido")
    if pm == "apt":
        miss = [p for p in REQUIRED_PKGS["apt"]
                if "install ok installed" not in sh("dpkg-query", "-W", "-f=${Status}", p, check=False).stdout]
        if miss:
            env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
            sh("apt-get", "update", "-q", check=False, env=env)
            sh("apt-get", "install", "-y", "-q", "--no-install-recommends", *miss, env=env)
    else:
        miss = REQUIRED_PKGS[pm]
        cmd = {"dnf": ["dnf", "install", "-y"], "yum": ["yum", "install", "-y"],
               "zypper": ["zypper", "--non-interactive", "install"], "pacman": ["pacman", "-S", "--noconfirm", "--needed"]}[pm]
        sh(*cmd, *miss)
    step(j, "pacotes do layout 2 presentes", installed=miss)


def _user_manager_timeout(uid: int) -> None:
    """Máquina lenta (I/O) pode passar dos 90 s padrão para subir o user@UID: dá 5 min só para a conta netops."""
    d = Path(f"/etc/systemd/system/user@{uid}.service.d")
    d.mkdir(parents=True, exist_ok=True)
    (d / "90-netops.conf").write_text("# NetOps: gerenciador do usuário operacional pode demorar em host com I/O alto\n"
                                      "[Service]\nTimeoutStartSec=5min\n")
    sh("systemctl", "daemon-reload", check=False)


def account(j: dict) -> None:
    try:
        pw = pwd.getpwnam(OP_USER)
        j["account_before"] = {"home": pw.pw_dir}
        save_journal(j)                      # rollback precisa saber o HOME antigo mesmo se falhar adiante
        if pw.pw_dir != OP_HOME:
            sh("usermod", "--home", OP_HOME, OP_USER)
    except KeyError:
        j["account_before"] = {"home": None}
        sh("useradd", "--system", "--home-dir", OP_HOME, "--create-home", "--shell", "/bin/bash", "--comment", "NetOps", OP_USER)
    pw = pwd.getpwnam(OP_USER)
    os.makedirs(OP_HOME, exist_ok=True)
    os.chown(OP_HOME, pw.pw_uid, pw.pw_gid)
    os.chmod(OP_HOME, 0o700)
    _user_manager_timeout(pw.pw_uid)
    sh("loginctl", "enable-linger", OP_USER)
    if not Path(f"/run/user/{pw.pw_uid}/bus").exists():   # subiu antes do dbus-user-session: reinicia
        sh("systemctl", "restart", f"user@{pw.pw_uid}.service", check=False)
    for _ in range(300):
        if Path(f"/run/user/{pw.pw_uid}/bus").exists():
            break
        time.sleep(1)
    if not Path(f"/run/user/{pw.pw_uid}/bus").exists():
        raise SystemExit("ERRO: gerenciador systemd do usuário netops não subiu (dbus-user-session?)")
    step(j, f"conta {OP_USER} (HOME {OP_HOME}, linger)", before=j["account_before"])


def chown_tree(root: Path, j: dict) -> None:
    pw = pwd.getpwnam(OP_USER)
    dev = root.lstat().st_dev
    n = 0
    for p, st in walk_entries(root):
        if st.st_dev != dev or st.st_uid not in (0, pw.pw_uid):
            continue
        if st.st_uid != pw.pw_uid or st.st_gid != pw.pw_gid:
            os.lchown(p, pw.pw_uid, pw.pw_gid)
            n += 1
    for priv in (root / ".netops-update",):
        if priv.is_dir():
            os.chmod(priv, 0o700)
    step(j, f"dono de {root} -> {OP_USER}", changed=n)


def copy_profile(root: Path, j: dict) -> None:
    pw = pwd.getpwnam(OP_USER)
    dst = Path(OP_HOME) / ".claude"
    copied = []
    if (ROOT_CLAUDE / "projects").is_dir():
        (dst / "projects").mkdir(parents=True, exist_ok=True)
        for src in sorted((ROOT_CLAUDE / "projects").glob(claude_slug(root) + "*")):
            target = dst / "projects" / src.name
            if target.exists():
                say(f"  ! {target} já existe: mantido (sem sobrescrever)")
                continue
            shutil.copytree(src, target, symlinks=True)
            copied.append(src.name)
        # conversas dos Projetos desta instalação (pastas listadas em runs/claude/projects.json)
        pf = root / "runs" / "claude" / "projects.json"
        if pf.exists():
            try:
                items = json.loads(pf.read_text()).get("projects") or []
            except ValueError:
                items = []
            for it in items:
                pth = it.get("path") if isinstance(it, dict) else None
                if not pth:
                    continue
                src = ROOT_CLAUDE / "projects" / claude_slug(pth)
                if src.is_dir() and not (dst / "projects" / src.name).exists():
                    shutil.copytree(src, dst / "projects" / src.name, symlinks=True)
                    copied.append(src.name)
    if (ROOT_CLAUDE / "settings.json").exists() and not (dst / "settings.json").exists():
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT_CLAUDE / "settings.json", dst / "settings.json")
        copied.append("settings.json")
    for p, st in walk_entries(Path(OP_HOME)):
        os.lchown(p, pw.pw_uid, pw.pw_gid)
    step(j, "perfil da IA (memória e conversas) copiado para /var/lib/netops/.claude", copied=copied)


def write_identity(root: Path, j: dict) -> None:
    sups = j["inventory"]["supervisors"]
    host = sups[0]["host"] if sups else ""
    port = sups[0]["port"] if sups and sups[0]["port"] else "8765"
    extra = {}
    if sups:
        fl = sups[0]["flags"]
        extra = {"NETOPS_UI_TERMINAL": "1" if "--enable-terminal" in fl else "0",
                 "NETOPS_UI_CLAUDE": "1" if "--enable-claude" in fl else "0",
                 "NETOPS_UI_CLAUDE_PERSIST": "1" if "--enable-claude-persist" in fl else "0"}
    path = rid.write(root, OP_USER, OP_HOME, port=port, host=host, extra=extra)
    step(j, f"identidade {path}", host=host, port=port)


def install_units(root: Path, j: dict) -> None:
    src = root / "scripts" / "engine" / "ui" / "systemd"
    Path("/etc/systemd/user").mkdir(parents=True, exist_ok=True)
    for f in ("netops-console@.service", "netops-localadmin@.service"):
        shutil.copy2(src / f, Path("/etc/systemd/user") / f)
        os.chown(Path("/etc/systemd/user") / f, 0, 0)
        os.chmod(Path("/etc/systemd/user") / f, 0o644)
    as_op(["systemctl", "--user", "daemon-reload"])
    as_op(["systemctl", "--user", "enable", rid.unit_name(root)])
    step(j, "unidades de usuário instaladas e habilitadas", unit=rid.unit_name(root))


def start_console(root: Path, j: dict) -> None:
    r = sh(str(root / "scripts" / "engine" / "ui" / "start.sh"), "--yes", check=False)
    say("    " + (r.stdout.strip().splitlines() or [""])[-1])
    ident = rid.load(root)
    host = ident["ui"].get("NETOPS_UI_HOST") or sh("hostname", "-I", check=False).stdout.split()[0]
    port = ident["ui"].get("NETOPS_UI_PORT", "8765")
    ok = False
    for _ in range(90):
        r = sh("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "2", f"http://{host}:{port}/", check=False)
        if r.stdout in ("200", "301", "302", "303", "401", "403"):
            ok = True
            break
        time.sleep(1)
    sups = supervisors(root)
    owner_ok = bool(sups) and all(s["uid"] == pwd.getpwnam(OP_USER).pw_uid for s in sups)
    if not (ok and owner_ok):
        raise SystemExit(f"ERRO: console não confirmou (HTTP={ok}, dono netops={owner_ok}). Rode `rollback`.")
    step(j, f"console no ar como {OP_USER} em http://{host}:{port}/")


def scheduler_and_claude(root: Path, j: dict) -> None:
    py = str(root / ".venv" / "bin" / "python3")
    r = as_op([py, str(root / "scripts" / "engine" / "scheduler" / "cli.py"), "install-cron"], cwd=str(root), check=False)
    step(j, "despachante do agendador no crontab de netops", output=(r.stdout + r.stderr).strip()[-300:])
    if not Path(OP_HOME, ".local", "bin", "claude").exists():
        r = sh("curl", "-fsSL", "--retry", "3", "https://claude.ai/install.sh", check=False)
        if r.returncode == 0:
            as_op(["bash", "-s"], input_text=r.stdout, check=False)
    step(j, "agente claude para netops", present=Path(OP_HOME, ".local", "bin", "claude").exists())


# --------------------------------------------------------------------------- comandos
def cmd_plan(root: Path, a) -> int:
    inv = inventory(root)
    b = blockers(inv)
    print(json.dumps({**inv, "blockers": b}, indent=2, ensure_ascii=False))
    say("\nResumo: " + ("PRONTA para migrar" if not b else "BLOQUEADA: " + "; ".join(b)))
    if inv["other_instances_shared_account"]:
        say("Atenção: outras instalações NetOps rodam nesta máquina (" + ", ".join(inv["other_instances_shared_account"])
            + "). Elas seguem como estão (root); a conta netops será compartilhada quando forem migradas.")
    return 0 if not b else 1


def cmd_apply(root: Path, a) -> int:
    inv = inventory(root)
    b = blockers(inv)
    if b:
        raise SystemExit("BLOQUEADO: " + "; ".join(b))
    if load_journal(root) and load_journal(root)["state"] not in ("rolled_back", "committed"):
        raise SystemExit("ERRO: já existe uma migração em andamento: use status/rollback/commit")
    if not a.yes:
        if not sys.stdin.isatty():
            raise SystemExit("ERRO: confirme com --yes")
        if input(f"Migrar {root} para a conta {OP_USER}? O console cai por ~1 min. [s/N] ").strip().lower() not in ("s", "y"):
            return 1
    say("Baseline...")
    j = baseline(root, inv)
    say(f"  ✓ baseline em {j['dir']}")
    j["state"] = "applying"
    save_journal(j)
    try:
        ensure_packages(j)      # antes de parar o console: falhar aqui não derruba nada
        account(j)              # idem: se o gerenciador do usuário falhar, nada caiu
        stop_legacy(root, j)
        chown_tree(root, j)
        copy_profile(root, j)
        write_identity(root, j)
        install_units(root, j)
        start_console(root, j)
        scheduler_and_claude(root, j)
    except BaseException as e:  # noqa: BLE001
        j["state"] = "failed"
        j["error"] = str(e)
        save_journal(j)
        say(f"\nFALHA: {e}\nJournal e baseline preservados em {j['dir']}. Desfaça com: migrate.py rollback --root {root}")
        return 1
    j["state"] = "applied"
    save_journal(j)
    say(f"\nMigração aplicada. Valide (login, aba Claude: /login, tarefas), REINICIE a máquina e rode:\n"
        f"  sudo python3 -I {root}/scripts/engine/identity/migrate.py commit --root {root}\n"
        f"Administração Local (etapa própria, cofre destrancado):\n"
        f"  sudo python3 -I {root}/scripts/engine/localadmin/provision.py install --root {root}")
    return 0


def cmd_status(root: Path, a) -> int:
    j = load_journal(root)
    print(json.dumps(j or {"state": "nenhuma migração"}, indent=2, ensure_ascii=False)[:20000])
    return 0


def cmd_rollback(root: Path, a) -> int:
    j = load_journal(root)
    if not j or j["state"] in ("committed", "rolled_back"):
        raise SystemExit("ERRO: nada a desfazer (sem migração aberta)")
    d = Path(j["dir"])
    say("Rollback...")
    if rid.config_path(root).exists():
        try:
            as_op(["systemctl", "--user", "disable", "--now", rid.unit_name(root)], check=False)
            as_op(["systemctl", "--user", "disable", "--now", rid.localadmin_unit(root)], check=False)
        except KeyError:
            pass
        rid.config_path(root).rename(d / "identity.env.revertido")
    for _ in range(30):
        if not supervisors(root):
            break
        time.sleep(1)
    n = 0
    with open(d / "ownership.jsonl") as f:
        for line in f:
            p, uid, gid, mode = json.loads(line)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if (st.st_uid, st.st_gid) != (uid, gid):
                os.lchown(p, uid, gid)
                n += 1
            if not stat.S_ISLNK(st.st_mode) and stat.S_IMODE(st.st_mode) != mode:
                os.chmod(p, mode)
    say(f"  ✓ dono/modo restaurados ({n} entradas; arquivos novos ficam como estão)")
    cron_removed = any(st.get("step") == "despachante root do agendador retirado" for st in j.get("steps", []))
    if cron_removed and (d / CRON_FILE.name).exists():
        cur = CRON_FILE.read_text().splitlines() if CRON_FILE.exists() else []
        old = (d / CRON_FILE.name).read_text().splitlines()
        merged = old + [ln for ln in cur if ln not in old]
        CRON_FILE.write_text("\n".join(merged) + "\n")
        os.chmod(CRON_FILE, 0o644)
        try:
            as_op(["bash", "-c", "crontab -l 2>/dev/null | sed '/>>> netops-scheduler/,/<<< netops-scheduler/d' | crontab -"], check=False)
        except KeyError:
            pass
        say("  ✓ despachante root restaurado (e retirado do crontab de netops)")
    before = j.get("account_before") or {}
    if before.get("home") and before["home"] != OP_HOME:
        sh("usermod", "--home", before["home"], OP_USER, check=False)
    stopped = any(st.get("step") == "console root parado" for st in j.get("steps", []))
    if stopped and (d / SYSTEM_UNIT.name).exists():
        sh("systemctl", "enable", "netops-console.service", check=False)
    if supervisors(root):
        say("  ✓ console antigo já está no ar (não foi parado nesta tentativa) — mantido")
    elif (d / SYSTEM_UNIT.name).exists() and "start.sh --yes" not in (d / SYSTEM_UNIT.name).read_text():
        sh("systemctl", "start", "netops-console.service", check=False)
    else:
        sh(str(root / "scripts" / "engine" / "ui" / "start.sh"), "--yes", check=False)
    for _ in range(60):
        if supervisors(root):
            break
        time.sleep(1)
    j["state"] = "rolled_back"
    save_journal(j)
    say("  ✓ console antigo (root) religado. Dados novos preservados; o banco NÃO foi restaurado "
        f"(cópia de antes em {d}/files/runs/netops.db).")
    return 0


def cmd_commit(root: Path, a) -> int:
    j = load_journal(root)
    if not j or j["state"] != "applied":
        raise SystemExit("ERRO: só dá para confirmar uma migração no estado 'applied'")
    sups = supervisors(root)
    if not sups or any(s["uid"] == 0 for s in sups):
        raise SystemExit("ERRO: o console não está rodando como netops — não confirmo")
    j["state"] = "committed"
    j["committed_at"] = datetime.now().isoformat(timespec="seconds")
    save_journal(j)
    journal_path(root).unlink()
    say(f"Migração confirmada. Backup mantido em {j['dir']} (apague quando quiser).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Migração para a conta dedicada netops")
    ap.add_argument("cmd", choices=["plan", "apply", "status", "rollback", "commit"])
    ap.add_argument("--root", default=str(HERE.parents[2]))
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    if os.geteuid() != 0:
        print("ERRO: rode como root: sudo python3 -I scripts/engine/identity/migrate.py " + a.cmd, file=sys.stderr)
        return 2
    root = Path(a.root).resolve()
    return {"plan": cmd_plan, "apply": cmd_apply, "status": cmd_status, "rollback": cmd_rollback,
            "commit": cmd_commit}[a.cmd](root, a)


if __name__ == "__main__":
    raise SystemExit(main())
