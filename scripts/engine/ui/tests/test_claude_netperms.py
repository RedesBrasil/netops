"""Permissões de rede (CRUD) da aba Claude: classificador + hook PreToolUse — sem agente real."""
import asyncio

import pytest

from services import claude_prefs, claude_svc  # importa deps (põe scripts/engine no sys.path)
from lib import net_perms as n  # noqa: E402

ROS = lambda ref: "ros"  # noqa: E731
SP = "python3 scripts/tools/access/session.py"


# ------------------------------------------------------------------ classificador
@pytest.mark.parametrize("dialect,cmd,expected", [
    ("ros", "/ip address print", {"read"}),
    ("ros", "/ping 8.8.8.8 count=3", {"read"}),
    ("ros", "/tool traceroute 8.8.8.8", {"read"}),
    ("ros", "/export", {"read"}),
    ("ros", '/ip firewall filter print where comment="remove me"', {"read"}),
    ("ros", "/ip address add address=10.0.0.1/24 interface=ether1", {"create"}),
    ("ros", "/interface set ether1 disabled=yes", {"edit"}),
    ("ros", "/system reboot", {"edit"}),
    ("ros", "/ip route remove [find dst-address=1.1.1.0/24]", {"delete", "read"}),
    ("ros", "/system resource", {"edit"}),          # sem verbo = desconhecido = alteração
    ("netcli", "show ip route", {"read"}),
    ("netcli", "configure terminal", {"read"}),
    ("netcli", "ip address 1.1.1.1 255.255.255.0", {"create", "edit"}),
    ("netcli", "no ip route 0.0.0.0 0.0.0.0 1.1.1.1", {"delete"}),
    ("netcli", "undo ip route-static 0.0.0.0 0", {"delete"}),
    ("netcli", "write memory", {"edit"}),
    ("shell", "ip a", {"read"}),
    ("shell", "cat /etc/hosts | grep x", {"read"}),
    ("shell", "ls -la 2>/dev/null; df -h", {"read"}),
    ("shell", "for i in 1 2; do ping -c1 10.0.0.$i; done", {"read"}),
    ("shell", "systemctl status nginx", {"read"}),
    ("shell", "sudo qm list", {"read"}),
    ("shell", "ip addr add 10.1.1.1/24 dev eth0", {"create"}),
    ("shell", "systemctl restart nginx", {"edit"}),
    ("shell", "sed -i s/a/b/ /etc/x", {"edit"}),
    ("shell", "rm -rf /var/tmp/x", {"delete"}),
    ("shell", "pct destroy 101", {"delete"}),
    ("shell", "bash -c 'rm -f /x'", {"delete"}),
    ("shell", "comando-desconhecido --x", {"edit"}),
    ("shell", "iptables -A INPUT -j DROP", {"create"}),
    ("shell", "iptables -nvL", {"read"}),
])
def test_classify(dialect, cmd, expected):
    assert n.classify(cmd, dialect) == expected


def test_redirecionamento_para_arquivo_e_alteracao():
    assert {"create", "edit"} <= n.classify("echo 1 > /proc/sys/net/ipv4/ip_forward", "shell")
    assert n.classify("echo x >/dev/null", "shell") == {"read"}
    assert "delete" in n.classify("echo $(rm x)", "shell")


def test_normalize_e_full():
    assert n.normalize(None) == list(n.CATEGORIES)          # ausente = Full (histórico)
    assert n.normalize([]) == []
    assert n.normalize(["edit", "read", "xx", "read"]) == ["read", "edit"]
    assert n.is_full(["delete", "edit", "create", "read"]) and not n.is_full(["read"])


def test_check_acha_session_py_e_soma_categorias():
    b = f'{SP} exec --host-id 3 --command "/ip address print" --command "/ip route remove 5"'
    r = n.check(b, ["read", "edit"], ROS)
    assert not r["ok"] and r["missing"] == ["delete"] and r["calls"][0]["host_id"] == 3
    assert n.check(f"{SP} run --host-id=3 --command=/export", ["read"], ROS)["ok"]
    # backup encadeado não conta (não altera equipamento)
    assert n.check(f"python3 scripts/tools/backup/change.py begin --host-id 3 && {SP} run --host-id 3 --command /export",
                   ["read"], ROS)["ok"]


def test_check_ignora_bash_sem_session_py():
    assert n.check("grep -n session.py AGENTS.md", []) == {"ok": True, "needed": [], "missing": [], "calls": []}
    assert n.check("ls /", [])["ok"]


def test_host_desconhecido_usa_pior_caso():
    r = n.check(f"{SP} exec --session abc --command 'interface print'", ["read"], None)
    assert r["calls"][0]["dialect"] == "unknown"


def test_comandos_de_arquivo(tmp_path):
    f = tmp_path / "cmds.txt"
    f.write_text("/ip address print\n/ip address remove 1\n")
    r = n.check(f"{SP} run --host-id 3 --commands-file {f}", ["read"], ROS)
    assert r["missing"] == ["delete"]


def test_dialeto_pelo_inventario():
    assert n.dialect_for({"vendor": "mikrotik"}) == "ros"
    assert n.dialect_for({"vendor": "zabbix", "os": "debian"}) == "shell"
    assert n.dialect_for({"vendor": "cisco"}) == "netcli"
    assert n.dialect_for({"vendor": "other", "os": "routeros"}) == "ros"


# ------------------------------------------------------------------ sessão / hooks
@pytest.fixture(autouse=True)
def _prefs_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_prefs, "_FILE", tmp_path / "prefs.json")


def _session(netperms=None, resume=None):
    class WS:
        query_params = {}
    if netperms is not None:
        WS.query_params = {"netperms": ",".join(netperms)}
    if resume:
        WS.query_params = {**WS.query_params, "resume": resume}
    s = claude_svc.ClaudeWebSession(WS())
    asks = []

    async def _send(obj, only=None, skip=None):
        pass

    s._send = _send
    s._busy = True
    s._asks = asks
    return s


def _answer(s, decision):
    async def _ask_ui(tool, inp, ctx=None):
        s._asks.append((tool, inp, ctx))
        return None if decision is None else {"decision": decision}
    s._ask_ui = _ask_ui


def _cmd(c):
    return {"tool_input": {"command": c}}


@pytest.fixture
def ros_inventory(monkeypatch):
    monkeypatch.setattr(n, "inventory_dialect", lambda root: ROS)


def test_padrao_e_full_e_retomada_sem_registro_e_full():
    assert _session()._netperms == list(n.CATEGORIES)
    assert _session(resume="11111111-1111-1111-1111-111111111111")._netperms == list(n.CATEGORIES)


def test_conversa_nova_usa_padrao_salvo():
    claude_prefs.set_defaults(None, None, ["read"])
    assert _session()._netperms == ["read"]
    assert _session(["read", "edit"])._netperms == ["read", "edit"]   # a aba manda o estado atual
    assert _session([])._netperms == []


def test_full_nao_pergunta(ros_inventory):
    s = _session()
    _answer(s, "deny")
    assert asyncio.run(s._hook_netperms(_cmd(f"{SP} exec --host-id 3 --command '/ip route remove 1'"), "t", None)) == {}
    assert s._asks == []


def test_leitura_permitida_passa(ros_inventory):
    s = _session(["read"])
    _answer(s, "deny")
    assert asyncio.run(s._hook_netperms(_cmd(f"{SP} exec --host-id 3 --command '/ip route print'"), "t", None)) == {}
    assert s._asks == []


def test_categoria_desmarcada_pede_aprovacao_e_libera(ros_inventory):
    s = _session(["read", "edit"])
    _answer(s, "allow")
    r = asyncio.run(s._hook_netperms(_cmd(f"{SP} exec --host-id 3 --command '/ip route remove 1'"), "t", None))
    assert r == {}
    tool, inp, _ = s._asks[0]
    assert tool == "NetPerms" and inp["missing"] == ["delete"]


@pytest.mark.parametrize("decision", ["deny", None])
def test_negado_ou_sessao_encerrada_bloqueia(ros_inventory, decision):
    s = _session(["read"])
    _answer(s, decision)
    r = asyncio.run(s._hook_netperms(_cmd(f"{SP} run --host-id 3 --command '/ip address add address=1.1.1.1/32 interface=lo'"), "t", None))
    out = r["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "Criar" in out["permissionDecisionReason"]


def test_bash_local_nao_e_afetado(ros_inventory):
    s = _session([])
    _answer(s, "deny")
    assert asyncio.run(s._hook_netperms(_cmd("rm -rf /var/tmp/netops-x"), "t", None)) == {}


def test_prompt_avisa_quando_restrito_e_quando_volta_a_full():
    s = _session()
    assert asyncio.run(s._hook_prompt_netperms({}, None, None)) == {}       # Full nunca restrito: silêncio
    s._netperms = ["read"]
    ctx = asyncio.run(s._hook_prompt_netperms({}, None, None))["hookSpecificOutput"]["additionalContext"]
    assert "NÃO execute" in ctx and "Apagar" in ctx
    s._netperms = list(n.CATEGORIES)
    ctx = asyncio.run(s._hook_prompt_netperms({}, None, None))["hookSpecificOutput"]["additionalContext"]
    assert "Full" in ctx
    assert asyncio.run(s._hook_prompt_netperms({}, None, None)) == {}       # já avisado


def test_opcoes_registram_hooks():
    s = _session()
    if not claude_svc._SDK_OK:
        pytest.skip("SDK ausente")
    hooks = s._options().hooks
    assert any(s._hook_netperms in m.hooks for m in hooks["PreToolUse"])
    assert hooks["UserPromptSubmit"][0].hooks == [s._hook_prompt_netperms]
