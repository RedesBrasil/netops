#!/usr/bin/env bash
# Baixa as dependências ESM do frontend p/ scripts/engine/ui/static/vendor/ (rode UMA vez, com internet).
# Depois disso o NetOps Console é self-contained / offline (sem CDN). Versões pinadas + SHA em VERSIONS.txt.
set -euo pipefail
cd "$(dirname "$0")/static/vendor"

PREACT=10.27.2
HTM=3.1.1
MARKED=12.0.2
JSYAML=4.1.0
XTERM=5.5.0
XTERM_FIT=0.10.0

get() {  # get <url> <destino>
  echo "  baixando $2"
  curl -fsSL "$1" -o "$2"
}

get "https://unpkg.com/preact@${PREACT}/dist/preact.module.js"            preact.module.js
get "https://unpkg.com/preact@${PREACT}/hooks/dist/hooks.module.js"        preact-hooks.module.js
get "https://unpkg.com/preact@${PREACT}/compat/dist/compat.module.js"      preact-compat.module.js
get "https://unpkg.com/preact@${PREACT}/jsx-runtime/dist/jsxRuntime.module.js" preact-jsx-runtime.module.js
get "https://unpkg.com/htm@${HTM}/dist/htm.module.js"                      htm.module.js
get "https://unpkg.com/htm@${HTM}/preact/index.module.js"                  htm-preact.module.js
get "https://cdn.jsdelivr.net/npm/marked@${MARKED}/lib/marked.esm.js"      marked.esm.js
get "https://cdn.jsdelivr.net/npm/js-yaml@${JSYAML}/dist/js-yaml.mjs"      js-yaml.mjs || \
  get "https://esm.sh/js-yaml@${JSYAML}/es2022/js-yaml.mjs"               js-yaml.mjs

# Editor visual de Markdown (HTML -> Markdown). Já vendorizados; rode de novo só para atualizar.
get "https://cdn.jsdelivr.net/npm/turndown@7.2.0/+esm"                    turndown.mjs
get "https://cdn.jsdelivr.net/npm/turndown-plugin-gfm@1.0.2/+esm"         turndown-plugin-gfm.mjs
sed -i '/sourceMappingURL/d' turndown.mjs turndown-plugin-gfm.mjs

# Terminal web (xterm.js). /+esm = bundle ESM self-contained (sem imports externos -> offline-safe).
get "https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM}/+esm"             xterm.mjs
get "https://cdn.jsdelivr.net/npm/@xterm/addon-fit@${XTERM_FIT}/+esm"     xterm-addon-fit.mjs
get "https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM}/css/xterm.css"    xterm.css

{
  echo "# Dependências do frontend — pinadas em $(date -u +%Y-%m-%dT%H:%MZ)"
  echo "preact ${PREACT} | htm ${HTM} | marked ${MARKED} | js-yaml ${JSYAML} | xterm ${XTERM} | addon-fit ${XTERM_FIT}"
  sha256sum ./*.js ./*.mjs ./*.css 2>/dev/null || true
} > VERSIONS.txt

echo "OK — assets em scripts/engine/ui/static/vendor/. O console agora roda offline."
