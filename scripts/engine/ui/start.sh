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
#   scripts/engine/ui/start.sh --read-only --no-vault-unlock   # flags extras (passthrough)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

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

# Instância única: encerra qualquer servidor anterior antes de subir.
pkill -f "scripts/engine/ui/server.py" 2>/dev/null && sleep 1 || true

echo "NetOps Console -> http://${HOST}:${PORT}/"
exec "$PY" scripts/engine/ui/server.py \
  --host "$HOST" --port "$PORT" --no-browser $TERM_FLAG $CLAUDE_FLAG "$@"
