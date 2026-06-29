#!/usr/bin/env python3
"""CLI do cofre de credenciais do NetOps.

Gerencia a criptografia das senhas em network/credentials.yaml com uma senha-mestra.
Nenhum segredo é passado por argumento — tudo via getpass (entrada oculta).

Subcomandos:
    init             Define a senha-mestra (cria o bloco 'vault:').
    encrypt|migrate  Criptografa os valores em texto puro -> 'enc.v1:' (idempotente).
    set              Define/rotaciona um campo secreto de uma credencial.
    unlock           Destranca a sessão (chave na RAM; --env p/ modo terminal-puro).
    lock             Tranca a sessão (apaga o cache).
    status           Estado do cofre e da sessão (não mostra segredos).
    change-password  Troca a senha-mestra e re-criptografa tudo.

A edição preserva comentários/layout do YAML (substituição textual valor-a-valor).
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

# Permite importar scripts/engine/lib/ de qualquer lugar.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NETOPS_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CREDS = NETOPS_ROOT / "network" / "credentials.yaml"
SECRET_FIELDS = ("password", "secret")

_FIELD_RE = re.compile(r"^(?P<indent>\s+)(?P<key>password|secret):[ \t]*(?P<val>.*?)\s*$")


# --------------------------------------------------------------------------- #
# I/O de arquivo (atômico, 0600)
# --------------------------------------------------------------------------- #
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load(path: Path) -> tuple[str, dict]:
    import yaml  # noqa: PLC0415
    if not path.exists():
        sys.exit(f"ERRO: arquivo não encontrado: {path}")
    text = _read(path)
    return text, (yaml.safe_load(text) or {})


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))


def _scalar(raw: str):
    """Converte o lado-direito de uma linha YAML no valor escalar (string)."""
    import yaml  # noqa: PLC0415
    try:
        return yaml.safe_load(raw)
    except Exception:
        return raw.strip().strip('"').strip("'")


def _emit(indent: str, key: str, token: str, comment: str = "") -> str:
    return f'{indent}{key}: "{token}"{comment}'


def _split_comment(val: str) -> str:
    """Comentário inline preservável (só após um valor entre aspas: \"...\"  # comentário)."""
    m = re.match(r'^\s*(?:".*?"|\'.*?\')\s+(#.*)$', val)
    return "   " + m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# Edição do bloco 'vault:' (preservando o resto do arquivo)
# --------------------------------------------------------------------------- #
def _vault_span(lines: list[str]) -> tuple[int, int] | None:
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^vault:\s*$", ln):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln.strip() == "":
            continue
        if not ln.startswith((" ", "\t")):
            end = j
            break
    return start, end


def _fmt_vault(meta: dict) -> list[str]:
    kdf = meta["kdf"]
    out = [
        "# Cofre — gerido por scripts/engine/vault/cli.py. NÃO editar à mão.",
        "vault:",
        f"  version: {meta.get('version', 1)}",
        "  kdf:",
        f"    algorithm: {kdf['algorithm']}",
        f'    salt: "{kdf["salt"]}"',
    ]
    if kdf["algorithm"] == "argon2id":
        out += [
            f"    iterations: {kdf['iterations']}",
            f"    memory_cost: {kdf['memory_cost']}",
            f"    lanes: {kdf['lanes']}",
            f"    length: {kdf['length']}",
        ]
    else:  # scrypt
        out += [
            f"    n: {kdf['n']}",
            f"    r: {kdf['r']}",
            f"    p: {kdf['p']}",
            f"    length: {kdf['length']}",
        ]
    out.append(f'  verifier: "{meta["verifier"]}"')
    return out


def _set_vault_block(text: str, meta: dict) -> str:
    lines = text.splitlines()
    block = _fmt_vault(meta)
    span = _vault_span(lines)
    if span:
        s, e = span
        if s > 0 and lines[s - 1].strip().startswith("# Cofre"):
            s -= 1
        new = lines[:s] + block + [""] + lines[e:]
    else:
        idx = None
        for i, ln in enumerate(lines):
            if re.match(r"^credentials:", ln):
                idx = i
                break
        if idx is None:
            idx = 0
            for i, ln in enumerate(lines):
                if re.match(r"^version:", ln):
                    idx = i + 1
                    break
        new = lines[:idx] + block + [""] + lines[idx:]
    return "\n".join(new) + "\n"


def _iter_secret_lines(lines: list[str]):
    for i, ln in enumerate(lines):
        m = _FIELD_RE.match(ln)
        if m:
            yield i, m


def _set_field(lines: list[str], cred: str, field: str, token: str) -> list[str] | None:
    cred_re = re.compile(rf"^(\s+){re.escape(cred)}:\s*$")
    ci = cred_indent = None
    for i, ln in enumerate(lines):
        m = cred_re.match(ln)
        if m:
            ci, cred_indent = i, len(m.group(1))
            break
    if ci is None:
        return None
    field_re = re.compile(rf"^(\s+){re.escape(field)}:[ \t]*(.*?)\s*$")
    field_indent = cred_indent + 2
    j = ci + 1
    while j < len(lines):
        ln = lines[j]
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            j += 1
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent <= cred_indent:
            break
        if field_re.match(ln):
            lines[j] = _emit(" " * indent, field, token)
            return lines
        field_indent = indent
        j += 1
    lines.insert(ci + 1, _emit(" " * field_indent, field, token))
    return lines


# --------------------------------------------------------------------------- #
# Obtenção da chave (sessão -> prompt)
# --------------------------------------------------------------------------- #
def _key_for_meta(meta: dict, prompt: str = "Senha mestra: ") -> bytes:
    from lib import vault, vault_session  # noqa: PLC0415
    try:
        k = vault_session.get_session_key()
        vault.verify_key(k, meta)
        return k
    except vault.VaultError:
        pass
    if not sys.stdin.isatty():
        raise vault.VaultError(
            "Precisa de um terminal interativo (getpass) ou do cofre destrancado."
        )
    key = vault.derive_key(getpass.getpass(prompt), meta)
    vault.verify_key(key, meta)
    return key


# --------------------------------------------------------------------------- #
# Subcomandos
# --------------------------------------------------------------------------- #
def cmd_init(args) -> int:
    from lib import vault  # noqa: PLC0415
    path: Path = args.file
    if path.exists():
        _text, data = _load(path)
        if data.get("vault"):
            print("ERRO: cofre já inicializado. Use 'change-password'.", file=sys.stderr)
            return 1
        text = _text
    else:
        text = "version: 1\n\ncredentials: {}\n"
    if not sys.stdin.isatty():
        print("ERRO: 'init' precisa de um terminal interativo.", file=sys.stderr)
        return 1
    pw1 = getpass.getpass("Nova senha mestra: ")
    if not pw1:
        print("ERRO: senha vazia.", file=sys.stderr)
        return 1
    if pw1 != getpass.getpass("Confirme a senha mestra: "):
        print("ERRO: as senhas não conferem.", file=sys.stderr)
        return 1
    meta, _key = vault.build_meta(pw1)
    _atomic_write(path, _set_vault_block(text, meta))
    print(f"OK — cofre inicializado em {path}.")
    print("Próximo passo: python scripts/engine/vault/cli.py encrypt")
    return 0


def cmd_encrypt(args) -> int:
    from lib import vault  # noqa: PLC0415
    path: Path = args.file
    text, data = _load(path)
    meta = vault.load_meta(data)
    key = _key_for_meta(meta)
    lines = text.splitlines()
    changed = []
    for i, m in list(_iter_secret_lines(lines)):
        plain = _scalar(m.group("val"))
        if not isinstance(plain, str) or vault.is_encrypted(plain):
            continue
        token = vault.encrypt_value(key, plain)
        if not args.dry_run:
            lines[i] = _emit(m.group("indent"), m.group("key"), token, _split_comment(m.group("val")))
        changed.append(f"{m.group('key')} (linha {i + 1})")
    if args.dry_run:
        print(f"[dry-run] {len(changed)} valor(es) em texto puro seriam criptografados:")
        for c in changed:
            print("  -", c)
        return 0
    _atomic_write(path, "\n".join(lines) + "\n")
    print(f"OK — {len(changed)} valor(es) criptografados em {path}.")
    return 0


def cmd_set(args) -> int:
    from lib import vault  # noqa: PLC0415
    path: Path = args.file
    text, data = _load(path)
    meta = vault.load_meta(data)
    key = _key_for_meta(meta)
    if not sys.stdin.isatty():
        print("ERRO: 'set' precisa de um terminal interativo.", file=sys.stderr)
        return 1
    val = getpass.getpass(f"Valor para {args.cred}.{args.field}: ")
    if val != getpass.getpass("Confirme: "):
        print("ERRO: valores não conferem.", file=sys.stderr)
        return 1
    token = vault.encrypt_value(key, val)
    new_lines = _set_field(text.splitlines(), args.cred, args.field, token)
    if new_lines is None:
        print(
            f"ERRO: credencial '{args.cred}' não encontrada. "
            "Adicione-a (texto puro) e rode 'encrypt'.",
            file=sys.stderr,
        )
        return 1
    _atomic_write(path, "\n".join(new_lines) + "\n")
    print(f"OK — {args.cred}.{args.field} atualizado e criptografado.")
    return 0


def cmd_unlock(args) -> int:
    from lib import vault, vault_session  # noqa: PLC0415
    path: Path = args.file
    _text, data = _load(path)
    meta = vault.load_meta(data)
    if not sys.stdin.isatty():
        print(
            "ERRO: 'unlock' precisa de um terminal interativo (getpass).\n"
            "Peça ao operador para destrancar o cofre nesta máquina.",
            file=sys.stderr,
        )
        return 1
    key = vault.derive_key(getpass.getpass("Senha mestra: "), meta)
    vault.verify_key(key, meta)
    ttl = args.ttl or vault_session.default_ttl()
    if args.env:
        print(f"export {vault_session.ENV_KEY}={vault_session.encode_key(key)}")
        print(
            "# Cofre destrancado SÓ neste shell (modo terminal-puro).\n"
            '# Uso: eval "$(python scripts/engine/vault/cli.py unlock --env)"',
            file=sys.stderr,
        )
        return 0
    p, fallback = vault_session.set_session_key(key, ttl)
    print(f"OK — cofre destrancado. Re-bloqueia após {ttl // 60} min de inatividade, no logout, ou com 'lock'.")
    if fallback:
        print(f"AVISO: cache em {p} pode estar em disco (sem XDG_RUNTIME_DIR/tmpfs).", file=sys.stderr)
    return 0


def cmd_lock(args) -> int:
    from lib import vault_session  # noqa: PLC0415
    existed = vault_session.clear_session()
    print("OK — cofre trancado." if existed else "Já estava trancado.")
    if os.environ.get(vault_session.ENV_KEY):
        print(
            f"AVISO: {vault_session.ENV_KEY} ainda está setada neste shell; "
            f"rode 'unset {vault_session.ENV_KEY}' ou feche o terminal.",
            file=sys.stderr,
        )
    return 0


def cmd_status(args) -> int:
    from lib import vault, vault_session  # noqa: PLC0415
    path: Path = args.file
    initialized, enc, plain = False, 0, 0
    if path.exists():
        text, data = _load(path)
        initialized = bool(data.get("vault"))
        for _i, m in _iter_secret_lines(text.splitlines()):
            v = _scalar(m.group("val"))
            if isinstance(v, str) and vault.is_encrypted(v):
                enc += 1
            else:
                plain += 1
    print(f"Arquivo: {path}")
    print(f"Cofre inicializado: {'sim' if initialized else 'não'}")
    print(f"Campos secretos: {enc} criptografado(s), {plain} em texto puro")

    st = vault_session.session_status()
    state = st["state"]
    if state == "cache":
        secs = st["expires_in"]
        print(f"Sessão: DESTRANCADO (cache, expira em {secs // 60}m{secs % 60:02d}s)")
        if st.get("fallback"):
            print(f"  cache: {st['path']} (em disco)")
        return 0
    if state == "env":
        print(f"Sessão: DESTRANCADO (variável {vault_session.ENV_KEY})")
        return 0
    if state == "insecure":
        print(f"Sessão: PERMISSÕES INSEGURAS — {st['detail']}")
        return 2
    print("Sessão: TRANCADO")
    return 1


def cmd_change_password(args) -> int:
    from lib import vault, vault_session  # noqa: PLC0415
    path: Path = args.file
    text, data = _load(path)
    meta = vault.load_meta(data)
    if not sys.stdin.isatty():
        print("ERRO: 'change-password' precisa de um terminal interativo.", file=sys.stderr)
        return 1
    old_key = vault.derive_key(getpass.getpass("Senha mestra atual: "), meta)
    vault.verify_key(old_key, meta)
    new1 = getpass.getpass("Nova senha mestra: ")
    if not new1:
        print("ERRO: senha vazia.", file=sys.stderr)
        return 1
    if new1 != getpass.getpass("Confirme a nova senha: "):
        print("ERRO: as senhas não conferem.", file=sys.stderr)
        return 1
    new_meta, new_key = vault.build_meta(new1)
    lines = text.splitlines()
    count = 0
    for i, m in list(_iter_secret_lines(lines)):
        plain = _scalar(m.group("val"))
        if isinstance(plain, str) and vault.is_encrypted(plain):
            dec = vault.decrypt_value(old_key, plain)
            lines[i] = _emit(m.group("indent"), m.group("key"), vault.encrypt_value(new_key, dec))
            count += 1
    _atomic_write(path, _set_vault_block("\n".join(lines) + "\n", new_meta))
    vault_session.clear_session()
    print(f"OK — senha mestra trocada; {count} segredo(s) re-criptografado(s). Sessão re-trancada.")
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(prog="vault", description="Cofre de credenciais do NetOps.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--file", type=Path, default=DEFAULT_CREDS,
        help="Arquivo de credenciais (default: network/credentials.yaml)",
    )

    sub.add_parser("init", parents=[common], help="Define a senha-mestra (cria o bloco 'vault:')")
    enc = sub.add_parser("encrypt", parents=[common], aliases=["migrate"],
                         help="Criptografa valores em texto puro -> enc.v1: (idempotente)")
    enc.add_argument("--dry-run", action="store_true", help="Só mostra o que mudaria")
    st = sub.add_parser("set", parents=[common], help="Define/rotaciona um campo secreto")
    st.add_argument("--cred", required=True, help="Nome da credencial (ex.: cred_mikrotik_admin)")
    st.add_argument("--field", required=True, choices=list(SECRET_FIELDS), help="Campo a definir")
    un = sub.add_parser("unlock", parents=[common], help="Destranca a sessão")
    un.add_argument("--ttl", type=int, default=0, help="TTL de inatividade em segundos (default: config/900)")
    un.add_argument("--env", action="store_true", help="Modo terminal-puro: imprime export NETOPS_VAULT_KEY")
    sub.add_parser("lock", parents=[common], help="Tranca a sessão (apaga o cache)")
    sub.add_parser("status", parents=[common], help="Estado do cofre e da sessão")
    sub.add_parser("change-password", parents=[common], help="Troca a senha-mestra e re-criptografa")

    args = parser.parse_args()
    from lib.vault import VaultError  # noqa: PLC0415
    dispatch = {
        "init": cmd_init, "encrypt": cmd_encrypt, "migrate": cmd_encrypt, "set": cmd_set,
        "unlock": cmd_unlock, "lock": cmd_lock, "status": cmd_status,
        "change-password": cmd_change_password,
    }
    try:
        return dispatch[args.cmd](args)
    except VaultError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
