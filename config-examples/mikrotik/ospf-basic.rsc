# ============================================================
# Exemplo: OSPF básico — MikroTik RouterOS 7.x
# Testado em: RouterOS 7.x (sintaxe nova de /routing/ospf)
# Ajuste antes de aplicar: router-id, redes/interfaces e a area.
# Boa prática: usar area backbone (0.0.0.0) e anunciar só o necessario.
# Observação: a sintaxe de OSPF mudou do RouterOS 6 para o 7 — este exemplo é v7.
# ============================================================

# --- Instancia OSPF ---
/routing/ospf/instance
add name=ospf-main router-id=10.0.0.1 disabled=no

# --- Area backbone ---
/routing/ospf/area
add name=backbone area-id=0.0.0.0 instance=ospf-main disabled=no

# --- Template de interface: quais interfaces participam do OSPF ---
# 'networks' define as redes que entram no OSPF; ajuste para as suas.
/routing/ospf/interface-template
add area=backbone networks=10.0.0.0/24 interfaces=bridge-core disabled=no
add area=backbone networks=10.0.1.0/30 interfaces=ether-link-dist passive=no

# --- Interface passiva: anuncia a rede mas nao forma adjacencia (ex.: LAN de acesso) ---
/routing/ospf/interface-template
add area=backbone networks=10.0.10.0/24 interfaces=bridge-access passive=yes disabled=no

# --- Conferir ---
# /routing/ospf/neighbor print      ;# vizinhanças formadas
# /routing/ospf/lsa print           ;# base de dados de estado de enlace
# /ip route print where ospf        ;# rotas aprendidas via OSPF
