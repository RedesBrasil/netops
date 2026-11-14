#!/usr/bin/env python3
"""O que um comando Bash REALMENTE executa (e não o que ele só menciona).

Os hooks da aba Claude e o guard-netops.sh precisam saber se um comando roda
`scripts/tools/access/session.py`, `change.py` etc. Procurar o texto no comando dá falso positivo:
`git commit -m "... session.py ..."`, `grep session.py`, heredoc de mensagem, `echo`, comentário…
Aqui o comando é interpretado como o shell faria (aproximação só com stdlib):

  - heredocs (`<<EOF`, `<<'EOF'`, `<<-EOF`) viram stdin do comando, não comandos soltos;
  - aspas simples/duplas, `\\` + quebra de linha, comentários `#`;
  - `;`, `&&`, `||`, `|`, `&`, quebras de linha e subshells separam comandos;
  - prefixos (`sudo`, `env`, `VAR=x`, `timeout 10`, `nice`, `nohup`, `exec`, `xargs`…) são descartados;
  - `bash -c '…'`, `bash <<EOF`, `$(…)` e crases são analisados recursivamente;
  - `python3 script.py` vira "executa script.py"; `python3 -c` / `python3 - <<EOF` vira CÓDIGO
    (devolvido à parte, porque código Python pode chamar qualquer coisa).

Só stdlib: o guard-netops.sh roda com o python3 do sistema, fora do .venv.

API:
  invocations(cmd) -> list[dict]   {"prog": str, "argv": [str], "code": str|None}
  runs_script(cmd, predicate) -> bool
CLI (usado pelo guard-netops.sh; comando no stdin):
  shell_cmds.py --session-call     exit 0 se algum comando executa session.py run|exec; senão 1
"""
from __future__ import annotations

import re
import shlex
import sys

_SHELLS = {"bash", "sh", "dash", "zsh", "ksh"}
_PYTHONS = re.compile(r"^(python|python3(\.\d+)?|pypy3?)$")
_PREFIX = {"sudo", "nice", "nohup", "time", "exec", "command", "builtin", "stdbuf", "ionice",
           "chrt", "taskset", "unbuffer", "setsid", "doas", "then", "do", "else", "elif", "if",
           "while", "until", "!", "{", "}"}
_OPT_ARG = {"sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
            "nice": {"-n"}, "ionice": {"-c", "-n", "-p"}, "stdbuf": {"-i", "-o", "-e"},
            "env": {"-u", "-C", "-S"}, "timeout": {"-s", "-k", "--signal", "--kill-after"},
            "xargs": {"-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s"}}
_CTRL = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "\n"}
_REDIR = re.compile(r"^(\d*|&)(>>?|<|<>|>&|<&|>\|)$")
_HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\?([A-Za-z_][A-Za-z0-9_]*))")
_MAX_DEPTH = 6


def _split_heredocs(cmd: str):
    """Tira os corpos de heredoc do texto. Devolve (texto_sem_corpos, {placeholder: corpo})."""
    lines = cmd.split("\n")
    out, bodies, pending = [], {}, []
    i = 0
    while i < len(lines):
        line = lines[i]
        if pending:
            strip_tabs, delim, key, buf = pending[0]
            check = line.lstrip("\t") if strip_tabs else line
            if check == delim:
                bodies[key] = "\n".join(buf)
                pending.pop(0)
            else:
                buf.append(line)
            i += 1
            continue

        def _sub(m):
            key = f"__NETOPS_HEREDOC_{len(bodies) + len(pending)}__"
            delim = m.group(2) or m.group(3) or m.group(4)
            pending.append((m.group(1) == "-", delim, key, []))
            return f"< {key}"
        # `<<<` (here-string) não é heredoc
        out.append(re.sub(r"(?<!<)" + _HEREDOC.pattern, _sub, line) if "<<" in line and "<<<" not in line
                   else line)
        i += 1
    for strip_tabs, delim, key, buf in pending:   # heredoc sem fim: o shell lê até o EOF
        bodies[key] = "\n".join(buf)
    return "\n".join(out), bodies


def _strip_comments(text: str) -> str:
    """Remove `# …` só onde o bash considera comentário: início de palavra, fora de aspas
    (`http://x/#a`, `${#v}` e `a#b` ficam intactos)."""
    out, i, n, q = [], 0, len(text), None
    while i < n:
        c = text[i]
        if q:
            out.append(c)
            if c == "\\" and q == '"' and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == q:
                q = None
        elif c == "\\" and i + 1 < n:
            out.append(c + text[i + 1])
            i += 2
            continue
        elif c in "'\"":
            q = c
            out.append(c)
        elif c == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
            while i < n and text[i] != "\n":
                i += 1
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _tokens(text: str) -> list[str] | None:
    try:
        text = _strip_comments(text.replace("\\\n", " "))
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|<>()\n")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:   # aspas desbalanceadas etc.
        return None


def _segments(tokens: list[str]) -> list[list[str]]:
    segs, cur = [], []
    for t in tokens:
        if t in _CTRL or (t and set(t) <= set(";&|()\n")):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _strip_prefixes(words: list[str]) -> list[str]:
    while words:
        w = words[0]
        base = w.rsplit("/", 1)[-1]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            words = words[1:]
        elif base in _PREFIX or base in ("env", "timeout", "xargs", "watch", "flock"):
            opts = _OPT_ARG.get(base, set())
            words = words[1:]
            while words and words[0].startswith("-"):
                o = words[0]
                words = words[1:]
                if o in opts and words:
                    words = words[1:]
            if base == "timeout" and words and re.match(r"^[0-9.]+[smhd]?$", words[0]):
                words = words[1:]
            if base == "flock" and words:
                words = words[1:]   # arquivo de lock
            if base == "env":
                while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
                    words = words[1:]
        else:
            break
    return words


def _substitutions(text: str) -> list[str]:
    """Conteúdo de $(…) e crases FORA de aspas simples (lá o shell não executa)."""
    no_single = re.sub(r"'[^']*'", "''", text)
    found = []
    i = 0
    while True:
        j = no_single.find("$(", i)
        if j < 0:
            break
        depth, k = 1, j + 2
        while k < len(no_single) and depth:
            if no_single[k] == "(":
                depth += 1
            elif no_single[k] == ")":
                depth -= 1
            k += 1
        if no_single[j + 2:j + 3] != "(":   # $(( aritmética )) não executa nada
            found.append(no_single[j + 2:k - 1])
        i = k
    found += re.findall(r"`([^`]*)`", no_single)
    return [f for f in found if f.strip()]


def invocations(cmd: str, _depth: int = 0) -> list[dict]:
    """Comandos efetivamente executados por `cmd`: [{"prog", "argv", "code"}]."""
    if _depth > _MAX_DEPTH or not (cmd or "").strip():
        return []
    text, bodies = _split_heredocs(cmd)
    toks = _tokens(text)
    if toks is None:   # não deu p/ interpretar: devolve o texto inteiro como "código" (conservador)
        return [{"prog": "", "argv": [], "code": cmd}]
    out: list[dict] = []
    for seg in _segments(toks):
        words, stdin_body = [], None
        i = 0
        while i < len(seg):
            t = seg[i]
            if _REDIR.match(t):
                target = seg[i + 1] if i + 1 < len(seg) else ""
                if t.endswith("<") and target in bodies:
                    stdin_body = bodies[target]
                i += 2
                continue
            if re.match(r"^\d*>&\d+$|^\d*<&\d+$", t):
                i += 1
                continue
            words.append(t)
            i += 1
        words = _strip_prefixes(words)
        if not words:
            continue
        prog, args = words[0], words[1:]
        base = prog.rsplit("/", 1)[-1]
        if base in _SHELLS:
            if "-c" in args:
                k = args.index("-c")
                if k + 1 < len(args):
                    out += invocations(args[k + 1], _depth + 1)
                continue
            script = next((a for a in args if not a.startswith("-")), None)
            if script:
                out.append({"prog": script, "argv": args[args.index(script) + 1:], "code": None})
            elif stdin_body is not None:
                out += invocations(stdin_body, _depth + 1)
            continue
        if _PYTHONS.match(base):
            k, code, target = 0, None, None
            while k < len(args):
                a = args[k]
                if a == "-c":
                    code = args[k + 1] if k + 1 < len(args) else ""
                    break
                if a == "-m":
                    target = ("-m " + args[k + 1]) if k + 1 < len(args) else "-m"
                    k += 1
                    break
                if a in ("-W", "-X") and k + 1 < len(args):
                    k += 2
                    continue
                if a == "-":
                    code = stdin_body or ""
                    break
                if not a.startswith("-"):
                    target = a
                    break
                k += 1
            if code is None and target is None:
                code = stdin_body or ""
            if code is not None:
                out.append({"prog": prog, "argv": args, "code": code})
            else:
                out.append({"prog": target, "argv": args[k + 1:], "code": None})
            continue
        out.append({"prog": prog, "argv": args, "code": None})
    for sub in _substitutions(text):
        out += invocations(sub, _depth + 1)
    return out


def runs_script(cmd: str, predicate) -> bool:
    return any(predicate(inv) for inv in invocations(cmd))


def session_calls(cmd: str) -> list[list[str]]:
    """argv (depois de `session.py`) de cada execução real de session.py run|exec."""
    return [inv["argv"] for inv in invocations(cmd)
            if inv["code"] is None and str(inv["prog"]).rsplit("/", 1)[-1] == "session.py"
            and inv["argv"][:1] in (["run"], ["exec"])]


_PY_SESSION_RE = re.compile(r"session\.py['\"]?\s*,?\s*['\"]?(run|exec)\b")


def python_calls_session(code: str) -> bool:
    """Código Python que parece chamar `session.py run|exec` (subprocess etc.)."""
    return bool(_PY_SESSION_RE.search(code or ""))


if __name__ == "__main__":
    if sys.argv[1:] == ["--session-call"]:
        src = sys.stdin.read()
        hit = bool(session_calls(src)) or any(inv["code"] is not None and python_calls_session(inv["code"])
                                              for inv in invocations(src))
        sys.exit(0 if hit else 1)
    print(__doc__)
    sys.exit(2)
