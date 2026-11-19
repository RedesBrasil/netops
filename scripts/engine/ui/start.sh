#!/usr/bin/env bash
# Único jeito suportado de subir OU reiniciar o NetOps Console (web). Um script só:
#   - console NÃO está rodando -> sobe;
#   - console JÁ está rodando  -> reinicia, preservando host/porta/terminal/claude.
# Em ambos os casos: desacopla (funciona de dentro da aba Claude/terminal web), espera o
# supervisor sair e o lock liberar, tenta até 3 vezes e só termina OK quando o HTTP responde
# (log: /tmp/netops-restart.log). Um `kill` só no filho deixa o supervisor segurando o flock e o
# console fica fora — por isso nunca `kill` à mão.
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

# Marcadores INTERNOS nunca vêm do ambiente: o console exporta NETOPS_UI_FOREGROUND/NETOPS_UPDATE_* p/
# os filhos (aba Claude, terminal web) e, herdados, faziam o start.sh de lá pular o modo gerenciado e
# recusar com "já existe um console" (12/11/2026) — e NETOPS_UPDATE_FROZEN=1 faria um supervisor novo
# pular a cópia do runtime. Os modos agora são escolhidos SÓ por argumento (--foreground / --no-detach);
# o supervisor recria as NETOPS_UPDATE_* dele.
unset NETOPS_UI_FOREGROUND NETOPS_RESTART_DETACHED \
      NETOPS_UPDATE_FROZEN NETOPS_UPDATE_MANAGED NETOPS_UPDATE_NONCE NETOPS_UPDATE_RECOVERING

# ----------------------------------------------------------------------------- identidade (layout 2)
# Instalação com /etc/netops/instances/<slug>.env (root-owned) roda como a conta operacional
# (`netops`), como serviço systemd DO USUÁRIO (netops-console@<slug>.service, linger = boot).
# Sem o arquivo = instalação legada (layout 1, console root): comportamento antigo, intacto.
# Fonte única: scripts/engine/lib/runtime_identity.py (mesmo formato; aqui lido em bash puro,
# para que root nunca execute Python da árvore gravável pela conta operacional).
IDENT_SLUG=$(printf '%s' "${ROOT#/}" | sed -E 's/[^A-Za-z0-9]+/-/g; s/^-+//; s/-+$//')
IDENT_FILE="${NETOPS_IDENTITY_DIR:-/etc/netops/instances}/$IDENT_SLUG.env"
USER_MODE=0
if [ -f "$IDENT_FILE" ]; then
  USER_MODE=1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    k="${line%%=*}"; v="${line#*=}"
    case "$k" in
      NETOPS_LAYOUT|NETOPS_DIR|NETOPS_RUNTIME_USER|NETOPS_RUNTIME_HOME|NETOPS_INSTANCE_ID|NETOPS_UI_HOST|NETOPS_UI_PORT|NETOPS_UI_TERMINAL|NETOPS_UI_CLAUDE|NETOPS_UI_CLAUDE_PERSIST) ;;
      *) echo "ERRO: chave inválida em $IDENT_FILE: $k" >&2; exit 2 ;;
    esac
    [[ "$v" =~ ^[A-Za-z0-9_./:@%+,-]*$ ]] || { echo "ERRO: valor inválido em $IDENT_FILE ($k)" >&2; exit 2; }
    printf -v "ID_$k" '%s' "$v"
  done < "$IDENT_FILE"
  [ "${ID_NETOPS_LAYOUT:-}" = 2 ] || { echo "ERRO: $IDENT_FILE: layout desconhecido" >&2; exit 2; }
  [ "${ID_NETOPS_DIR:-}" = "$ROOT" ] || { echo "ERRO: $IDENT_FILE aponta para ${ID_NETOPS_DIR:-?}, não para $ROOT" >&2; exit 2; }
  RT_USER="${ID_NETOPS_RUNTIME_USER:-netops}"
  RT_UID=$(id -u "$RT_USER" 2>/dev/null) || { echo "ERRO: a conta operacional $RT_USER não existe" >&2; exit 2; }
  [ "$RT_UID" != 0 ] || { echo "ERRO: a conta operacional não pode ser root" >&2; exit 2; }
  RT_HOME=$(getent passwd "$RT_USER" | cut -d: -f6)
  UNIT="netops-console@$IDENT_SLUG.service"
  ME=$(id -u)
  if [ "$ME" = 0 ]; then
    # Root nunca sobe o console: delega para a conta operacional, com o ambiente DELA
    # (HOME, runtime e bus do gerenciador do usuário). Trocar só o $HOME mantendo UID 0 não vale.
    if [ ! -S "/run/user/$RT_UID/bus" ]; then
      loginctl enable-linger "$RT_USER" 2>/dev/null || true
      for _ in $(seq 180); do [ -S "/run/user/$RT_UID/bus" ] && break; sleep 1; done
    fi
    [ -S "/run/user/$RT_UID/bus" ] || { echo "ERRO: gerenciador systemd do usuário $RT_USER indisponível (linger?). Veja: loginctl show-user $RT_USER" >&2; exit 2; }
    cd /
    exec runuser -u "$RT_USER" -- env -i \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME="$RT_HOME" USER="$RT_USER" LOGNAME="$RT_USER" \
      XDG_RUNTIME_DIR="/run/user/$RT_UID" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$RT_UID/bus" \
      LANG="${LANG:-C.UTF-8}" TERM="${TERM:-dumb}" "$ROOT/scripts/engine/ui/start.sh" "$@"
  elif [ "$ME" != "$RT_UID" ]; then
    echo "ERRO: esta instalação roda como '$RT_USER'; você é '$(id -un)'. Rode: sudo $ROOT/scripts/engine/ui/start.sh $*" >&2
    exit 2
  fi
  export HOME="$RT_HOME" USER="$RT_USER" LOGNAME="$RT_USER"
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$RT_UID}"
  export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
fi

# Pré-validação comum aos dois layouts: nada é parado se o novo console não tiver como subir.
# Porta ocupada NO ENDEREÇO do console (ou em curinga). Um serviço alheio em outro endereço
# (ex.: 127.0.0.1:PORT) não conflita com HOST:PORT e não pode barrar a subida.
port_busy() {  # $1=host $2=port
  local h="$1" p="$2"
  ss -ltnH "sport = :$p" 2>/dev/null | awk -v h="$h" -v p="$p" '
    BEGIN { wild = (h == "0.0.0.0" || h == "::" || h == "*" || h == "") }
    { a = $4; sub(":" p "$", "", a); gsub(/^\[|\]$/, "", a); sub(/%.*$/, "", a)
      if (wild || a == h || a == "0.0.0.0" || a == "*" || a == "::") found = 1 }
    END { exit found ? 0 : 1 }'
}

preflight_checks() {  # stdout = motivo da falha; exit != 0 se falhou
  [ -x "$ROOT/.venv/bin/python3" ] || [ -f "$ROOT/.netops-update/journal.json" ] || { echo "venv ausente"; return 1; }
  [ -f "$ROOT/scripts/engine/update/supervisor.py" ] || { echo "supervisor.py ausente"; return 1; }
  local pyv="$ROOT/.venv/bin/python3" err rc smoke
  [ -x "$pyv" ] || pyv=python3
  # Sintaxe de TODO o backend (server, services, routers, update) — não só do server.py.
  err=$("$pyv" - "$ROOT/scripts/engine/ui" "$ROOT/scripts/engine/update" <<'PYEOF' 2>&1
import ast, pathlib, sys
bad = []
for base in sys.argv[1:]:
    for f in pathlib.Path(base).rglob("*.py"):
        if "tests" in f.parts or "__pycache__" in f.parts:
            continue
        try:
            ast.parse(f.read_text(encoding="utf-8"), str(f))
        except Exception as e:
            bad.append(f"{f}: {e}")
print("\n".join(bad)); sys.exit(1 if bad else 0)
PYEOF
) || { echo "erro de sintaxe no backend: $err"; return 1; }
  # Import SECO do app (o mesmo venv do console), com dados/HOME numa pasta vazia.
  if [ -x "$ROOT/.venv/bin/python3" ]; then
    smoke=$(mktemp -d); rc=0
    (cd "$ROOT/scripts/engine/ui" && env -i PATH="/usr/bin:/bin" HOME="$smoke" \
      NETOPS_UI_DATA_ROOT="$smoke" timeout 60 "$ROOT/.venv/bin/python3" \
      -c "import sys; sys.path.insert(0, '.'); import app") >"$smoke.log" 2>&1 || rc=$?
    err=$(tail -3 "$smoke.log" 2>/dev/null); rm -rf "$smoke" "$smoke.log"
    [ "$rc" = 0 ] || { echo "o app não importa: $err"; return 1; }
  fi
  return 0
}

# ----------------------------------------------------------------------------- modo gerenciado (layout 2)
# Sobe/reinicia o serviço de usuário. O helper roda numa unidade transitória DO USUÁRIO
# (systemd-run --user), fora do cgroup do console: não morre junto com a aba Claude que pediu.
if [ "$USER_MODE" = 1 ] && [ "${1:-}" != "--foreground" ]; then
  STATE_DIR="$RT_HOME/.local/state/netops"; mkdir -p "$STATE_DIR"; chmod 700 "$RT_HOME/.local/state" "$STATE_DIR" 2>/dev/null || true
  LOG="$STATE_DIR/restart-$IDENT_SLUG.log"
  log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
  ASSUME_YES=0; NO_DETACH=0; PASS=()
  for a in "$@"; do
    case "$a" in -y|--yes) ASSUME_YES=1;; --no-detach) NO_DETACH=1;; *) PASS+=("$a");; esac
  done
  if [ ${#PASS[@]} -gt 0 ]; then
    echo "ERRO: flags extras (${PASS[*]}) só valem com --foreground (depuração). A configuração do serviço fica em $IDENT_FILE." >&2
    exit 2
  fi
  HOST="${ID_NETOPS_UI_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"; HOST="${HOST:-127.0.0.1}"
  PORT="${ID_NETOPS_UI_PORT:-8765}"
  URLH="$HOST"; case "$HOST" in *:*) URLH="[$HOST]";; esac
  ACTIVE=$(systemctl --user is-active "$UNIT" 2>/dev/null || true)
  if [ "$NO_DETACH" = 0 ]; then
    if [ "$ACTIVE" = active ] && [ "$ASSUME_YES" = 0 ] && [ -t 0 ] && [ -t 1 ]; then
      echo "O console já está rodando. Reiniciar ENCERRA as sessões vivas da aba Claude (tarefas em andamento)."
      read -r -p "Reiniciar mesmo assim? [s/N] " ans
      case "$ans" in s|S|y|Y) ;; *) echo "Cancelado."; exit 0;; esac
    fi
    : >"$LOG"; chmod 600 "$LOG"
    systemd-run --user --quiet --collect --unit="netops-restart-$IDENT_SLUG-$(date +%s)" \
      "$ROOT/scripts/engine/ui/start.sh" --no-detach \
      || { echo "ERRO: systemd-run --user falhou (gerenciador do usuário indisponível?)" >&2; exit 1; }
    echo "$([ "$ACTIVE" = active ] && echo Reinício || echo Subida) agendado(a) (desacoplado). Acompanhe: tail -f $LOG"
    echo "Console volta em ~15 s; aba Claude reconecta sozinha / F5."
    exit 0
  fi
  # helper: pré-validação -> restart do serviço -> HTTP + boot_id novo + processo da conta certa
  OLD_ROOT_SUP=$(pgrep -u 0 -of "update/supervisor.py --root $ROOT --" || true)
  [ -z "$OLD_ROOT_SUP" ] || { log "PRÉ-VALIDAÇÃO FALHOU: um console ROOT antigo desta pasta está rodando (pid $OLD_ROOT_SUP) — migração pendente; nada foi tocado"; exit 1; }
  if ! why=$(preflight_checks); then log "PRÉ-VALIDAÇÃO FALHOU: $why — console atual NÃO foi tocado"; exit 1; fi
  if [ "$ACTIVE" != active ] && port_busy "$HOST" "$PORT"; then
    log "PRÉ-VALIDAÇÃO FALHOU: porta $PORT ocupada por outro processo"; exit 1
  fi
  log "pré-validação OK ($UNIT, conta $RT_USER, http://$URLH:$PORT/)"
  boot_id() { curl -s --max-time 2 "http://$URLH:$PORT/api/config/meta" 2>/dev/null | sed -nE 's/.*"boot_id": *"([^"]*)".*/\1/p'; }
  OLD_BOOT=$(boot_id || true)
  set +e
  for try in 1 2 3; do
    log "$([ "$ACTIVE" = active ] && echo reiniciando || echo subindo) (tentativa $try)"
    if [ "$ACTIVE" = active ] || [ "$try" -gt 1 ]; then systemctl --user restart "$UNIT"; else systemctl --user start "$UNIT"; fi
    for _ in $(seq 40); do
      b=$(boot_id)
      if [ -n "$b" ] && [ "$b" != "$OLD_BOOT" ]; then
        sleep 8; b2=$(boot_id)
        sup=$(systemctl --user show -p MainPID --value "$UNIT" 2>/dev/null)
        owner=$(stat -c %u "/proc/${sup:-0}" 2>/dev/null)
        if [ "$b2" = "$b" ] && [ "$owner" = "$RT_UID" ]; then
          log "OK: console respondendo em http://$URLH:$PORT/ (boot $b, conta $RT_USER) e estável após 8 s"; exit 0
        fi
        log "console caiu ou mudou após subir (boot $b -> ${b2:-?}, dono ${owner:-?})"; break
      fi
      sleep 1
    done
    log "sem resposta válida; tentando de novo"; sleep 3
  done
  log "FALHA: console NÃO subiu. Veja: journalctl --user -u $UNIT -n 50 ; $LOG"
  exit 1
fi

# ----------------------------------------------------------------------------- modo gerenciado (legado)
# (padrão) sobe ou reinicia de forma desacoplada. O modo "primeiro plano" (mais abaixo) é o que o
# systemd/setsid executa de fato, chamando este script com --foreground.
if [ "${1:-}" != "--foreground" ]; then
  LOG=/tmp/netops-restart.log
  log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
  ASSUME_YES=0; NO_DETACH=0; PASS=()
  for a in "$@"; do
    case "$a" in -y|--yes) ASSUME_YES=1;; --no-detach) NO_DETACH=1;; *) PASS+=("$a");; esac
  done
  # Alvo = o console deste ROOT. Se host/porta foram pedidos, casa SÓ o console dessa porta: assim
  # um teste em outra porta nunca derruba o console real.
  if [ -n "${NETOPS_UI_PORT:-}" ]; then
    SUP=$(pgrep -of "update/supervisor.py --root $ROOT -- .*--port ${NETOPS_UI_PORT}( |\$)" || true)
  else
    SUP=$(pgrep -of "update/supervisor.py --root $ROOT --" || true)
  fi

  if [ "$NO_DETACH" = "0" ]; then
    if [ -n "$SUP" ] && [ "$ASSUME_YES" = "0" ] && [ -t 0 ] && [ -t 1 ]; then
      echo "O console já está rodando. Reiniciar ENCERRA as sessões vivas da aba Claude (tarefas em andamento)."
      read -r -p "Reiniciar mesmo assim? [s/N] " ans
      case "$ans" in s|S|y|Y) ;; *) echo "Cancelado."; exit 0;; esac
    fi
    : >"$LOG"
    if command -v systemd-run >/dev/null; then
      systemd-run --quiet --collect --unit="netops-restart-$(date +%s)" \
        --setenv=HOME="${HOME:-/root}" \
        --setenv=NETOPS_UI_HOME="${NETOPS_UI_HOME:-}" --setenv=NETOPS_UI_HOST="${NETOPS_UI_HOST:-}" \
        --setenv=NETOPS_UI_PORT="${NETOPS_UI_PORT:-}" --setenv=NETOPS_UI_TERMINAL="${NETOPS_UI_TERMINAL:-}" \
        --setenv=NETOPS_UI_CLAUDE="${NETOPS_UI_CLAUDE:-}" --setenv=NETOPS_UI_CLAUDE_PERSIST="${NETOPS_UI_CLAUDE_PERSIST:-}" \
        "$0" --no-detach "${PASS[@]}" \
        && { echo "$([ -n "$SUP" ] && echo Reinício || echo Subida) agendado(a) (desacoplado). Acompanhe: tail -f $LOG"; echo "Console volta em ~15 s; aba Claude reconecta sozinha / F5."; exit 0; }
    fi
    setsid nohup "$0" --no-detach "${PASS[@]}" >/dev/null 2>&1 < /dev/null &
    echo "Agendado (setsid). Acompanhe: tail -f $LOG"; exit 0
  fi

  # 1) captura o console atual (host/porta/flags); env explícito tem precedência
  HOST=""; PORT=8765; TERM_ON=1; CLAUDE_ON=1
  if [ -n "$SUP" ]; then
    mapfile -d '' ARGS < "/proc/$SUP/cmdline" 2>/dev/null || ARGS=()
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
  why=$(preflight_checks) || preflight_fail "$why"
  if [ -z "$SUP" ] && port_busy "$HOST" "$PORT"; then preflight_fail "porta $PORT ocupada por outro processo"; fi
  log "pré-validação OK"

  # 2) para: SIGTERM no supervisor, espera ele (e o filho) sumirem; KILL após 30 s.
  # Daqui em diante o console antigo está parando: NENHUM comando pode abortar o helper (set -e)
  # antes de subir o novo — todo comando que pode "falhar à toa" leva `|| true`.
  set +e
  if [ -n "$SUP" ]; then
    sleep 2; kill -TERM "$SUP" 2>/dev/null || true
    for _ in $(seq 30); do kill -0 "$SUP" 2>/dev/null || break; sleep 1; done
    if kill -0 "$SUP" 2>/dev/null; then
      log "supervisor não saiu em 30 s — KILL"
      pkill -KILL -P "$SUP" 2>/dev/null || true; kill -KILL "$SUP" 2>/dev/null || true; sleep 1
    fi
  fi
  # 3) espera o lock ficar livre (até 30 s)
  mkdir -p "$(dirname "$LOCK")" || true
  for _ in $(seq 30); do
    { exec 8>"$LOCK"; } 2>/dev/null && flock -n 8 && { exec 8>&-; break; }
    exec 8>&- 2>/dev/null; sleep 1
  done

  # O console NUNCA pode ficar no cgroup do helper: quando a unidade do helper termina, o systemd
  # mata tudo que sobrou nela. Sobe numa unidade própria
  # (netops-console-*), que vive até o próximo restart.
  launch_console() {
    if command -v systemd-run >/dev/null; then
      systemd-run --quiet --collect --unit="netops-console-$(date +%s)" --working-directory="$ROOT" \
        --setenv=HOME="${HOME:-/root}" --setenv=NETOPS_UI_HOME="${NETOPS_UI_HOME:-}" \
        --setenv=NETOPS_UI_HOST --setenv=NETOPS_UI_PORT --setenv=NETOPS_UI_TERMINAL \
        --setenv=NETOPS_UI_CLAUDE --setenv=NETOPS_UI_CLAUDE_PERSIST \
        --property=StandardOutput=append:"$LOG" --property=StandardError=append:"$LOG" \
        "$ROOT/scripts/engine/ui/start.sh" --foreground "${PASS[@]}" >>"$LOG" 2>&1 && return 0
      log "systemd-run falhou; usando setsid"
    fi
    ( cd "$ROOT" && setsid nohup scripts/engine/ui/start.sh --foreground "${PASS[@]}" >>"$LOG" 2>&1 < /dev/null & )
  }

  # 4) sobe com até 3 tentativas; 5) valida HTTP (responde e continua respondendo após 8 s)
  http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://$HOST:$PORT/" 2>/dev/null || true; }
  for try in 1 2 3; do
    log "subindo (tentativa $try)"
    launch_console || true
    for _ in $(seq 25); do
      code=$(http_code)
      case "$code" in
        200|301|302|303|401|403)
          sleep 8; c2=$(http_code)
          case "$c2" in
            ""|000) log "console caiu após subir"; break ;;
            *) log "OK: console respondendo ($code/$c2) em http://$HOST:$PORT/ e estável após 8 s"; exit 0 ;;
          esac ;;
      esac
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
if [ "$USER_MODE" = 1 ]; then
  # layout 2: HOME = o da conta operacional (já fixado acima); NETOPS_UI_HOME não se aplica.
  # Defaults do serviço vêm do arquivo de identidade (o env explícito, se houver, prevalece).
  NETOPS_UI_HOST="${NETOPS_UI_HOST:-${ID_NETOPS_UI_HOST:-}}"
  NETOPS_UI_PORT="${NETOPS_UI_PORT:-${ID_NETOPS_UI_PORT:-}}"
  NETOPS_UI_TERMINAL="${NETOPS_UI_TERMINAL:-${ID_NETOPS_UI_TERMINAL:-}}"
  NETOPS_UI_CLAUDE="${NETOPS_UI_CLAUDE:-${ID_NETOPS_UI_CLAUDE:-}}"
  NETOPS_UI_CLAUDE_PERSIST="${NETOPS_UI_CLAUDE_PERSIST:-${ID_NETOPS_UI_CLAUDE_PERSIST:-}}"
  export NETOPS_INSTANCE_ID="${ID_NETOPS_INSTANCE_ID:-}"
elif [ -n "${NETOPS_UI_HOME:-}" ]; then
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
