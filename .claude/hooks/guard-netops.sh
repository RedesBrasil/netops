#!/usr/bin/env bash
# NetOps — PreToolUse guard (Bash). Bloqueia comandos perigosos registrados na memória.
#
#   e só devolve +x a `if*`, `/opt/unetlab/scripts/*` e `*_wrapper*` → ZERA o +x do
#
# Entrada: JSON no stdin com .tool_input.command. Saída: exit 2 = bloqueia (msg vai ao modelo).

input=$(cat)

cmd=$(printf '%s' "$input" | python3 -c 'import sys,json
try:
    print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception:
    print("")' 2>/dev/null)

# Backup antes de alterar equipamento (memory/feedback-backup-antes-de-alterar.md):
# `session.py run|exec --host-id N` com comando que ALTERA config exige `change.py begin` antes.
if printf '%s' "$cmd" | grep -Eq 'access/session\.py[[:space:]]+(run|exec)'; then
  hid=$(printf '%s' "${cmd#*access/session.py}" | grep -Eo -- '--host-id[ =][0-9]+' | head -1 | grep -Eo '[0-9]+$')
  if [ -n "$hid" ] && printf '%s' "$cmd" | grep -Eiq -- '--command[ =]+["'"'"']?[^|]*(^|[ /"'"'"'])(add|set|remove|unset|enable|disable|move|import|reset|configure|conf t|commit|write|wr mem|systemctl (restart|stop|start|reload)|sed -i|rm |mv |cp |tee |apt |qm (set|stop|start|destroy)|pct (set|stop|start|destroy)|sysctl -w|iptables|ip (addr|route|link) (add|del|set))([ "'"'"']|$)'; then
    root="${CLAUDE_PROJECT_DIR:-/opt/netops}"
    # `change.py begin --host-id N && ... session.py ...` no MESMO comando: o && garante a ordem
    # (begin falhou = alteração não roda), então não bloqueia.
    if printf '%s' "$cmd" | grep -Eq -- "change\.py[[:space:]]+begin[[:space:]]+--host-id[ =]$hid([[:space:]]|\$)[^;|]*&&.*access/session\.py"; then
      exit 0
    fi
    if ! msg=$(python3 "$root/scripts/tools/backup/change.py" check --host-id "$hid" 2>&1); then
      printf 'BLOQUEADO: %s\nDepois de TODAS as alterações da sessão rode: python3 scripts/tools/backup/change.py end --host-id %s\n' "$msg" "$hid" >&2
      exit 2
    fi
  fi
fi

exit 0
