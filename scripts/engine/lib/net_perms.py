#!/usr/bin/env python3
"""Permissões de rede (CRUD) — classifica o que um comando faz num EQUIPAMENTO.

Usado pela aba Claude Code (services/claude_svc.py): o usuário marca o que o agente pode
fazer nos equipamentos — Ler/diagnosticar, Criar, Editar, Apagar ("Full" = as 4) — e um hook
PreToolUse(Bash) confere cada chamada de `scripts/tools/access/session.py` antes de rodar.

Critério: "altera o estado do equipamento?". Não altera = `read` (inclui ping/traceroute/torch).
Comando que não dá para classificar com segurança conta como `edit` (na dúvida, é alteração).

É uma GRADE DE PROTEÇÃO contra erro do agente, não uma fronteira de segurança: classifica
por padrão de texto. MikroTik/Cisco/Huawei têm verbos bem definidos (confiável); em shell
Linux há infinitas formas de alterar algo, por isso o desconhecido vira `edit`.

API:
  CATEGORIES, normalize(perms) -> list, is_full(perms) -> bool
  classify(command, dialect) -> set[str]              ("ros" | "netcli" | "shell")
  analyze_bash(bash, host_dialect=callable) -> list[dict]   chamadas de session.py encontradas
  check(bash, allowed, host_dialect=None) -> dict      {"ok", "needed", "missing", "calls"}
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

CATEGORIES = ("read", "create", "edit", "delete")
LABELS = {"read": "Ler e diagnosticar", "create": "Criar", "edit": "Editar", "delete": "Apagar"}
_ORDER = {c: i for i, c in enumerate(CATEGORIES)}


def normalize(perms) -> list[str]:
    """Lista válida, ordenada e sem repetição. None/inválido = Full (comportamento histórico)."""
    if not isinstance(perms, (list, tuple, set)):
        return list(CATEGORIES)
    out = sorted({p for p in perms if p in CATEGORIES}, key=_ORDER.get)
    return out


def is_full(perms) -> bool:
    return set(normalize(perms)) == set(CATEGORIES)


def _sorted(cats) -> list[str]:
    return sorted(set(cats), key=_ORDER.get)


# ------------------------------------------------------------------ MikroTik (RouterOS)
_ROS_READ = {"print", "export", "monitor", "monitor-traffic", "ping", "traceroute", "torch", "get",
             "put", "find", "bandwidth-test", "profile", "scan", "check-for-updates", "quick",
             "flood-ping", "mac-ping", "ip-scan", "speed-test", "len", "typeof", "pick",
             "tostr", "tonum", "toip", "totime", "resolve", "environment", "terminal",
             "inspect", "blink"}
_ROS_CREATE = {"add", "save", "copy", "fetch", "generate"}
_ROS_EDIT = {"set", "enable", "disable", "move", "comment", "edit", "import", "run", "reboot",
             "shutdown", "upgrade", "downgrade", "install", "uninstall", "reset-counters",
             "reset-counters-all", "flush", "start", "stop", "make-static", "release", "renew",
             "cancel", "apply", "sign", "update", "local", "global", "do", "execute", "send",
             "clear", "unschedule", "schedule"}
_ROS_DELETE = {"remove", "unset", "reset-configuration", "reset", "delete", "drop"}
# Navegação/estrutura de script (não altera nada por si só).
_ROS_NEUTRAL = {"if", "foreach", "for", "while", "from", "to", "in", "where", "detail", "terse",
                "value-list", "without-paging", "count-only", "as-value", "file", "proplist",
                "interval", "once", "duration", "count", "address", "else", "true", "false",
                "and", "or", "not"}


def _strip_quotes(s: str) -> str:
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', s)


def _classify_ros(cmd: str) -> set[str]:
    text = _strip_quotes(cmd)
    # palavras "soltas" (não atribuições): `set disabled=yes` -> "set"; `print where x=1` -> "print"
    words = []
    for tok in re.split(r"[\s;\[\]{}()]+", text):
        if not tok or "=" in tok:
            continue
        for part in tok.lstrip(":").split("/"):
            if part:
                words.append(part.lower())
    cats: set[str] = set()
    for w in words:
        if w in _ROS_DELETE:
            cats.add("delete")
        elif w in _ROS_CREATE:
            cats.add("create")
        elif w in _ROS_EDIT:
            cats.add("edit")
        elif w in _ROS_READ:
            cats.add("read")
    if not cats:
        # Caminho sem verbo (ex.: "/system resource") só lista no terminal interativo; via
        # automação, sem verbo conhecido = desconhecido -> trata como alteração.
        return {"edit"}
    return cats


# ------------------------------------------------------- Cisco / Huawei / Datacom (CLI de rede)
_NET_READ_PREFIX = ("show", "sh ", "display", "dis ", "ping", "traceroute", "tracert", "trace ",
                    "terminal ", "term ", "screen-length", "dir", "more ", "who", "whoami",
                    "enable", "configure", "conf t", "conf terminal", "system-view", "sys",
                    "end", "exit", "quit", "return", "do show", "do display", "do ping",
                    "?", "history", "ssh session", "verify ")
_NET_DELETE_PREFIX = ("no ", "undo ", "delete ", "erase ", "clear configuration", "reset saved",
                      "write erase", "remove ")
_NET_EDIT_PREFIX = ("write", "wr", "copy run", "copy running", "save", "reload", "reboot",
                    "commit", "shutdown", "clear ", "reset ", "rollback", "configure replace",
                    "request ", "restart ")


def _classify_netcli(cmd: str) -> set[str]:
    cats: set[str] = set()
    for line in cmd.splitlines() or [cmd]:
        l = line.strip().lower()
        if not l or l.startswith(("!", "#")):
            continue
        if l.startswith(_NET_DELETE_PREFIX) or l.startswith("do no "):
            cats.add("delete")
        elif l.startswith(_NET_EDIT_PREFIX) or l in ("wr", "write", "save", "reload", "reboot", "commit", "shutdown"):
            cats.add("edit")
        elif l.startswith(_NET_READ_PREFIX) or l in ("sys", "dir", "end", "exit", "quit", "return", "enable"):
            cats.add("read")
        else:
            # Linha de configuração: não dá para saber se cria ou altera sem o estado atual.
            # Exige as duas (conservador).
            cats.update(("create", "edit"))
    return cats or {"read"}


# ---------------------------------------------------------------- shell (Linux / Proxmox)
_SH_READ = {"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "zgrep", "zcat", "ls",
            "ll", "stat", "df", "du", "free", "uptime", "top", "htop", "ps", "pgrep", "pidof",
            "ss", "netstat", "ping", "ping6", "traceroute", "traceroute6", "tracepath", "mtr", "dig",
            "nslookup", "host", "lsblk", "blkid", "findmnt", "journalctl", "dmesg", "uname",
            "whoami", "id", "which", "type", "command", "echo", "printf", "wc", "sort", "uniq",
            "cut", "tr", "jq", "yq", "lscpu", "lspci", "lsusb", "lsmod", "dmidecode", "sensors",
            "lsof", "last", "lastlog", "who", "w", "env", "printenv", "pwd", "cd", "test", "[",
            "[[", "true", "false", "sleep", "history", "getent", "column", "diff", "cmp",
            "md5sum", "sha256sum", "sha1sum", "file", "readlink", "realpath", "basename",
            "dirname", "seq", "nproc", "arch", "locale", "timedatectl", "hostnamectl",
            "pveversion", "pvesm", "pvecm", "pvesh", "pvs", "vgs", "lvs", "pvdisplay",
            "vgdisplay", "lvdisplay", "tcpdump", "nmap", "arping", "iperf3", "iperf",
            "ethtool", "arp", "route", "iostat", "vmstat", "mpstat", "sar", "nstat", "bc",
            "expr", "xxd", "hexdump", "strings", "tree", "nc", "telnet", "openssl", "nvme",
            "smartctl", "zpool", "zfs", "mount", "hostname", "date", "dpkg", "rpm", "lspci",
            "set", "export", "source", ".", "local", "read", "wait", "uptime", "awk", "sed",
            "find", "systemctl", "qm", "pct", "ip", "iptables", "ip6tables", "iptables-save",
            "ip6tables-save", "nft", "sysctl", "apt", "apt-get", "apt-cache", "docker",
            "crontab", "curl", "wget", "tar", "xargs", "bash", "sh", "timeout", "sudo", "nice",
            "nohup", "time", "watch", "stdbuf", "ionice", "brctl", "bridge", "ovs-vsctl",
            "virsh", "mysql", "unl_wrapper", "ha-manager", "pvenode", "service", "lvm",
            "conntrack", "chronyc", "ntpq", "resolvectl", "nmcli", "zcat"}
# Comandos cujo efeito depende dos argumentos (tratados em _classify_simple):
_SH_DYNAMIC = {"awk", "sed", "find", "systemctl", "qm", "pct", "ip", "iptables", "ip6tables", "nft",
               "sysctl", "apt", "apt-get", "docker", "crontab", "curl", "wget", "tar", "smartctl",
               "nvme", "zpool", "zfs", "mount", "hostname", "date", "pvesm", "pvecm", "pvesh",
               "ethtool", "route", "arp", "dpkg", "service", "brctl", "bridge", "ovs-vsctl",
               "virsh", "mysql", "unl_wrapper", "ha-manager", "pvenode", "lvm", "conntrack",
               "nmcli", "resolvectl", "timedatectl", "hostnamectl", "set", "export", "openssl",
               "chronyc", "crontab"}
_SH_CREATE = {"touch", "mkdir", "useradd", "adduser", "groupadd", "addgroup", "lvcreate", "vgcreate",
              "pvcreate", "mkfs", "mkswap", "ln", "install", "cp", "rsync", "scp", "git"}
_SH_DELETE = {"rm", "rmdir", "unlink", "shred", "wipefs", "userdel", "deluser", "groupdel",
              "delgroup", "lvremove", "vgremove", "pvremove", "dd"}
_SH_PREFIX = {"sudo", "nice", "nohup", "time", "stdbuf", "ionice", "command", "exec", "then",
              "do", "else", "!", "{", "(", "watch"}
_SH_SKIP = {"for", "while", "until", "case", "esac", "done", "fi", "}", ")", "function", "select",
            "in", ";;", "elif", "if"}

_CTRL = {";", "&&", "||", "|", "&", "\n", "|&", ";;", "(", ")"}
_SAFE_REDIR_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr"}


def _tokens(cmd: str) -> list[str] | None:
    try:
        lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>()")
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return None


def _segments(tokens: list[str]) -> list[list[str]]:
    segs, cur = [], []
    for t in tokens:
        if t in _CTRL:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _sub_action(args: list[str], read=(), create=(), delete=(), edit=None) -> set[str]:
    """Primeiro argumento não-opção decide; `edit=None` = qualquer outro é edição."""
    for a in args:
        if a.startswith("-"):
            continue
        if a in read:
            return {"read"}
        if a in create:
            return {"create"}
        if a in delete:
            return {"delete"}
        return {"edit"}
    return {"read"}


def _classify_simple(words: list[str]) -> set[str]:
    # descarta prefixos (sudo, nice, VAR=x, timeout 10 ...)
    while words:
        w = words[0]
        if w in _SH_PREFIX or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            words = words[1:]
        elif w == "timeout":
            words = words[1:]
            while words and (words[0].startswith("-") or re.match(r"^[0-9.]+[smhd]?$", words[0])):
                words = words[1:]
        elif w in ("env",) and len(words) > 1:
            words = words[1:]
        else:
            break
    if not words:
        return {"read"}
    prog = words[0].rsplit("/", 1)[-1]
    args = words[1:]
    if prog in _SH_SKIP:
        return {"read"}
    if prog in ("bash", "sh", "zsh", "dash") and "-c" in args:
        i = args.index("-c")
        return _classify_shell(args[i + 1]) if i + 1 < len(args) else {"read"}
    if prog in ("bash", "sh", "zsh", "dash", "python", "python3", "perl", "ruby", "node", "php"):
        return {"edit"}   # script/código arbitrário: não dá para saber
    if prog == "xargs":
        rest = [a for a in args if not a.startswith("-")]
        return _classify_simple(rest) if rest else {"read"}
    if prog in _SH_DELETE:
        return {"delete"}
    if prog in _SH_CREATE:
        return {"create"}
    a = set(args)
    if prog == "sed":
        return {"edit"} if any(x.startswith("-i") or x == "--in-place" for x in args) else {"read"}
    if prog == "awk":
        return {"edit"} if "inplace" in " ".join(args) else {"read"}
    if prog == "find":
        if "-delete" in a:
            return {"delete"}
        for flag in ("-exec", "-execdir", "-ok"):
            if flag in a:
                i = args.index(flag)
                sub = [x for x in args[i + 1:] if x not in (";", "+", "{}", "\\;")]
                return _classify_simple(sub) if sub else {"edit"}
        return {"read"}
    if prog in ("systemctl", "service"):
        return _sub_action(args, read=("status", "is-active", "is-enabled", "is-failed", "list-units",
                                       "list-unit-files", "list-timers", "list-sockets", "show", "cat",
                                       "list-dependencies", "get-default", "--version"))
    if prog in ("qm", "pct"):
        return _sub_action(args, read=("list", "status", "config", "pending", "showcmd", "listsnapshot",
                                       "df", "help", "cloudinit", "terminal", "enter"),
                           create=("create", "clone", "restore", "snapshot", "importdisk", "import"),
                           delete=("destroy", "delsnapshot", "unlink", "disk-unlink"))
    if prog in ("pvesm", "pvecm", "pvenode", "ha-manager"):
        return _sub_action(args, read=("status", "list", "nodes", "path", "scan", "config", "help",
                                       "qdevice"),
                           create=("add", "alloc"), delete=("remove", "free", "delnode"))
    if prog == "pvesh":
        return _sub_action(args, read=("get", "ls", "usage", "help"), create=("create",), delete=("delete",))
    if prog == "ip":
        obj = [x for x in args if not x.startswith("-")]
        act = obj[1] if len(obj) > 1 else ""
        if act in ("add", "append"):
            return {"create"}
        if act in ("del", "delete", "flush"):
            return {"delete"}
        if act in ("set", "change", "replace", "save", "restore", "exec", "attach", "detach"):
            return {"edit"}
        return {"read"}
    if prog in ("iptables", "ip6tables"):
        if a & {"-A", "--append", "-I", "--insert", "-N", "--new-chain"}:
            return {"create"}
        if a & {"-D", "--delete", "-F", "--flush", "-X", "--delete-chain", "-Z", "--zero"}:
            return {"delete"}
        if a & {"-R", "--replace", "-P", "--policy", "-E", "--rename-chain"}:
            return {"edit"}
        return {"read"}
    if prog == "nft":
        return _sub_action(args, read=("list", "describe", "monitor", "-c"), create=("add", "create", "insert"),
                           delete=("delete", "flush", "destroy"))
    if prog == "sysctl":
        return {"edit"} if ("-w" in a or "-p" in a or "--system" in a or any("=" in x for x in args)) else {"read"}
    if prog in ("apt", "apt-get", "apt-cache"):
        return _sub_action(args, read=("list", "show", "policy", "search", "depends", "rdepends", "showpkg",
                                       "changelog", "madison", "-s", "--simulate", "check"),
                           create=("install", "download", "source"),
                           delete=("remove", "purge", "autoremove", "clean", "autoclean"))
    if prog == "dpkg":
        if a & {"-l", "-L", "-s", "-S", "--list", "--status", "--search", "--listfiles", "-p", "--print-architecture"}:
            return {"read"}
        if a & {"-r", "--remove", "-P", "--purge"}:
            return {"delete"}
        if a & {"-i", "--install"}:
            return {"create"}
        return {"edit"}
    if prog == "docker":
        return _sub_action(args, read=("ps", "logs", "inspect", "images", "stats", "top", "version", "info",
                                       "port", "diff", "history", "events", "search"),
                           create=("run", "create", "pull", "build", "commit", "tag", "cp"),
                           delete=("rm", "rmi", "prune", "kill"))
    if prog == "crontab":
        return {"read"} if "-l" in a else ({"delete"} if "-r" in a else {"edit"})
    if prog == "curl":
        writes = {"-X", "--request", "-d", "--data", "--data-raw", "--data-binary", "-F", "--form",
                  "-T", "--upload-file", "-o", "--output", "-O", "--remote-name", "--json"}
        if a & writes or any(x.startswith(("-d", "-X", "--data", "-o")) and len(x) > 2 for x in args):
            return {"edit"}
        return {"read"}
    if prog == "wget":
        return {"read"} if ("--spider" in a or "-O-" in a or ("-O" in args and "-" in args)) else {"create"}
    if prog == "tar":
        flags = "".join(x.lstrip("-") for x in args if x.startswith("-") or args.index(x) == 0)
        if "t" in flags or "--list" in a:
            return {"read"}
        if "c" in flags or "--create" in a:
            return {"create"}
        return {"create", "edit"}
    if prog in ("smartctl",):
        return {"edit"} if (a & {"-t", "--test", "-s", "--smart", "-o", "-S", "-X"}) else {"read"}
    if prog == "nvme":
        return _sub_action(args, read=("list", "smart-log", "id-ctrl", "id-ns", "error-log", "get-feature",
                                       "list-subsys", "fw-log", "show-regs", "help", "version"))
    if prog == "zpool":
        return _sub_action(args, read=("status", "list", "iostat", "get", "history", "events", "help"),
                           create=("create", "add", "attach"), delete=("destroy", "remove", "detach", "labelclear"))
    if prog == "zfs":
        return _sub_action(args, read=("list", "get", "help", "diff", "holds", "userspace", "groupspace"),
                           create=("create", "snapshot", "clone", "bookmark"), delete=("destroy",))
    if prog == "mount":
        return {"read"} if not [x for x in args if not x.startswith("-")] or a <= {"-l", "-v"} else {"edit"}
    if prog in ("hostname", "date"):
        ro = ("-f", "-i", "-I", "-a", "-A", "-d", "-R", "-u", "--fqdn", "--iso-8601")
        return {"read"} if all(x.startswith("+") or x in ro for x in args) else {"edit"}
    if prog in ("ethtool",):
        return {"edit"} if (a & {"-s", "-K", "-G", "-A", "-C", "-L", "-E", "-p", "--change"}) else {"read"}
    if prog in ("route", "arp"):
        if a & {"add"}:
            return {"create"}
        if a & {"del", "delete", "-d"}:
            return {"delete"}
        return {"read"}
    if prog in ("brctl", "bridge", "ovs-vsctl", "virsh", "nmcli", "resolvectl", "timedatectl",
                "hostnamectl", "lvm", "conntrack", "chronyc", "openssl"):
        txt = " ".join(args)
        if re.search(r"\b(add|addbr|addif|add-br|add-port|create|define|new)\b", txt):
            return {"create"}
        if re.search(r"\b(del|delete|delbr|delif|del-br|del-port|destroy|undefine|remove|-D|-F|flush)\b", txt):
            return {"delete"}
        if re.search(r"\b(set|set-\S+|modify|start|stop|reboot|shutdown|edit|up|down|reload|restart|connect|disconnect|burst|makestep|-U)\b", txt):
            return {"edit"}
        return {"read"}
    if prog == "mysql":
        txt = " ".join(args).lower()
        if re.search(r"\b(insert|create)\b", txt):
            return {"create"}
        if re.search(r"\b(delete|drop|truncate)\b", txt):
            return {"delete"}
        if re.search(r"\b(update|alter|grant|revoke|replace|set)\b", txt) or "-e" not in a:
            return {"edit"}
        return {"read"}
    if prog == "unl_wrapper":
        return {"edit"}
    if prog in ("set", "export"):
        return {"read"}   # variáveis do próprio shell, não do equipamento
    if prog in _SH_READ:
        return {"read"}
    return {"edit"}   # desconhecido: na dúvida, é alteração


def _classify_shell(cmd: str) -> set[str]:
    toks = _tokens(cmd)
    if toks is None:
        return {"edit"}
    cats: set[str] = set()
    for seg in _segments(toks):
        words: list[str] = []
        i = 0
        while i < len(seg):
            t = seg[i]
            if t in (">", ">>", ">|", "&>", "&>>") or re.match(r"^\d?>{1,2}$", t):
                target = seg[i + 1] if i + 1 < len(seg) else ""
                if target and target not in _SAFE_REDIR_TARGETS and not target.startswith("&"):
                    cats.add("edit" if t.endswith(">>") else "create")
                    if not t.endswith(">>"):
                        cats.add("edit")   # `>` cria OU sobrescreve
                i += 2
                continue
            if t in ("<", "<<", "<<<", "<&", ">&"):
                i += 2
                continue
            if re.match(r"^\d?>&\d$", t):
                i += 1
                continue
            words.append(t)
            i += 1
        if words and words[0] == "tee":
            cats.add("edit" if "-a" in words else "create")
            if "-a" not in words:
                cats.add("edit")
            continue
        if words:
            cats |= _classify_simple(words)
    # $(...) e `...`: classifica o conteúdo também
    for sub in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", cmd):
        inner = sub[0] or sub[1]
        if inner.strip():
            cats |= _classify_shell(inner)
    return cats or {"read"}


def classify(command: str, dialect: str) -> set[str]:
    """Categorias que `command` exige no dialeto do equipamento ("ros" | "netcli" | "shell")."""
    command = (command or "").strip()
    if not command:
        return {"read"}
    if dialect == "ros":
        return _classify_ros(command)
    if dialect == "netcli":
        return _classify_netcli(command)
    return _classify_shell(command)


# ------------------------------------------------------------------ dialeto do host
_ROS_OS = {"routeros", "ros", "swos"}
_SHELL_OS = {"debian", "ubuntu", "centos", "rocky", "alma", "rhel", "fedora", "alpine", "linux",
             "proxmox", "arch", "opensuse", "suse", "freebsd"}
_NETCLI_VENDORS = {"cisco", "huawei", "datacom", "juniper", "fiberhome", "zte", "nokia", "arista",
                   "dell", "hp", "aruba", "extreme", "ubiquiti", "unifi", "tplink", "intelbras",
                   "furukawa", "parks", "vsol", "fortinet"}


def dialect_for(host: dict | None) -> str:
    h = host or {}
    os_ = str(h.get("os") or "").strip().lower()
    vendor = str(h.get("vendor") or "").strip().lower()
    if os_ in _ROS_OS or vendor == "mikrotik":
        return "ros"
    if os_ in _SHELL_OS or vendor in ("linux", "proxmox", "zabbix"):
        return "shell"
    if vendor in _NETCLI_VENDORS:
        return "netcli"
    return "shell"   # o classificador de shell trata desconhecido como edição


def inventory_dialect(root: Path):
    """Callable host_ref -> dialeto, lendo network/hosts.yaml (sem credenciais, sem cofre)."""
    cache: dict = {}

    def _lookup(ref) -> str:
        if ref in cache:
            return cache[ref]
        d = "shell"
        try:
            import yaml  # noqa: PLC0415
            from lib.inventory import resolve_host  # noqa: PLC0415
            hosts = yaml.safe_load((root / "network" / "hosts.yaml").read_text(encoding="utf-8")) or {}
            h, _ = resolve_host(ref, hosts, {}, decrypt=False)
            d = dialect_for(h)
        except Exception:
            d = "unknown"
        cache[ref] = d
        return d
    return _lookup


# ------------------------------------------------------------------ análise do Bash
def _session_calls(tokens: list[str]) -> list[dict]:
    calls = []
    for i, t in enumerate(tokens):
        if not t.endswith("session.py"):
            continue
        rest = tokens[i + 1:]
        sub = rest[0] if rest else ""
        if sub not in ("run", "exec"):
            continue
        call = {"sub": sub, "host_id": None, "host": None, "session": None, "commands": [], "files": []}
        j = 1
        while j < len(rest):
            a = rest[j]
            if a in _CTRL:
                break
            key, _, val = a.partition("=") if a.startswith("--") and "=" in a else (a, "", None)
            if key in ("--host-id", "--host", "--session", "--command", "--commands-file"):
                if val is None:
                    val = rest[j + 1] if j + 1 < len(rest) else ""
                    j += 1
                if key == "--host-id":
                    call["host_id"] = int(val) if str(val).isdigit() else val
                elif key == "--host":
                    call["host"] = val
                elif key == "--session":
                    call["session"] = val
                elif key == "--command":
                    call["commands"].append(val)
                else:
                    call["files"].append(val)
            j += 1
        calls.append(call)
    return calls


def analyze_bash(bash: str, host_dialect=None) -> list[dict]:
    """Acha as chamadas `session.py run|exec` no comando Bash e classifica cada `--command`."""
    if "session.py" not in (bash or ""):
        return []
    toks = _tokens(bash)
    if toks is None:
        return [{"sub": "?", "host_id": None, "host": None, "dialect": "unknown",
                 "commands": [{"command": bash, "needs": ["edit"]}],
                 "needs": ["edit"], "note": "não deu para interpretar o comando (aspas/heredoc)"}]
    out = []
    for c in _session_calls(toks):
        ref = c["host_id"] if c["host_id"] is not None else c["host"]
        dialect = host_dialect(ref) if (host_dialect and ref is not None) else "unknown"
        cmds = list(c["commands"])
        note = None
        for f in c["files"]:
            try:
                cmds.extend(l for l in Path(f).read_text(encoding="utf-8").splitlines() if l.strip())
            except OSError:
                cmds.append(f"<arquivo {f} ilegível>")
                note = "arquivo de comandos ilegível: tratado como alteração"
        items = []
        for cmd in cmds:
            if dialect == "unknown":
                # host não resolvido (ou --session sem host): o pior caso dos três dialetos
                needs = classify(cmd, "ros") | classify(cmd, "netcli") | classify(cmd, "shell")
                needs = needs - {"read"} or {"read"}
            elif cmd.startswith("<arquivo "):
                needs = {"edit"}
            else:
                needs = classify(cmd, dialect)
            items.append({"command": cmd, "needs": _sorted(needs)})
        total = set()
        for it in items:
            total |= set(it["needs"])
        out.append({"sub": c["sub"], "host_id": c["host_id"], "host": c["host"], "session": c["session"],
                    "dialect": dialect, "commands": items, "needs": _sorted(total or {"read"}),
                    **({"note": note} if note else {})})
    return out


def check(bash: str, allowed, host_dialect=None) -> dict:
    """{"ok": bool, "needed": [...], "missing": [...], "calls": [...]} para as permissões `allowed`."""
    allowed_set = set(normalize(allowed))
    calls = analyze_bash(bash, host_dialect)
    needed = set()
    for c in calls:
        needed |= set(c["needs"])
    missing = needed - allowed_set
    return {"ok": not missing, "needed": _sorted(needed), "missing": _sorted(missing), "calls": calls}


def describe(perms) -> str:
    p = normalize(perms)
    if set(p) == set(CATEGORIES):
        return "Full (ler, criar, editar e apagar)"
    return ", ".join(f"{LABELS[c]} {'✔' if c in p else '✘'}" for c in CATEGORIES)
