#!/usr/bin/env python3
"""
Analisa template do Zabbix - lista itens e triggers
"""
import sys
import json
import requests
from collections import defaultdict

ZABBIX_URL = "http://10.8.200.10/zabbix/api_jsonrpc.php"
API_TOKEN = "REMOVIDO-TOKEN-ZABBIX"

def zabbix_request(method, params):
    """Faz requisição à API do Zabbix"""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "auth": API_TOKEN,
        "id": 1
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(ZABBIX_URL, json=payload, headers=headers)
    result = response.json()

    if "error" in result:
        print(f"Erro na API: {result['error']}", file=sys.stderr)
        sys.exit(1)

    return result.get("result")

def main():
    template_name = sys.argv[1] if len(sys.argv) > 1 else "SNMP LINUX"

    print(f"🔍 Analisando template: {template_name}\n")

    # 1. Buscar o template
    templates = zabbix_request("template.get", {
        "filter": {"host": template_name},
        "output": ["templateid", "name", "host"]
    })

    if not templates:
        print(f"❌ Template '{template_name}' não encontrado")
        sys.exit(1)

    template_id = templates[0]["templateid"]
    print(f"✓ Template ID: {template_id}")
    print(f"  Nome: {templates[0]['name']}\n")

    # 2. Buscar itens do template
    items = zabbix_request("item.get", {
        "templateids": template_id,
        "output": ["itemid", "name", "key_", "type", "value_type", "delay", "units"],
        "sortfield": "name"
    })

    print(f"📊 ITENS MONITORADOS: {len(items)}\n")
    print("=" * 100)

    # Agrupar por categoria (baseado no nome)
    categorias = defaultdict(list)

    for item in items:
        nome = item["name"]

        # Classificar por categoria baseado em palavras-chave
        if any(k in nome.lower() for k in ["cpu", "processor", "load"]):
            cat = "CPU & Load"
        elif any(k in nome.lower() for k in ["memory", "memória", "mem ", "swap"]):
            cat = "Memória"
        elif any(k in nome.lower() for k in ["disk", "disco", "storage", "filesystem", "mount", "raid"]):
            cat = "Disco & Storage"
        elif any(k in nome.lower() for k in ["network", "interface", "rede", "traffic", "packet", "ethernet"]):
            cat = "Rede"
        elif any(k in nome.lower() for k in ["temp", "temperatura", "fan", "ventilador", "sensor"]):
            cat = "Hardware & Sensores"
        elif any(k in nome.lower() for k in ["service", "process", "serviço"]):
            cat = "Serviços & Processos"
        else:
            cat = "Outros"

        categorias[cat].append(item)

    # Mostrar itens por categoria
    for cat in sorted(categorias.keys()):
        print(f"\n📁 {cat} ({len(categorias[cat])} itens)")
        print("-" * 100)

        for item in categorias[cat]:
            tipo_map = {
                "0": "Zabbix agent",
                "1": "SNMPv1 agent",
                "2": "Zabbix trapper",
                "3": "Simple check",
                "4": "SNMPv2 agent",
                "5": "Zabbix internal",
                "7": "Zabbix agent (active)",
                "10": "External check",
                "11": "Database monitor",
                "12": "IPMI agent",
                "13": "SSH agent",
                "14": "TELNET agent",
                "15": "Calculated",
                "16": "JMX agent",
                "17": "SNMP trap",
                "18": "Dependent item",
                "19": "HTTP agent",
                "20": "SNMP agent"
            }

            value_type_map = {
                "0": "float",
                "1": "char",
                "2": "log",
                "3": "unsigned int",
                "4": "text"
            }

            tipo = tipo_map.get(item["type"], f"tipo_{item['type']}")
            vtype = value_type_map.get(item["value_type"], f"vtype_{item['value_type']}")
            units = f" {item['units']}" if item["units"] else ""

            print(f"  • {item['name']}")
            print(f"    Key: {item['key_']}")
            print(f"    Tipo: {tipo} | Valor: {vtype}{units} | Intervalo: {item['delay']}")

    # 3. Buscar triggers do template
    print("\n\n" + "=" * 100)
    print("🚨 TRIGGERS (ALERTAS)")
    print("=" * 100)

    triggers = zabbix_request("trigger.get", {
        "templateids": template_id,
        "output": ["triggerid", "description", "expression", "priority", "status"],
        "selectItems": ["name", "key_"],
        "sortfield": "priority",
        "sortorder": "DESC"
    })

    print(f"\nTotal de triggers: {len(triggers)}\n")

    if triggers:
        priority_map = {
            "0": "Não classificado",
            "1": "Informação",
            "2": "Aviso",
            "3": "Média",
            "4": "Alta",
            "5": "Desastre"
        }

        for trig in triggers:
            prio = priority_map.get(trig["priority"], trig["priority"])
            status = "✓ ATIVA" if trig["status"] == "0" else "✗ DESABILITADA"

            print(f"🔔 {trig['description']}")
            print(f"   Prioridade: {prio} | Status: {status}")
            print(f"   Expressão: {trig['expression']}")

            if trig.get("items"):
                print(f"   Itens relacionados:")
                for item in trig["items"]:
                    print(f"     - {item['name']} ({item['key_']})")

            print()
    else:
        print("⚠️  Nenhuma trigger configurada neste template!")

    # 4. Resumo comparativo
    print("\n" + "=" * 100)
    print("📈 RESUMO COMPARATIVO")
    print("=" * 100)

    items_por_categoria = {cat: len(items) for cat, items in categorias.items()}

    # Contar triggers por categoria
    triggers_por_categoria = defaultdict(int)
    for trig in triggers:
        if trig.get("items"):
            for item in trig["items"]:
                nome = item["name"]

                if any(k in nome.lower() for k in ["cpu", "processor", "load"]):
                    triggers_por_categoria["CPU & Load"] += 1
                elif any(k in nome.lower() for k in ["memory", "memória", "mem ", "swap"]):
                    triggers_por_categoria["Memória"] += 1
                elif any(k in nome.lower() for k in ["disk", "disco", "storage", "filesystem", "mount", "raid"]):
                    triggers_por_categoria["Disco & Storage"] += 1
                elif any(k in nome.lower() for k in ["network", "interface", "rede", "traffic", "packet", "ethernet"]):
                    triggers_por_categoria["Rede"] += 1
                elif any(k in nome.lower() for k in ["temp", "temperatura", "fan", "ventilador", "sensor"]):
                    triggers_por_categoria["Hardware & Sensores"] += 1
                elif any(k in nome.lower() for k in ["service", "process", "serviço"]):
                    triggers_por_categoria["Serviços & Processos"] += 1
                else:
                    triggers_por_categoria["Outros"] += 1
                break  # Conta só uma vez por trigger

    print(f"\n{'Categoria':<25} {'Itens':<10} {'Triggers':<10} {'Cobertura':<15} {'Status'}")
    print("-" * 100)

    for cat in sorted(items_por_categoria.keys()):
        n_items = items_por_categoria[cat]
        n_triggers = triggers_por_categoria.get(cat, 0)

        if n_items > 0:
            cobertura_pct = (n_triggers / n_items) * 100
            cobertura = f"{cobertura_pct:.1f}%"
        else:
            cobertura = "N/A"

        if n_triggers == 0:
            status = "❌ SEM ALERTAS"
        elif cobertura_pct < 30:
            status = "⚠️  BAIXA COBERTURA"
        elif cobertura_pct < 70:
            status = "⚡ COBERTURA MÉDIA"
        else:
            status = "✓ BOA COBERTURA"

        print(f"{cat:<25} {n_items:<10} {n_triggers:<10} {cobertura:<15} {status}")

    print("-" * 100)
    print(f"{'TOTAL':<25} {len(items):<10} {len(triggers):<10}")

    print("\n✨ Análise concluída!\n")

if __name__ == "__main__":
    main()
