# ============================================================
# Exemplo: Hardening de segurança — MikroTik RouterOS
# Testado em: RouterOS 7.x
# Ajuste antes de aplicar: a sub-rede de gerência (10.0.0.0/24) e a interface-list de WAN.
# Boa prática relacionada: best-practices/mikrotik/security-hardening.md
# ATENÇÃO: aplicar via 'safe-mode' — mudanças em /ip service podem te trancar para fora.
# ============================================================

# --- Interface-lists (gerência interna x WAN) ---
/interface list
add name=MGMT comment="Interfaces de gerencia"
add name=WAN  comment="Interfaces de borda/WAN"
# Associe as interfaces reais:
# /interface list member add list=WAN interface=ether1
# /interface list member add list=MGMT interface=bridge-lan

# --- Serviços de gerência: desligar inseguros, restringir os mantidos ---
/ip service
set telnet disabled=yes
set ftp    disabled=yes
set www    disabled=yes
set api    disabled=yes
set ssh     address=10.0.0.0/24
set winbox  address=10.0.0.0/24
set api-ssl address=10.0.0.0/24

# --- Descoberta de vizinhos só nas interfaces internas ---
/ip neighbor discovery-settings
set discover-interface-list=MGMT

# --- MAC-server (Winbox/Telnet por MAC) restrito ---
/tool mac-server set allowed-interface-list=MGMT
/tool mac-server mac-winbox set allowed-interface-list=MGMT
/tool mac-server ping set enabled=no

# --- Serviços extras desligados ---
/tool bandwidth-server set enabled=no
/ip proxy set enabled=no
/ip socks set enabled=no
/tool romon set enabled=no

# --- SNMP: community unica e restrita (ajuste o nome e o endereco) ---
/snmp community
set [ find default=yes ] name=NETOPS-RO-TROCAR addresses=10.0.0.0/24 read-access=yes write-access=no
/snmp set enabled=yes contact="netops" location="matriz"

# --- Usuario: criar conta nomeada e remover/senhar o admin ---
# /user add name=netops group=full password="DEFINA-SENHA-FORTE"
# /user set admin password="DEFINA-SENHA-FORTE"

# --- Horario e log remoto (ajuste os IPs) ---
/system ntp client set enabled=yes
/system ntp client servers add address=200.160.7.186
# /system logging action add name=remote target=remote remote=10.0.0.250
# /system logging add topics=info,error,warning,critical action=remote
