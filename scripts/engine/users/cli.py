#!/usr/bin/env python3
"""CLI de usuários do console NetOps (banco de acesso SQLite: runs/netops.db).

Uso normal = tela Sistema → Usuários. Este CLI é o caminho de RECUPERAÇÃO (admin esqueceu a senha,
desativou a si mesmo, apagou o grupo errado) e de automação. Roda como root no servidor — quem tem
shell aqui já é dono de tudo. Senha nunca por argumento: getpass (entrada oculta) ou --password-stdin.

Subcomandos:
    list                         usuários, grupos, último login, sessões abertas
    groups                       grupos de acesso e permissões
    add <user> [--groups g1,g2] [--admin] [--name "Nome"] [--temp]
    passwd <user> [--temp]       define senha nova (derruba as sessões; --temp = troca obrigatória)
    reset-admin [--user admin]   cria/reativa o usuário no grupo admin e define senha nova
    disable <user> | enable <user> | delete <user>
    sessions [--user u] | logout <user>|--all
    audit [--user u] [--action a] [--limit 50]
    snapshot <destino.db>        cópia consistente do banco (segura com o console no ar)

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

from lib import accessdb  # noqa: E402

NETOPS_ROOT = Path(__file__).resolve().parents[3]


def _db(args) -> Path:
    root = Path(args.data_root or os.environ.get("NETOPS_UI_DATA_ROOT") or NETOPS_ROOT).resolve()
    return root / "runs" / "netops.db"


def _ts(v) -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(v)) if v else "—"


def _password(args, prompt="Senha nova: ") -> str:
    if getattr(args, "password_stdin", False):
        pw = sys.stdin.readline().rstrip("\n")
    else:
        if not sys.stdin.isatty():
            sys.exit("Precisa de terminal interativo (getpass) ou --password-stdin.")
        pw = getpass.getpass(prompt)
        if pw != getpass.getpass("Confirme: "):
            sys.exit("As senhas não conferem.")
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
        print("Nenhum usuário — console no modo senha-mestra (o 1º login cria o admin).")
        return
    print(f"{'USUÁRIO':<20} {'GRUPOS':<28} {'ATIVO':<6} {'ÚLTIMO LOGIN':<17} {'SESSÕES':<7} COFRE")
    for u in users:
        print(f"{u['username']:<20} {','.join(u['groups']):<28} {'não' if u['disabled'] else 'sim':<6} "
              f"{_ts(u['last_login']):<17} {u['sessions']:<7} {'slot' if u['vault_slot'] else '—'}")


def cmd_groups(args):
    for g in accessdb.list_groups(_db(args)):
        perms = "TUDO" if "*" in g["permissions"] else ", ".join(g["permissions"]) or "—"
        print(f"{g['name']}{' (fixo)' if g['builtin'] else ''}: {g['description']}\n"
              f"  permissões: {perms}\n  rede: {', '.join(g['net_perms']) or '—'}\n"
              f"  membros: {', '.join(g['members']) or '—'}")


def cmd_add(args):
    groups = [g for g in (args.groups or "").split(",") if g]
    if args.admin:
        groups.append(accessdb.ADMIN_GROUP)
    pw = _password(args)
    u = accessdb.create_user(_db(args), args.user, pw, display_name=args.name or "", groups=groups,
                             must_change=args.temp, created_by="cli", vault_key=_vault_key(args))
    accessdb.audit(_db(args), "user_created", username="cli", target=u["username"], detail="via CLI")
    print(f"Usuário {u['username']} criado (grupos: {', '.join(u['groups']) or '—'}).")


def cmd_passwd(args):
    pw = _password(args)
    accessdb.set_password(_db(args), args.user, pw, must_change=args.temp, vault_key=_vault_key(args))
    accessdb.audit(_db(args), "password_reset", username="cli", target=args.user, detail="via CLI")
    print(f"Senha de {args.user} definida; sessões encerradas.")


def cmd_reset_admin(args):
    db = _db(args)
    user = args.user
    pw = _password(args, f"Senha nova para {user}: ")
    if accessdb.get_user(db, user) is None:
        accessdb.create_user(db, user, pw, display_name="Administrador", groups=[accessdb.ADMIN_GROUP],
                             created_by="cli reset-admin", vault_key=_vault_key(args))
    else:
        cur = accessdb.get_user(db, user)
        groups = sorted(set(cur["groups"]) | {accessdb.ADMIN_GROUP})
        with accessdb.connect(db, write=True) as c:   # direto: recuperação ignora as travas de "si mesmo"
            c.execute("UPDATE users SET disabled=0 WHERE username=?", (user,))
            c.execute("DELETE FROM user_groups WHERE username=?", (user,))
            c.executemany("INSERT INTO user_groups(username, group_name) VALUES(?,?)", [(user, g) for g in groups])
        accessdb.set_password(db, user, pw, must_change=False, vault_key=_vault_key(args))
    accessdb.audit(db, "reset_admin", username="cli", target=user, detail="via CLI")
    print(f"{user} ativo, no grupo admin, senha nova definida.")


def cmd_disable(args, flag=True):
    accessdb.update_user(_db(args), args.user, disabled=flag)
    accessdb.audit(_db(args), "user_updated", username="cli", target=args.user,
                   detail="desativado" if flag else "reativado")
    print(f"{args.user} {'desativado' if flag else 'reativado'}.")


def cmd_delete(args):
    accessdb.delete_user(_db(args), args.user)
    accessdb.audit(_db(args), "user_deleted", username="cli", target=args.user, detail="via CLI")
    print(f"{args.user} apagado.")


def cmd_sessions(args):
    for s in accessdb.list_sessions(_db(args), args.user):
        print(f"{s['id']}  {s['username']:<16} {s['ip']:<16} visto {_ts(s['last_seen'])}  expira {_ts(s['exp'])}")


def cmd_logout(args):
    if args.all:
        accessdb.clear_sessions(_db(args))
        print("Todas as sessões encerradas.")
    else:
        print(f"{accessdb.drop_user_sessions(_db(args), args.user)} sessão(ões) de {args.user} encerradas.")


def cmd_audit(args):
    res = accessdb.query_audit(_db(args), username=args.user or "", action=args.action or "", limit=args.limit)
    for i in reversed(res["items"]):
        what = f"{i['method']} {i['path']} -> {i['status']}" if i["action"] == "api" else (i["target"] or i["detail"])
        print(f"{_ts(i['ts'])}  {i['username'] or '—':<14} {i['ip'] or '—':<15} {i['action']:<18} {what}")


def cmd_snapshot(args):
    print(accessdb.snapshot(_db(args), args.dest))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("groups").set_defaults(fn=cmd_groups)
    p = sub.add_parser("add")
    p.add_argument("user")
    p.add_argument("--groups", default="")
    p.add_argument("--admin", action="store_true")
    p.add_argument("--name")
    p.add_argument("--temp", action="store_true", help="senha provisória (troca no 1º login)")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("passwd")
    p.add_argument("user")
    p.add_argument("--temp", action="store_true")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(fn=cmd_passwd)
    p = sub.add_parser("reset-admin")
    p.add_argument("--user", default="admin")
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
    args = ap.parse_args(argv)
    if args.cmd == "logout" and not args.all and not args.user:
        ap.error("logout <usuário> ou --all")
    try:
        args.fn(args)
    except accessdb.AccessError as exc:
        sys.exit(f"erro: {exc.detail}")


if __name__ == "__main__":
    main()
