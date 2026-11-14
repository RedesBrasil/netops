#!/usr/bin/env bash
# NetOps — instalador em uma linha (Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/RedesBrasil/netops/main/install.sh | sudo bash
#
# O que faz, de ponta a ponta:
#   1. instala os pacotes do sistema (Python, nmap, cron, ping/traceroute/mtr, ssh, git, gh...);
#   2. baixa o pacote da última release do GitHub (netops-X.Y.Z.tar.gz), confere o SHA256 e o
#      manifesto (hash e permissão de cada arquivo) e extrai em /opt/netops;
#   3. cria o .venv e instala requirements.txt;
#   4. cria o usuário `netops` (o terminal web nunca abre shell root) e instala o agente `claude`;
#   5. pede a senha-mestra do cofre (é o login do console);
#   6. registra o serviço de boot e sobe o console com scripts/engine/ui/start.sh;
#   7. testa tudo e mostra o endereço: http://<IP>:<porta>/
#
# Rodar de novo é seguro: numa instalação existente ele NÃO substitui código nem dados — só
# confere/repara dependências, serviço e console (atualizações são pelo console).
#
# Variáveis opcionais (use `sudo VAR=valor bash` no fim do pipe):
#   NETOPS_DIR=/opt/netops        pasta de instalação
#   NETOPS_VERSION=2.4.0          versão específica (padrão: última release estável)
#   NETOPS_PORT=8765              porta do console
#   NETOPS_HOST=10.0.0.5          IP de bind (padrão: o 1º IP da máquina)
#   GITHUB_TOKEN=ghp_...          token, se o repositório for privado
#   NETOPS_PACKAGE=/tmp/x.tar.gz  instala de um pacote local (offline/teste), sem baixar
#   NETOPS_SKIP_CLAUDE=1          não instala o agente `claude`
#   NETOPS_NO_SERVICE=1           não registra o serviço de boot (systemd)
#   NETOPS_MASTER_PASSWORD=...    senha-mestra sem pergunta (instalação automatizada)
#
# Tudo fica registrado em /var/log/netops-install.log.

# O corpo inteiro está em main(), chamada só na última linha: se o download pelo curl for
# interrompido no meio, o bash não executa um script pela metade.

set -Eeuo pipefail

REPO="RedesBrasil/netops"
LOG="/var/log/netops-install.log"
MIN_VENV_PY="3.10"   # Python do .venv (dependências)
MIN_SYS_PY="3.9"     # python3 do sistema (supervisor do console e re-exec dos scripts)

# ----------------------------------------------------------------------------- saída
if [ -t 1 ]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; C=""; N=""
fi
log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >>"$LOG" 2>/dev/null || true; }
step() { printf '\n%s==>%s %s%s%s\n' "$C" "$N" "$B" "$*" "$N"; log "== $*"; }
info() { printf '    %s\n' "$*"; log "$*"; }
ok()   { printf '    %s✓%s %s\n' "$G" "$N" "$*"; log "OK $*"; }
warn() { printf '    %s!%s %s\n' "$Y" "$N" "$*"; log "AVISO $*"; WARNINGS+=("$*"); }
die()  {
  printf '\n%s✗ ERRO:%s %s\n' "$R" "$N" "$*" >&2; log "ERRO $*"
  printf '  Log completo: %s\n' "$LOG" >&2
  exit 1
}
run()  { log "\$ $*"; "$@" >>"$LOG" 2>&1; }          # comando com saída só no log
WARNINGS=()
trap 'die "falha inesperada na linha $LINENO (comando: $BASH_COMMAND)"' ERR

# ----------------------------------------------------------------------------- utilitários
ver_ge() {  # ver_ge 3.11 3.10 -> verdadeiro se $1 >= $2
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]
}
py_ver() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true; }
have() { command -v "$1" >/dev/null 2>&1; }

has_tty() { { : </dev/tty; } 2>/dev/null; }

gh_curl() {  # gh_curl <url> [args...] — curl na API do GitHub (com token, se houver)
  local url="$1"; shift
  local auth=()
  [ -n "${TOKEN:-}" ] && auth=(-H "Authorization: Bearer $TOKEN")
  curl -fsSL --retry 3 --connect-timeout 15 -H "X-GitHub-Api-Version: 2022-11-28" "${auth[@]}" "$@" "$url"
}

primary_ip() {  # o mesmo IP que o start.sh escolhe (1º de `hostname -I`), com alternativa
  local ip=""
  ip=$(hostname -I 2>/dev/null | awk '{print $1}') || true
  if [ -z "$ip" ] && have ip; then
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}') || true
  fi
  printf '%s' "$ip"
}

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null || true; }

# ----------------------------------------------------------------------------- 1. pré-requisitos
preflight() {
  step "Verificando o sistema"
  [ "$(uname -s)" = "Linux" ] || die "este instalador é só para Linux (Windows virá depois)."
  if [ "$(id -u)" -ne 0 ]; then
    die "rode como root. Use:  curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | sudo bash"
  fi
  : >>"$LOG" && chmod 600 "$LOG"
  log "---- instalação iniciada (args: $*)"
  case "$(uname -m)" in
    x86_64|amd64|aarch64|arm64) ;;
    *) warn "arquitetura $(uname -m) não testada; seguindo mesmo assim." ;;
  esac
  OS_ID=""; OS_LIKE=""; OS_NAME="Linux"
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-}"; OS_LIKE="${ID_LIKE:-}"; OS_NAME="${PRETTY_NAME:-Linux}"
  fi
  if have apt-get; then PM=apt
  elif have dnf; then PM=dnf
  elif have yum; then PM=yum
  elif have zypper; then PM=zypper
  elif have pacman; then PM=pacman
  elif have apk; then die "Alpine não é suportado (sem systemd/glibc). Use Debian, Ubuntu, RHEL/Rocky/Alma, Fedora, openSUSE ou Arch."
  else die "gerenciador de pacotes não reconhecido. Suportados: apt, dnf, yum, zypper, pacman."
  fi
  ok "$OS_NAME ($(uname -m)) — pacotes via $PM"

  NETOPS_DIR="${NETOPS_DIR:-/opt/netops}"
  NETOPS_DIR="${NETOPS_DIR%/}"
  PORT="${NETOPS_PORT:-8765}"
  TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  case "$PORT" in ''|*[!0-9]*) die "NETOPS_PORT inválida: $PORT" ;; esac
}

# ----------------------------------------------------------------------------- 2. pacotes do sistema
pkg_install() {  # pkg_install <obrigatórios...> -- <opcionais...>
  local req=() opt=() seen=0 p
  for p in "$@"; do
    if [ "$p" = "--" ]; then seen=1; continue; fi
    if [ "$seen" = 0 ]; then req+=("$p"); else opt+=("$p"); fi
  done
  case "$PM" in
    apt)    export DEBIAN_FRONTEND=noninteractive
            run apt-get update -q || die "apt-get update falhou (rede/repositórios?)."
            run apt-get install -y -q --no-install-recommends "${req[@]}" || die "falha ao instalar: ${req[*]}"
            for p in "${opt[@]}"; do run apt-get install -y -q --no-install-recommends "$p" || warn "pacote opcional indisponível: $p"; done ;;
    dnf|yum) run "$PM" install -y "${req[@]}" || die "falha ao instalar: ${req[*]}"
            for p in "${opt[@]}"; do run "$PM" install -y "$p" || warn "pacote opcional indisponível: $p"; done ;;
    zypper) run zypper --non-interactive refresh || true
            run zypper --non-interactive install --no-recommends "${req[@]}" || die "falha ao instalar: ${req[*]}"
            for p in "${opt[@]}"; do run zypper --non-interactive install --no-recommends "$p" || warn "pacote opcional indisponível: $p"; done ;;
    pacman) run pacman -Sy --noconfirm --needed "${req[@]}" || die "falha ao instalar: ${req[*]}"
            for p in "${opt[@]}"; do run pacman -S --noconfirm --needed "$p" || warn "pacote opcional indisponível: $p"; done ;;
  esac
}

install_system_packages() {
  step "Instalando pacotes do sistema (pode levar alguns minutos)"
  case "$PM" in
    apt)
      pkg_install python3 python3-venv python3-pip ca-certificates curl tar gzip iproute2 util-linux \
        procps hostname cron nmap iputils-ping openssh-client git zip unzip \
        -- traceroute mtr-tiny python-is-python3 gh ;;
    dnf|yum)
      pkg_install python3 python3-pip ca-certificates curl tar gzip iproute util-linux procps-ng \
        hostname cronie nmap iputils openssh-clients git zip unzip \
        -- traceroute mtr
      # gh não vem no RHEL/Rocky/Alma: usa o repositório oficial do GitHub CLI
      if ! have gh && ! run "$PM" install -y gh; then
        curl -fsSL https://cli.github.com/packages/rpm/gh-cli.repo -o /etc/yum.repos.d/gh-cli.repo 2>>"$LOG" \
          && run "$PM" install -y gh || warn "pacote opcional indisponível: gh"
      fi ;;
    zypper)
      pkg_install python3 python3-pip ca-certificates curl tar gzip iproute2 util-linux procps \
        hostname cron nmap iputils openssh-clients git zip unzip \
        -- traceroute mtr gh ;;
    pacman)
      pkg_install python python-pip ca-certificates curl tar gzip iproute2 util-linux procps-ng \
        inetutils cronie nmap iputils openssh git zip unzip \
        -- traceroute mtr github-cli ;;
  esac
  # cron: as Tarefas agendadas do console usam /etc/cron.d (precisa do daemon ativo)
  if [ -d /run/systemd/system ]; then
    local unit
    for unit in cron crond cronie; do
      if systemctl list-unit-files "$unit.service" >/dev/null 2>&1 && \
         systemctl list-unit-files "$unit.service" | grep -q "^$unit.service"; then
        run systemctl enable --now "$unit.service" || warn "não consegui ativar $unit.service"
        break
      fi
    done
  fi
  ok "pacotes do sistema instalados"
}

# ----------------------------------------------------------------------------- 3. Python
pick_python() {
  step "Conferindo o Python"
  local sysv
  sysv=$(py_ver python3)
  [ -n "$sysv" ] || die "python3 não encontrado após instalar os pacotes."
  ver_ge "$sysv" "$MIN_SYS_PY" || die "python3 do sistema é $sysv; o NetOps precisa de >= $MIN_SYS_PY. Use uma distribuição mais nova (Debian 12+, Ubuntu 22.04+, RHEL 9+)."

  PY=""
  local c v
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    have "$c" || continue
    v=$(py_ver "$c"); [ -n "$v" ] || continue
    if ver_ge "$v" "$MIN_VENV_PY"; then PY=$(command -v "$c"); break; fi
  done
  if [ -z "$PY" ]; then
    info "python3 $sysv é antigo para as dependências; tentando instalar um Python mais novo..."
    case "$PM" in
      dnf|yum) for c in python3.12 python3.11; do
                 if run "$PM" install -y "$c" "$c-pip" || run "$PM" install -y "$c"; then break; fi
               done ;;
      zypper)  for c in python312 python311; do if run zypper --non-interactive install "$c"; then break; fi; done ;;
      apt)     for c in python3.12 python3.11; do if run apt-get install -y -q "$c" "$c-venv"; then break; fi; done ;;
    esac
    for c in python3.13 python3.12 python3.11 python3.10; do
      have "$c" && ver_ge "$(py_ver "$c")" "$MIN_VENV_PY" && { PY=$(command -v "$c"); break; }
    done
  fi
  [ -n "$PY" ] || die "nenhum Python >= $MIN_VENV_PY disponível (sistema tem $sysv). Use Debian 12+, Ubuntu 22.04+, RHEL/Rocky/Alma 9+, Fedora, openSUSE Tumbleweed ou Arch."
  ok "Python do .venv: $PY ($(py_ver "$PY")) · supervisor: python3 $sysv"
}

# ----------------------------------------------------------------------------- 4. download
resolve_release() {
  if [ -n "${NETOPS_PACKAGE:-}" ]; then
    [ -f "$NETOPS_PACKAGE" ] || die "NETOPS_PACKAGE não existe: $NETOPS_PACKAGE"
    PKG_FILE="$NETOPS_PACKAGE"; PKG_VERSION="${NETOPS_VERSION:-}"
    if [ -z "$PKG_VERSION" ]; then
      PKG_VERSION=$(basename "$PKG_FILE" | sed -nE 's/^netops-([0-9]+\.[0-9]+\.[0-9]+)\.tar\.gz$/\1/p')
    fi
    [ -n "$PKG_VERSION" ] || die "não deu para ler a versão do nome do pacote; defina NETOPS_VERSION."
    ok "pacote local: $PKG_FILE (v$PKG_VERSION)"
    return
  fi
  local endpoint="releases/latest"
  [ -n "${NETOPS_VERSION:-}" ] && endpoint="releases/tags/v${NETOPS_VERSION#v}"
  local meta="$WORK/release.json"
  if ! gh_curl "https://api.github.com/repos/$REPO/$endpoint" -o "$meta" 2>>"$LOG"; then
    if [ -z "$TOKEN" ]; then
      die "não consegui consultar as releases de $REPO no GitHub. Se o repositório for privado, rode com um token:
    curl -fsSL -H \"Authorization: Bearer SEU_TOKEN\" https://raw.githubusercontent.com/$REPO/main/install.sh | sudo GITHUB_TOKEN=SEU_TOKEN bash"
    fi
    die "não consegui consultar as releases de $REPO (token sem acesso, release inexistente ou sem internet)."
  fi
  # tag e URLs (API) dos assets: netops-X.Y.Z.tar.gz e SHA256SUMS
  local parsed
  parsed=$("$PY" -I - "$meta" 2>&1 <<'PYEOF'
import json, re, sys
d = json.load(open(sys.argv[1]))
tag = d.get("tag_name", "")
m = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
if not m or d.get("draft") or d.get("prerelease"):
    sys.exit("release inválida: " + tag)
v = m[1]
assets = {a["name"]: a["url"] for a in d.get("assets", [])}
pkg, sums = assets.get(f"netops-{v}.tar.gz"), assets.get("SHA256SUMS")
if not pkg or not sums:
    sys.exit(f"a release {tag} não tem o pacote netops-{v}.tar.gz e SHA256SUMS")
print(v); print(pkg); print(sums)
PYEOF
) || die "$(tail -1 <<<"$parsed")"
  PKG_VERSION=$(sed -n 1p <<<"$parsed")
  local pkg_url sums_url
  pkg_url=$(sed -n 2p <<<"$parsed"); sums_url=$(sed -n 3p <<<"$parsed")
  info "release: v$PKG_VERSION"
  PKG_FILE="$WORK/netops-$PKG_VERSION.tar.gz"
  gh_curl "$pkg_url" -H "Accept: application/octet-stream" -o "$PKG_FILE" 2>>"$LOG" || die "download do pacote falhou."
  gh_curl "$sums_url" -H "Accept: application/octet-stream" -o "$WORK/SHA256SUMS" 2>>"$LOG" || die "download do SHA256SUMS falhou."
  local expected actual
  expected=$(awk -v f="netops-$PKG_VERSION.tar.gz" '$2==f || $2=="*"f {print $1}' "$WORK/SHA256SUMS")
  actual=$(sha256sum "$PKG_FILE" | awk '{print $1}')
  [ -n "$expected" ] && [ "$expected" = "$actual" ] || die "SHA256 do pacote não confere (esperado $expected, obtido $actual)."
  ok "pacote v$PKG_VERSION baixado e SHA256 conferido"
}

# Extrai o pacote como o atualizador do console faz (scripts/engine/update/engine.py:unpack):
# sem links/entradas especiais, conteúdo idêntico ao manifesto, hash e permissão de cada arquivo.
# Grava .netops-update/installed.json = manifesto, que o atualizador usa como versão instalada.
extract_package() {
  "$PY" -I - "$PKG_FILE" "$NETOPS_DIR" "$PKG_VERSION" <<'PYEOF' >>"$LOG" 2>&1 || die "pacote inválido (veja o log)."
import hashlib, json, os, sys, tarfile
from pathlib import Path, PurePosixPath
pkg, root, version = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
def safe(rel):
    p = PurePosixPath(rel)
    if not rel or "\\" in rel or "\x00" in rel or p.is_absolute() or any(x in ("", ".", "..") for x in rel.split("/")):
        sys.exit("caminho inseguro no pacote: " + rel)
    return rel
with tarfile.open(pkg, "r:gz") as tar:
    members = {}
    for m in tar:
        if not m.isfile() or m.name in members:
            sys.exit("pacote contém links, entradas especiais ou duplicatas")
        members[safe(m.name)] = m
    manifest = json.load(tar.extractfile(members["manifest.json"]))
    if manifest.get("repository") != "RedesBrasil/netops" or manifest.get("version") != version:
        sys.exit("manifesto de outro repositório/versão")
    files = manifest["files"]
    if set(members) != {"manifest.json"} | {"files/" + r for r in files}:
        sys.exit("conteúdo do pacote diverge do manifesto")
    for rel, info in sorted(files.items()):
        safe(rel)
        m = members["files/" + rel]
        raw = tar.extractfile(m).read()
        if len(raw) != info["size"] or m.mode != info["mode"] or hashlib.sha256(raw).hexdigest() != info["sha256"]:
            sys.exit("arquivo adulterado: " + rel)
        dest = root.joinpath(*PurePosixPath(rel).parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".netops-tmp")
        tmp.write_bytes(raw); os.chmod(tmp, info["mode"]); os.replace(tmp, dest)
state = root / ".netops-update"
state.mkdir(mode=0o700, exist_ok=True); os.chmod(state, 0o700)
fd = os.open(str(state / "installed.json"), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w") as out:
    json.dump(manifest, out, sort_keys=True)
print(f"extraídos {len(files)} arquivos (v{version})")
PYEOF
}

install_code() {
  step "Baixando o NetOps"
  FRESH=0
  if [ -f "$NETOPS_DIR/core/config/core-config.yaml" ]; then
    INSTALLED_VERSION=$(sed -nE 's/^  version: "([0-9.]+)".*/\1/p' "$NETOPS_DIR/core/config/core-config.yaml" | head -1)
    ok "NetOps v${INSTALLED_VERSION:-?} já instalado em $NETOPS_DIR — código e dados preservados (modo reparo)"
    info "atualizações: botão \"Verificar atualizações\" no console"
    return
  fi
  if [ -e "$NETOPS_DIR" ] && [ -n "$(ls -A "$NETOPS_DIR" 2>/dev/null)" ]; then
    die "$NETOPS_DIR existe, não está vazia e não é uma instalação do NetOps. Escolha outra pasta: sudo NETOPS_DIR=/outra/pasta bash"
  fi
  resolve_release
  mkdir -p "$NETOPS_DIR"
  extract_package
  INSTALLED_VERSION="$PKG_VERSION"; FRESH=1
  # pastas de trabalho que o pacote não traz (dados locais, git-ignorados no repositório)
  mkdir -p "$NETOPS_DIR"/{runs,reports,backups,memory}
  [ -f "$NETOPS_DIR/memory/MEMORY.md" ] || printf '# Memória — NetOps\n\n' >"$NETOPS_DIR/memory/MEMORY.md"
  ok "NetOps v$PKG_VERSION instalado em $NETOPS_DIR"
}

# ----------------------------------------------------------------------------- 5. venv
setup_venv() {
  step "Instalando as dependências Python (.venv)"
  local venv="$NETOPS_DIR/.venv"
  if [ -x "$venv/bin/python3" ] && ! ver_ge "$(py_ver "$venv/bin/python3")" "$MIN_VENV_PY"; then
    warn ".venv existente usa Python antigo; recriando"
    rm -rf "$venv"
  fi
  if [ ! -x "$venv/bin/python3" ]; then
    if ! run "$PY" -m venv "$venv"; then
      rm -rf "$venv"
      if [ "$PM" = apt ]; then   # Debian/Ubuntu separam o ensurepip no pacote pythonX.Y-venv
        run apt-get install -y -q "python$(py_ver "$PY")-venv" || true
      fi
      run "$PY" -m venv "$venv" || die "não consegui criar o .venv com $PY."
    fi
  fi
  run "$venv/bin/python3" -m pip install --upgrade --disable-pip-version-check -q pip || warn "não consegui atualizar o pip"
  info "pip install -r requirements.txt ..."
  run "$venv/bin/python3" -m pip install --disable-pip-version-check -q -r "$NETOPS_DIR/requirements.txt" \
    || die "pip install falhou. Últimas linhas:
$(tail -15 "$LOG")"
  ok ".venv pronto ($(py_ver "$venv/bin/python3"))"
}

# ----------------------------------------------------------------------------- 6. usuário + claude
setup_user() {
  step "Usuário do terminal web e agente Claude Code"
  # O terminal web do console roda como root mas abre o shell como `netops` (nunca shell root).
  if ! getent passwd netops >/dev/null; then
    run useradd --system --home-dir "$NETOPS_DIR" --no-create-home --shell /bin/bash netops \
      || die "não consegui criar o usuário netops."
    ok "usuário netops criado (home = $NETOPS_DIR)"
  else
    ok "usuário netops já existe"
  fi
  if [ "$FRESH" = 1 ]; then
    chown -R netops:netops "$NETOPS_DIR"
    chown -R root:root "$NETOPS_DIR/.netops-update"
  fi

  if [ "${NETOPS_SKIP_CLAUDE:-0}" = "1" ]; then
    warn "agente claude não instalado (NETOPS_SKIP_CLAUDE=1): a aba Claude Code não vai funcionar"
    return
  fi
  if [ -x /root/.local/bin/claude ] || HOME=/root PATH="/root/.local/bin:$PATH" have claude; then
    ok "agente claude já instalado"
    return
  fi
  info "instalando o agente claude (instalador oficial da Anthropic)..."
  if curl -fsSL --retry 3 https://claude.ai/install.sh -o "$WORK/claude-install.sh" 2>>"$LOG" \
     && run env HOME=/root bash "$WORK/claude-install.sh" && [ -x /root/.local/bin/claude ]; then
    ok "agente claude instalado ($(/root/.local/bin/claude --version 2>/dev/null | head -1))"
  else
    warn "não consegui instalar o agente claude; a aba Claude Code fica indisponível. Instale depois: curl -fsSL https://claude.ai/install.sh | bash"
  fi
}

# ----------------------------------------------------------------------------- 7. cofre = login
vault_ready() {
  [ -f "$NETOPS_DIR/network/credentials.yaml" ] && grep -qE '^vault:' "$NETOPS_DIR/network/credentials.yaml"
}

setup_vault() {
  step "Senha-mestra (login do console + cofre de credenciais)"
  local creds="$NETOPS_DIR/network/credentials.yaml"
  if vault_ready; then
    ok "cofre já inicializado — o login do console usa a senha-mestra existente"
    return
  fi
  if [ -n "${NETOPS_MASTER_PASSWORD:-}" ]; then
    (cd "$NETOPS_DIR" && NETOPS_MASTER_PASSWORD="$NETOPS_MASTER_PASSWORD" "$NETOPS_DIR/.venv/bin/python3" - "$creds" <<'PYEOF') >>"$LOG" 2>&1 || die "não consegui inicializar o cofre."
import os, sys
from pathlib import Path
sys.path.insert(0, "scripts/engine"); sys.path.insert(0, "scripts/engine/vault")
import cli
from lib import vault
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8") if path.exists() else "version: 1\n\ncredentials: {}\n"
meta, _key = vault.build_meta(os.environ["NETOPS_MASTER_PASSWORD"])
cli._atomic_write(path, cli._set_vault_block(text, meta))
PYEOF
    ok "cofre inicializado com NETOPS_MASTER_PASSWORD"
  elif has_tty; then
    info "Crie a senha-mestra. Ela é o LOGIN do console e protege as senhas dos equipamentos."
    info "Guarde-a bem: não há como recuperá-la."
    local tries=0
    until vault_ready; do
      tries=$((tries + 1))
      [ "$tries" -le 3 ] || die "senha-mestra não definida."
      (cd "$NETOPS_DIR" && "$NETOPS_DIR/.venv/bin/python3" scripts/engine/vault/cli.py init) </dev/tty >/dev/tty 2>&1 || true
    done
    ok "cofre inicializado"
  else
    NO_LOGIN=1
    warn "sem terminal para definir a senha-mestra: o console vai escutar só em 127.0.0.1 (sem login ele ficaria aberto na rede). Rode o instalador de novo num terminal para liberar o acesso pela rede."
  fi
  [ -f "$creds" ] && chown root:root "$creds" && chmod 600 "$creds"
  return 0
}

# ----------------------------------------------------------------------------- 8. serviço + console
setup_service() {
  step "Serviço de boot e console web"
  # Endereço: NETOPS_HOST > 127.0.0.1 (sem senha-mestra) > o 1º IP da máquina (o mesmo do start.sh)
  BIND_HOST="${NETOPS_HOST:-}"
  local fixed_host="$BIND_HOST"
  if [ "${NO_LOGIN:-0}" = "1" ]; then BIND_HOST=127.0.0.1; fixed_host=127.0.0.1; fi
  if [ -z "$BIND_HOST" ]; then
    BIND_HOST=$(primary_ip)
    # sem `hostname -I` (ex.: Arch) o start.sh não acharia o IP sozinho: fixa no serviço
    hostname -I >/dev/null 2>&1 || fixed_host="$BIND_HOST"
  fi
  BIND_HOST="${BIND_HOST:-127.0.0.1}"

  # start.sh novo (>= 2.4) sobe desacoplado com --yes; o antigo (<= 2.3.1) roda em primeiro plano.
  local start="$NETOPS_DIR/scripts/engine/ui/start.sh"
  START_MANAGED=0; grep -q -- '--yes' "$start" && START_MANAGED=1
  if [ "$START_MANAGED" = 1 ]; then
    UNIT_TYPE=$'Type=oneshot\nRemainAfterExit=yes'; START_ARGS=" --yes"
  else
    UNIT_TYPE=$'Type=simple\nRestart=on-failure\nRestartSec=5\nKillMode=mixed'; START_ARGS=""
  fi
  if [ "${NETOPS_NO_SERVICE:-0}" != "1" ] && [ -d /run/systemd/system ]; then
    local envfile=/etc/default/netops-console unit=/etc/systemd/system/netops-console.service
    if [ -f "$unit" ] && ! grep -q 'netops-install' "$unit"; then
      ok "serviço netops-console já existe (personalizado) — mantido como está"
    else
      {
        echo "# NetOps Console — lido pelo serviço netops-console (gerado pelo install.sh)."
        echo "NETOPS_UI_PORT=$PORT"
        [ -n "$fixed_host" ] && echo "NETOPS_UI_HOST=$fixed_host"
        true
      } >"$envfile"
      cat >"$unit" <<EOF
# netops-install — gerado pelo install.sh. Sobe o console no boot pelo launcher oficial
# (scripts/engine/ui/start.sh), que desacopla, valida e mantém uma instância só.
[Unit]
Description=NetOps Console
Wants=network-online.target
After=network-online.target

[Service]
$UNIT_TYPE
WorkingDirectory=$NETOPS_DIR
Environment=HOME=/root NETOPS_UI_HOME=/root
EnvironmentFile=-$envfile
ExecStart=$NETOPS_DIR/scripts/engine/ui/start.sh$START_ARGS
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
EOF
      run systemctl daemon-reload
      run systemctl enable netops-console.service || warn "não consegui habilitar o serviço de boot"
      ok "serviço netops-console habilitado (sobe sozinho no boot)"
    fi
  elif [ "${NETOPS_NO_SERVICE:-0}" != "1" ]; then
    warn "systemd ausente: o console não sobe sozinho no boot (suba com $NETOPS_DIR/scripts/engine/ui/start.sh)"
  fi

  open_firewall

  URL="http://$BIND_HOST:$PORT/"
  local sup
  sup=$(pgrep -of "update/supervisor.py --root $NETOPS_DIR --" || true)
  if [ -n "$sup" ]; then
    # Já rodando: NÃO reinicia (derrubaria as sessões da aba Claude). Usa o host/porta reais dele.
    local args=() i h="" p=""
    mapfile -d '' args < "/proc/$sup/cmdline" 2>/dev/null || true
    for i in "${!args[@]}"; do
      case "${args[$i]}" in --host) h="${args[$((i+1))]:-}" ;; --port) p="${args[$((i+1))]:-}" ;; esac
    done
    BIND_HOST="${h:-$BIND_HOST}"; PORT="${p:-$PORT}"; URL="http://$BIND_HOST:$PORT/"
    case "$(http_code "$URL")" in
      200|301|302|303|401|403) ok "console já está rodando em $URL (não reiniciado, para não derrubar sessões)" ;;
      *) warn "console já roda nesta pasta, mas não respondeu em $URL; não mexi nele (reinicie com start.sh --yes)" ;;
    esac
    return
  fi
  info "subindo o console (scripts/engine/ui/start.sh)..."
  if [ "$START_MANAGED" = 0 ] && [ -f /etc/systemd/system/netops-console.service ] && [ -d /run/systemd/system ] \
     && grep -q 'netops-install' /etc/systemd/system/netops-console.service; then
    run systemctl restart netops-console.service || true          # start.sh antigo: o serviço segura o processo
  elif [ "$START_MANAGED" = 0 ]; then
    # `exec` = o subshell vira o próprio console: não herda o trap nem segura o stdout do instalador
    (cd "$NETOPS_DIR" && exec env HOME=/root NETOPS_UI_HOME=/root NETOPS_UI_HOST="$BIND_HOST" \
      NETOPS_UI_PORT="$PORT" setsid "$start") >>/tmp/netops-restart.log 2>&1 </dev/null &
    disown || true
  else
    (cd "$NETOPS_DIR" && HOME=/root NETOPS_UI_HOME=/root NETOPS_UI_HOST="$BIND_HOST" NETOPS_UI_PORT="$PORT" \
      "$start" --yes) >>"$LOG" 2>&1 </dev/null || true
  fi
  local i code=""
  for i in $(seq 90); do
    code=$(http_code "$URL")
    case "$code" in 200|301|302|303|401|403) break ;; esac
    sleep 1
  done
  case "$code" in
    200|301|302|303|401|403) ok "console respondendo em $URL" ;;
    *) die "o console não respondeu em $URL. Veja /tmp/netops-restart.log e $LOG.
$(tail -15 /tmp/netops-restart.log 2>/dev/null || true)" ;;
  esac
}

open_firewall() {
  [ "${NO_LOGIN:-0}" = "1" ] && return 0
  if have ufw && ufw status 2>/dev/null | grep -q "Status: active"; then
    run ufw allow "$PORT/tcp" && ok "firewall (ufw): porta $PORT/tcp liberada" || warn "não liberei a porta $PORT no ufw"
  elif have firewall-cmd && firewall-cmd --state >/dev/null 2>&1; then
    { run firewall-cmd --permanent --add-port="$PORT/tcp" && run firewall-cmd --reload; } \
      && ok "firewall (firewalld): porta $PORT/tcp liberada" || warn "não liberei a porta $PORT no firewalld"
  fi
  return 0
}

# ----------------------------------------------------------------------------- 9. testes
health_check() {
  step "Testando a instalação"
  local fails=0 py="$NETOPS_DIR/.venv/bin/python3" out
  if out=$(cd "$NETOPS_DIR" && "$py" - <<'PYEOF' 2>&1
import re, subprocess, sys
from importlib import metadata
names = []
for line in open("requirements.txt", encoding="utf-8"):
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line.split("#", 1)[0])
    if m:
        names.append(m[1])
bad = []
for n in names:
    try:
        metadata.version(n)
    except metadata.PackageNotFoundError:
        bad.append(n)
chk = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
if chk.returncode:
    bad.append("pip check: " + chk.stdout.strip().splitlines()[0])
print("faltando: " + ", ".join(bad) if bad else f"{len(names)} pacotes do requirements.txt, pip check OK")
raise SystemExit(1 if bad else 0)
PYEOF
  ); then ok "Python: $out"; else printf '    %s✗%s Python: %s\n' "$R" "$N" "$out"; log "FALHA $out"; fails=$((fails + 1)); fi

  if (cd "$NETOPS_DIR/scripts/engine/ui" && env -i PATH=/usr/bin:/bin HOME="$WORK" NETOPS_UI_DATA_ROOT="$WORK/smoke" \
        timeout 60 "$py" -c "import sys; sys.path.insert(0, '.'); import app") >>"$LOG" 2>&1; then
    ok "backend do console importa sem erro"
  else printf '    %s✗%s backend do console não importa (ver log)\n' "$R" "$N"; fails=$((fails + 1)); fi

  if (cd "$NETOPS_DIR" && python3 scripts/tools/access/session.py --help) >>"$LOG" 2>&1; then
    ok "acesso a equipamentos (session.py) pronto"
  else printf '    %s✗%s session.py não executa (ver log)\n' "$R" "$N"; fails=$((fails + 1)); fi

  local b missing=()
  for b in nmap ping ssh sftp git zip curl flock ss pgrep; do have "$b" || missing+=("$b"); done
  if [ ${#missing[@]} -eq 0 ]; then ok "ferramentas: nmap ping ssh sftp git zip curl flock ss pgrep"
  else printf '    %s✗%s ferramentas ausentes: %s\n' "$R" "$N" "${missing[*]}"; fails=$((fails + 1)); fi
  for b in traceroute mtr; do have "$b" || warn "$b ausente (diagnósticos que o usam ficam indisponíveis)"; done

  if [ -d /run/systemd/system ]; then
    if systemctl is-active --quiet cron 2>/dev/null || systemctl is-active --quiet crond 2>/dev/null \
       || systemctl is-active --quiet cronie 2>/dev/null; then ok "cron ativo (Tarefas agendadas)"
    else warn "cron não está ativo: Tarefas agendadas não disparam"; fi
  fi

  getent passwd netops >/dev/null && ok "usuário netops (terminal web)" || { printf '    %s✗%s usuário netops ausente\n' "$R" "$N"; fails=$((fails + 1)); }

  if [ -x /root/.local/bin/claude ]; then ok "agente claude $(/root/.local/bin/claude --version 2>/dev/null | head -1)"
  elif [ "${NETOPS_SKIP_CLAUDE:-0}" != "1" ]; then printf '    %s!%s agente claude ausente (aba Claude Code indisponível)\n' "$Y" "$N"; fi

  if vault_ready; then ok "cofre inicializado (login exigido no console)"; else warn "cofre sem senha-mestra"; fi

  local st
  st=$(curl -s --max-time 5 "${URL}api/auth/status" 2>/dev/null || true)
  if printf '%s' "$st" | grep -q '"auth_required"'; then ok "API do console respondendo ($st)"
  else printf '    %s✗%s API do console não respondeu em %sapi/auth/status\n' "$R" "$N" "$URL"; fails=$((fails + 1)); fi

  have gh || warn "GitHub CLI (gh) ausente: o botão de atualizar do console precisa dele (instale e rode: gh auth login)"
  HEALTH_FAILS=$fails
}

# ----------------------------------------------------------------------------- 10. resumo
summary() {
  local line="────────────────────────────────────────────────────────────────"
  echo
  if [ "${HEALTH_FAILS:-0}" -gt 0 ]; then
    printf '%s%s%s\n' "$Y" "$line" "$N"
    printf ' %s⚠ NetOps instalado com %s falha(s) nos testes — veja acima e %s%s\n' "$Y$B" "$HEALTH_FAILS" "$LOG" "$N"
  else
    printf '%s%s%s\n' "$G" "$line" "$N"
    printf ' %s✅ NetOps v%s está pronto!%s\n' "$G$B" "${INSTALLED_VERSION:-?}" "$N"
  fi
  echo
  printf '   Acesse:  %s%s%s\n' "$B$C" "$URL" "$N"
  echo
  if [ "${NO_LOGIN:-0}" = "1" ]; then
    echo "   Escutando só nesta máquina (sem senha-mestra). Para liberar na rede, rode de novo"
    echo "   num terminal:  curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | sudo bash"
  else
    echo "   1. Entre com a senha-mestra que você acabou de criar."
  fi
  echo "   2. Cadastre seus equipamentos em Hosts (e as credenciais em Credenciais)."
  echo "   3. Na aba Claude Code, digite /login uma vez e peça o que precisar."
  echo
  echo "   Pasta: $NETOPS_DIR   ·   Log: $LOG"
  echo "   Reiniciar o console: $NETOPS_DIR/scripts/engine/ui/start.sh --yes"
  if [ ${#WARNINGS[@]} -gt 0 ]; then
    echo
    printf '   %sAvisos:%s\n' "$Y" "$N"
    local w; for w in "${WARNINGS[@]}"; do printf '    - %s\n' "$w"; done
  fi
  if [ "${HEALTH_FAILS:-0}" -gt 0 ]; then printf '%s%s%s\n' "$Y" "$line" "$N"; else printf '%s%s%s\n' "$G" "$line" "$N"; fi
}

main() {
  printf '\n%sNetOps — instalação%s  (github.com/%s)\n' "$B" "$N" "$REPO"
  preflight "$@"
  WORK=$(mktemp -d /tmp/netops-install.XXXXXX)
  trap 'rm -rf "$WORK"' EXIT
  install_system_packages
  pick_python
  install_code
  setup_venv
  setup_user
  setup_vault
  setup_service
  health_check
  summary
  trap - ERR
  [ "${HEALTH_FAILS:-0}" -eq 0 ] || exit 1
}

main "$@"
