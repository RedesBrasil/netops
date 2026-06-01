# ============================================================
# Exemplo: Firewall baseline — chain input segura (MikroTik RouterOS)
# Testado em: RouterOS 7.x
# Ajuste antes de aplicar: a sub-rede de gerencia (10.0.0.0/24) e a interface-list WAN.
# Boa prática relacionada: best-practices/mikrotik/firewall.md
# ATENÇÃO: aplique em 'safe-mode'. A ordem das regras importa — o drop final por último.
# ============================================================

# --- Address-list de redes de gerencia/confiaveis ---
/ip firewall address-list
add list=mgmt address=10.0.0.0/24 comment="Sub-rede de gerencia"

# --- Chain INPUT (trafego destinado ao proprio roteador) ---
/ip firewall filter

# 1) Conexoes ja estabelecidas / relacionadas: aceitar
add chain=input action=accept connection-state=established,related comment="aceita established/related"

# 2) Conexoes invalidas: dropar
add chain=input action=drop connection-state=invalid comment="dropa invalid"

# 3) ICMP controlado (nao dropar tudo — quebra PMTUD/diagnostico)
add chain=input action=accept protocol=icmp limit=10,20:packet comment="aceita ICMP limitado"

# 4) Anti-brute-force de SSH/Winbox: escalona quem insiste em conexao nova
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

# 5) Gerencia: aceitar SSH/Winbox/API-SSL apenas das redes de gerencia
add chain=input action=accept src-address-list=mgmt protocol=tcp dst-port=22,8291,8729 \
    comment="aceita gerencia das redes confiaveis"

# 6) Bloquear qualquer acesso vindo da WAN ao roteador
add chain=input action=drop in-interface-list=WAN comment="dropa tudo da WAN"

# 7) DROP FINAL — nega tudo que nao foi aceito acima
add chain=input action=drop comment="DROP FINAL — politica default deny"
