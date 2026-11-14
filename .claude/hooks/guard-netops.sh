#!/usr/bin/env bash
# Compatibilidade: o hook mudou para scripts/engine/hooks/guard-netops.sh (vai no pacote de release).
# Sessões/clones com o settings.json antigo ainda chamam este caminho; repassa stdin e exit code.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/engine/hooks/guard-netops.sh"
