#!/usr/bin/env python3
"""Usa segredos do Cofre de senhas em comandos SEM gravá-los em arquivo e SEM mostrá-los.

Referência (vai no .env, no export ou no --set, no lugar do valor). <ID> = número do item no console
(#vault/<ID>; não muda se o título mudar); o campo vai em slug ("API key" -> api-key):
    COOLIFY_TOKEN=nvault://3/api-key                          # valor inteiro
    DATABASE_URL=postgres://app:{{nvault://7/senha}}@db:5432/app   # embutido
IDs antigos em slug (formato anterior) e nomes antigos de campo continuam resolvendo (apelidos).

`run` resolve as referências (cofre destrancado), injeta SÓ no ambiente do processo filho e mascara
(`***`) qualquer segredo que apareça na saída. A IA usa as chaves sem nunca ver o valor.

    python3 scripts/tools/secrets/run.py run -- npx wrangler deploy          # lê ./.env sozinho
    python3 scripts/tools/secrets/run.py run --env-file app/.env -- npm start
    python3 scripts/tools/secrets/run.py run --item 3 --prefix COOLIFY_ -- sh -c 'curl -H "Authorization: Bearer $COOLIFY_API_KEY" "$COOLIFY_URL/api/v1/servers"'
    python3 scripts/tools/secrets/run.py list            # itens e referências (nunca valores)
    python3 scripts/tools/secrets/run.py check           # confere as referências do ./.env

Códigos de saída: o do comando; 2 = referência/argumento inválido; 3 = cofre trancado/não iniciado;
4 = sem permissão (usuário do console sem vault.use).
"""
from __future__ import annotations

import argparse
import os
import re
import select
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))            # scripts/tools
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()

PROJECT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path(os.environ.get("NETOPS_UI_DATA_ROOT") or PROJECT)
VAULT_FILE = DATA_ROOT / "network" / "vault.yaml"
CREDS_FILE = DATA_ROOT / "network" / "credentials.yaml"
DB_FILE = DATA_ROOT / "runs" / "netops.db"
SCHEME = "nvault://"
WHOLE_RE = re.compile(r"^nvault://([a-z0-9][a-z0-9-]*)/(.+)$")
EMBED_RE = re.compile(r"\{\{\s*nvault://([a-z0-9][a-z0-9-]*)/([^}]+?)\s*\}\}")
MASK = b"***"
MIN_MASK = 3


class Fail(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- #
# Cofre
# --------------------------------------------------------------------------- #
class Vault:
    """Lê vault.yaml (estrutura) e decifra sob demanda com a chave da sessão."""

    def __init__(self):
        from lib import pwvault
        self.pw = pwvault
        self.data, _ = pwvault.load(VAULT_FILE)
        self._key = None
        self.used: set[str] = set()

    def key(self) -> bytes:
        if self._key is None:
            import yaml
            from lib import vault, vault_session
            try:
                text = CREDS_FILE.read_text(encoding="utf-8") if CREDS_FILE.exists() else ""
                meta = vault.load_meta(yaml.safe_load(text) if text.strip() else {})
                key = vault_session.get_session_key()
                vault.verify_key(key, meta)
            except vault.VaultError as exc:
                raise Fail(3, f"Cofre trancado ou não iniciado ({exc.__class__.__name__}). "
                              "Destranque no console (cadeado no topo) e rode de novo.") from exc
            self._key = key
        return self._key

    def item(self, ref) -> tuple[int, dict]:
        k = self.pw.find_item(self.data, ref)
        if k is None:
            raise Fail(2, f"item '{ref}' não existe no Cofre de senhas (veja: nvault list)")
        return k, self.data["items"][k]

    def field_name(self, item_id: str, ref_field: str) -> tuple[dict, str]:
        k, item = self.item(item_id)
        name = self.pw.find_value_name(self.data, item, ref_field)
        if not name:
            raise Fail(2, f"campo '{ref_field}' sem valor no item {k} ({item.get('title', '')}) (veja: nvault list)")
        return item, name

    def value(self, item_id: str, ref_field: str) -> tuple[str, bool]:
        """(valor em claro, é_segredo). Só o processo filho recebe o valor."""
        from lib import vault
        item, name = self.field_name(item_id, ref_field)
        raw = item["values"][name]
        self.used.add(f"{self.pw.find_item(self.data, item_id)}")
        if vault.is_encrypted(raw):
            return vault.decrypt_value(self.key(), raw), True
        return str(raw), False


def check_permission() -> str:
    """Na aba Claude/terminal do console, NETOPS_USER = quem pediu; exige vault.use (ou admin)."""
    user = os.environ.get("NETOPS_USER", "").strip()
    if not user or not DB_FILE.exists():
        return user
    from lib import accessdb
    try:
        if not accessdb.has_users(DB_FILE):
            return user
        eff = accessdb.effective(DB_FILE, user)
    except Exception:
        return user
    if not eff or not (eff["is_admin"] or "vault.use" in eff["permissions"]):
        raise Fail(4, f"o usuário '{user}' não tem a permissão vault.use (Grupos de acesso).")
    return user


# --------------------------------------------------------------------------- #
# .env
# --------------------------------------------------------------------------- #
def parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            out[k] = v
    return out


def has_ref(v: str) -> bool:
    return isinstance(v, str) and (bool(WHOLE_RE.match(v.strip())) or bool(EMBED_RE.search(v)))


def resolve(v: str, vault: Vault, secrets: list[str]) -> str:
    def take(item, field):
        val, is_secret = vault.value(item, field.strip())
        if is_secret and len(val) >= MIN_MASK:
            secrets.append(val)
        return val
    m = WHOLE_RE.match(v.strip())
    if m:
        return take(m.group(1), m.group(2))
    return EMBED_RE.sub(lambda mm: take(mm.group(1), mm.group(2)), v)


def build_env(args, vault: Vault) -> tuple[dict, list[str], list[str]]:
    env = dict(os.environ)
    names: list[str] = []
    files = [Path(f) for f in args.env_file] if args.env_file else (
        [Path(".env")] if not args.no_dotenv and Path(".env").is_file() else [])
    for f in files:
        if not f.is_file():
            raise Fail(2, f"arquivo não encontrado: {f}")
        for k, v in parse_env_file(f).items():
            if has_ref(v) or k not in env:      # referência do .env vence; valor comum não sobrescreve o ambiente
                env[k] = v
    for item_ref in args.item or []:
        item_id, item = vault.item(item_ref)
        for name in (item.get("values") or {}):
            var = (args.prefix or "") + re.sub(r"[^A-Za-z0-9]+", "_", vault.pw.slugify(name)).upper()
            env[var] = f"{SCHEME}{item_id}/{vault.pw.slugify(name)}"
    for s in args.set or []:
        if "=" not in s:
            raise Fail(2, f"--set precisa de VAR=REFERENCIA: {s}")
        k, v = s.split("=", 1)
        if not v.startswith(SCHEME) and "{{" not in v and "/" in v:
            v = SCHEME + v                       # atalho: --set TOKEN=item/campo
        env[k.strip()] = v
    secrets: list[str] = []
    for k, v in list(env.items()):
        if has_ref(v):
            env[k] = resolve(v, vault, secrets)
            names.append(k)
    return env, secrets, names


# --------------------------------------------------------------------------- #
# Mascaramento da saída
# --------------------------------------------------------------------------- #
class Masker:
    def __init__(self, secrets: list[str]):
        self.secrets = sorted({s.encode() for s in secrets if len(s) >= MIN_MASK}, key=len, reverse=True)
        self.keep = max((len(s) for s in self.secrets), default=1) - 1
        self.buf = b""

    def _mask(self, data: bytes) -> bytes:
        for s in self.secrets:
            data = data.replace(s, MASK)
        return data

    def _partial_at_end(self, data: bytes) -> int:
        """Tamanho do maior sufixo de `data` que é começo de algum segredo (precisa esperar mais bytes)."""
        best = 0
        for s in self.secrets:
            for n in range(min(len(s) - 1, len(data)), best, -1):
                if data.endswith(s[:n]):
                    best = n
                    break
        return best

    def feed(self, chunk: bytes) -> bytes:
        data = self._mask(self.buf + chunk)
        hold = self._partial_at_end(data)
        self.buf = data[len(data) - hold:] if hold else b""
        return data[:len(data) - hold] if hold else data

    def flush(self) -> bytes:
        data, self.buf = self._mask(self.buf), b""
        return data


def run_masked(cmd: list[str], env: dict, secrets: list[str]) -> int:
    if not secrets:
        return subprocess.call(cmd, env=env)
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=None)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda s, _f: proc.send_signal(s))
    streams = {proc.stdout.fileno(): (Masker(secrets), sys.stdout.buffer),
               proc.stderr.fileno(): (Masker(secrets), sys.stderr.buffer)}
    open_fds = set(streams)
    while open_fds:
        ready, _, _ = select.select(list(open_fds), [], [], 1.0)
        if not ready:                     # ocioso 1 s: solta o que estava retido (prompt, barra de progresso)
            for fd in open_fds:
                masker, out = streams[fd]
                if masker.buf:
                    out.write(masker.flush()); out.flush()
            continue
        for fd in ready:
            masker, out = streams[fd]
            chunk = os.read(fd, 65536)
            if not chunk:
                out.write(masker.flush()); out.flush()
                open_fds.discard(fd)
                continue
            out.write(masker.feed(chunk)); out.flush()
    return proc.wait()


# --------------------------------------------------------------------------- #
# Subcomandos
# --------------------------------------------------------------------------- #
def audit(user: str, target: str, detail: str) -> None:
    if not DB_FILE.exists():
        return
    try:
        from lib import accessdb
        accessdb.audit(DB_FILE, "vault.run", username=user or "cli", target=("item " + target)[:200], detail=detail[:500])
    except Exception:
        pass


def cmd_run(args) -> int:
    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        raise Fail(2, "informe o comando depois de --  (ex.: run.py run -- npx wrangler deploy)")
    user = check_permission()
    vault = Vault()
    env, secrets, names = build_env(args, vault)
    if not names:
        print("aviso: nenhuma referência nvault:// encontrada; rodando o comando sem segredos.", file=sys.stderr)
    else:
        print(f"[nvault] {len(names)} variável(is) do cofre: {', '.join(sorted(names))} (valores mascarados na saída)",
              file=sys.stderr)
        audit(user, ",".join(sorted(vault.used)), f"vars={','.join(sorted(names))} cmd={Path(cmd[0]).name}")
    try:
        return run_masked(cmd, env, secrets)
    except FileNotFoundError:
        raise Fail(2, f"comando não encontrado: {cmd[0]}")


def cmd_list(args) -> int:
    vault = Vault()
    items = vault.data["items"]
    if not items:
        print("Cofre de senhas vazio. Cadastre em Inventário → Cofre de senhas.")
        return 0
    for iid, it in sorted(items.items()):
        extra = (f"  [{it['template_label']}]" if it.get("template_label") else "") + \
                (f"  (apelidos: {', '.join(it['aliases'])})" if it.get("aliases") else "")
        print(f"{iid}  —  {it.get('title', '')}{extra}")
        for name, raw in (it.get("values") or {}).items():
            kind = "segredo" if str(raw).startswith("enc.v1:") else "texto"
            print(f"    {SCHEME}{iid}/{vault.pw.slugify(name):<28} {name} ({kind})")
    return 0


def cmd_check(args) -> int:
    vault = Vault()
    files = [Path(f) for f in args.env_file] if args.env_file else [Path(".env")]
    bad = 0
    for f in files:
        if not f.is_file():
            print(f"{f}: não encontrado"); bad += 1
            continue
        for k, v in parse_env_file(f).items():
            if not has_ref(v):
                continue
            refs = [(m.group(1), m.group(2)) for m in [WHOLE_RE.match(v.strip())] if m] or \
                   [(m.group(1), m.group(2)) for m in EMBED_RE.finditer(v)]
            for item_id, field in refs:
                try:
                    vault.field_name(item_id, field.strip())
                    print(f"OK    {k} -> {SCHEME}{item_id}/{field.strip()}")
                except Fail as e:
                    print(f"ERRO  {k}: {e}"); bad += 1
    return 2 if bad else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Segredos do Cofre de senhas em variáveis de ambiente (sem arquivo, saída mascarada).")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Roda um comando com as referências nvault:// resolvidas")
    r.add_argument("--env-file", action="append", help="Arquivo .env com referências (padrão: ./.env se existir)")
    r.add_argument("--no-dotenv", action="store_true", help="Não ler ./.env automaticamente")
    r.add_argument("--set", action="append", metavar="VAR=REF", help="VAR=nvault://item/campo (ou VAR=item/campo)")
    r.add_argument("--item", action="append", help="Exporta todos os campos do item (API key -> API_KEY)")
    r.add_argument("--prefix", default="", help="Prefixo das variáveis do --item (ex.: COOLIFY_)")
    r.add_argument("command", nargs=argparse.REMAINDER, help="-- comando e argumentos")
    sub.add_parser("list", help="Itens e referências disponíveis (nunca mostra valores)")
    c = sub.add_parser("check", help="Confere as referências de um .env (não decifra)")
    c.add_argument("--env-file", action="append")
    args = p.parse_args()
    try:
        return {"run": cmd_run, "list": cmd_list, "check": cmd_check}[args.cmd](args)
    except Fail as e:
        print(f"[nvault] ERRO: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    raise SystemExit(main())
