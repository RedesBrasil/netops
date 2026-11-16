#!/usr/bin/env python3
"""Gerencia as chaves dedicadas de tarefas agendadas (ver scripts/engine/lib/taskkeys.py).

  task_key.py provision --task <id> --hosts 16,35 [--mode ro|rw]   # cria a chave e autoriza nos equipamentos
  task_key.py test      --task <id>                                 # prova que a chave funciona e que o resto é negado
  task_key.py list                                                  # chaves existentes e fila de revogação
  task_key.py revoke-pending                                        # remove dos equipamentos as chaves de tarefas apagadas
  task_key.py delete    --task <id>                                 # apaga a chave (e enfileira a revogação)

provision/revoke-pending alteram equipamentos: precisam do cofre destrancado UMA vez (usam session.py,
com backup pré/pós via change.py). O uso diário da chave (task_exec.py) não precisa do cofre.
"""
import argparse, base64, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()

from lib import taskkeys  # noqa: E402
import task_exec  # noqa: E402

PY = sys.executable
SESSION = [PY, str(ROOT / "scripts/tools/access/session.py"), "exec"]
CHANGE = [PY, str(ROOT / "scripts/tools/backup/change.py")]
WRAPPER = ROOT / "scripts/tools/access/ro_shell.py"

# roda no equipamento: tira as linhas da tarefa e (opcional) acrescenta a nova — escreve NO LUGAR (authorized_keys do
# Proxmox é symlink para o pmxcfs, que não aceita rename)
REMOTE_AK = """
import os,sys
p=os.path.expanduser('~/.ssh/authorized_keys'); mark=sys.argv[1]; new=sys.argv[2] if len(sys.argv)>2 else ''
os.makedirs(os.path.dirname(p),mode=0o700,exist_ok=True)
old=open(p).read().splitlines() if os.path.exists(p) else []
keep=[l for l in old if mark not in l]+([new] if new else [])
open(p,'w').write('\\n'.join(keep)+'\\n'); os.chmod(os.path.realpath(p),0o600)
print('authorized_keys: %d -> %d linhas'%(len(old),len(keep)))
"""


def sess(host_id: int, cmd: str, timeout: int = 60) -> str:
    p = subprocess.run(SESSION + ["--host-id", str(host_id), "--timeout", str(timeout), "--command", cmd],
                       capture_output=True, text=True, cwd=ROOT)
    out = p.stdout + p.stderr
    if "exit=0" not in out:
        raise SystemExit(f"falha no host {host_id}: {out[-400:]}")
    return out


def b64(s: str | bytes) -> str:
    return base64.b64encode(s.encode() if isinstance(s, str) else s).decode()


def run_ak(host_id: int, mark: str, new: str = "") -> str:
    args = f"'{mark}'" + (f" '{new}'" if new else "")
    return sess(host_id, f"echo {b64(REMOTE_AK)} | base64 -d | python3 - {args}")


def install_wrapper(host_id: int) -> None:
    data = b64(WRAPPER.read_bytes())
    sess(host_id, "rm -f /tmp/.netops-ro.b64")
    for i in range(0, len(data), 3000):
        sess(host_id, f"printf %s '{data[i:i + 3000]}' >> /tmp/.netops-ro.b64")
    sess(host_id, f"base64 -d /tmp/.netops-ro.b64 > {taskkeys.FORCED} && chmod 755 {taskkeys.FORCED} && rm -f /tmp/.netops-ro.b64 "
                  f"&& python3 {taskkeys.FORCED} --check 'docker ps | head -3'")


def with_backup(host_id: int, fn):
    b = subprocess.run(CHANGE + ["begin", "--host-id", str(host_id)], capture_output=True, text=True, cwd=ROOT)
    if b.returncode != 0:
        raise SystemExit(f"backup pré falhou no host {host_id} — nada foi alterado:\n{(b.stdout + b.stderr)[-400:]}")
    try:
        return fn()
    finally:
        subprocess.run(CHANGE + ["end", "--host-id", str(host_id)], capture_output=True, text=True, cwd=ROOT)


def cmd_provision(a) -> int:
    hosts = [int(x) for x in a.hosts.split(",")]
    pub = taskkeys.generate(ROOT, a.task)
    acc = taskkeys.load_access(ROOT, a.task) or {"task": a.task, "hosts": []}
    for h in hosts:
        def go():
            if a.mode == "ro":
                install_wrapper(h)
            print(f"host {h}:", run_ak(h, taskkeys.MARK + a.task, taskkeys.authorized_line(pub, a.mode)).splitlines()[0])
        with_backup(h, go)
        c, pin = task_exec.connect(a.task, h, learn=True)
        c.close()
        acc["hosts"] = [x for x in acc["hosts"] if x["host_id"] != h] + [
            {"host_id": h, "mode": a.mode, "fingerprint": pin.seen, "provisioned": datetime.now().isoformat(timespec="seconds")}]
        taskkeys.save_access(ROOT, a.task, acc)
    return cmd_test(a)


def cmd_test(a) -> int:
    acc = taskkeys.load_access(ROOT, a.task)
    ok = True
    for h in acc.get("hosts", []):
        c, _ = task_exec.connect(a.task, h["host_id"])
        def run(cmd):
            _, o, e = c.exec_command(cmd, timeout=30)
            return o.channel.recv_exit_status(), (o.read() + e.read()).decode(errors="replace").strip()
        c1, o1 = run("uptime")
        c2, o2 = run("touch /tmp/netops-ro-teste")
        c3, _ = run("ls /tmp/netops-ro-teste")
        c.close()
        good = c1 == 0 and (h["mode"] != "ro" or (c2 != 0 and c3 != 0))
        ok &= good
        print(f"host {h['host_id']} [{h['mode']}] leitura={'OK' if c1 == 0 else 'FALHOU'} "
              f"escrita={'NEGADA' if c2 != 0 else 'PERMITIDA'} -> {'OK' if good else 'PROBLEMA'}")
    return 0 if ok else 1


def cmd_list(a) -> int:
    kr = taskkeys.keys_root(ROOT)
    for d in sorted(kr.iterdir()) if kr.exists() else []:
        if d.is_dir():
            acc = taskkeys.load_access(ROOT, d.name)
            print(d.name, [(h["host_id"], h["mode"]) for h in acc.get("hosts", [])])
    print("revogação pendente:", taskkeys.pending_revocations(ROOT) or "nenhuma")
    return 0


def cmd_revoke(a) -> int:
    left = []
    for item in taskkeys.pending_revocations(ROOT):
        rest = []
        for h in item["hosts"]:
            try:
                with_backup(h, lambda: print(f"host {h}:", run_ak(h, taskkeys.MARK + item["task_id"]).splitlines()[0]))
            except SystemExit as e:
                print(f"host {h}: pendente ({str(e)[:120]})"); rest.append(h)
        if rest:
            left.append({"task_id": item["task_id"], "hosts": rest})
    taskkeys.save_revocations(ROOT, left)
    return 0 if not left else 1


def cmd_delete(a) -> int:
    print("apagada" if taskkeys.delete(ROOT, a.task) else "não existe")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("provision"); p.add_argument("--task", required=True); p.add_argument("--hosts", required=True)
    p.add_argument("--mode", choices=["ro", "rw"], default="ro")
    for n in ("test", "delete"):
        sp.add_parser(n).add_argument("--task", required=True)
    sp.add_parser("list"); sp.add_parser("revoke-pending")
    a = ap.parse_args()
    return {"provision": cmd_provision, "test": cmd_test, "list": cmd_list, "revoke-pending": cmd_revoke, "delete": cmd_delete}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
