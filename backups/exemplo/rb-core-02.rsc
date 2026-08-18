# EXEMPLO de backup (placeholder) — gerado manualmente para testar o visualizador.
# Sera substituido por coletas reais quando o runner existir.
/system identity set name=rb-core-01-novo
/interface bridge add name=bridge-lan
/ip address add address=192.168.88.1/24 interface=bridge-lan
/ip firewall filter add chain=input action=accept protocol=icmp comment=permite-ping
