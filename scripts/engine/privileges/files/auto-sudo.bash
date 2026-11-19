# NetOps — "sudo automático" da conta netops (carregado pelo ~/.bashrc; a aba Claude e o terminal herdam).
# Com o cofre DESTRANCADO, os comandos de administração abaixo rodam como root sem digitar sudo.
# Com o cofre trancado, rodam normalmente como netops (e dão o erro de permissão de sempre).
# O resto (git, python, edição em /opt/netops...) continua como netops, para não criar arquivo de root.
# Root por trás: sudo liberado pelo PAM só com o cofre (/usr/local/sbin/netops-sudo-cofre).
# Arquivo root-owned: edite como root. Para rodar UM comando como netops mesmo: `command <cmd>`.

__netops_cofre_aberto() { [ -f "/run/user/$(id -u)/netops/session.key" ]; }

__netops_root() {  # $1 = comando; resto = argumentos
  if [ "$(id -u)" != 0 ] && __netops_cofre_aberto; then
    sudo -- "$@"
    local rc=$?
    [ $rc = 1 ] && ! __netops_cofre_aberto && echo "(cofre trancado: destranque no console para usar root)" >&2
    return $rc
  fi
  command "$@"
}

# Escopo de usuário (--user) é da própria conta netops: nunca vira root.
__netops_root_unless_user() {
  local a; for a in "$@"; do [ "$a" = "--user" ] && { command "$@"; return; }; done
  __netops_root "$@"
}

for __c in apt apt-get apt-cache aptitude dpkg dpkg-reconfigure update-alternatives \
           service dmesg nft iptables ip6tables iptables-save ip6tables-save iptables-restore \
           ip6tables-restore ebtables conntrack ufw docker podman mount umount losetup \
           useradd usermod userdel groupadd groupmod groupdel chpasswd visudo \
           modprobe rmmod lsmod sysctl ethtool tc brctl bridge iw ss lsof \
           reboot shutdown poweroff halt fdisk parted lvm pvs vgs lvs zfs zpool smartctl; do
  eval "$__c() { __netops_root $__c \"\$@\"; }"
done
for __c in systemctl journalctl loginctl; do
  eval "$__c() { __netops_root_unless_user $__c \"\$@\"; }"
done
unset __c

# Arquivos do sistema: leitura/edição como root sem mudar dono.
rootcat()  { __netops_root cat "$@"; }        # ler arquivo protegido: rootcat /etc/shadow
rootedit() { SUDO_EDITOR="${EDITOR:-nano}" sudo -e -- "$@"; }   # editar como root com segurança (sudoedit)
rootsh()   { __netops_root bash -c "$*"; }    # pipeline inteiro como root: rootsh 'cmd1 | cmd2 > /etc/x'
