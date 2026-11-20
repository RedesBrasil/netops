# ============================================================
# Example: Security hardening — MikroTik RouterOS
# Tested on: RouterOS 7.x
# Adjust before applying: the management subnet (10.0.0.0/24) and the WAN interface-list.
# Related best practice: best-practices/mikrotik/security-hardening.md
# WARNING: apply via 'safe-mode' — changes to /ip service can lock you out.
# ============================================================

# --- Interface-lists (internal management x WAN) ---
/interface list
add name=MGMT comment="Interfaces de gerencia"
add name=WAN  comment="Interfaces de borda/WAN"
# Assign the real interfaces:
# /interface list member add list=WAN interface=ether1
# /interface list member add list=MGMT interface=bridge-lan

# --- Management services: turn off insecure ones, restrict the ones kept ---
/ip service
set telnet disabled=yes
set ftp    disabled=yes
set www    disabled=yes
set api    disabled=yes
set ssh     address=10.0.0.0/24
set winbox  address=10.0.0.0/24
set api-ssl address=10.0.0.0/24

# --- Neighbor discovery only on internal interfaces ---
/ip neighbor discovery-settings
set discover-interface-list=MGMT

# --- MAC-server (Winbox/Telnet by MAC) restricted ---
/tool mac-server set allowed-interface-list=MGMT
/tool mac-server mac-winbox set allowed-interface-list=MGMT
/tool mac-server ping set enabled=no

# --- Extra services turned off ---
/tool bandwidth-server set enabled=no
/ip proxy set enabled=no
/ip socks set enabled=no
/tool romon set enabled=no

# --- SNMP: unique, restricted community (adjust the name and the address) ---
/snmp community
set [ find default=yes ] name=NETOPS-RO-TROCAR addresses=10.0.0.0/24 read-access=yes write-access=no
/snmp set enabled=yes contact="netops" location="matriz"

# --- User: create a named account and remove admin or set its password ---
# /user add name=netops group=full password="DEFINA-SENHA-FORTE"
# /user set admin password="DEFINA-SENHA-FORTE"

# --- Time and remote logging (adjust the IPs) ---
/system ntp client set enabled=yes
/system ntp client servers add address=200.160.7.186
# /system logging action add name=remote target=remote remote=10.0.0.250
# /system logging add topics=info,error,warning,critical action=remote
