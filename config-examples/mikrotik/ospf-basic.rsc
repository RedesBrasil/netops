# ============================================================
# Example: basic OSPF — MikroTik RouterOS 7.x
# Tested on: RouterOS 7.x (new /routing/ospf syntax)
# Adjust before applying: router-id, networks/interfaces and the area.
# Best practice: use the backbone area (0.0.0.0) and advertise only what is needed.
# Note: the OSPF syntax changed from RouterOS 6 to 7 — this example is v7.
# ============================================================

# --- OSPF instance ---
/routing/ospf/instance
add name=ospf-main router-id=10.0.0.1 disabled=no

# --- Backbone area ---
/routing/ospf/area
add name=backbone area-id=0.0.0.0 instance=ospf-main disabled=no

# --- Interface template: which interfaces take part in OSPF ---
# 'networks' defines the networks that go into OSPF; adjust to yours.
/routing/ospf/interface-template
add area=backbone networks=10.0.0.0/24 interfaces=bridge-core disabled=no
add area=backbone networks=10.0.1.0/30 interfaces=ether-link-dist passive=no

# --- Passive interface: advertises the network but forms no adjacency (e.g. access LAN) ---
/routing/ospf/interface-template
add area=backbone networks=10.0.10.0/24 interfaces=bridge-access passive=yes disabled=no

# --- Verify ---
# /routing/ospf/neighbor print      ;# neighbors formed
# /routing/ospf/lsa print           ;# link-state database
# /ip route print where ospf        ;# routes learned via OSPF
