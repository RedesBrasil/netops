"""Execução real × menção: cofre, permissões de rede e guard não podem disparar só pelo TEXTO.

Falso positivo de 14/11/2026: um `git commit` cuja mensagem citava "session.py" abriu o pop-up do
cofre (e o guard de backup bloqueou um comando de teste que só citava o script).
"""
import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from services import claude_svc  # importa deps (põe scripts/engine no sys.path)
from lib import net_perms, shell_cmds  # noqa: E402

SP = "scripts/tools/access/session.py"
CH = "scripts/tools/backup/change.py"
ROOT = Path(__file__).resolve().parents[4]

MENTIONS = [
    f"git commit -m 'uso de {SP} run --host-id 3'",
    f"git commit -q -F - <<'EOF'\nfix {SP} exec --host-id 3 --command '/ip route remove 1'\nEOF\ngit push origin main",
    f"grep -n '{SP} run' AGENTS.md | head",
    f"cat scripts/tools/access/SKILL.md; sed -n 1,20p {CH}",
    f"echo '$(python3 {SP} run --host-id 2 --command ls)'",
    f"ls  # python3 {SP} run --host-id 1 --command '/ip address add a=1'",
    f"python3 - <<'EOF'\ns = open('x').read().replace('{SP}', '{CH}')\nEOF",
    f"git log -S 'change.py begin' --oneline",
    f"python3 {SP} --help",
    "python3 scripts/tools/access/terminal_link.py --host-id 3",
]

RUNS = [
    f"cd /opt/netops && python3 {SP} exec --host-id 3 --command '/ip address print'",
    f"python3 {CH} begin --host-id 3 && python3 {SP} run --host-id 3 --command x; python3 {CH} end --host-id 3",
    f"bash -c 'python3 {SP} run --host-id 2 --command ls'",
    f'echo "$(python3 {SP} run --host-id 2 --command ls)"',
    f"sudo -u netops timeout 30 env A=1 python3 -u {SP} run --host-id 2 --command ls",
    f"bash <<'EOF'\npython3 {SP} run --host-id 2 --command ls\nEOF",
    "python3 scripts/tools/diagnostics/ping_advanced.py --host-id 2",
    f"python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['python3', '{SP}', 'run', '--host-id', '2'])\nEOF",
]


@pytest.mark.parametrize("cmd", MENTIONS)
def test_mencao_nao_pede_cofre(cmd):
    assert not claude_svc._needs_vault(cmd)


@pytest.mark.parametrize("cmd", RUNS)
def test_execucao_real_pede_cofre(cmd):
    assert claude_svc._needs_vault(cmd)


@pytest.mark.parametrize("cmd", MENTIONS)
def test_mencao_nao_vira_chamada_de_equipamento(cmd):
    assert net_perms.check(cmd, [])["ok"]


def test_execucao_real_e_classificada():
    r = net_perms.check(f"bash -c \"python3 {SP} run --host-id 3 --command '/ip route remove 1'\"", ["read"],
                        lambda ref: "ros")
    assert r["missing"] == ["delete"]


def test_comentario_so_no_inicio_de_palavra():
    invs = shell_cmds.invocations("curl -s http://x/a#frag && echo ${#x}")
    assert invs[0]["argv"] == ["-s", "http://x/a#frag"] and invs[1]["argv"] == ["${#x}"]


def test_aritmetica_nao_e_execucao():
    assert shell_cmds._substitutions("echo $((1+2))") == []


def test_hook_do_cofre_ignora_mencao(monkeypatch):
    class WS:
        query_params = {}
    s = claude_svc.ClaudeWebSession(WS())
    sent = []

    async def _send(obj, only=None, skip=None):
        sent.append(obj["type"])

    s._send, s._busy = _send, True
    monkeypatch.setattr(s, "_vault_locked", lambda: True)
    r = asyncio.run(s._hook_vault_gate({"tool_input": {"command": MENTIONS[1]}}, "t", None))
    assert r == {} and sent == []


@pytest.mark.parametrize("cmd,blocked", [
    (f"git commit -m 'x {SP} run --host-id 999999 --command \"/ip address add a=1\"'", False),
    (f"grep -n '{SP} run --host-id 999999 --command add' AGENTS.md", False),
])
def test_guard_ignora_mencao(cmd, blocked):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}
    r = subprocess.run(["bash", str(ROOT / "scripts/engine/hooks/guard-netops.sh")],
                       input=json.dumps({"tool_input": {"command": cmd}}), text=True,
                       capture_output=True, env=env)
    assert (r.returncode == 2) is blocked
