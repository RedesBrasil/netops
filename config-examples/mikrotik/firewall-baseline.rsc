# ============================================================
# Example: Firewall baseline — secure input chain (MikroTik RouterOS)
# Tested on: RouterOS 7.x
# Adjust before applying: the management subnet (10.0.0.0/24) and the WAN interface-list.
# Related best practice: best-practices/mikrotik/firewall.md
# WARNING: apply in 'safe-mode'. Rule order matters — the final drop goes last.
# ============================================================

# --- Address-list of management/trusted networks ---
/ip firewall address-list
add list=mgmt address=10.0.0.0/24 comment="Sub-rede de gerencia"

# --- INPUT chain (traffic destined to the router itself) ---
/ip firewall filter

# 1) Already established / related connections: accept
add chain=input action=accept connection-state=established,related comment="aceita established/related"

# 2) Invalid connections: drop
add chain=input action=drop connection-state=invalid comment="dropa invalid"

# 3) Controlled ICMP (do not drop everything — it breaks PMTUD/diagnostics)
add chain=input action=accept protocol=icmp limit=10,20:packet comment="aceita ICMP limitado"

# 4) SSH/Winbox anti-brute-force: escalates sources that keep opening new connections
add chain=input action=drop src-address-list=blacklist comment="dropa blacklist"
add chain=input action=add-src-to-address-list connection-state=new protocol=tcp \
    dst-port=22,8291 src-address-list=ssh-stage3 address-list=blacklist \
    address-list-timeout=1d comment="3 falhas -> blacklist"
add chain=input action=add-src-to-address-list connection-state=new protocol=tcp \
    dst-port=22,8291 src-address-list=ssh-stage2 address-list=ssh-stage3 \
    address-list-timeout=1m
add chain=input action=add-src-to-address-list connection-state=new protocol=tcp \
    dst-port=22,8291 src-address-list=ssh-stage1 address-list=ssh-stage2 \
    address-list-timeout=1m
add chain=input action=add-src-to-address-list connection-state=new protocol=tcp \
    dst-port=22,8291 address-list=ssh-stage1 address-list-timeout=1m

# 5) Management: accept SSH/Winbox/API-SSL only from the management networks
add chain=input action=accept src-address-list=mgmt protocol=tcp dst-port=22,8291,8729 \
    comment="aceita gerencia das redes confiaveis"

# 6) Block any access to the router coming from the WAN
add chain=input action=drop in-interface-list=WAN comment="dropa tudo da WAN"

# 7) FINAL DROP — denies everything not accepted above
add chain=input action=drop comment="DROP FINAL — politica default deny"
