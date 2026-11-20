#!/usr/bin/env python3
"""
Analisa template do Zabbix - lista itens e triggers
"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))  # scripts/engine (lib)
from lib._venv import ensure_venv  # noqa: E402
ensure_venv()  # python3 do sistema -> re-executa no .venv do projeto
import requests  # noqa: E402
from lib import i18n  # noqa: E402
from collections import defaultdict

ZABBIX_URL = os.environ.get("ZABBIX_URL", "")
if not ZABBIX_URL:
    sys.exit(i18n.t("cli_zabbix.url_missing"))
API_TOKEN = os.environ.get("ZABBIX_API_TOKEN", "")
if not API_TOKEN:
    sys.exit(i18n.t("cli_zabbix.token_missing"))

# Internal category names (dict keys) -> catalog keys; translated only when printed.
CATEGORY_KEYS = {"CPU & Load": "cat_cpu", "Memória": "cat_memory", "Disco & Storage": "cat_disk", "Rede": "cat_network",
                 "Hardware & Sensores": "cat_hardware", "Serviços & Processos": "cat_services", "Outros": "cat_other"}


def _cat(name):
    key = CATEGORY_KEYS.get(name)
    return i18n.t("cli_zabbix." + key) if key else name


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
        print(i18n.t("cli_zabbix.api_error", error=result["error"]), file=sys.stderr)
        sys.exit(1)

    return result.get("result")

def main():
    template_name = sys.argv[1] if len(sys.argv) > 1 else "SNMP LINUX"

    print(i18n.t("cli_zabbix.analyzing", name=template_name) + "\n")

    # 1. Buscar o template
    templates = zabbix_request("template.get", {
        "filter": {"host": template_name},
        "output": ["templateid", "name", "host"]
    })

    if not templates:
        print(i18n.t("cli_zabbix.template_not_found", name=template_name))
        sys.exit(1)

    template_id = templates[0]["templateid"]
    print(f"✓ Template ID: {template_id}")
    print(i18n.t("cli_zabbix.template_name", name=templates[0]["name"]) + "\n")

    # 2. Buscar itens do template
    items = zabbix_request("item.get", {
        "templateids": template_id,
        "output": ["itemid", "name", "key_", "type", "value_type", "delay", "units"],
        "sortfield": "name"
    })

    print(i18n.t("cli_zabbix.items_monitored", count=len(items)) + "\n")
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
        print("\n" + i18n.t("cli_zabbix.category_header", category=_cat(cat), count=len(categorias[cat])))
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
            print(i18n.t("cli_zabbix.item_line", type=tipo, value=f"{vtype}{units}", interval=item["delay"]))

    # 3. Buscar triggers do template
    print("\n\n" + "=" * 100)
    print(i18n.t("cli_zabbix.triggers_header"))
    print("=" * 100)

    triggers = zabbix_request("trigger.get", {
        "templateids": template_id,
        "output": ["triggerid", "description", "expression", "priority", "status"],
        "selectItems": ["name", "key_"],
        "sortfield": "priority",
        "sortorder": "DESC"
    })

    print("\n" + i18n.t("cli_zabbix.triggers_total", count=len(triggers)) + "\n")

    if triggers:
        priority_map = {
            "0": i18n.t("cli_zabbix.prio_not_classified"),
            "1": i18n.t("cli_zabbix.prio_information"),
            "2": i18n.t("cli_zabbix.prio_warning"),
            "3": i18n.t("cli_zabbix.prio_average"),
            "4": i18n.t("cli_zabbix.prio_high"),
            "5": i18n.t("cli_zabbix.prio_disaster")
        }

        for trig in triggers:
            prio = priority_map.get(trig["priority"], trig["priority"])
            status = i18n.t("cli_zabbix.trigger_enabled") if trig["status"] == "0" else i18n.t("cli_zabbix.trigger_disabled")

            print(f"🔔 {trig['description']}")
            print(i18n.t("cli_zabbix.trigger_status", priority=prio, status=status))
            print(i18n.t("cli_zabbix.trigger_expression", expression=trig["expression"]))

            if trig.get("items"):
                print(i18n.t("cli_zabbix.related_items"))
                for item in trig["items"]:
                    print(f"     - {item['name']} ({item['key_']})")

            print()
    else:
        print(i18n.t("cli_zabbix.no_triggers"))

    # 4. Resumo comparativo
    print("\n" + "=" * 100)
    print(i18n.t("cli_zabbix.summary_header"))
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

    print(f"\n{i18n.t('cli_zabbix.col_category'):<25} {i18n.t('cli_zabbix.col_items'):<10} {'Triggers':<10} "
          f"{i18n.t('cli_zabbix.col_coverage'):<15} {'Status'}")
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
            status = i18n.t("cli_zabbix.coverage_none")
        elif cobertura_pct < 30:
            status = i18n.t("cli_zabbix.coverage_low")
        elif cobertura_pct < 70:
            status = i18n.t("cli_zabbix.coverage_medium")
        else:
            status = i18n.t("cli_zabbix.coverage_good")

        print(f"{_cat(cat):<25} {n_items:<10} {n_triggers:<10} {cobertura:<15} {status}")

    print("-" * 100)
    print(f"{'TOTAL':<25} {len(items):<10} {len(triggers):<10}")

    print("\n" + i18n.t("cli_zabbix.done") + "\n")

if __name__ == "__main__":
    main()
