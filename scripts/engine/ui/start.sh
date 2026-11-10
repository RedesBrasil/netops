#!/usr/bin/env bash
# Único jeito suportado de subir o NetOps Console (web).
#
# Por que um script (e não `python scripts/engine/ui/server.py` direto):
#   - liga o TERMINAL WEB e a página CLAUDE CODE por padrão (são opt-in — sem o script, as
#     abas "Terminal"/"Claude Code" não aparecem). Desligue com NETOPS_UI_TERMINAL=0 / NETOPS_UI_CLAUDE=0;
#   - garante o PATH do agente `claude` (~/.local/bin) para a página Claude funcionar de fato;
#   - faz bind no IP da máquina (acesso pela rede) e garante UMA instância só.
# Acesso protegido pelo LOGIN com a senha-mestra do cofre (ver server.py).
#
# Uso:
#   scripts/engine/ui/start.sh                          # IP da máquina, porta 8765, terminal ON
#   NETOPS_UI_HOST=127.0.0.1 scripts/engine/ui/start.sh # força loopback (só local)
#   NETOPS_UI_PORT=9000      scripts/engine/ui/start.sh # outra porta
#   NETOPS_UI_TERMINAL=0     scripts/engine/ui/start.sh # sobe SEM o terminal web
#   NETOPS_UI_CLAUDE=0       scripts/engine/ui/start.sh # sobe SEM a página Claude Code
#   NETOPS_UI_CLAUDE_PERSIST=1 scripts/engine/ui/start.sh # aba Claude SOBREVIVE a standby (persistência)
#   NETOPS_UI_HOME=/root     scripts/engine/ui/start.sh # fixa o store do agente Claude (ver abaixo)
#   scripts/engine/ui/start.sh --read-only --no-vault-unlock   # flags extras (passthrough)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

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
if [ ! -x "$PY" ]; then
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

# Persistência da sessão Claude (a aba SOBREVIVE a standby/queda do socket: o turno termina e
# você re-anexa ao voltar). Opt-in — default OFF (kill-switch). Ligue com NETOPS_UI_CLAUDE_PERSIST=1.
# Só vale com a página Claude ligada. Limites finos: --claude-max-sessions/-detach-grace/-ask-timeout.
PERSIST_FLAG=""
[ "${NETOPS_UI_CLAUDE_PERSIST:-0}" = "1" ] && [ -n "$CLAUDE_FLAG" ] && PERSIST_FLAG="--enable-claude-persist"

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
exec "$PY" scripts/engine/ui/server.py \
  --host "$HOST" --port "$PORT" --no-browser $TERM_FLAG $CLAUDE_FLAG $PERSIST_FLAG "$@"
