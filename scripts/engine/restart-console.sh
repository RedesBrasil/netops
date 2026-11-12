#!/usr/bin/env bash
# Reinício PADRÃO do NetOps Console. Use SEMPRE este script (nunca kill + start.sh à mão).
#
# Garante, nesta ordem: (1) captura host/porta/flags do console em execução; (2) se chamado de
# dentro do próprio console (aba Claude/terminal web), se destaca num cgroup systemd próprio
# para não morrer junto; (3) para o supervisor e ESPERA ele sair e o lock ficar livre;
# (4) sobe via start.sh com as mesmas opções, com tentativas; (5) só termina OK quando o
# HTTP responde. Se falhar, grava o motivo em /tmp/netops-restart.log e sai !=0.
# Causa do incidente de 11/11/2026: o kill esperava só o filho (server.py); o supervisor ainda
# segurava o flock → start.sh recusou ("já existe um console") e o serviço ficou fora.
#
# Uso: scripts/engine/restart-console.sh [--no-detach]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG=/tmp/netops-restart.log
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

if [ "${1:-}" != "--no-detach" ] && [ -z "${NETOPS_RESTART_DETACHED:-}" ]; then
  : >"$LOG"
  if command -v systemd-run >/dev/null; then
    systemd-run --quiet --collect --unit="netops-restart-$(date +%s)" \
      --setenv=NETOPS_RESTART_DETACHED=1 --setenv=HOME="${HOME:-/root}" \
      --setenv=NETOPS_UI_HOME="${NETOPS_UI_HOME:-}" "$0" --no-detach \
      && { echo "Reinício agendado (desacoplado). Acompanhe: tail -f $LOG"; echo "Console volta em ~15 s; aba Claude reconecta sozinha / F5."; exit 0; }
  fi
  setsid nohup "$0" --no-detach >/dev/null 2>&1 < /dev/null &
  echo "Reinício agendado (setsid). Acompanhe: tail -f $LOG"; exit 0
fi

# 1) captura o console atual (supervisor do ROOT)
SUP=$(pgrep -of "update/supervisor.py --root $ROOT --" || true)
HOST=""; PORT=8765; TERM=1; CLAUDE=1; PERSIST="${NETOPS_UI_CLAUDE_PERSIST:-1}"   # persistência: default ON
if [ -n "$SUP" ]; then
  mapfile -d '' ARGS < "/proc/$SUP/cmdline"
  for i in "${!ARGS[@]}"; do
    case "${ARGS[$i]}" in
      --host) HOST="${ARGS[$((i+1))]}";; --port) PORT="${ARGS[$((i+1))]}";;
    esac
  done
  printf '%s\n' "${ARGS[@]}" | grep -qx -- '--enable-terminal' || TERM=0
  printf '%s\n' "${ARGS[@]}" | grep -qx -- '--enable-claude' || CLAUDE=0
  log "console atual: supervisor=$SUP host=$HOST port=$PORT term=$TERM claude=$CLAUDE persist=$PERSIST"
else
  log "nenhum supervisor ativo — subindo com padrões"
fi
[ -z "$HOST" ] && HOST="$(hostname -I | awk '{print $1}')"
export NETOPS_UI_HOST="$HOST" NETOPS_UI_PORT="$PORT" NETOPS_UI_TERMINAL="$TERM" NETOPS_UI_CLAUDE="$CLAUDE" NETOPS_UI_CLAUDE_PERSIST="$PERSIST"
KEY="$(printf '%s' "${NETOPS_UI_DATA_ROOT:-$ROOT}:$HOST:$PORT" | sha256sum | cut -c1-24)"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/netops-ui-$(id -u)/$KEY.lock"

# 2) para: SIGTERM no supervisor, espera ele (e o filho) sumirem; KILL após 30 s
if [ -n "$SUP" ]; then
  sleep 2; kill -TERM "$SUP" 2>/dev/null
  for _ in $(seq 30); do kill -0 "$SUP" 2>/dev/null || break; sleep 1; done
  if kill -0 "$SUP" 2>/dev/null; then log "supervisor não saiu em 30 s — KILL"; pkill -KILL -P "$SUP"; kill -KILL "$SUP"; sleep 1; fi
fi
# 3) espera o lock ficar livre (até 30 s)
for _ in $(seq 30); do
  { exec 8>"$LOCK"; } 2>/dev/null; flock -n 8 && { exec 8>&-; break; }; exec 8>&-; sleep 1
done

# O console NUNCA pode ficar no cgroup deste helper: quando a unidade do helper termina, o systemd
# mata tudo que sobrou nela (foi o 2º erro do incidente de 11/11: console subiu e morreu 1 s depois).
# Por isso sobe numa unidade própria (netops-console-*), que vive até o próximo restart.
launch_console() {
  if command -v systemd-run >/dev/null; then
    systemd-run --quiet --collect --unit="netops-console-$(date +%s)" --working-directory="$ROOT" \
      --setenv=HOME="${HOME:-/root}" --setenv=NETOPS_UI_HOME="${NETOPS_UI_HOME:-}" \
      --setenv=NETOPS_UI_HOST --setenv=NETOPS_UI_PORT --setenv=NETOPS_UI_TERMINAL \
      --setenv=NETOPS_UI_CLAUDE --setenv=NETOPS_UI_CLAUDE_PERSIST \
      --property=StandardOutput=append:"$LOG" --property=StandardError=append:"$LOG" \
      "$ROOT/scripts/engine/ui/start.sh" >>"$LOG" 2>&1 && return 0
    log "systemd-run falhou; usando setsid"
  fi
  ( cd "$ROOT" && setsid nohup scripts/engine/ui/start.sh >>"$LOG" 2>&1 < /dev/null & )
}

# 4) sobe com até 3 tentativas; 5) valida HTTP
for try in 1 2 3; do
  log "subindo (tentativa $try)"
  launch_console
  for _ in $(seq 25); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://$HOST:$PORT/" 2>/dev/null)
    case "$code" in 200|301|302|303|401|403) sleep 8; c2=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://$HOST:$PORT/"); [ "$c2" != "000" ] && { log "OK: console respondendo ($code/$c2) em http://$HOST:$PORT/ e estável após 8 s"; exit 0; }; log "console caiu após subir"; break;; esac
    sleep 1
  done
  log "sem resposta HTTP; aguardando lock e tentando de novo"; sleep 5
done
log "FALHA: console NÃO subiu. Suba manualmente: NETOPS_UI_HOST=$HOST NETOPS_UI_CLAUDE_PERSIST=$PERSIST scripts/engine/ui/start.sh"
exit 1
