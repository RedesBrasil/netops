#!/usr/bin/env bash
# Atalho de compatibilidade: subir e reiniciar agora são o MESMO script (ui/start.sh).
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ui/start.sh" --yes "$@"
