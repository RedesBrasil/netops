#!/usr/bin/env python3
"""Investigador de lentidão do atendimento: coleta pronta + agente de IA (somente leitura).

1) Coleta determinística (task_exec.py com a chave dedicada da tarefa, só leitura) no PROXMOX TECHIFY (host 16) e no
   COOLIFY-REDES_BRASIL (host 35): pressão CPU/IO/mem, load, docker stats, logs recentes.
2) `claude -p` recebe a evidência + o mapa da infra e investiga a fundo, do início ao fim.
3) Relatório salvo em reports/atendimento-lentidao-<data>.md e resumo no Telegram.
Disparado pelo monitor.py; também roda à mão:  investigate.py [--evidence arq.json]
"""
from __future__ import annotations

import argparse, json, os, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import monitor  # noqa: E402
from lib import i18n  # noqa: E402  (path set by monitor)

TASK_ID = "monitor-de-lentidao-atendimento"   # chave dedicada da tarefa (network/task-keys/<id>/), não usa o cofre
SESSION = ["python3", str(ROOT / "scripts/tools/access/task_exec.py"), "--task", TASK_ID]
APP = "$(docker ps --format '{{.Names}}' | grep '^whatsbot-' | head -1)"

PROXMOX = {  # host 16 — PROXMOX TECHIFY
    "uptime/load": "uptime; nproc",
    "pressao (PSI) host": "grep . /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory",
    "memoria/swap": "free -m; vmstat 1 3",
    "pressao do CT 212": "grep . /sys/fs/cgroup/lxc/212/cpu.pressure /sys/fs/cgroup/lxc/212/io.pressure /sys/fs/cgroup/lxc/212/memory.pressure /sys/fs/cgroup/lxc/212/memory.events 2>&1",
    "top CPU (host)": "ps -eo pid,pcpu,pmem,etime,comm --sort=-pcpu | head -12",
    "CTs rodando": "pct list | grep running",
    "storage": "pvesm status; df -h / /var/lib/vz 2>/dev/null",
    "erros recentes de disco/kernel": "dmesg -T --level=err,warn | tail -15; journalctl -p err --since '30 min ago' --no-pager | tail -10",
    "NVMe/IO": "cat /proc/diskstats | awk '$3 ~ /^(nvme[0-9]n1|sd[a-z])$/{print $3, \"io_em_andamento=\"$12}'",
}
COOLIFY = {  # host 35 — COOLIFY-REDES_BRASIL (CT 212)
    "uptime/load": "uptime; nproc; vmstat 1 3",
    "pressao (PSI)": "grep . /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory",
    "memoria/disco": "free -m; df -h / | tail -1; df -i / | tail -1",
    "docker stats": "docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}} netio={{.NetIO}} blk={{.BlockIO}} pids={{.PIDs}}' | sort -t= -k2 -rn | head -14",
    "containers não saudáveis / reinícios": "docker ps --filter health=unhealthy --format '{{.Names}} {{.Status}}'; docker ps -a --filter status=exited --format '{{.Names}} {{.Status}}' | head; docker inspect " + APP + " --format 'restarts={{.RestartCount}} oom={{.State.OOMKilled}} started={{.State.StartedAt}}'",
    "top processos": "ps -eo pid,pcpu,pmem,etime,args --sort=-pcpu | cut -c1-140 | head -12",
    "tempos até o app (dentro do CT)": "for u in /health /api/channels/providers; do curl -sk -o /dev/null -m 15 --resolve atendimento.coolify.redesbrasil.com.br:443:127.0.0.1 -w \"$u via-traefik-local dns=%{time_namelookup} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total} code=%{http_code}\\n\" https://atendimento.coolify.redesbrasil.com.br$u; done",
    "logs do app (10 min)": "docker logs --since 10m " + APP + " 2>&1 | grep -i -E 'error|exception|timeout|slow|warn|traceback' | tail -25; echo '--- últimas linhas:'; docker logs --tail 15 " + APP + " 2>&1 | cut -c1-220",
    "logs Traefik (5xx / lentos)": "docker logs --since 10m coolify-proxy 2>&1 | grep -i -E 'error|50[0-9]|timeout' | tail -12",
    "logs Evolution API (10 min)": "docker logs --since 10m $(docker ps --format '{{.Names}}' | grep '^api-' | head -1) 2>&1 | grep -i -E 'error|timeout|fail|disconnect' | tail -12",
    "conexões": "ss -s | head -3; dmesg -T --level=err,warn 2>/dev/null | tail -8",
}


COLETA = ROOT / "network" / "atendimento-coleta.yaml"
GROUPS = {16: ("PROXMOX TECHIFY", PROXMOX), 35: ("COOLIFY-REDES_BRASIL", COOLIFY)}
MAX_POR_HOST = 40
PROIBIDO = re.compile(
    r"(^|[\s;&|(])(rm|mv|cp|dd|kill|killall|pkill|reboot|shutdown|poweroff|halt|mkfs|chmod|chown|apt|apt-get|dpkg|pip|"
    r"systemctl\s+(restart|stop|start|reload|disable|enable|mask)|service\s+\S+\s+(restart|stop|start)|"
    r"docker\s+(restart|stop|start|rm|kill|pause|run|compose|exec\s+-\w*\s*\S+\s+(rm|kill))|"
    r"pct\s+(stop|start|shutdown|set|destroy|restore)|qm\s+(stop|start|set|destroy)|iptables|nft|ip\s+(link|addr|route)\s+(set|add|del)|"
    r"tee|truncate|crontab|sed\s+-i|sysctl\s+-w|echo\b[^|]*>|swapoff|swapon|mount|umount)\b|[^>]>[^>&]|>>")


def comando_seguro(cmd: str) -> bool:
    return bool(cmd.strip()) and len(cmd) < 600 and "\n" not in cmd and not PROIBIDO.search(cmd)


def load_coleta() -> dict[int, dict[str, str]]:
    """Base embutida + o que o agente aprendeu (network/atendimento-coleta.yaml)."""
    res = {h: dict(g[1]) for h, g in GROUPS.items()}
    try:
        for h, items in (monitor._yaml(COLETA).get("extras") or {}).items():
            for it in items:
                res.setdefault(int(h), {})[it["title"]] = it["cmd"]
    except Exception:
        pass
    return res


def aprender(report: str) -> tuple[str, list[str]]:
    """Extrai o bloco ```coleta-add do relatório, valida (só leitura), testa e grava no YAML."""
    m = re.search(r"```coleta-add\s*(.*?)```", report, re.S)
    clean = re.sub(r"```coleta-add.*?```", "", report, flags=re.S).strip()
    if not m:
        return clean, []
    import yaml
    try:
        props = json.loads(m.group(1))
    except Exception:
        return clean, [i18n.t("cli_diagnostics.inv_block_invalid")]
    cur = monitor._yaml(COLETA) if COLETA.exists() else {}
    extras = cur.get("extras") or {}
    existentes = {c for h in load_coleta().values() for c in h.values()}
    log = []
    for pr in props if isinstance(props, list) else []:
        try:
            h, title, cmd = int(pr["host_id"]), str(pr["title"])[:80], str(pr["cmd"]).strip()
        except Exception:
            continue
        if h not in GROUPS or cmd in existentes:
            continue
        if not comando_seguro(cmd):
            log.append(i18n.t("cli_diagnostics.inv_rejected_not_readonly", cmd=cmd[:80])); continue
        if len(extras.get(h, [])) >= MAX_POR_HOST:
            log.append(i18n.t("cli_diagnostics.inv_limit", max=MAX_POR_HOST, host_id=h, title=title)); continue
        t = subprocess.run(SESSION + ["--host-id", str(h), "--timeout", "30", "--command", cmd],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        if "exit=0" not in t.stdout + t.stderr:
            log.append(i18n.t("cli_diagnostics.inv_rejected_test", cmd=cmd[:80])); continue
        extras.setdefault(h, []).append({"title": title, "cmd": cmd, "why": str(pr.get("reason", ""))[:200],
                                         "added": datetime.now().isoformat(timespec="seconds")})
        log.append(i18n.t("cli_diagnostics.inv_learned", host_id=h, title=title))
    cur["extras"] = extras
    COLETA.write_text("# Comandos de coleta aprendidos pelo agente investigador (somente leitura, validados). Pode editar/remover.\n"
                      + yaml.safe_dump(cur, allow_unicode=True, sort_keys=False))
    return clean, log


def run_group(host_id: int, cmds: dict[str, str]) -> str:
    out = []
    for title, cmd in cmds.items():
        try:
            p = subprocess.run(SESSION + ["--host-id", str(host_id), "--timeout", "60", "--command", cmd],
                               capture_output=True, text=True, timeout=90, cwd=ROOT)
            body = "\n".join(l for l in (p.stdout + p.stderr).splitlines() if not l.startswith(("[sessão", "[status")))
        except Exception as e:
            body = i18n.t("cli_diagnostics.inv_collect_failed", error=type(e).__name__)
        out.append(f"### {title}\n{body.strip()[:2500]}")
    return "\n\n".join(out)


def collect() -> str:
    cmds = load_coleta()
    with ThreadPoolExecutor(2) as ex:
        fut = {h: ex.submit(run_group, h, cmds[h]) for h in GROUPS}
        return "\n\n".join(f"## {GROUPS[h][0]} (host {h})\n{f.result()}" for h, f in fut.items())




def prepare() -> int:
    """Fase script da tarefa híbrida: sem incidente pendente → não acorda o agente."""
    pend = monitor.DATA / "pending.json"
    if not pend.exists():
        print('{"wakeAgent": false}'); return 0
    cfg = monitor._yaml(ROOT / "network" / "atendimento-monitor.yaml")
    evidence = pend.read_text()
    pend.rename(monitor.DATA / f"incident-{datetime.now():%Y%m%d-%H%M%S}.json")
    try:
        recent = (monitor.DATA / f"metrics-{datetime.now():%Y%m%d}.jsonl").read_text().splitlines()[-10:]
        evidence += "\n\n" + i18n.t("cli_diagnostics.inv_recent_cycles") + "\n" + "\n".join(recent)
    except Exception:
        pass
    print("## " + i18n.t("cli_diagnostics.inv_infra_map") + "\n" + json.dumps(cfg["infra"], ensure_ascii=False, indent=1))
    print("\n## " + i18n.t("cli_diagnostics.inv_evidence_incident") + "\n" + evidence[:6000])
    print("\n## " + i18n.t("cli_diagnostics.inv_collected_now") + "\n" + collect())
    return 0


BASE_URL_CONSOLE = "https://netops.redesbrasil.com.br"     # domínio do console (Traefik); NETOPS_UI_BASE_URL sobrescreve


def link_conversa() -> str:
    """URL da conversa desta execução na aba Claude do console (<domínio>/#claude/<id>).
    O id vem de CLAUDE_CODE_SESSION_ID; sem ele devolve '' e a linha é omitida."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not sid:
        return ""
    base = (os.environ.get("NETOPS_UI_BASE_URL", "").strip() or BASE_URL_CONSOLE).rstrip("/")
    return f"{base}/#claude/{sid}"


def resumo_telegram(report: str, caminho: str) -> str:
    """Versão curta do relatório para o Telegram: causa, impacto e 1ª ação (texto puro, ~900 caracteres)."""
    # the self-improvement heading may be in any language (old reports: Portuguese)
    heads = {"Auto-aperfeiçoamento", i18n.t("cli_diagnostics.inv_self_improvement_word")}
    corpo = re.split(r"\n\*\*(?:" + "|".join(re.escape(h) for h in heads) + r")|```coleta-add", report)[0]
    cab = r"\*\*([^*\n]+?)(?::\*\*|\*\*\s*\([^)\n]*\):)"      # **Rótulo:** ou **Rótulo** (obs):
    secoes = {m.group(1).strip().lower(): m.group(2).strip()
              for m in re.finditer(cab + r"\s*(.*?)(?=\n" + cab + r"|\Z)", corpo, re.S)}

    def limpa(t: str, n: int) -> str:
        t = re.sub(r"\s+", " ", re.sub(r"[`*]", "", t)).strip()
        if len(t) <= n:
            return t
        corte = t[:n]
        ponto = max(corte.rfind(". "), corte.rfind("; "))
        return (corte[:ponto + 1] if ponto > n // 2 else corte.rstrip() + "…")

    acoes = [ln.lstrip("- ").strip() for ln in secoes.get("ação recomendada", "").splitlines()
             if ln.strip().startswith("- ")]
    acao = acoes[0] if acoes else secoes.get("ação recomendada", "")
    partes = [i18n.t("cli_diagnostics.inv_tg_title"), ""]
    # section keys = the bold labels AGENT_PROMPT.md keeps in Portuguese (parsed, never translated)
    for rotulo, chave, n in ((i18n.t("cli_diagnostics.inv_tg_cause"), "causa provável", 260),
                             (i18n.t("cli_diagnostics.inv_tg_impact"), "impacto", 160),
                             (i18n.t("cli_diagnostics.inv_tg_action"), None, 160)):
        txt = limpa(acao if chave is None else secoes.get(chave, ""), n)
        if txt:
            partes.append(f"{rotulo}: {txt}")
    if len(partes) == 2:               # relatório fora do formato: pega o começo
        partes.append(limpa(corpo, 600))
    link = link_conversa()
    if link:
        partes += ["", i18n.t("cli_diagnostics.inv_tg_more_info", link=link)]
    partes += ["", i18n.t("cli_diagnostics.inv_tg_report", path=caminho)]
    return "\n".join(partes)


def finish(path: str) -> int:
    f = Path(path)
    report, log = aprender(f.read_text())
    if log:
        report += "\n\n**" + i18n.t("cli_diagnostics.inv_self_improvement") + "**\n" + "\n".join(f"- {l}" for l in log)
    f.write_text(report + "\n")
    print("\n".join(log) or i18n.t("cli_diagnostics.inv_nothing_learned"))
    monitor.telegram(resumo_telegram(report, str(f.relative_to(ROOT) if f.is_absolute() else f)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--finish")
    ap.add_argument("--evidence")
    ap.add_argument("--no-telegram", action="store_true")
    a = ap.parse_args()
    if a.prepare:
        return prepare()
    if a.finish:
        return finish(a.finish)
    cfg = monitor._yaml(ROOT / "network" / "atendimento-monitor.yaml")
    evidence = Path(a.evidence).read_text() if a.evidence else i18n.t("cli_diagnostics.inv_manual_run")
    try:
        recent = (monitor.DATA / f"metrics-{datetime.now():%Y%m%d}.jsonl").read_text().splitlines()[-10:]
        evidence += "\n\n" + i18n.t("cli_diagnostics.inv_recent_cycles") + "\n" + "\n".join(recent)
    except Exception:
        pass
    collected = collect()
    prompt = ("## " + i18n.t("cli_diagnostics.inv_infra_map") + "\n" + json.dumps(cfg["infra"], ensure_ascii=False, indent=1)
              + "\n\n## " + i18n.t("cli_diagnostics.inv_evidence") + "\n" + evidence[:6000]
              + "\n\n## " + i18n.t("cli_diagnostics.inv_collected") + "\n" + collected + "\n\n" + (HERE / "AGENT_PROMPT.md").read_text())
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    timeout = cfg["investigate"].get("timeout_minutes", 15) * 60
    try:
        p = subprocess.run([claude, "-p", prompt, "--output-format", "text", "--dangerously-skip-permissions",
                            "--disallowedTools", "Edit", "Write", "NotebookEdit", "CronCreate", "AskUserQuestion"],
                           capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        report = p.stdout.strip() or i18n.t("cli_diagnostics.inv_agent_no_output", code=p.returncode) + f" {p.stderr[-500:]}"
    except subprocess.TimeoutExpired:
        report = i18n.t("cli_diagnostics.inv_agent_timeout")
    report, aprendido = aprender(report)
    if aprendido:
        report += "\n\n**" + i18n.t("cli_diagnostics.inv_self_improvement") + "**\n" + "\n".join(f"- {l}" for l in aprendido)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    out = ROOT / "reports" / f"atendimento-lentidao-{stamp}.md"
    out.write_text(f"# {i18n.t('cli_diagnostics.inv_report_title', stamp=stamp)}\n\n{report}\n\n---\n"
                   f"## {i18n.t('cli_diagnostics.inv_evidence_monitor')}\n```\n{evidence}\n```\n\n"
                   f"## {i18n.t('cli_diagnostics.inv_collected')}\n{collected}\n")
    print(out)
    if not a.no_telegram:
        monitor.telegram(resumo_telegram(report, f"reports/{out.name}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
