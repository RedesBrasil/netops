#!/usr/bin/env bash
# Sobe um console ISOLADO (cópia do código + dados fictícios) em 127.0.0.1:8771 p/ testes *.browser.mjs.
# Uso: tests/e2e-env.sh up|down|sync   (sync = recopia static/ do working tree)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
E=/tmp/netops-e2e; PORT=${NETOPS_E2E_PORT:-8771}; PY=${NETOPS_E2E_PY:-/tmp/ccq/venv/bin/python}
sync_code() {
  mkdir -p "$E/code" && cd "$ROOT"
  rm -rf "$E/code"; mkdir -p "$E/code"
  tar -c --exclude=__pycache__ --exclude='*.bak*' --exclude='*.orig' --exclude=console.log scripts core agents workflows best-practices config-examples memory AGENTS.md | tar -x -C "$E/code"
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
    mkdir -p "$D/backups/by-id/1"; printf 'v1\n' > "$D/backups/by-id/1/a.rsc"; printf 'v2\n' > "$D/backups/by-id/1/b.rsc"
    cd "$E/code"
    NETOPS_UI_DATA_ROOT="$D" NETOPS_UI_HOST=127.0.0.1 NETOPS_UI_PORT=$PORT NETOPS_UI_CLAUDE=0 NETOPS_UI_TERMINAL=0 \
      nohup "$PY" scripts/engine/ui/server.py --host 127.0.0.1 --port "$PORT" --no-browser --enable-terminal > "$E/server.log" 2>&1 &
    echo $! > "$E/pid"
    for i in $(seq 30); do curl -sf "http://127.0.0.1:$PORT/api/config/meta" >/dev/null && break; sleep 1; done
    REV=$(curl -s "http://127.0.0.1:$PORT/api/backups" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["rev"])')
    curl -s -X PUT "http://127.0.0.1:$PORT/api/backups" -H "If-Match: $REV" -H 'Content-Type: application/json' -d '{"version":3,"legacy_sources":[],"services":[
      {"id":"svc-a","name":"Servico A","enabled":true,"schedule":{"frequency":"daily","time":"03:00"},"targets":{"hosts":[1],"groups":[]},"retention":{"mode":"count","value":7}},
      {"id":"svc-b","name":"Servico B","enabled":false,"schedule":{"frequency":"daily","time":"04:00"},"targets":{"hosts":[2],"groups":[]},"retention":{"mode":"count","value":7}}]}' >/dev/null
    for t in '{"name":"Changelog MikroTik","kind":"agent","prompt":"veja o changelog","schedule":{"type":"cron","expr":"0 8 * * *"}}' \
             '{"name":"Eco diario","kind":"script","script":"echo eco","schedule":{"type":"cron","expr":"0 3 * * *"}}' \
             '{"name":"Backup + analise","kind":"hybrid","script":"true","prompt":"compare","schedule":{"type":"interval","minutes":30}}'; do
      curl -s -X POST "http://127.0.0.1:$PORT/api/schedules/tasks" -H 'Content-Type: application/json' -d "$t" >/dev/null
    done
    curl -sf "http://127.0.0.1:$PORT/api/config/meta" >/dev/null && { echo "up :$PORT"; exit 0; }
    tail -20 "$E/server.log"; exit 1 ;;
esac
