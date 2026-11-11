#!/usr/bin/env bash
# Sobe um console ISOLADO (cópia do código + dados fictícios) em 127.0.0.1:8771 p/ testes *.browser.mjs.
# Uso: tests/e2e-env.sh up|down|sync   (sync = recopia static/ do working tree)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
E=/tmp/netops-e2e; PORT=${NETOPS_E2E_PORT:-8771}; PY=${NETOPS_E2E_PY:-/tmp/ccq/venv/bin/python}
sync_code() {
  mkdir -p "$E/code" && cd "$ROOT"
  rm -rf "$E/code"; mkdir -p "$E/code"
  tar -c --exclude=__pycache__ --exclude='*.bak*' --exclude='*.orig' --exclude=console.log scripts core agents workflows best-practices config-examples memory | tar -x -C "$E/code"
  # reports/ e runs/ moram na raiz do código (NETOPS_ROOT), não no DATA_ROOT
  mkdir -p "$E/code/reports" "$E/code/runs/run-a" "$E/code/runs/run-b"
  echo '# Relatório A' > "$E/code/reports/a.md"; echo '# Relatório B' > "$E/code/reports/b.md"
  echo '{"status":"completed"}' > "$E/code/runs/run-a/state.json"; echo '{"status":"failed"}' > "$E/code/runs/run-b/state.json"
}
case "${1:-up}" in
  sync) sync_code ;;
  down) [ -f "$E/pid" ] && kill "$(cat "$E/pid")" 2>/dev/null || true; fuser -k "$PORT/tcp" 2>/dev/null || true ;;
  up)
    "$0" down; sync_code
    D="$E/data"; rm -rf "$D"; mkdir -p "$D/network" "$D/core/config" "$D/runs" "$D/backups"
    cat > "$D/network/hosts.yaml" <<Y
version: 2
next_host_id: 4
groups:
  linux-servers: {vendor: linux, role: other, access: {method: ssh, port: 22}, credential: cred_demo}
  mikrotik-core: {vendor: mikrotik, role: core, access: {method: ssh, port: 22}, credential: cred_demo}
hosts:
  - {id: 1, hostname: RT-CORE-01, mgmt_ip: 192.0.2.1, group: mikrotik-core}
  - {id: 2, hostname: SW-ACESSO-02, mgmt_ip: 192.0.2.2, group: mikrotik-core}
  - {id: 3, hostname: SRV-WEB-01, mgmt_ip: 192.0.2.3, group: linux-servers}
Y
    printf 'version: 1\ncredentials:\n  cred_demo: {username: demo}\n' > "$D/network/credentials.yaml"
    printf 'version: 1\nnodes: []\nlinks: []\n' > "$D/network/topology.yaml"
    printf 'project:\n  network_name: Teste\n' > "$D/core/config/project-config.yaml"
    cd "$E/code"
    NETOPS_UI_DATA_ROOT="$D" NETOPS_UI_HOST=127.0.0.1 NETOPS_UI_PORT=$PORT NETOPS_UI_CLAUDE=0 NETOPS_UI_TERMINAL=0 \
      nohup "$PY" scripts/engine/ui/server.py --host 127.0.0.1 --port "$PORT" --no-browser > "$E/server.log" 2>&1 &
    echo $! > "$E/pid"
    for i in $(seq 30); do curl -sf "http://127.0.0.1:$PORT/api/config/meta" >/dev/null && { echo "up :$PORT"; exit 0; }; sleep 1; done
    tail -20 "$E/server.log"; exit 1 ;;
esac
