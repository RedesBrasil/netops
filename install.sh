#!/usr/bin/env bash
# NetOps — instalador em uma linha (Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/RedesBrasil/netops/main/install.sh | sudo bash
#
# O que faz, de ponta a ponta:
#   1. instala os pacotes do sistema (Python, nmap, cron, ping/traceroute/mtr/tcpdump, ssh, git, gh...);
#   2. baixa o pacote da última release do GitHub (netops-X.Y.Z.tar.gz), confere o SHA256 e o
#      manifesto (hash e permissão de cada arquivo) e extrai em /opt/netops;
#   3. cria o .venv e instala requirements.txt;
#   4. cria a conta operacional `netops` (HOME /var/lib/netops). TODO o NetOps roda como ela:
#      console, supervisor, IA, terminal, agendador e atualizador — nunca como root;
#   5. instala o .venv e o agente `claude` COMO `netops`; pede a senha-mestra do cofre;
#   6. serviço systemd DO USUÁRIO netops-console@<slug> (linger = sobe no boot sem login);
#   7. administração Local: conta `netops-admin` (senha aleatória só no cofre) + host Local protegido;
#   7b. permissões da conta: rede sem root (ping/nmap/tcpdump...) e, com o cofre destrancado, root por
#       `sudo` ou direto (apt/systemctl/nft... — "sudo automático"). Ver scripts/engine/privileges/SKILL.md;
#   8. testa tudo e mostra o endereço: http://<IP>:<porta>/
#
# Root só PROVISIONA (pacotes, contas, serviço, firewall). Instalação antiga (console como root,
# "layout 1") é detectada e NÃO é migrada sozinha: o instalador repara e mostra o comando de migração
# (scripts/engine/identity/migrate.py).
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
#   NETOPS_SSH_KEY=/root/.ssh/netops_deploy   repositório privado por chave SSH (deploy key somente leitura):
#                                 clona a tag da release via git+SSH e monta o pacote localmente
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
  # identidade operacional (layout 2): ver scripts/engine/lib/runtime_identity.py
  SLUG=$(printf '%s' "${NETOPS_DIR#/}" | sed -E 's/[^A-Za-z0-9]+/-/g; s/^-+//; s/-+$//')
  IDENT_FILE="/etc/netops/instances/$SLUG.env"
  OP_USER="netops"; OP_HOME="/var/lib/netops"
  UNIT="netops-console@$SLUG.service"
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
        procps hostname cron nmap iputils-ping openssh-client git zip unzip sudo dbus-user-session \
        -- traceroute mtr-tiny python-is-python3 gh openssh-sftp-server libcap2-bin tcpdump iputils-arping \
           iputils-tracepath fping iperf3 whois snmp ethtool socat arp-scan bind9-dnsutils ;;
    dnf|yum)
      pkg_install python3 python3-pip ca-certificates curl tar gzip iproute util-linux procps-ng \
        hostname cronie nmap iputils openssh-clients git zip unzip sudo dbus \
        -- traceroute mtr openssh-server libcap tcpdump fping iperf3 whois net-snmp-utils ethtool socat bind-utils
      # gh não vem no RHEL/Rocky/Alma: usa o repositório oficial do GitHub CLI
      if ! have gh && ! run "$PM" install -y gh; then
        curl -fsSL https://cli.github.com/packages/rpm/gh-cli.repo -o /etc/yum.repos.d/gh-cli.repo 2>>"$LOG" \
          && run "$PM" install -y gh || warn "pacote opcional indisponível: gh"
      fi ;;
    zypper)
      pkg_install python3 python3-pip ca-certificates curl tar gzip iproute2 util-linux procps \
        hostname cron nmap iputils openssh-clients git zip unzip sudo dbus-1 \
        -- traceroute mtr gh openssh-server libcap-progs tcpdump fping iperf whois net-snmp ethtool socat bind-utils ;;
    pacman)
      pkg_install python python-pip ca-certificates curl tar gzip iproute2 util-linux procps-ng \
        inetutils cronie nmap iputils openssh git zip unzip sudo dbus \
        -- traceroute mtr github-cli libcap tcpdump fping iperf3 whois net-snmp ethtool socat bind arp-scan ;;
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
# Repositório privado por chave SSH: a API de releases não aceita chave, então clona a tag da release
# (git+SSH, deploy key somente leitura) e monta o pacote com o próprio motor de release do código clonado.
resolve_release_ssh() {
  local key="$NETOPS_SSH_KEY" url="git@github.com:$REPO.git"
  [ -r "$key" ] || die "NETOPS_SSH_KEY não encontrada ou sem leitura: $key"
  have git && have ssh || die "git e ssh são necessários para o modo SSH."
  # known_hosts com as chaves oficiais do GitHub, obtidas por HTTPS (TLS) em api.github.com/meta
  local kh="$WORK/known_hosts"
  curl -fsSL --retry 3 https://api.github.com/meta -o "$WORK/meta.json" 2>>"$LOG" \
    && "$PY" -I - "$WORK/meta.json" >"$kh" <<'PYEOF' || die "não consegui obter as chaves de host do GitHub (api.github.com/meta)."
import json, sys
for k in json.load(open(sys.argv[1]))["ssh_keys"]:
    print("github.com", k)
PYEOF
  export GIT_SSH_COMMAND="ssh -i $key -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile=$kh -o StrictHostKeyChecking=yes"
  local tag="${NETOPS_VERSION:+v${NETOPS_VERSION#v}}"
  if [ -z "$tag" ]; then
    tag=$(git ls-remote --tags --refs "$url" 'v*' 2>>"$LOG" | sed -E 's|.*refs/tags/||' \
          | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1) || true
    [ -n "$tag" ] || die "não consegui listar as versões em $url por SSH. Confira se a chave está cadastrada como Deploy key do repositório:
    $(cat "$key.pub" 2>/dev/null || echo "(sem $key.pub)")"
  fi
  info "versão: $tag (via git+SSH)"
  run git clone -q --depth 1 --branch "$tag" "$url" "$WORK/src" || die "git clone de $tag falhou (tag inexistente ou chave sem acesso). Veja $LOG."
  PKG_VERSION="${tag#v}"; PKG_FILE="$WORK/netops-$PKG_VERSION.tar.gz"
  "$PY" -I - "$WORK/src" "$PKG_FILE" "$PKG_VERSION" >>"$LOG" 2>&1 <<'PYEOF' || die "não consegui montar o pacote a partir do clone (veja o log)."
import sys
from pathlib import Path
src, out, version = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(src / "scripts" / "engine"))
from update.engine import git_files
from update.release import build_package
from update.common import read_version
assert read_version(src) == version, "versão do código difere da tag"
build_package(git_files(src), version, out)
PYEOF
  ok "pacote v$PKG_VERSION montado do clone SSH"
}

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
  if [ -n "${NETOPS_SSH_KEY:-}" ]; then resolve_release_ssh; return; fi
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
    if [ -f "$IDENT_FILE" ]; then LAYOUT=2; else
      LAYOUT=1
      warn "instalação LEGADA (console roda como root). Ela continua funcionando, mas a migração para a conta dedicada \`netops\` é recomendada: sudo python3 -I $NETOPS_DIR/scripts/engine/identity/migrate.py plan"
    fi
    return
  fi
  if [ -e "$NETOPS_DIR" ] && [ -n "$(ls -A "$NETOPS_DIR" 2>/dev/null)" ]; then
    die "$NETOPS_DIR existe, não está vazia e não é uma instalação do NetOps. Escolha outra pasta: sudo NETOPS_DIR=/outra/pasta bash"
  fi
  resolve_release
  mkdir -p "$NETOPS_DIR"
  extract_package
  INSTALLED_VERSION="$PKG_VERSION"; FRESH=1; LAYOUT=2
  # versão antiga (sem suporte à conta dedicada no launcher): instala no modelo antigo
  grep -q 'USER_MODE' "$NETOPS_DIR/scripts/engine/ui/start.sh" 2>/dev/null || { LAYOUT=1; warn "v$PKG_VERSION é anterior à conta dedicada: instalada no modelo antigo (root)"; }
  # pastas de trabalho que o pacote não traz (dados locais, git-ignorados no repositório)
  mkdir -p "$NETOPS_DIR"/{runs,reports,backups,memory}
  [ -f "$NETOPS_DIR/memory/MEMORY.md" ] || printf '# Memória — NetOps\n\n' >"$NETOPS_DIR/memory/MEMORY.md"
  [ -f "$NETOPS_DIR/core/config/project-config.yaml" ] || cp "$NETOPS_DIR/core/config/project-config.example.yaml" "$NETOPS_DIR/core/config/project-config.yaml" 2>/dev/null || true
  ok "NetOps v$PKG_VERSION instalado em $NETOPS_DIR"
}

# ----------------------------------------------------------------------------- 5. venv
setup_venv() {
  step "Instalando as dependências Python (.venv${OP_USER:+ como $OP_USER})"
  local venv="$NETOPS_DIR/.venv"
  local run=run; [ "${LAYOUT:-1}" = 2 ] && run=run_op
  if [ -x "$venv/bin/python3" ] && ! ver_ge "$(py_ver "$venv/bin/python3")" "$MIN_VENV_PY"; then
    warn ".venv existente usa Python antigo; recriando"
    rm -rf "$venv"
  fi
  if [ ! -x "$venv/bin/python3" ]; then
    if ! $run "$PY" -m venv "$venv"; then
      rm -rf "$venv"
      if [ "$PM" = apt ]; then   # Debian/Ubuntu separam o ensurepip no pacote pythonX.Y-venv
        run apt-get install -y -q "python$(py_ver "$PY")-venv" || true
      fi
      $run "$PY" -m venv "$venv" || die "não consegui criar o .venv com $PY."
    fi
  fi
  $run "$venv/bin/python3" -m pip install --upgrade --disable-pip-version-check -q pip || warn "não consegui atualizar o pip"
  info "pip install -r requirements.txt ..."
  $run "$venv/bin/python3" -m pip install --disable-pip-version-check -q -r "$NETOPS_DIR/requirements.txt" \
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
  # Hooks do Claude Code (guarda: backup antes de alterar etc.) em .claude/settings.json.
  # Pacotes até a 2.3.1 não trazem scripts/engine/hooks/: aí não há o que instalar.
  local hooks="$NETOPS_DIR/scripts/engine/hooks/install_claude_hooks.py"
  if [ -f "$hooks" ]; then
    if run python3 "$hooks" --root "$NETOPS_DIR"; then ok "hooks de segurança do Claude Code em .claude/settings.json"
    else warn "não consegui gravar os hooks em $NETOPS_DIR/.claude/settings.json (veja o log)"; fi
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


# ----------------------------------------------------------------------------- 6b. conta operacional (layout 2)
# Executa como a conta operacional, com o ambiente DELA (nunca só trocar $HOME mantendo UID 0).
as_op() {
  local uid; uid=$(id -u "$OP_USER")
  runuser -u "$OP_USER" -- env -i PATH="$OP_HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    HOME="$OP_HOME" USER="$OP_USER" LOGNAME="$OP_USER" LANG=C.UTF-8 TERM="${TERM:-dumb}" \
    XDG_RUNTIME_DIR="/run/user/$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" "$@"
}
# (segredos NUNCA entram na linha de comando acima: ela aparece no `ps` de qualquer usuário)
run_op() { log "\$ (como $OP_USER) $*"; (cd "$NETOPS_DIR" && as_op "$@") >>"$LOG" 2>&1; }

require_user_systemd() {
  [ -d /run/systemd/system ] || die "systemd ausente: o NetOps roda como serviço systemd do usuário $OP_USER. Use uma máquina/CT com systemd."
  have loginctl && have runuser || die "loginctl/runuser ausentes (pacotes systemd/util-linux)."
}

setup_account() {
  step "Conta operacional ($OP_USER) — o NetOps nunca roda como root"
  require_user_systemd
  if getent passwd "$OP_USER" >/dev/null; then
    local home uid; home=$(getent passwd "$OP_USER" | cut -d: -f6); uid=$(id -u "$OP_USER")
    [ "$uid" != 0 ] || die "a conta $OP_USER tem UID 0 — incompatível; não vou reaproveitar."
    if [ "$home" != "$OP_HOME" ]; then
      [ "$home" = "$NETOPS_DIR" ] || die "a conta $OP_USER já existe com HOME $home (esperado $OP_HOME). Ajuste ou remova a conta antes."
      run usermod --home "$OP_HOME" "$OP_USER" || die "não consegui ajustar o HOME de $OP_USER"
    fi
    if id -nG "$OP_USER" | tr ' ' '\n' | grep -qxE 'sudo|wheel|docker|lxd|disk|root'; then
      die "a conta $OP_USER está num grupo administrativo (sudo/wheel/docker/lxd/disk/root). Remova antes de instalar."
    fi
    ok "conta $OP_USER já existe (HOME $OP_HOME)"
  else
    run useradd --system --home-dir "$OP_HOME" --create-home --shell /bin/bash --comment "NetOps" "$OP_USER" \
      || die "não consegui criar a conta $OP_USER."
    ok "conta $OP_USER criada (HOME $OP_HOME, sem senha; sudo só com o cofre destrancado)"
  fi
  install -d -m 700 -o "$OP_USER" -g "$OP_USER" "$OP_HOME"
  chown "$OP_USER:$OP_USER" "$OP_HOME"; chmod 700 "$OP_HOME"
  local uid i; uid=$(id -u "$OP_USER")
  # host com I/O alto pode passar dos 90 s padrão para subir o user@UID: 5 min só para esta conta
  install -d -m 755 "/etc/systemd/system/user@$uid.service.d"
  printf '%s\n' "# NetOps: gerenciador do usuário operacional pode demorar em host com I/O alto" "[Service]" "TimeoutStartSec=5min" \
    >"/etc/systemd/system/user@$uid.service.d/90-netops.conf"
  run systemctl daemon-reload || true
  # logind pode demorar logo após instalar pacotes (dbus/logind reiniciando): tenta de novo e, em último
  # caso, usa o mesmo mecanismo do loginctl (arquivo de linger + user@UID.service)
  for i in 1 2 3; do run loginctl enable-linger "$OP_USER" && break; sleep 5; done
  if [ ! -e "/var/lib/systemd/linger/$OP_USER" ]; then
    install -d -m 755 /var/lib/systemd/linger && : >"/var/lib/systemd/linger/$OP_USER"
    run systemctl start "user@$uid.service" || die "não consegui habilitar o linger de $OP_USER (loginctl enable-linger $OP_USER)"
  fi
  [ -S "/run/user/$uid/bus" ] || info "aguardando o gerenciador systemd do usuário $OP_USER (pode levar 1–2 min na 1ª vez)..."
  for i in $(seq 300); do [ -S "/run/user/$uid/bus" ] && break; sleep 1; done
  [ -S "/run/user/$uid/bus" ] || die "o gerenciador systemd do usuário $OP_USER não subiu (/run/user/$uid/bus). Em Debian/Ubuntu: apt install dbus-user-session; confira 'loginctl show-user $OP_USER'."
  ok "linger + gerenciador systemd do usuário ativo"
}

own_tree() {  # só numa instalação NOVA: pasta inteira para a conta operacional (sem seguir links)
  [ "$FRESH" = 1 ] || return 0
  chown -R --no-dereference "$OP_USER:$OP_USER" "$NETOPS_DIR"
  chmod 750 "$NETOPS_DIR"
  chmod 700 "$NETOPS_DIR/.netops-update"
  ok "$NETOPS_DIR pertence a $OP_USER"
}

setup_hooks_claude_op() {
  step "Hooks e agente Claude Code (como $OP_USER)"
  local hooks="$NETOPS_DIR/scripts/engine/hooks/install_claude_hooks.py"
  if [ -f "$hooks" ]; then
    if run_op python3 "$hooks" --root "$NETOPS_DIR"; then ok "hooks de segurança do Claude Code em .claude/settings.json"
    else warn "não consegui gravar os hooks em $NETOPS_DIR/.claude/settings.json (veja o log)"; fi
  fi
  if [ "${NETOPS_SKIP_CLAUDE:-0}" = "1" ]; then
    warn "agente claude não instalado (NETOPS_SKIP_CLAUDE=1): a aba Claude Code não vai funcionar"; return
  fi
  if [ -x "$OP_HOME/.local/bin/claude" ]; then ok "agente claude já instalado em $OP_HOME/.local/bin"; return; fi
  info "instalando o agente claude como $OP_USER (instalador oficial da Anthropic)..."
  if curl -fsSL --retry 3 https://claude.ai/install.sh -o "$WORK/claude-install.sh" 2>>"$LOG"; then
    install -m 644 -o "$OP_USER" -g "$OP_USER" "$WORK/claude-install.sh" "$OP_HOME/.claude-install.sh"
    run_op bash "$OP_HOME/.claude-install.sh" || true
    rm -f "$OP_HOME/.claude-install.sh"
  fi
  if [ -x "$OP_HOME/.local/bin/claude" ]; then ok "agente claude instalado ($(as_op "$OP_HOME/.local/bin/claude" --version 2>/dev/null | head -1))"
  else warn "não consegui instalar o agente claude; a aba Claude Code fica indisponível. Depois: sudo -u $OP_USER -H bash -c 'curl -fsSL https://claude.ai/install.sh | bash'"; fi
}

setup_vault_op() {
  step "Senha-mestra (login do console + cofre de credenciais)"
  local creds="$NETOPS_DIR/network/credentials.yaml"
  if vault_ready; then ok "cofre já inicializado — o login do console usa a senha-mestra existente"; return; fi
  if [ -n "${NETOPS_MASTER_PASSWORD:-}" ]; then
    # senha-mestra pelo stdin (nunca em argv/env de outro usuário)
    (cd "$NETOPS_DIR" && printf '%s\n' "$NETOPS_MASTER_PASSWORD" | as_op "$NETOPS_DIR/.venv/bin/python3" -c '
import sys
from pathlib import Path
sys.path.insert(0, "scripts/engine"); sys.path.insert(0, "scripts/engine/vault")
import cli
from lib import vault
pw = sys.stdin.readline().rstrip("\n")
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8") if path.exists() else "version: 1\n\ncredentials: {}\n"
meta, _key = vault.build_meta(pw)
cli._atomic_write(path, cli._set_vault_block(text, meta))
' "$creds") >>"$LOG" 2>&1 || die "não consegui inicializar o cofre."
    ok "cofre inicializado com NETOPS_MASTER_PASSWORD"
  elif has_tty; then
    info "Crie a senha-mestra. Ela é o LOGIN do console e protege as senhas dos equipamentos."
    info "Guarde-a bem: não há como recuperá-la."
    local tries=0
    until vault_ready; do
      tries=$((tries + 1)); [ "$tries" -le 3 ] || die "senha-mestra não definida."
      (cd "$NETOPS_DIR" && as_op "$NETOPS_DIR/.venv/bin/python3" scripts/engine/vault/cli.py init) </dev/tty >/dev/tty 2>&1 || true
    done
    ok "cofre inicializado"
  else
    NO_LOGIN=1
    warn "sem terminal para definir a senha-mestra: o console vai escutar só em 127.0.0.1. Rode o instalador de novo num terminal para liberar o acesso pela rede."
  fi
  if [ -f "$creds" ]; then chown "$OP_USER:$OP_USER" "$creds"; chmod 600 "$creds"; fi
  return 0
}

setup_projects_base() {
  local base=/opt/projetos
  if [ ! -e "$base" ]; then install -d -m 750 -o "$OP_USER" -g "$OP_USER" "$base"; ok "base de projetos $base (de $OP_USER)"
  elif [ "$(stat -c %U "$base")" = "$OP_USER" ]; then ok "base de projetos $base"
  else warn "$base existe e não pertence a $OP_USER: projetos novos ali vão falhar por permissão (não alterei nada)"; fi
}

write_identity() {
  # bind: NETOPS_HOST > 127.0.0.1 (sem senha-mestra) > vazio (start.sh usa o 1º IP)
  local host="${NETOPS_HOST:-}"
  [ "${NO_LOGIN:-0}" = "1" ] && host=127.0.0.1
  hostname -I >/dev/null 2>&1 || host="${host:-$(primary_ip)}"
  [[ "$host" =~ ^[A-Za-z0-9_.:%-]*$ ]] || die "NETOPS_HOST inválido"
  local id=""
  [ -f "$IDENT_FILE" ] && id=$(sed -nE 's/^NETOPS_INSTANCE_ID=(.*)$/\1/p' "$IDENT_FILE")
  [ -n "$id" ] || id=$(cat /proc/sys/kernel/random/uuid)
  install -d -m 755 -o root -g root /etc/netops /etc/netops/instances
  local tmp="$IDENT_FILE.tmp"
  {
    echo "# NetOps — identidade desta instalação (gerado por install.sh; root-owned)."
    echo "# A conta operacional NÃO pode alterar este arquivo. Ver scripts/engine/lib/runtime_identity.py"
    echo "NETOPS_LAYOUT=2"
    echo "NETOPS_DIR=$NETOPS_DIR"
    echo "NETOPS_RUNTIME_USER=$OP_USER"
    echo "NETOPS_RUNTIME_HOME=$OP_HOME"
    echo "NETOPS_INSTANCE_ID=$id"
    echo "NETOPS_UI_PORT=$PORT"
    if [ -n "$host" ]; then echo "NETOPS_UI_HOST=$host"; fi
  } >"$tmp"
  chmod 644 "$tmp"; chown root:root "$tmp"; mv -f "$tmp" "$IDENT_FILE"
  ok "identidade: $IDENT_FILE (conta $OP_USER, instância $id)"
}

setup_user_service() {
  step "Serviço de boot (systemd do usuário $OP_USER) e console web"
  local src="$NETOPS_DIR/scripts/engine/ui/systemd" f
  install -d -m 755 /etc/systemd/user
  for f in netops-console@.service netops-localadmin@.service; do
    [ -f "$src/$f" ] || die "unidade $f ausente no pacote"
    install -m 644 -o root -g root "$src/$f" "/etc/systemd/user/$f"
  done
  # serviço root antigo desta pasta (instalação legada) nunca fica ativo junto
  if [ -f /etc/systemd/system/netops-console.service ] && grep -q "$NETOPS_DIR" /etc/systemd/system/netops-console.service; then
    warn "existe /etc/systemd/system/netops-console.service (root) para $NETOPS_DIR: desabilitado para não subir em paralelo"
    run systemctl disable netops-console.service || true
  fi
  run_op systemctl --user daemon-reload || die "systemctl --user daemon-reload falhou"
  run_op systemctl --user enable "$UNIT" || die "não consegui habilitar $UNIT"
  ok "$UNIT habilitado (sobe no boot pelo linger, sem login)"
  open_firewall
  local h; h=$(sed -nE 's/^NETOPS_UI_HOST=(.*)$/\1/p' "$IDENT_FILE"); BIND_HOST="${h:-$(primary_ip)}"; BIND_HOST="${BIND_HOST:-127.0.0.1}"
  URL="http://$BIND_HOST:$PORT/"
  if as_op systemctl --user is-active --quiet "$UNIT"; then
    case "$(http_code "$URL")" in
      200|301|302|303|401|403) ok "console já está rodando em $URL (não reiniciado, para não derrubar sessões)"; return ;;
    esac
  fi
  info "subindo o console (scripts/engine/ui/start.sh, delegado a $OP_USER)..."
  "$NETOPS_DIR/scripts/engine/ui/start.sh" --yes >>"$LOG" 2>&1 </dev/null || true
  local i code=""
  for i in $(seq 90); do
    code=$(http_code "$URL"); case "$code" in 200|301|302|303|401|403) break ;; esac; sleep 1
  done
  case "$code" in
    200|301|302|303|401|403)
      local pid owner
      pid=$(as_op systemctl --user show -p MainPID --value "$UNIT" 2>/dev/null || true)
      owner=$(stat -c %U "/proc/${pid:-0}" 2>/dev/null || true)
      [ "$owner" = "$OP_USER" ] || die "algo responde em $URL, mas o serviço $UNIT não é dono dele (pid ${pid:-?}, conta ${owner:-?})."
      ok "console respondendo em $URL (processo de $OP_USER)" ;;
    *) die "o console não respondeu em $URL. Veja: sudo -u $OP_USER XDG_RUNTIME_DIR=/run/user/$(id -u "$OP_USER") journalctl --user -u $UNIT -n 50" ;;
  esac
}

setup_localadmin() {
  step "Administração Local (root sob demanda, sem SSH)"
  if [ "${NETOPS_NO_LOCALADMIN:-0}" = 1 ]; then warn "administração Local não instalada (NETOPS_NO_LOCALADMIN=1)"; return 0; fi
  local extra=() rc=0
  vault_ready || extra=(--no-credential)
  if has_tty && [ -z "${NETOPS_MASTER_PASSWORD:-}" ]; then
    python3 -I -B "$NETOPS_DIR/scripts/engine/localadmin/provision.py" install --root "$NETOPS_DIR" "${extra[@]}" </dev/tty >/dev/tty 2>&1 || rc=$?
  else
    python3 -I -B "$NETOPS_DIR/scripts/engine/localadmin/provision.py" install --root "$NETOPS_DIR" "${extra[@]}" </dev/null >>"$LOG" 2>&1 || rc=$?
  fi
  if [ "$rc" = 0 ]; then ok "host Local pronto: destranque o cofre quando precisar de root neste servidor"
  else warn "administração Local incompleta (veja $LOG). Depois: sudo python3 -I $NETOPS_DIR/scripts/engine/localadmin/provision.py install"; fi
}

# AGENTS.md é LOCAL de cada instalação (fora do git e do pacote; nunca sobrescrito por atualização):
# nasce do modelo limpo core/templates/AGENTS.tmpl.md. O usuário acrescenta o que é dele (menu Memória).
setup_agents_md() {
  local tpl="$NETOPS_DIR/core/templates/AGENTS.tmpl.md" dst="$NETOPS_DIR/AGENTS.md"
  if [ -e "$dst" ]; then ok "AGENTS.md da instalação mantido (é local)"; return 0; fi
  [ -f "$tpl" ] || { warn "modelo do AGENTS.md ausente nesta versão: o console cria quando houver"; return 0; }
  sed '1,/-->/d' "$tpl" >"$dst"
  chmod 644 "$dst"
  if [ "${LAYOUT:-1}" = 2 ]; then chown "$OP_USER:$OP_USER" "$dst"; fi
  ok "AGENTS.md criado do modelo limpo (regras padrão da IA, inclusive sudo e rede sem root)"
}

# ----------------------------------------------------------------------------- 7b. permissões da conta
# Rede sem root + sudo só com o cofre destrancado + "sudo automático" no shell da conta operacional.
setup_privileges() {
  step "Permissões da conta $OP_USER (rede sem root; root só com o cofre destrancado)"
  if [ "${NETOPS_NO_PRIVILEGES:-0}" = 1 ]; then warn "permissões não instaladas (NETOPS_NO_PRIVILEGES=1)"; return 0; fi
  local prov="$NETOPS_DIR/scripts/engine/privileges/provision.py" extra=()
  if [ ! -f "$prov" ]; then
    warn "v${INSTALLED_VERSION:-?} não traz scripts/engine/privileges: ping/nmap sem root e sudo pelo cofre ficam para a próxima atualização (depois: sudo python3 -I -B $prov install --root $NETOPS_DIR)"
    return 0
  fi
  # instalação NOVA: o cofre acabou de ser criado por este instalador -> pode confiar no verificador dele
  if [ "${FRESH:-0}" = 1 ]; then extra=(--trust-creds); fi
  local out rc=0
  out=$(python3 -I -B "$prov" install --root "$NETOPS_DIR" "${extra[@]}" 2>&1) || rc=$?
  printf '%s\n' "$out" >>"$LOG"
  local l; while IFS= read -r l; do warn "$l"; done < <(printf '%s\n' "$out" | sed -n 's/^ *! //p')
  if [ "$rc" = 0 ]; then
    ok "permissões prontas: rede sem root; root por sudo/direto só com o cofre destrancado"
  else
    warn "permissões da conta incompletas (veja $LOG). Depois: sudo python3 -I -B $prov install --root $NETOPS_DIR"
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

  # Porta: se outro programa (ex.: um NetOps antigo em outra pasta) já usa a porta e o console DESTA
  # pasta não é quem a segura, escolhe a próxima livre. Sem isso o start.sh recusa subir ("porta ocupada")
  # e o teste de HTTP responderia com o console alheio, declarando sucesso falso.
  if ! pgrep -f "update/supervisor.py --root $NETOPS_DIR --" >/dev/null; then
    port_busy() { ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN; }
    if port_busy "$PORT"; then
      local orig="$PORT" p
      [ -z "${NETOPS_PORT:-}" ] || die "a porta $PORT (NETOPS_PORT) já está em uso por outro programa. Escolha outra: NETOPS_PORT=<porta>."
      for p in $(seq $((PORT + 1)) $((PORT + 50))); do port_busy "$p" || { PORT="$p"; break; }; done
      [ "$PORT" != "$orig" ] || die "nenhuma porta livre entre $orig e $((orig + 50))."
      local who; who=$(ss -ltnp "sport = :$orig" 2>/dev/null | grep -oE 'users:\(\("[^"]+"' | head -1 | sed 's/users:(("//; s/"//') || true
      warn "a porta $orig já está em uso (${who:-outro programa}; talvez outro NetOps). Este console usará a porta $PORT."
    fi
  fi

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
    200|301|302|303|401|403)
      # Quem responde precisa ser o console DESTA instalação (e não outro NetOps na mesma porta).
      pgrep -f "update/supervisor.py --root $NETOPS_DIR --" >/dev/null \
        || die "algo responde em $URL, mas não é o console de $NETOPS_DIR (ele não subiu). Veja /tmp/netops-restart.log e $LOG.
$(tail -15 /tmp/netops-restart.log 2>/dev/null || true)"
      ok "console respondendo em $URL" ;;
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
  # layout 2: os testes rodam como a conta operacional (root não executa código da árvore dela)
  local X=(); [ "${LAYOUT:-1}" = 2 ] && X=(as_op)
  if out=$(cd "$NETOPS_DIR" && "${X[@]}" "$py" - <<'PYEOF' 2>&1
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

  local smoke="$WORK"; [ "${LAYOUT:-1}" = 2 ] && smoke=$(as_op mktemp -d)
  if (cd "$NETOPS_DIR/scripts/engine/ui" && "${X[@]}" env -i PATH=/usr/bin:/bin HOME="$smoke" NETOPS_UI_DATA_ROOT="$smoke/smoke" \
        timeout 60 "$py" -c "import sys; sys.path.insert(0, '.'); import app") >>"$LOG" 2>&1; then
    ok "backend do console importa sem erro"
  else printf '    %s✗%s backend do console não importa (ver log)\n' "$R" "$N"; fails=$((fails + 1)); fi

  [ "${LAYOUT:-1}" = 2 ] && rm -rf "$smoke"
  if (cd "$NETOPS_DIR" && "${X[@]}" python3 scripts/tools/access/session.py --help) >>"$LOG" 2>&1; then
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

  if [ "${LAYOUT:-1}" = 2 ]; then
    # identidade: supervisor e servidor rodando como a conta operacional; nada root nesta pasta
    local bad; bad=$(pgrep -u 0 -f "($NETOPS_DIR/scripts/engine/ui/server.py|supervisor.py --root $NETOPS_DIR )" || true)
    if [ -z "$bad" ] && pgrep -u "$OP_USER" -f "supervisor.py --root $NETOPS_DIR " >/dev/null; then ok "console roda como $OP_USER (nenhum processo root desta instalação)"
    else printf '    %s✗%s identidade do console errada (root: %s)\n' "$R" "$N" "${bad:-—}"; fails=$((fails + 1)); fi
    if [ -n "$(find "$NETOPS_DIR" -xdev \( -path "$NETOPS_DIR/.git" -prune \) -o -user root -print -quit 2>/dev/null)" ]; then
      warn "há arquivos de root dentro de $NETOPS_DIR (ex.: $(find "$NETOPS_DIR" -xdev -user root -print -quit 2>/dev/null))"
    else ok "nenhum arquivo de root em $NETOPS_DIR"; fi
    if [ -x "$OP_HOME/.local/bin/claude" ]; then ok "agente claude $(as_op "$OP_HOME/.local/bin/claude" --version 2>/dev/null | head -1) (perfil em $OP_HOME/.claude)"
    elif [ "${NETOPS_SKIP_CLAUDE:-0}" != "1" ]; then printf '    %s!%s agente claude ausente (aba Claude Code indisponível)\n' "$Y" "$N"; fi
    if id -nG "$OP_USER" | tr ' ' '\n' | grep -qxE 'sudo|wheel|docker|lxd|disk|root' || sudo -l -n -U "$OP_USER" 2>/dev/null | grep -q 'may run'; then
      printf '    %s✗%s %s tem sudo/grupo administrativo\n' "$R" "$N" "$OP_USER"; fails=$((fails + 1))
    else ok "$OP_USER sem sudo e sem grupos administrativos"; fi
    if [ -f "/etc/netops/instances/$SLUG.local" ]; then
      local la; la=$(as_op systemctl --user is-active "netops-localadmin@$SLUG.service" 2>/dev/null || true)
      [ "$la" = active ] && ok "administração Local instalada (serviço ativo; root só com o cofre destrancado)" || warn "serviço netops-localadmin@$SLUG não está ativo ($la)"
    fi
  else
    getent passwd netops >/dev/null && ok "usuário netops (terminal web)" || { printf '    %s✗%s usuário netops ausente\n' "$R" "$N"; fails=$((fails + 1)); }
    if [ -x /root/.local/bin/claude ]; then ok "agente claude $(/root/.local/bin/claude --version 2>/dev/null | head -1)"
    elif [ "${NETOPS_SKIP_CLAUDE:-0}" != "1" ]; then printf '    %s!%s agente claude ausente (aba Claude Code indisponível)\n' "$Y" "$N"; fi
  fi

  if vault_ready; then ok "cofre inicializado (login exigido no console)"; else warn "cofre sem senha-mestra"; fi

  if [ -f "$NETOPS_DIR/scripts/engine/hooks/install_claude_hooks.py" ]; then
    if "${X[@]}" python3 "$NETOPS_DIR/scripts/engine/hooks/install_claude_hooks.py" --root "$NETOPS_DIR" --check >>"$LOG" 2>&1; then
      ok "hooks de segurança do Claude Code ativos"
    else printf '    %s✗%s hooks do Claude Code ausentes em .claude/settings.json\n' "$R" "$N"; fails=$((fails + 1)); fi
  fi

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
  if [ "${LAYOUT:-1}" = 2 ]; then
    echo "   Conta operacional: $OP_USER (HOME $OP_HOME) — console, IA e terminal rodam como ela, nunca como root."
    echo "   Rede (ping, traceroute, mtr, nmap, tcpdump...): direto, sem root e sem cofre."
    echo "   Root neste servidor: com o cofre destrancado, \`sudo <cmd>\` ou direto (apt, systemctl, nft...)."
    echo "   Cofre trancado = sem root. Ver scripts/engine/privileges/SKILL.md"
  else
    echo "   ⚠ Instalação no modelo antigo (console como root). Migre: sudo python3 -I $NETOPS_DIR/scripts/engine/identity/migrate.py plan"
  fi
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
  if [ "$LAYOUT" = 2 ]; then
    setup_account
    own_tree
    setup_venv
    setup_hooks_claude_op
    setup_vault_op
    setup_projects_base
    setup_agents_md
    write_identity
    setup_user_service
    setup_localadmin
    setup_privileges
  else
    setup_venv
    setup_user
    setup_agents_md
    setup_vault
    setup_service
  fi
  health_check
  summary
  trap - ERR
  [ "${HEALTH_FAILS:-0}" -eq 0 ] || exit 1
}

main "$@"
