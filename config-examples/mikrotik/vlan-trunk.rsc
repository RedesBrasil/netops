# ============================================================
# Exemplo: VLANs sobre bridge com trunk — MikroTik RouterOS 7.x
# Testado em: RouterOS 7.x
# Ajuste antes de aplicar: nomes de interface e os IDs de VLAN.
# Conceito: 1 bridge com vlan-filtering; porta trunk leva todas as VLANs taggeadas;
#           portas de acesso entram untagged numa VLAN (pvid).
# ============================================================

# --- Bridge com filtragem de VLAN ---
/interface bridge
add name=bridge-vlan vlan-filtering=no comment="ative o vlan-filtering SO no final"

# --- Portas na bridge ---
/interface bridge port
# Porta trunk (uplink) — pvid 1, recebe VLANs taggeadas
add bridge=bridge-vlan interface=ether1 comment="TRUNK uplink"
# Portas de acesso — cada uma fixa numa VLAN via pvid
add bridge=bridge-vlan interface=ether2 pvid=10 comment="acesso VLAN 10"
add bridge=bridge-vlan interface=ether3 pvid=20 comment="acesso VLAN 20"
add bridge=bridge-vlan interface=ether4 pvid=99 comment="acesso VLAN 99 (gerencia)"

# --- Tabela de VLANs: quem é tagged (trunk) e quem é untagged (acesso) ---
/interface bridge vlan
add bridge=bridge-vlan vlan-ids=10 tagged=bridge-vlan,ether1 untagged=ether2
add bridge=bridge-vlan vlan-ids=20 tagged=bridge-vlan,ether1 untagged=ether3
add bridge=bridge-vlan vlan-ids=99 tagged=bridge-vlan,ether1 untagged=ether4

# --- Interface de VLAN para o roteador rotear/gerenciar (ex.: gerencia) ---
/interface vlan
add interface=bridge-vlan name=vlan99-mgmt vlan-id=99
/ip address
add address=10.0.0.1/24 interface=vlan99-mgmt comment="gerencia"

# --- POR ULTIMO: ativar a filtragem de VLAN ---
# Faça isto só depois de conferir tudo — ativar antes pode te trancar para fora.
/interface bridge set bridge-vlan vlan-filtering=yes
