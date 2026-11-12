#!/usr/bin/env bash
# Único jeito suportado de subir OU reiniciar o NetOps Console (web). Um script só:
#   - console NÃO está rodando -> sobe;
#   - console JÁ está rodando  -> reinicia, preservando host/porta/terminal/claude.
# Em ambos os casos: desacopla (funciona de dentro da aba Claude/terminal web), espera o
# supervisor sair e o lock liberar, tenta até 3 vezes e só termina OK quando o HTTP responde
# (log: /tmp/netops-restart.log). Causa do incidente de 11/11/2026: kill esperava só o filho,
# o supervisor ainda segurava o flock e o console ficou fora — por isso nunca `kill` à mão.
#
# Por que um script (e não `python scripts/engine/ui/server.py` direto):
#   - liga o TERMINAL WEB e a página CLAUDE CODE por padrão (são opt-in — sem o script, as
#     abas "Terminal"/"Claude Code" não aparecem). Desligue com NETOPS_UI_TERMINAL=0 / NETOPS_UI_CLAUDE=0;
#   - garante o PATH do agente `claude` (~/.local/bin) para a página Claude funcionar de fato;
#   - faz bind no IP da máquina (acesso pela rede) e garante UMA instância só.
# Acesso protegido pelo LOGIN com a senha-mestra do cofre (ver server.py).
#
# ATENÇÃO: reiniciar encerra as sessões vivas da aba Claude (a persistência cobre F5/standby,
# não o fim do processo do console). Em terminal interativo o script pede confirmação;
# use --yes para pular. Sem terminal (IA, atualizador) reinicia direto.
#
# Uso:
#   scripts/engine/ui/start.sh                          # sobe, ou reinicia se já estiver rodando
#   scripts/engine/ui/start.sh --yes                    # idem, sem pedir confirmação
#   scripts/engine/ui/start.sh --foreground             # roda em primeiro plano (debug), sem desacoplar
#   NETOPS_UI_HOST=127.0.0.1 scripts/engine/ui/start.sh # força loopback (só local)
#   NETOPS_UI_PORT=9000      scripts/engine/ui/start.sh # outra porta
#   NETOPS_UI_TERMINAL=0     scripts/engine/ui/start.sh # sobe SEM o terminal web
#   NETOPS_UI_CLAUDE=0       scripts/engine/ui/start.sh # sobe SEM a página Claude Code
#   NETOPS_UI_CLAUDE_PERSIST=0 scripts/engine/ui/start.sh # DESLIGA a persistência (default ON: a tarefa da aba Claude continua com a aba fechada/F5)
#   NETOPS_UI_HOME=/root     scripts/engine/ui/start.sh # fixa o store do agente Claude (ver abaixo)
#   scripts/engine/ui/start.sh --read-only --no-vault-unlock   # flags extras (passthrough)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

# ----------------------------------------------------------------------------- modo gerenciado
# (padrão) sobe ou reinicia de forma desacoplada. O modo "primeiro plano" (mais abaixo) é o que o
# systemd/setsid executa de fato, com NETOPS_UI_FOREGROUND=1.
if [ "${NETOPS_UI_FOREGROUND:-0}" != "1" ] && [ "${1:-}" != "--foreground" ]; then
  LOG=/tmp/netops-restart.log
  log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
  ASSUME_YES=0; NO_DETACH=0; PASS=()
  for a in "$@"; do
    case "$a" in -y|--yes) ASSUME_YES=1;; --no-detach) NO_DETACH=1;; *) PASS+=("$a");; esac
  done
  # Alvo = o console deste ROOT. Se host/porta foram pedidos, casa SÓ o console dessa porta: assim
  # um teste em outra porta nunca derruba o console real (incidente 12/11/2026).
  if [ -n "${NETOPS_UI_PORT:-}" ]; then
    SUP=$(pgrep -of "update/supervisor.py --root $ROOT -- .*--port ${NETOPS_UI_PORT}( |\$)" || true)
  else
    SUP=$(pgrep -of "update/supervisor.py --root $ROOT --" || true)
  fi

  if [ "$NO_DETACH" = "0" ] && [ -z "${NETOPS_RESTART_DETACHED:-}" ]; then
    if [ -n "$SUP" ] && [ "$ASSUME_YES" = "0" ] && [ -t 0 ] && [ -t 1 ]; then
      echo "O console já está rodando. Reiniciar ENCERRA as sessões vivas da aba Claude (tarefas em andamento)."
      read -r -p "Reiniciar mesmo assim? [s/N] " ans
      case "$ans" in s|S|y|Y) ;; *) echo "Cancelado."; exit 0;; esac
    fi
    : >"$LOG"
    if command -v systemd-run >/dev/null; then
      systemd-run --quiet --collect --unit="netops-restart-$(date +%s)" \
        --setenv=NETOPS_RESTART_DETACHED=1 --setenv=HOME="${HOME:-/root}" \
        --setenv=NETOPS_UI_HOME="${NETOPS_UI_HOME:-}" --setenv=NETOPS_UI_HOST="${NETOPS_UI_HOST:-}" \
        --setenv=NETOPS_UI_PORT="${NETOPS_UI_PORT:-}" --setenv=NETOPS_UI_TERMINAL="${NETOPS_UI_TERMINAL:-}" \
        --setenv=NETOPS_UI_CLAUDE="${NETOPS_UI_CLAUDE:-}" --setenv=NETOPS_UI_CLAUDE_PERSIST="${NETOPS_UI_CLAUDE_PERSIST:-}" \
        "$0" --no-detach "${PASS[@]}" \
        && { echo "$([ -n "$SUP" ] && echo Reinício || echo Subida) agendado(a) (desacoplado). Acompanhe: tail -f $LOG"; echo "Console volta em ~15 s; aba Claude reconecta sozinha / F5."; exit 0; }
    fi
    NETOPS_RESTART_DETACHED=1 setsid nohup "$0" --no-detach "${PASS[@]}" >/dev/null 2>&1 < /dev/null &
    echo "Agendado (setsid). Acompanhe: tail -f $LOG"; exit 0
  fi

  # 1) captura o console atual (host/porta/flags); env explícito tem precedência
  HOST=""; PORT=8765; TERM_ON=1; CLAUDE_ON=1
  if [ -n "$SUP" ]; then
    mapfile -d '' ARGS < "/proc/$SUP/cmdline"
    for i in "${!ARGS[@]}"; do
      case "${ARGS[$i]}" in --host) HOST="${ARGS[$((i+1))]}";; --port) PORT="${ARGS[$((i+1))]}";; esac
    done
    printf '%s\n' "${ARGS[@]}" | grep -qx -- '--enable-terminal' || TERM_ON=0
    printf '%s\n' "${ARGS[@]}" | grep -qx -- '--enable-claude' || CLAUDE_ON=0
    log "console rodando (supervisor=$SUP host=$HOST port=$PORT) — reiniciando"
  else
    log "console não está rodando — subindo"
  fi
  HOST="${NETOPS_UI_HOST:-${HOST:-$(hostname -I | awk '{print $1}')}}"
  PORT="${NETOPS_UI_PORT:-$PORT}"
  export NETOPS_UI_HOST="$HOST" NETOPS_UI_PORT="$PORT"
  export NETOPS_UI_TERMINAL="${NETOPS_UI_TERMINAL:-$TERM_ON}" NETOPS_UI_CLAUDE="${NETOPS_UI_CLAUDE:-$CLAUDE_ON}"
  export NETOPS_UI_CLAUDE_PERSIST="${NETOPS_UI_CLAUDE_PERSIST:-1}"
  KEY="$(printf '%s' "${NETOPS_UI_DATA_ROOT:-$ROOT}:$HOST:$PORT" | sha256sum | cut -c1-24)"
  LOCK="${XDG_RUNTIME_DIR:-/tmp}/netops-ui-$(id -u)/$KEY.lock"

  # 1b) PRÉ-VALIDAÇÃO: nada é parado se o novo console não tiver como subir (acesso web nunca pode cair)
  preflight_fail() { log "PRÉ-VALIDAÇÃO FALHOU: $1 — console atual NÃO foi tocado"; exit 1; }
  PYV="$ROOT/.venv/bin/python3"; [ -x "$PYV" ] || PYV=python3
  { [ -x "$ROOT/.venv/bin/python3" ] || [ -f "$ROOT/.netops-update/journal.json" ]; } || preflight_fail "venv ausente"
  [ -f "$ROOT/scripts/engine/update/supervisor.py" ] || preflight_fail "supervisor.py ausente"
  "$PYV" -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$ROOT/scripts/engine/ui/server.py" 2>/dev/null || preflight_fail "server.py com erro de sintaxe"
  if [ -z "$SUP" ] && ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then preflight_fail "porta $PORT ocupada por outro processo"; fi
  log "pré-validação OK"

  # 2) para: SIGTERM no supervisor, espera ele (e o filho) sumirem; KILL após 30 s
  if [ -n "$SUP" ]; then
    sleep 2; kill -TERM "$SUP" 2>/dev/null
    for _ in $(seq 30); do kill -0 "$SUP" 2>/dev/null || break; sleep 1; done
    if kill -0 "$SUP" 2>/dev/null; then log "supervisor não saiu em 30 s — KILL"; pkill -KILL -P "$SUP"; kill -KILL "$SUP"; sleep 1; fi
  fi
  # 3) espera o lock ficar livre (até 30 s)
  mkdir -p "$(dirname "$LOCK")"
  for _ in $(seq 30); do
    { exec 8>"$LOCK"; } 2>/dev/null; flock -n 8 && { exec 8>&-; break; }; exec 8>&-; sleep 1
  done

  # O console NUNCA pode ficar no cgroup do helper: quando a unidade do helper termina, o systemd
  # mata tudo que sobrou nela (2º erro do incidente de 11/11). Sobe numa unidade própria
  # (netops-console-*), que vive até o próximo restart.
  launch_console() {
    if command -v systemd-run >/dev/null; then
      systemd-run --quiet --collect --unit="netops-console-$(date +%s)" --working-directory="$ROOT" \
        --setenv=NETOPS_UI_FOREGROUND=1 --setenv=HOME="${HOME:-/root}" --setenv=NETOPS_UI_HOME="${NETOPS_UI_HOME:-}" \
        --setenv=NETOPS_UI_HOST --setenv=NETOPS_UI_PORT --setenv=NETOPS_UI_TERMINAL \
        --setenv=NETOPS_UI_CLAUDE --setenv=NETOPS_UI_CLAUDE_PERSIST \
        --property=StandardOutput=append:"$LOG" --property=StandardError=append:"$LOG" \
        "$ROOT/scripts/engine/ui/start.sh" "${PASS[@]}" >>"$LOG" 2>&1 && return 0
      log "systemd-run falhou; usando setsid"
    fi
    ( cd "$ROOT" && NETOPS_UI_FOREGROUND=1 setsid nohup scripts/engine/ui/start.sh "${PASS[@]}" >>"$LOG" 2>&1 < /dev/null & )
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
  log "FALHA: console NÃO subiu. Veja $LOG; para depurar: scripts/engine/ui/start.sh --foreground"
  exit 1
fi
[ "${1:-}" = "--foreground" ] && shift
# ------------------------------------------------------------------------ modo primeiro plano

# HOME manda no STORE da aba Claude Code: login (`$HOME/.claude/.credentials.json`) E lista de
# conversas (`$HOME/.claude/projects/`). Trocar de HOME entre um restart e outro troca as duas
# coisas — e sob `sudo` o HOME muda sem avisar (root vs. o usuário que chamou). NETOPS_UI_HOME
# fixa isso de propósito; sem ele, vale o HOME de quem subiu o console.
if [ -n "${NETOPS_UI_HOME:-}" ]; then
  export HOME="$NETOPS_UI_HOME"
fi

# Binários do usuário (ex.: o agente `claude`, normalmente em ~/.local/bin) no PATH. Sem isto,
# a página Claude Code sobe mas não acha o agente (claude_svc.is_available() = False) — a aba
# aparece e não conecta. Como o console costuma subir via sudo, o PATH "enxuto" do sudo não
# inclui ~/.local/bin; por isso o garantimos aqui.
export PATH="$HOME/.local/bin:$PATH"

PY="$ROOT/.venv/bin/python3"
if [ ! -x "$PY" ] && [ ! -f "$ROOT/.netops-update/journal.json" ]; then
  echo "ERRO: venv ausente em .venv/. Rode:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# Host: env > IP privado auto-detectado > loopback.
HOST="${NETOPS_UI_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
HOST="${HOST:-127.0.0.1}"
PORT="${NETOPS_UI_PORT:-8765}"

# Terminal web ligado por padrão (NETOPS_UI_TERMINAL=0 desliga).
TERM_FLAG="--enable-terminal"
[ "${NETOPS_UI_TERMINAL:-1}" = "0" ] && TERM_FLAG=""

# Página Claude Code ligada por padrão (NETOPS_UI_CLAUDE=0 desliga). ⚠ executa comandos / edita arquivos.
CLAUDE_FLAG="--enable-claude"
[ "${NETOPS_UI_CLAUDE:-1}" = "0" ] && CLAUDE_FLAG=""

# Persistência da sessão Claude (a aba SOBREVIVE a F5/standby/queda do socket: o turno termina e
# você re-anexa ao voltar). Default ON; kill-switch: NETOPS_UI_CLAUDE_PERSIST=0.
# Só vale com a página Claude ligada. Limites finos: --claude-max-sessions/-detach-grace/-ask-timeout.
PERSIST_FLAG=""
[ "${NETOPS_UI_CLAUDE_PERSIST:-1}" = "1" ] && [ -n "$CLAUDE_FLAG" ] && PERSIST_FLAG="--enable-claude-persist"

# Instância única por diretório de dados e endereço. Um teste isolado não encerra
# o console real. O lock é herdado pelo servidor e liberado quando ele termina.
KEY="$(printf '%s' "${NETOPS_UI_DATA_ROOT:-$ROOT}:$HOST:$PORT" | sha256sum | cut -c1-24)"
LOCK_DIR="${XDG_RUNTIME_DIR:-/tmp}/netops-ui-$(id -u)"
mkdir -p "$LOCK_DIR"
chmod 700 "$LOCK_DIR"
exec 9>"$LOCK_DIR/$KEY.lock"
if ! flock -n 9; then
  echo "ERRO: já existe um console para estes dados em $HOST:$PORT." >&2
  exit 1
fi

echo "NetOps Console -> http://${HOST}:${PORT}/"
[ -n "$CLAUDE_FLAG" ] && echo "Claude Code     -> store ${HOME}/.claude (login e conversas da aba)"
[ -n "$PERSIST_FLAG" ] && echo "Persistência    -> ON (a aba Claude sobrevive a standby)"
# Supervisor só usa stdlib. Continua recuperável mesmo se a troca de venv for interrompida.
SUPERVISOR="$ROOT/scripts/engine/update/supervisor.py"
if [ -f "$ROOT/.netops-update/recovery-supervisor" ]; then
  IFS= read -r SAVED_SUPERVISOR < "$ROOT/.netops-update/recovery-supervisor"
  case "$SAVED_SUPERVISOR" in
    "$ROOT"/.netops-update/runtime/*/update/supervisor.py) SUPERVISOR="$SAVED_SUPERVISOR" ;;
    *) printf '%s\n' 'ERRO: caminho de recuperação inválido.' >&2; exit 1 ;;
  esac
fi
exec python3 "$SUPERVISOR" --root "$ROOT" -- \
  --host "$HOST" --port "$PORT" --no-browser $TERM_FLAG $CLAUDE_FLAG $PERSIST_FLAG "$@"
