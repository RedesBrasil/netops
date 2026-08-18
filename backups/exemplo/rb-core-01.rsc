# EXEMPLO de backup (placeholder) — gerado manualmente para testar o visualizador.
# Sera substituido por coletas reais quando o runner existir.
/system identity set name=rb-core-01
/interface bridge add name=bridge-lan
/ip address add address=192.168.88.1/24 interface=bridge-lan
/ip dns set servers=1.1.1.1,8.8.8.8
