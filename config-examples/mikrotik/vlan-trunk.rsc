# ============================================================
# Example: VLANs over a bridge with a trunk — MikroTik RouterOS 7.x
# Tested on: RouterOS 7.x
# Adjust before applying: interface names and the VLAN IDs.
# Concept: 1 bridge with vlan-filtering; the trunk port carries all VLANs tagged;
#          access ports join one VLAN untagged (pvid).
# ============================================================

# --- Bridge with VLAN filtering ---
/interface bridge
add name=bridge-vlan vlan-filtering=no comment="ative o vlan-filtering SO no final"

# --- Bridge ports ---
/interface bridge port
# Trunk port (uplink) — pvid 1, receives tagged VLANs
add bridge=bridge-vlan interface=ether1 comment="TRUNK uplink"
# Access ports — each one pinned to a VLAN via pvid
add bridge=bridge-vlan interface=ether2 pvid=10 comment="acesso VLAN 10"
add bridge=bridge-vlan interface=ether3 pvid=20 comment="acesso VLAN 20"
add bridge=bridge-vlan interface=ether4 pvid=99 comment="acesso VLAN 99 (gerencia)"

# --- VLAN table: who is tagged (trunk) and who is untagged (access) ---
/interface bridge vlan
add bridge=bridge-vlan vlan-ids=10 tagged=bridge-vlan,ether1 untagged=ether2
add bridge=bridge-vlan vlan-ids=20 tagged=bridge-vlan,ether1 untagged=ether3
add bridge=bridge-vlan vlan-ids=99 tagged=bridge-vlan,ether1 untagged=ether4

# --- VLAN interface for the router to route/manage (e.g. management) ---
/interface vlan
add interface=bridge-vlan name=vlan99-mgmt vlan-id=99
/ip address
add address=10.0.0.1/24 interface=vlan99-mgmt comment="gerencia"

# --- LAST: enable VLAN filtering ---
# Do this only after checking everything — enabling it earlier can lock you out.
/interface bridge set bridge-vlan vlan-filtering=yes
