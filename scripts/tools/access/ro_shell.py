#!/usr/bin/env python3
"""netops-ro-shell — comando forçado (authorized_keys `command=`) das chaves de tarefa agendada SOMENTE LEITURA.

Instalado nos equipamentos como /usr/local/sbin/netops-ro-shell. Recebe o comando em SSH_ORIGINAL_COMMAND,
valida (lista de permissão por comando/subcomando, sem redirecionamento para arquivo, sem substituição
perigosa, sem arquivos sensíveis) e só então executa com /bin/bash -c. Tudo é registrado no syslog.

É uma segunda barreira (defesa em profundidade), não um sandbox: a chave dá acesso de leitura a logs e
estado do sistema. Só biblioteca padrão; python3 >= 3.8.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys

try:
    import syslog
except ImportError:  # pragma: no cover
    syslog = None

MAX_LEN = 2000

# comandos sem restrição de argumentos (além das proibições globais)
SIMPLE = set("""uptime nproc free vmstat grep egrep fgrep zgrep head tail sort uniq cut wc ps df du ss ls stat
uname hostname date id whoami lsblk lscpu iostat mpstat sar top dmesg lsof findmnt mount nstat zcat tr seq sleep
echo printf true false test [ ] cat readlink basename dirname nvme smartctl lvs vgs pvs zpool lsmod getconf
pveversion uptime tac rev nl column fold expand paste comm diff cmp md5sum sha256sum who w last ethtool""".split())

DENY_TOKEN = re.compile(
    r"(\.env\b|shadow|gshadow|id_rsa|id_ed25519|id_ecdsa|authorized_keys|\.ssh\b|\.pem\b|\.key\b|printenv|"
    r"Config\.Env|/proc/[^ ]*/environ|credentials|secret|passwd\b|\.netrc|\.pgpass|vault|\.kube|\.aws|\.docker/config)",
    re.I,
)

KEYWORDS_CMD_AFTER = {"do", "then", "else", "elif", "while", "until", "if", "{", "!", "time"}
KEYWORDS_SKIP = {"done", "fi", "}", "esac"}


class Denied(Exception):
    pass


def _deny(msg: str):
    raise Denied(msg)


def _check_cat_like(argv):
    pass  # caminhos sensíveis já cobertos por DENY_TOKEN


def _check_docker(argv):
    sub = next((a for a in argv[1:] if not a.startswith("-")), "")
    ok = {"ps", "stats", "logs", "inspect", "top", "port", "images", "info", "version", "diff", "events"}
    if sub in ok:
        if sub == "events" and "--until" not in argv:
            _deny("docker events sem --until")
        return
    if sub in ("network", "volume", "system", "container", "image"):
        rest = argv[argv.index(sub) + 1:]
        if rest and rest[0] in ("ls", "inspect", "df", "list", "stats", "top", "logs", "port", "history"):
            return
    if sub == "exec":
        i = argv.index("exec") + 1
        while i < len(argv) and argv[i].startswith("-"):
            if argv[i] in ("-u", "--user", "-w", "--workdir", "-e", "--env"):
                if argv[i] in ("-e", "--env"):
                    _deny("docker exec -e")
                i += 1
            i += 1
        i += 1  # container
        inner = argv[i:]
        if not inner:
            _deny("docker exec sem comando")
        _check_simple_command(inner)
        return
    _deny(f"docker {sub or '?'} não permitido")


def _check_pct(argv):
    if len(argv) > 1 and argv[1] in ("list", "status", "config", "listsnapshot"):
        return
    _deny("pct: só list/status/config")


def _check_qm(argv):
    if len(argv) > 1 and argv[1] in ("list", "status", "config", "listsnapshot"):
        return
    _deny("qm: só list/status/config")


def _check_pvesm(argv):
    if len(argv) > 1 and argv[1] in ("status", "list"):
        return
    _deny("pvesm: só status/list")


def _check_systemctl(argv):
    sub = next((a for a in argv[1:] if not a.startswith("-")), "")
    if sub in ("status", "is-active", "is-enabled", "is-failed", "list-units", "list-timers",
               "list-unit-files", "show", "list-sockets", "cat"):
        return
    _deny(f"systemctl {sub or '?'}")


def _check_journalctl(argv):
    for a in argv[1:]:
        if a.startswith(("--vacuum", "--rotate", "--flush", "--sync", "--relinquish", "--smart-relinquish", "--setup-keys",
                         "--rotate", "--update-catalog", "--verify")):
            _deny("journalctl de escrita")


def _check_dmesg(argv):
    for a in argv[1:]:
        if a in ("-c", "-C", "--clear", "--read-clear", "-D", "--console-off", "-E", "--console-on", "-n", "--console-level"):
            _deny("dmesg de escrita")


def _check_sysctl(argv):
    for a in argv[1:]:
        if a in ("-w", "--write", "-p", "--load", "--system") or "=" in a:
            _deny("sysctl de escrita")


def _check_ip(argv):
    words = [a for a in argv[1:] if not a.startswith("-")]
    if not words or words[0] in ("a", "addr", "address", "route", "r", "link", "l", "neigh", "n", "rule", "maddr", "netns"):
        if any(w in ("add", "del", "delete", "set", "flush", "change", "replace", "append") for w in words):
            _deny("ip de escrita")
        return
    _deny("ip: subcomando")


def _check_curl(argv):
    bad = {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-X", "--request", "-T", "--upload-file",
           "-F", "--form", "-K", "--config", "-O", "--remote-name", "-u", "--user", "-H"}
    for i, a in enumerate(argv[1:], 1):
        if a in bad or a.startswith(("--data", "--form")):
            _deny("curl com corpo/método/auth")
        if a in ("-o", "--output") and (i + 1 >= len(argv) or argv[i + 1] != "/dev/null"):
            _deny("curl -o só para /dev/null")
    urls = [a for a in argv[1:] if re.match(r"^https?://", a)]
    for u in urls:
        host = re.split(r"[/$:]", re.sub(r"^https?://", "", u))[0]
        if host not in ("localhost", "127.0.0.1", "atendimento.coolify.redesbrasil.com.br"):
            _deny(f"curl só para localhost/atendimento ({host})")
    if not urls:
        _deny("curl sem URL")


def _check_find(argv):
    for a in argv[1:]:
        if a in ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls", "-fprint0"):
            _deny("find de escrita/execução")


def _check_sed(argv):
    for a in argv[1:]:
        if a.startswith("-i") or a == "--in-place" or re.search(r"(^|;|\s)[0-9$,]*[we]\s", a):
            _deny("sed de escrita")


def _check_awk(argv):
    for a in argv[1:]:
        if re.search(r"system\s*\(|getline|\|\s*\"|>\s*\"|print\s*>|printf\s*>", a):
            _deny("awk com execução/redirecionamento")


def _check_ping(argv):
    if "-c" not in argv and not any(a.startswith("-c") for a in argv):
        _deny("ping exige -c")
    if "-f" in argv:
        _deny("ping -f")


def _check_smartctl(argv):
    for a in argv[1:]:
        if a in ("-s", "--smart", "-t", "--test", "-X", "--abort", "-C", "--captive"):
            _deny("smartctl de escrita")


def _check_nvme(argv):
    sub = argv[1] if len(argv) > 1 else ""
    if sub not in ("list", "smart-log", "id-ctrl", "id-ns", "error-log", "list-subsys"):
        _deny("nvme: somente leitura")


def _check_zpool(argv):
    if len(argv) < 2 or argv[1] not in ("status", "list", "iostat", "get", "history", "events"):
        _deny("zpool: somente leitura")


def _check_mount(argv):
    if len(argv) > 1:
        _deny("mount com argumentos")


def _check_top(argv):
    if "-b" not in argv:
        _deny("top exige -b")


def _check_timeout(argv):
    i = 1
    while i < len(argv) and (argv[i].startswith("-") or re.match(r"^[0-9.]+[smhd]?$", argv[i])):
        i += 1
    inner = argv[i:]
    if not inner:
        _deny("timeout sem comando")
    _check_simple_command(inner)


def _check_py_spy(argv):
    if len(argv) < 2 or argv[1] not in ("dump", "top"):
        _deny("py-spy: só dump")


def _check_ps(argv):
    pass


def _check_ethtool(argv):
    for a in argv[1:]:
        if a.startswith("-") and a not in ("-S", "-i", "-k", "--statistics", "--driver", "--show-features", "-g", "-c"):
            _deny("ethtool de escrita")


SPECIAL = {
    "docker": _check_docker, "pct": _check_pct, "qm": _check_qm, "pvesm": _check_pvesm, "systemctl": _check_systemctl,
    "journalctl": _check_journalctl, "dmesg": _check_dmesg, "sysctl": _check_sysctl, "ip": _check_ip, "curl": _check_curl,
    "find": _check_find, "sed": _check_sed, "awk": _check_awk, "gawk": _check_awk, "mawk": _check_awk, "ping": _check_ping,
    "smartctl": _check_smartctl, "nvme": _check_nvme, "zpool": _check_zpool, "mount": _check_mount, "top": _check_top,
    "timeout": _check_timeout, "py-spy": _check_py_spy, "ethtool": _check_ethtool,
}
ALLOWED = SIMPLE | set(SPECIAL) | {"journalctl", "sysctl", "find", "sed", "awk", "gawk", "mawk"}


def _check_simple_command(argv: list[str]) -> None:
    cmd = os.path.basename(argv[0])
    if "/" in argv[0] and not argv[0].startswith(("/usr/bin/", "/bin/", "/usr/sbin/", "/sbin/", "/usr/local/bin/")):
        _deny(f"caminho de executável não permitido: {argv[0]}")
    if cmd not in ALLOWED:
        _deny(f"comando não permitido: {cmd}")
    fn = SPECIAL.get(cmd)
    if fn:
        fn(argv)


def validate(command: str) -> None:
    """Levanta Denied se o comando não for 100% leitura."""
    if not command or not command.strip():
        _deny("comando vazio")
    if len(command) > MAX_LEN:
        _deny("comando longo demais")
    if "\n" in command or "\r" in command or "\x00" in command:
        _deny("quebra de linha não permitida")
    if "`" in command:
        _deny("crase não permitida")
    if DENY_TOKEN.search(command):
        _deny("referência a arquivo/dado sensível")
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError as e:
        _deny(f"sintaxe: {e}")
    exp: list[str] = []
    for t in tokens:     # separa operadores colados (ex.: `);`)
        if t and set(t) <= set(";|&()<>"):
            exp += re.findall(r"&&|\|\||;;|\|&|>>|>&|&>|<&|[;|&()<>]", t)
        else:
            exp.append(t)
    tokens = exp
    # `$(` dentro de aspas não vira token de pontuação: bloqueia
    for t in tokens:
        if "$(" in t or "${" in t and "}" not in t:
            _deny("substituição de comando entre aspas")
    cmd: list[str] = []
    stack: list[list[str]] = []
    expect = True        # próximo token é início de comando
    in_for_head = False
    depth = 0
    i = 0
    n = len(tokens)

    def flush():
        nonlocal cmd
        if cmd:
            _check_simple_command(cmd)
        cmd = []

    while i < n:
        t = tokens[i]
        if set(t) <= set(";|&()<>"):   # token de operador
            if t in (";", "|", "&&", "||", ";;", "|&"):
                flush(); expect = True
                if t == ";":
                    in_for_head = False
            elif t == "(":
                stack.append(cmd); cmd = []; expect = True; depth += 1
            elif t == ")":
                flush(); expect = False; depth -= 1
                if depth < 0:
                    _deny("parêntese")
                cmd = stack.pop()
            elif t in (">", ">>", ">&", "&>", "<&"):
                nxt = tokens[i + 1] if i + 1 < n else ""
                if nxt in ("/dev/null", "&1", "&2", "1", "2") or (t == ">&" and nxt in ("1", "2")):
                    i += 1       # redirecionamento inofensivo
                else:
                    _deny("redirecionamento para arquivo")
            elif t == "&":
                _deny("processo em segundo plano")
            else:
                _deny(f"operador não permitido: {t}")
            i += 1
            continue
        if in_for_head:
            i += 1
            continue
        if expect:
            if t == "for":
                in_for_head = True; i += 1; expect = False; continue
            if t in KEYWORDS_CMD_AFTER:
                i += 1; continue
            if t in KEYWORDS_SKIP:
                flush(); i += 1; expect = False; continue
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):   # VAR=valor cmd
                i += 1; continue
            expect = False
        if t in KEYWORDS_SKIP and not cmd:
            i += 1; continue
        if t in ("do", "then", "else", "elif") and not cmd:
            expect = True; i += 1; continue
        cmd.append(t)
        i += 1
    flush()
    if depth != 0:
        _deny("parênteses desbalanceados")


def log(msg: str) -> None:
    if syslog:
        syslog.openlog("netops-ro-shell")
        syslog.syslog(msg[:900])


def main() -> int:
    cmd = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    who = (os.environ.get("SSH_CONNECTION") or "?").split(" ")[0]
    if len(sys.argv) > 2 and sys.argv[1] == "--check":    # modo de teste: valida sem executar
        try:
            validate(sys.argv[2]); print("OK"); return 0
        except Denied as e:
            print(f"NEGADO: {e}"); return 3
    try:
        validate(cmd)
    except Denied as e:
        log(f"NEGADO de {who}: {e} :: {cmd}")
        sys.stderr.write(f"netops-ro-shell: comando negado ({e}). Esta chave é somente leitura.\n")
        return 126
    log(f"OK de {who}: {cmd}")
    return subprocess.call(["/bin/bash", "-c", cmd])


if __name__ == "__main__":
    sys.exit(main())
