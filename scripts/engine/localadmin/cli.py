#!/usr/bin/env python3
"""Administração Local — CLI da conta operacional (`netops`). Ver SKILL.md.

    cli.py status                                   estado (backend, vínculo, cofre) sem segredos
    cli.py exec [--cwd D] [--timeout S] [--scope TXT] -- <argv...>    roda como root (argv)
    cli.py exec --script-file F|-  [...]            roda um script bash como root
    cli.py ensure-host                              cria/repara o host Local protegido no inventário
    cli.py store-credential --stdin                 grava a senha de netops-admin no cofre (instalador/rotate)

A IA usa o acesso Local pela fachada oficial: `scripts/tools/access/session.py exec --host-id <ID-LOCAL> ...`.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()
sys.path.insert(0, str(HERE))

import common  # noqa: E402
from common import CREDENTIAL, LOCAL_HOSTNAME, LocalAdminError  # noqa: E402
from lib import i18n  # noqa: E402
from lib import runtime_identity as rid  # noqa: E402

ROOT = HERE.parents[2]


def _ui():
    sys.path.insert(0, str(ROOT / "scripts" / "engine" / "ui"))
    import deps  # noqa: F401,PLC0415
    from services import credentials_svc, inventory_svc  # noqa: PLC0415
    return inventory_svc, credentials_svc


def cmd_status(_a) -> int:
    import client  # noqa: PLC0415
    st = client.status(ROOT)
    st.pop("type", None)
    print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0 if st.get("ready") else 1


def cmd_exec(a) -> int:
    import client  # noqa: PLC0415
    script = None
    if a.script_file:
        script = sys.stdin.read() if a.script_file == "-" else Path(a.script_file).read_text()
    argv = a.argv[1:] if a.argv and a.argv[0] == "--" else a.argv
    if not argv and not script:
        print(i18n.t("cli_localadmin.exec_usage"), file=sys.stderr)
        return 2
    out = sys.stdout.buffer
    try:
        end = client.run(ROOT, argv=argv or None, script=script, cwd=a.cwd, timeout=a.timeout,
                         scope=a.scope, on_output=lambda d: (out.write(d), out.flush()))
    except LocalAdminError as e:
        print(f"\n[local] ERRO {e.code}: {e.detail}", file=sys.stderr)
        return 3
    flag = " TIMEOUT" if end.get("timeout") else ""
    trunc = " (saída truncada)" if end.get("truncated") else ""
    print(f"\n[local uid={end['effective_uid']} exit={end['exit_code']}{flag} {end.get('duration_s')}s"
          f" op={end['operation_id']}]{trunc}", file=sys.stderr)
    return int(end["exit_code"]) if isinstance(end.get("exit_code"), int) and end["exit_code"] >= 0 else 1


def ensure_host(root=ROOT) -> int:
    """Cria ou repara o host Local (idempotente). Devolve o ID. Exige layout 2."""
    ident = rid.load(root)
    if not ident:
        raise SystemExit(i18n.t("cli_localadmin.legacy_layout"))
    inv, creds = _ui()
    data, rev = inv.load_hosts()
    hosts = data.get("hosts") or []
    mine = [h for h in hosts if str((h.get("access") or {}).get("method", "")).lower() == "local"]
    fields = {"hostname": LOCAL_HOSTNAME, "mgmt_ip": "127.0.0.1", "vendor": "linux", "role": "server",
              "access": {"method": "local"}, "credential": CREDENTIAL, "local_instance": ident["instance_id"],
              "backup_before_change": True,
              "notes": "Este servidor NetOps. Acesso Local (sem SSH): elevação por netops-admin com a senha do "
                       "cofre. Host protegido: não pode ser apagado (desative com provision.py disable)."}
    if mine:
        h = mine[0]
        fix = {k: v for k, v in fields.items() if k not in ("hostname", "notes") and h.get(k) != v}
        if fix:
            inv.update_host(int(h["id"]), fix, None, partial=True, system=True)
        return int(h["id"])
    # o hostname padrão pode já existir num host comum: usa sufixo, nunca reaproveita outro host
    names = {str(h.get("hostname", "")).upper() for h in hosts}
    name, n = LOCAL_HOSTNAME, 2
    while name in names:
        name, n = f"{LOCAL_HOSTNAME}-{n}", n + 1
    created = inv.create_host({**fields, "hostname": name}, rev, system=True)
    return int(created["id"])


def cmd_ensure_host(_a) -> int:
    print(json.dumps({"host_id": ensure_host()}))
    return 0


def _vault_key(meta: dict) -> bytes:
    from lib import vault, vault_session  # noqa: PLC0415
    try:
        k = vault_session.get_session_key()
        vault.verify_key(k, meta)
        return k
    except vault.VaultError:
        pass
    if os.environ.get("NETOPS_MASTER_PASSWORD"):
        k = vault.derive_key(os.environ["NETOPS_MASTER_PASSWORD"], meta)
    else:
        try:
            tty = open("/dev/tty", "r+")
        except OSError:
            raise vault.VaultLocked(i18n.t("cli_localadmin.vault_locked_no_tty"))
        with tty:
            k = vault.derive_key(getpass.getpass(i18n.t("cli_localadmin.prompt_master"),
                                                 stream=tty), meta)
    vault.verify_key(k, meta)
    return k


def store_credential(password: str, root=ROOT) -> None:
    """Grava CRED_LOCAL_ADMIN (username netops-admin + password cifrada). Nunca imprime o valor."""
    from lib import vault  # noqa: PLC0415
    from vault import cli as vcli  # noqa: PLC0415
    import yaml  # noqa: PLC0415
    _inv, creds = _ui()
    path = root / "network" / "credentials.yaml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    data = yaml.safe_load(text) if text.strip() else {}
    meta = vault.load_meta(data or {})
    key = _vault_key(meta)
    existing = {str(k).upper() for k in ((data or {}).get("credentials") or {})}
    if CREDENTIAL.upper() not in existing:
        creds.create_credential(CREDENTIAL, {"username": common.ADMIN_USER}, None)
        text = path.read_text(encoding="utf-8")
    token = vault.encrypt_value(key, password)
    lines = vcli._set_field(text.splitlines(), CREDENTIAL, "password", token)
    if lines is None:
        raise SystemExit(i18n.t("cli_localadmin.credential_missing"))
    vcli._atomic_write(path, "\n".join(lines) + "\n")


def cmd_store_credential(a) -> int:
    if not a.stdin:
        print(i18n.t("cli_localadmin.use_stdin"), file=sys.stderr)
        return 2
    pw = sys.stdin.readline().rstrip("\n")
    if len(pw) < 16:
        print(i18n.t("cli_localadmin.short_password"), file=sys.stderr)
        return 2
    try:
        store_credential(pw)
    except Exception as e:  # noqa: BLE001
        print(i18n.t("cli_localadmin.error", error=f"{type(e).__name__}: {e}"), file=sys.stderr)
        return 1
    print(i18n.t("cli_localadmin.credential_stored", cred=CREDENTIAL))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=i18n.t("cli_localadmin.description"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    ex = sub.add_parser("exec")
    ex.add_argument("--cwd", default="/root")
    ex.add_argument("--timeout", type=int, default=900)
    ex.add_argument("--scope", default="")
    ex.add_argument("--script-file")
    ex.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("ensure-host")
    sc = sub.add_parser("store-credential")
    sc.add_argument("--stdin", action="store_true")
    a = ap.parse_args(argv)
    try:
        ok, msg = rid.current_ok(rid.load(ROOT))
    except rid.IdentityError as e:
        print(i18n.t("cli_localadmin.error", error=e), file=sys.stderr)
        return 2
    if not ok:
        print(i18n.t("cli_localadmin.error", error=msg), file=sys.stderr)
        return 2
    return {"status": cmd_status, "exec": cmd_exec, "ensure-host": cmd_ensure_host,
            "store-credential": cmd_store_credential}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
