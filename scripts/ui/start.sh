#!/usr/bin/env bash
# Único jeito suportado de subir o NetOps Console (web).
#
# Por que um script (e não `python scripts/ui/server.py` direto):
#   - mantém o TOKEN estável entre reinícios (sua URL/aba continua válida);
#   - liga o TERMINAL WEB por padrão (senão a aba "Terminal" some — é opt-in);
#   - faz bind no IP da máquina (acesso pela rede) e garante UMA instância só.
#
# Uso:
#   scripts/ui/start.sh                          # IP da máquina, porta 8765, terminal ON
#   NETOPS_UI_HOST=127.0.0.1 scripts/ui/start.sh # força loopback (só local)
#   NETOPS_UI_PORT=9000      scripts/ui/start.sh # outra porta
#   NETOPS_UI_TERMINAL=0     scripts/ui/start.sh # sobe SEM o terminal web
#   scripts/ui/start.sh --read-only --no-vault-unlock   # flags extras (passthrough)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python3"
if [ ! -x "$PY" ]; then
  echo "ERRO: venv ausente em .venv/. Rode:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# Token estável entre reinícios (gitignorado, 0600).
TOKEN_FILE="$ROOT/scripts/ui/.ui-token"
if [ ! -s "$TOKEN_FILE" ]; then
  ( umask 077; "$PY" -c "import os; print(os.urandom(16).hex())" > "$TOKEN_FILE" )
fi
chmod 600 "$TOKEN_FILE" 2>/dev/null || true
TOKEN="$(cat "$TOKEN_FILE")"

# Host: env > IP privado auto-detectado > loopback.
HOST="${NETOPS_UI_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
HOST="${HOST:-127.0.0.1}"
PORT="${NETOPS_UI_PORT:-8765}"

# Terminal web ligado por padrão (NETOPS_UI_TERMINAL=0 desliga).
TERM_FLAG="--enable-terminal"
[ "${NETOPS_UI_TERMINAL:-1}" = "0" ] && TERM_FLAG=""

# Instância única: encerra qualquer servidor anterior antes de subir.
pkill -f "scripts/ui/server.py" 2>/dev/null && sleep 1 || true

echo "NetOps Console -> http://${HOST}:${PORT}/?token=${TOKEN}"
exec "$PY" scripts/ui/server.py \
  --host "$HOST" --port "$PORT" --token "$TOKEN" --no-browser $TERM_FLAG "$@"
