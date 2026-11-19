#!/usr/bin/env python3
"""Backup automático antes/depois de uma sessão de mudança num host.

  change.py begin --host-id N [--force]   # backup "pré" (bloqueia a mudança se falhar)
  change.py end   --host-id N             # backup "pós" + diff pré×pós + retenção

Usa o mesmo armazenamento da aba Backups: backups/by-id/<id>/. Só roda se o host tem
`backup_before_change` ligado (padrão p/ mikrotik/cisco/huawei/linux/proxmox; `false` no host/grupo desliga) ou --force.
  change.py check --host-id N   # exit 3 se há backup pendente (usado pelo hook guard-netops.sh)
 Segredos no backup ficam em
texto puro (como o próprio export do equipamento); a credencial de acesso nunca é lida aqui.
Conexão: por padrão reusa a sessão persistente do host (session.py; abre uma se não houver, 1 login por host);
se falhar, cai no login avulso. NETOPS_BACKUP_NO_SESSION=1 força o login avulso.
Retenção: project-config.yaml -> backups.keep_versions (padrão 10 arquivos por host).
"""
import argparse, difflib, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "engine"))
sys.path.insert(0, str(ROOT / "scripts" / "tools"))
sys.path.insert(0, str(ROOT / "scripts" / "engine" / "ui"))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto

import yaml  # noqa: E402
from lib.inventory import resolve_host  # noqa: E402
from lib.cli_runner import run_commands  # noqa: E402
from backup_runner import _strip_ros, _atomic_write  # noqa: E402

STORE = ROOT / "backups" / "by-id"
STATE = ROOT / "runs" / "changes"
LINUX_FILES = "/etc/network/interfaces /etc/hosts /etc/resolv.conf /etc/fstab /etc/ssh/sshd_config /etc/sysctl.conf"
LINUX_CMD = ("for f in %s /etc/pve/*.cfg /etc/pve/nodes/*/host.fw /etc/pve/firewall/*.fw; do "
             "[ -f \"$f\" ] && { echo \"### $f\"; cat \"$f\"; }; done; echo '### iptables-save'; iptables-save 2>/dev/null" % LINUX_FILES)


# Host Local (este servidor; ver scripts/engine/localadmin): baseline mais completo, coletado como root
# pelo serviço netops-localadmin (sem SSH). Inclui o que uma instalação de pacote costuma mudar.
LOCAL_CMD = LINUX_CMD + (
    "; echo '### os-release'; cat /etc/os-release"
    "; echo '### pacotes'; (dpkg-query -W -f='${Package} ${Version}\\n' 2>/dev/null || rpm -qa --qf '%{NAME} %{VERSION}-%{RELEASE}\\n' 2>/dev/null || pacman -Q 2>/dev/null) | sort"
    "; echo '### repositórios'; ls -1 /etc/apt/sources.list.d /etc/yum.repos.d 2>/dev/null"
    "; echo '### serviços habilitados'; systemctl list-unit-files --state=enabled --no-legend --no-pager 2>/dev/null"
    "; echo '### portas em escuta'; ss -ltnu 2>/dev/null | awk 'NR>1{print $1, $5}' | sort -u"
    "; echo '### grupos'; getent group | cut -d: -f1,4 | sort"
    "; echo '### nft'; nft list ruleset 2>/dev/null"
    "; echo '### disco'; df -hP -x tmpfs -x devtmpfs 2>/dev/null")


def _run_local(cmd: str, timeout: int = 300) -> str:
    sys.path.insert(0, str(ROOT / "scripts" / "engine" / "localadmin"))
    import client  # noqa: PLC0415
    from common import LocalAdminError  # noqa: PLC0415
    chunks = []
    try:
        end = client.run(ROOT, script=cmd, cwd="/", timeout=timeout, scope="backup pré/pós (change.py)",
                         on_output=chunks.append)
    except LocalAdminError as e:
        raise SystemExit(f"backup do host Local falhou: {e.code}: {e.detail}")
    if end.get("timeout"):
        raise SystemExit("backup do host Local estourou o tempo")
    return b"".join(chunks).decode(errors="replace").replace("\r\n", "\n")


def collector(vendor: str):
    """(comando, limpeza) por vendor; None = vendor sem coletor."""
    v = vendor.lower()
    if v == "mikrotik":
        return "/export show-sensitive", _strip_ros
    if v == "cisco":
        return "show running-config", str.strip
    if v == "huawei":
        return "display current-configuration", str.strip
    if v in ("linux", "proxmox", "zabbix"):
        return LINUX_CMD, str.strip
    return None


def keep_versions() -> int:
    try:
        cfg = yaml.safe_load((ROOT / "core/config/project-config.yaml").read_text()) or {}
        return max(2, int((cfg.get("backups") or {}).get("keep_versions", 10)))
    except Exception:  # noqa: BLE001
        return 10


def host_info(hid: int):
    hosts = yaml.safe_load((ROOT / "network/hosts.yaml").read_text()) or {}
    h, _ = resolve_host(hid, hosts, {}, decrypt=False)
    return h


def _run_via_session(hid: int, method: str, cmd: str, timeout: int = 120) -> str:
    """Roda `cmd` na sessão persistente do host (reusa a viva ou abre uma: 1 login por host).
    Levanta RuntimeError se não der — o chamador cai no login avulso."""
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("netops_session", ROOT / "scripts/tools/access/session.py")
    sess = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sess)
    sid, msg = sess.acquire_session(hid, method, False)
    if not sid:
        raise RuntimeError(msg)
    res = sess._request(sid, {"op": "exec", "command": cmd, "timeout": timeout,
                              "expect": None, "timing": False}, timeout=timeout + sess.CLIENT_SLACK)
    if res.get("status") != "ok":
        raise RuntimeError(f"sessão devolveu status={res.get('status')}")
    return res.get("output", "")


def _run(hid: int, method: str, cmd: str) -> str:
    """Padrão: sessão persistente já aberta. Falhou → login avulso (comportamento antigo)."""
    if os.environ.get("NETOPS_BACKUP_NO_SESSION") != "1":
        try:
            return _run_via_session(hid, method, cmd)
        except BaseException as exc:  # noqa: BLE001 — inclui SystemExit (cofre trancado etc.)
            print(f"AVISO: sessão persistente indisponível ({exc}); usando login avulso.", file=sys.stderr)
    return run_commands(hid, [cmd], force_method=method, read_timeout=120)[cmd]


def collect(hid: int, h: dict) -> str:
    col = collector(h.get("vendor") or "")
    if not col:
        raise SystemExit(f"vendor '{h.get('vendor')}' sem coletor de backup")
    cmd, clean = col
    method = (h.get("access") or {}).get("method", "ssh")
    if method == "local":
        text = clean(_run_local(LOCAL_CMD))
        if len(text.strip()) < 200 or "### pacotes" not in text:
            raise SystemExit("backup do host Local vazio/incompleto — abortando por segurança")
        return text + "\n"
    if method not in ("ssh", "telnet"):
        raise SystemExit(f"acesso {method} não coleta config — cadastre SSH")
    out = _run(hid, method, cmd)
    if cmd.startswith("/export show-sensitive") and ("expected end of command" in out or "syntax error" in out):
        out = _run(hid, method, "/export")
    text = clean(out)
    if len(text.strip()) < 50:
        raise SystemExit("backup vazio/curto demais — abortando por segurança")
    return text if text.endswith("\n") else text + "\n"


def prune(hid: int) -> int:
    files = sorted(STORE.joinpath(str(hid)).glob("*.cfg"), key=lambda p: p.stat().st_mtime)
    extra = files[:-keep_versions()] if len(files) > keep_versions() else []
    for p in extra:
        p.unlink()
    return len(extra)


def save(hid: int, tag: str, text: str) -> str:
    d = STORE / str(hid)
    d.mkdir(parents=True, exist_ok=True)
    name = f"change-{time.strftime('%Y%m%d-%H%M%S')}-{tag}.cfg"
    _atomic_write(d / name, text, 0o600)
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["begin", "end", "check"])
    ap.add_argument("--host-id", type=int, required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--mode", choices=["snapshot", "none"], help="só CT/VM de Proxmox: snapshot pré-mudança ou sem backup")
    ap.add_argument("--tag", default="", help="CT/VM: rótulo curto no nome do snapshot")
    ap.add_argument("--force-space", action="store_true", help="CT/VM: ignora o bloqueio de espaço do pool")
    a = ap.parse_args()
    hid = a.host_id
    h = host_info(hid)
    STATE.mkdir(parents=True, exist_ok=True)
    marker = STATE / f"{hid}.json"
    flag = h.get("backup_before_change")
    import snapshot as SN  # noqa: PLC0415 — CT/VM de Proxmox usam snapshot, não backup de config
    guest = SN.guest_of(h)
    if flag is None:   # padrão: ligado p/ equipamentos de rede e Linux/Proxmox; false explícito desliga
        flag = guest is not None or collector(h.get("vendor") or "") is not None
    if a.action == "check":   # usado pelo hook: exit 3 = falta rodar `begin` antes de alterar
        if flag and not marker.exists():
            print(f"FALTA BACKUP: rode `python3 scripts/tools/backup/change.py begin --host-id {hid}` antes de alterar o host {hid}.")
            sys.exit(3)
        return
    if not flag and not a.force:
        print(f"SKIP: host {hid} com backup_before_change desligado (use --force para forçar)")
        return
    if guest and a.action == "begin":
        if not a.mode:   # a IA NÃO decide sozinha: precisa perguntar ao usuário (AskUserQuestion)
            print(f"PERGUNTE AO USUÁRIO: o host {hid} é {guest[0].upper().replace('LXC','CT')} {guest[1]} do Proxmox (host {guest[2]}). "
                  "Fazer snapshot antes da mudança? Sim → `change.py begin --host-id %d --mode snapshot [--tag x]`; "
                  "Não → `... --mode none`." % hid)
            sys.exit(4)
        if a.mode == "snapshot":
            snap = SN.create(hid, h, a.tag, force_space=a.force_space)
            marker.write_text(json.dumps({"snapshot": snap, "started": int(time.time())}))
        else:
            marker.write_text(json.dumps({"skipped": True, "started": int(time.time())}))
            print("OK: sem backup (usuário recusou o snapshot)")
        return
    if guest and a.action == "end":
        if not marker.exists():
            raise SystemExit("sessão não iniciada (rode begin antes)")
        m = json.loads(marker.read_text())
        marker.unlink()
        if m.get("snapshot"):
            print(f"OK: mudança encerrada. Snapshot {m['snapshot']} continua no Proxmox.")
            print(f"AÇÃO: avise o usuário que concluiu e PERGUNTE (AskUserQuestion) se apaga o snapshot: "
                  f"`python3 scripts/tools/backup/snapshot.py delete --host-id {hid}` (só após o 'sim').")
        else:
            print("OK: mudança encerrada (sem snapshot).")
        return
    if a.action == "begin":
        name = save(hid, "pre", collect(hid, h))
        marker.write_text(json.dumps({"pre": name, "started": int(time.time())}))
        print(f"OK pre: backups/by-id/{hid}/{name} (podados: {prune(hid)})")
    else:
        if not marker.exists():
            raise SystemExit("sessão não iniciada (rode begin antes)")
        pre = json.loads(marker.read_text())["pre"]
        name = save(hid, "post", collect(hid, h))
        a_txt = (STORE / str(hid) / pre).read_text().splitlines()
        b_txt = (STORE / str(hid) / name).read_text().splitlines()
        diff = list(difflib.unified_diff(a_txt, b_txt, pre, name, lineterm="", n=1))
        marker.unlink()
        print(f"OK post: backups/by-id/{hid}/{name} (podados: {prune(hid)})")
        print(f"DIFF: {sum(1 for l in diff if l[:1] in '+-' and l[:3] not in ('+++','---'))} linhas alteradas")
        print("\n".join(diff[:200]))


if __name__ == "__main__":
    main()
