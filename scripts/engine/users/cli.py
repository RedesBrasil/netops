#!/usr/bin/env python3
"""CLI de usuários do console NetOps (banco de acesso SQLite: runs/netops.db).

Uso normal = tela Sistema → Usuários. Este CLI é o caminho de RECUPERAÇÃO (admin esqueceu a senha,
desativou a si mesmo, apagou o grupo errado) e de automação. Roda como root no servidor — quem tem
shell aqui já é dono de tudo. Senha nunca por argumento: getpass (entrada oculta) ou --password-stdin.

Subcomandos:
    list                         usuários, grupos, último login, sessões abertas
    groups                       grupos de acesso e permissões
    add <e-mail> [--groups g1,g2] [--admin] [--name "Nome"] [--temp] [--id joao]   (login = e-mail)
    passwd <id|e-mail> [--temp]       define senha nova (derruba as sessões; --temp = troca obrigatória)
    reset-admin [--user admin] [--email a@b.com]   cria/reativa o admin e define senha nova
    disable <id|e-mail> | enable <id|e-mail> | delete <id|e-mail>
    sessions [--user u] | logout <id|e-mail>|--all
    audit [--user u] [--action a] [--limit 50]
    snapshot <destino.db>        cópia consistente do banco (segura com o console no ar)
    setup-link [--port N] [--hours 24]   gera (de novo) o link do PRIMEIRO ACESSO (#setup?token=...)

--data-root: raiz de dados (padrão: NETOPS_UI_DATA_ROOT ou a raiz do projeto).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto

from lib import accessdb, i18n  # noqa: E402

NETOPS_ROOT = Path(__file__).resolve().parents[3]


def _db(args) -> Path:
    root = Path(args.data_root or os.environ.get("NETOPS_UI_DATA_ROOT") or NETOPS_ROOT).resolve()
    return root / "runs" / "netops.db"


def _ts(v) -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(v)) if v else "—"


def _password(args, prompt=None) -> str:
    if getattr(args, "password_stdin", False):
        pw = sys.stdin.readline().rstrip("\n")
    else:
        if not sys.stdin.isatty():
            sys.exit(i18n.t("cli_users.needs_tty"))
        pw = getpass.getpass(prompt or i18n.t("cli_users.prompt_new_password"))
        if pw != getpass.getpass(i18n.t("cli_users.prompt_confirm")):
            sys.exit(i18n.t("cli_users.passwords_mismatch"))
    accessdb.check_password_policy(pw)
    return pw


def _vault_key(args) -> bytes | None:
    """Chave do cofre se ele estiver destrancado (p/ já criar o keyslot do usuário)."""
    try:
        import yaml  # noqa: PLC0415
        from lib import vault, vault_session  # noqa: PLC0415
        root = _db(args).parents[1]
        meta = vault.load_meta(yaml.safe_load((root / "network" / "credentials.yaml").read_text()) or {})
        key = vault_session.get_session_key()
        vault.verify_key(key, meta)
        return key
    except Exception:
        return None


def cmd_list(args):
    users = accessdb.list_users(_db(args))
    if not users:
        print(i18n.t("cli_users.no_users"))
        return
    print(f"{i18n.t('cli_users.col_email'):<34} {'ID':<16} {i18n.t('cli_users.col_groups'):<22} {i18n.t('cli_users.col_active'):<6} "
          f"{i18n.t('cli_users.col_last_login'):<17} {i18n.t('cli_users.col_sessions'):<7} {i18n.t('cli_users.col_vault')}")
    for u in users:
        print(f"{u['email'] or i18n.t('cli_users.no_email'):<34} {u['username']:<16} {','.join(u['groups']):<22} {i18n.t('cli_users.no') if u['disabled'] else i18n.t('cli_users.yes'):<6} "
              f"{_ts(u['last_login']):<17} {u['sessions']:<7} {'slot' if u['vault_slot'] else '—'}")


def cmd_groups(args):
    for g in accessdb.list_groups(_db(args)):
        perms = i18n.t("cli_users.all_perms") if "*" in g["permissions"] else ", ".join(g["permissions"]) or "—"
        print(i18n.t("cli_users.group_line", name=g["name"], builtin=i18n.t("cli_users.builtin_suffix") if g["builtin"] else "",
                     description=g["description"], perms=perms, net=", ".join(g["net_perms"]) or "—",
                     members=", ".join(g["members"]) or "—"))


def cmd_add(args):
    groups = [g for g in (args.groups or "").split(",") if g]
    if args.admin:
        groups.append(accessdb.ADMIN_GROUP)
    pw = _password(args)
    u = accessdb.create_user(_db(args), args.id, pw, email=args.email, display_name=args.name or "", groups=groups,
                             must_change=args.temp, created_by="cli", vault_key=_vault_key(args), require_email=True)
    accessdb.audit(_db(args), "user_created", username="cli", target=u["username"], detail=f"{u['email']} via CLI")
    print(i18n.t("cli_users.user_created", email=u["email"], id=u["username"], groups=", ".join(u["groups"]) or "—"))


def _uid(args) -> str:
    """Aceita o ID interno ou o e-mail (login)."""
    u = accessdb.login_username(_db(args), args.user)
    if not u:
        sys.exit(i18n.t("cli_users.user_not_found", user=args.user))
    return u


def cmd_passwd(args):
    args.user = _uid(args)
    pw = _password(args)
    accessdb.set_password(_db(args), args.user, pw, must_change=args.temp, vault_key=_vault_key(args))
    accessdb.audit(_db(args), "password_reset", username="cli", target=args.user, detail="via CLI")
    print(i18n.t("cli_users.password_set", user=args.user))


def cmd_reset_admin(args):
    db = _db(args)
    user = args.user
    pw = _password(args, i18n.t("cli_users.prompt_new_password_for", user=user))
    if accessdb.get_user(db, user) is None:
        accessdb.create_user(db, user, pw, display_name="Administrador", email=args.email or "",
                             groups=[accessdb.ADMIN_GROUP], created_by="cli reset-admin", vault_key=_vault_key(args))
    else:
        cur = accessdb.get_user(db, user)
        groups = sorted(set(cur["groups"]) | {accessdb.ADMIN_GROUP})
        with accessdb.connect(db, write=True) as c:   # direto: recuperação ignora as travas de "si mesmo"
            c.execute("UPDATE users SET disabled=0 WHERE username=?", (user,))
            c.execute("DELETE FROM user_groups WHERE username=?", (user,))
            c.executemany("INSERT INTO user_groups(username, group_name) VALUES(?,?)", [(user, g) for g in groups])
        accessdb.set_password(db, user, pw, must_change=False, vault_key=_vault_key(args))
        if args.email:
            accessdb.update_user(db, user, email=args.email)
    accessdb.audit(db, "reset_admin", username="cli", target=user, detail="via CLI")
    print(i18n.t("cli_users.admin_reset", user=user))


def cmd_disable(args, flag=True):
    args.user = _uid(args)
    accessdb.update_user(_db(args), args.user, disabled=flag)
    accessdb.audit(_db(args), "user_updated", username="cli", target=args.user,
                   detail="desativado" if flag else "reativado")
    print(i18n.t("cli_users.user_disabled" if flag else "cli_users.user_enabled", user=args.user))


def cmd_delete(args):
    args.user = _uid(args)
    accessdb.delete_user(_db(args), args.user)
    accessdb.audit(_db(args), "user_deleted", username="cli", target=args.user, detail="via CLI")
    print(i18n.t("cli_users.user_deleted", user=args.user))


def cmd_sessions(args):
    for s in accessdb.list_sessions(_db(args), args.user):
        print(i18n.t("cli_users.session_line", id=s["id"], user=f"{s['username']:<16}", ip=f"{s['ip']:<16}",
                     seen=_ts(s["last_seen"]), expires=_ts(s["exp"])))


def cmd_logout(args):
    if args.all:
        accessdb.clear_sessions(_db(args))
        print(i18n.t("cli_users.all_sessions_ended"))
    else:
        print(i18n.t("cli_users.sessions_ended", count=accessdb.drop_user_sessions(_db(args), args.user), user=args.user))


def cmd_audit(args):
    res = accessdb.query_audit(_db(args), username=args.user or "", action=args.action or "", limit=args.limit)
    for i in reversed(res["items"]):
        what = f"{i['method']} {i['path']} -> {i['status']}" if i["action"] == "api" else (i["target"] or i["detail"])
        print(f"{_ts(i['ts'])}  {i['username'] or '—':<14} {i['ip'] or '—':<15} {i['action']:<18} {what}")


def cmd_snapshot(args):
    print(accessdb.snapshot(_db(args), args.dest))


def _ident_port() -> str:
    """Porta do console na identidade da instalação (/etc/netops/instances/<slug>.env), senão 8765."""
    try:
        from lib import runtime_identity as rid  # noqa: PLC0415
        for line in rid.config_path(NETOPS_ROOT).read_text(encoding="utf-8").splitlines():
            if line.startswith("NETOPS_UI_PORT="):
                return line.split("=", 1)[1].strip() or "8765"
    except Exception:  # noqa: BLE001
        pass
    return "8765"


def cmd_setup_link(args):
    """Link de uso único do primeiro acesso. Recusa se o console já tem cofre ou usuário."""
    import re  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    from lib import setup_token  # noqa: PLC0415
    db = _db(args)
    root = db.parents[1]
    creds = root / "network" / "credentials.yaml"
    has_vault = creds.exists() and re.search(r"^vault:", creds.read_text(encoding="utf-8"), re.M)
    if has_vault or (db.exists() and accessdb.has_users(db)):
        sys.exit(i18n.t("cli_users.setup_done"))
    token = setup_token.issue(root, ttl=max(1, int(args.hours)) * 3600)
    if os.geteuid() == 0:   # rodado com sudo: o arquivo é da conta operacional (dona de runs/), não de root
        st = (root / "runs").stat()
        for p in (setup_token.token_path(root).parent, setup_token.token_path(root)):
            os.chown(p, st.st_uid, st.st_gid)
    port = str(args.port or _ident_port())
    try:
        ips = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout.split()
    except Exception:  # noqa: BLE001
        ips = []
    ips = [i for i in ips if not i.startswith("fe80:")] or ["127.0.0.1"]
    if args.quiet:
        for ip in ips:
            print(f"http://{'[' + ip + ']' if ':' in ip else ip}:{port}/#setup?token={token}")
        return
    print(i18n.t("cli_users.setup_link_header", hours=int(args.hours)))
    for ip in ips:
        print(f"  http://{'[' + ip + ']' if ':' in ip else ip}:{port}/#setup?token={token}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=i18n.t("cli_users.description"), formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("groups").set_defaults(fn=cmd_groups)
    p = sub.add_parser("add")
    p.add_argument("email", help=i18n.t("cli_users.help_email"))
    p.add_argument("--id", help=i18n.t("cli_users.help_id"))
    p.add_argument("--groups", default="")
    p.add_argument("--admin", action="store_true")
    p.add_argument("--name")
    p.add_argument("--temp", action="store_true", help=i18n.t("cli_users.help_temp"))
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("passwd")
    p.add_argument("user")
    p.add_argument("--temp", action="store_true")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(fn=cmd_passwd)
    p = sub.add_parser("reset-admin")
    p.add_argument("--user", default="admin")
    p.add_argument("--email", help=i18n.t("cli_users.help_admin_email"))
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(fn=cmd_reset_admin)
    for name, flag in (("disable", True), ("enable", False)):
        p = sub.add_parser(name)
        p.add_argument("user")
        p.set_defaults(fn=lambda a, f=flag: cmd_disable(a, f))
    p = sub.add_parser("delete")
    p.add_argument("user")
    p.set_defaults(fn=cmd_delete)
    p = sub.add_parser("sessions")
    p.add_argument("--user")
    p.set_defaults(fn=cmd_sessions)
    p = sub.add_parser("logout")
    p.add_argument("user", nargs="?")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_logout)
    p = sub.add_parser("audit")
    p.add_argument("--user")
    p.add_argument("--action")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_audit)
    p = sub.add_parser("snapshot")
    p.add_argument("dest")
    p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser("setup-link")
    p.add_argument("--port", type=int)
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--quiet", action="store_true", help=i18n.t("cli_users.help_quiet"))
    p.set_defaults(fn=cmd_setup_link)
    args = ap.parse_args(argv)
    if args.cmd == "logout" and not args.all and not args.user:
        ap.error(i18n.t("cli_users.logout_usage"))
    if args.cmd in ("logout", "sessions") and getattr(args, "user", None):
        args.user = _uid(args)
    try:
        args.fn(args)
    except accessdb.AccessError as exc:
        sys.exit(i18n.t("cli_users.error", detail=exc.detail))


if __name__ == "__main__":
    main()
