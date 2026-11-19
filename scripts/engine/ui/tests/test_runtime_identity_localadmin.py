"""Conta operacional `netops` (layout 2) e administração Local — plano 2026-11-19.

Cobre o que dá para testar sem root/systemd: identidade (parse e validação), proteção do host Local e
da credencial do admin local no inventário/cofre, autorização da rota do modo root dos Arquivos, contrato
do backend `su` (nada de segredo em argv; quoting) e o `start.sh` lendo o arquivo de identidade em bash puro.
O fluxo real (su/PAM, linger, reboot, migração) é validado em CTs descartáveis (relatório da entrega).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ENGINE = Path(__file__).resolve().parents[2]
PROJECT = ENGINE.parents[1]
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "localadmin"))

from lib import runtime_identity as rid  # noqa: E402

UUID = "0b5c1b0e-7a52-4e0c-9a55-2f9d3e1f6a10"


@pytest.fixture()
def ident_dir(tmp_path, monkeypatch):
    d = tmp_path / "instances"
    d.mkdir()
    monkeypatch.setenv("NETOPS_IDENTITY_DIR", str(d))
    monkeypatch.setattr(rid, "CONF_DIR", d)
    return d


def _me():
    import pwd
    return pwd.getpwuid(os.getuid())


# --------------------------------------------------------------------------- identidade
def test_slug_and_unit_names():
    assert rid.slug("/opt/netops") == "opt-netops"
    assert rid.slug("/opt/NetOps-Francisco") == "opt-NetOps-Francisco"
    assert rid.unit_name("/opt/netops") == "netops-console@opt-netops.service"


def test_legacy_when_no_file(ident_dir, tmp_path):
    assert rid.load(tmp_path) is None
    assert rid.current_ok(None)[0] is True


def test_load_valid_identity(ident_dir, tmp_path):
    me = _me()
    if me.pw_uid == 0:
        pytest.skip("o teste usa a conta atual como conta operacional (não pode ser root)")
    (ident_dir / f"{rid.slug(tmp_path)}.env").write_text(
        f"NETOPS_LAYOUT=2\nNETOPS_DIR={tmp_path}\nNETOPS_RUNTIME_USER={me.pw_name}\n"
        f"NETOPS_RUNTIME_HOME={me.pw_dir}\nNETOPS_INSTANCE_ID={UUID}\nNETOPS_UI_PORT=8765\n")
    ident = rid.load(tmp_path)
    assert ident["user"] == me.pw_name and ident["instance_id"] == UUID
    assert rid.current_ok(ident)[0] is True


@pytest.mark.parametrize("bad", [
    "NETOPS_LAYOUT=2\nNETOPS_DIR=/outra/pasta\nNETOPS_RUNTIME_USER=nobody\n",      # outra instalação
    "NETOPS_LAYOUT=2\nNETOPS_DIR={root}\nNETOPS_RUNTIME_USER=root\n",              # nunca root
    "NETOPS_LAYOUT=2\nNETOPS_DIR={root}\nNETOPS_RUNTIME_USER=$(id)\n",             # sem expansão
    "NETOPS_LAYOUT=2\nNETOPS_DIR={root}\nLD_PRELOAD=/x.so\n",                       # chave fora da lista
    "NETOPS_LAYOUT=9\nNETOPS_DIR={root}\nNETOPS_RUNTIME_USER=nobody\n",            # layout desconhecido
])
def test_reject_invalid_identity(ident_dir, tmp_path, bad):
    (ident_dir / f"{rid.slug(tmp_path)}.env").write_text(bad.format(root=tmp_path))
    with pytest.raises(rid.IdentityError):
        rid.load(tmp_path)


def test_write_keeps_instance_id(ident_dir, tmp_path):
    me = _me()
    p = rid.write(tmp_path, me.pw_name, me.pw_dir, port="9000")
    first = rid.parse_env(p.read_text())["NETOPS_INSTANCE_ID"]
    rid.write(tmp_path, me.pw_name, me.pw_dir, port="9001", host="10.0.0.5")
    env = rid.parse_env(p.read_text())
    assert env["NETOPS_INSTANCE_ID"] == first and env["NETOPS_UI_PORT"] == "9001"
    with pytest.raises(rid.IdentityError):
        rid.write(tmp_path, me.pw_name, me.pw_dir, host="1.2.3.4; rm -rf /")


# --------------------------------------------------------------------------- start.sh (bash puro)
def _start_sh(ident_dir, body: str):
    root = PROJECT
    (ident_dir / f"{rid.slug(root)}.env").write_text(body)
    return subprocess.run(["bash", str(root / "scripts/engine/ui/start.sh"), "--foreground"],
                          env={**os.environ, "NETOPS_IDENTITY_DIR": str(ident_dir)},
                          capture_output=True, text=True, timeout=30)


def test_start_sh_rejects_identity_of_other_dir(ident_dir):
    r = _start_sh(ident_dir, "NETOPS_LAYOUT=2\nNETOPS_DIR=/somewhere/else\nNETOPS_RUNTIME_USER=nobody\n")
    assert r.returncode == 2 and "aponta para" in r.stderr


def test_start_sh_rejects_injection(ident_dir):
    r = _start_sh(ident_dir, f"NETOPS_LAYOUT=2\nNETOPS_DIR={PROJECT}\nNETOPS_RUNTIME_USER=a;id\n")
    assert r.returncode == 2 and "valor inválido" in r.stderr


def test_start_sh_refuses_wrong_account(ident_dir):
    if os.getuid() == 0:
        pytest.skip("como root o start.sh delega (testado no CT)")
    r = _start_sh(ident_dir, f"NETOPS_LAYOUT=2\nNETOPS_DIR={PROJECT}\nNETOPS_RUNTIME_USER=nobody\n")
    assert r.returncode == 2 and "roda como 'nobody'" in r.stderr


# --------------------------------------------------------------------------- host Local protegido
LOCAL = {"id": 90, "hostname": "NETOPS-LOCAL", "mgmt_ip": "127.0.0.1", "vendor": "LINUX", "role": "SERVER",
         "access": {"method": "local"}, "credential": "CRED_LOCAL_ADMIN", "local_instance": UUID}


def _add_local(env):
    p = env / "network" / "hosts.yaml"
    data = yaml.safe_load(p.read_text())
    data["hosts"].append(dict(LOCAL))
    data["next_host_id"] = max(data["next_host_id"], 91)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def test_api_cannot_create_local_host(client):
    r = client.post("/api/hosts", json={"hostname": "OUTRO", "mgmt_ip": "127.0.0.1", "vendor": "linux",
                                        "access": {"method": "local"}, "credential": "CRED_LOCAL_ADMIN"})
    assert r.status_code == 422, r.text


def test_local_host_cannot_be_deleted_or_rewired(client, env):
    _add_local(env)
    assert client.delete("/api/hosts/90").status_code == 422
    rev = client.get("/api/hosts").json()["rev"]
    r = client.patch("/api/hosts/90", json={"access": {"method": "ssh", "port": 22}}, headers={"If-Match": rev})
    assert r.status_code == 422, r.text
    r = client.patch("/api/hosts/90", json={"credential": "CRED_LINUX_ROOT"}, headers={"If-Match": rev})
    assert r.status_code == 422, r.text
    r = client.patch("/api/hosts/90", json={"notes": "servidor principal"}, headers={"If-Match": rev})
    assert r.status_code == 200, r.text       # nota/site continuam editáveis


def test_other_host_cannot_use_local_credential(client, env):
    _add_local(env)
    r = client.patch("/api/hosts/1", json={"credential": "CRED_LOCAL_ADMIN"},
                     headers={"If-Match": client.get("/api/hosts").json()["rev"]})
    assert r.status_code == 422, r.text


def test_validate_flags_two_local_hosts(env):
    from services import inventory_svc
    data = yaml.safe_load((env / "network" / "hosts.yaml").read_text())
    data["hosts"] += [dict(LOCAL), {**LOCAL, "id": 91, "hostname": "NETOPS-LOCAL-2"}]
    msgs = [e["msg"] for e in inventory_svc._local_errors(data)]
    assert any("só pode existir um host" in m for m in msgs)


def test_local_admin_credential_is_system_managed(client, env):
    (env / "network" / "credentials.yaml").write_text(
        "version: 1\n\ncredentials:\n  CRED_LOCAL_ADMIN:\n    username: netops-admin\n    password: \"enc.v1:x\"\n")
    lst = client.get("/api/credentials").json()
    item = next(c for c in lst["credentials"] if c["name"] == "CRED_LOCAL_ADMIN")
    assert item["system"] == "local_admin" and item["password"] == {"set": True, "encrypted": True}
    rev = lst["rev"]
    assert client.delete("/api/credentials/CRED_LOCAL_ADMIN?force=true", headers={"If-Match": rev}).status_code == 422


# --------------------------------------------------------------------------- autorização
def test_root_files_routes_need_server_admin():
    from services import authz
    assert authz.required_perm("POST", "/files/root/open") == "server.admin"
    from lib import accessdb
    assert "server.admin" in accessdb.ADMIN_ONLY


# --------------------------------------------------------------------------- backend su (contrato)
def test_su_line_has_no_secret_and_quotes_argv():
    import su_backend
    inner = su_backend.build_exec(["echo", "a b", "$(id)", "'q'"], None, "/root", 30)
    p = su_backend.SuProcess("S3GREDO-NAO-PODE-APARECER", inner)
    assert "S3GREDO" not in p.line
    # o comando chega ao root exatamente como argv (sem expansão de $(id))
    assert shlex.join(["echo", "a b", "$(id)", "'q'"]) in shlex.split(p.line)[-1]
    assert "env -i" in p.line and "timeout --kill-after=10 30" in p.line


def test_su_rejects_echo_on_and_unknown_prompt(monkeypatch):
    """Sem prompt de senha reconhecido, o backend não envia nada e falha como backend_unavailable."""
    import su_backend
    from common import LocalAdminError
    monkeypatch.setattr(su_backend, "SU", "/bin/echo")
    monkeypatch.setattr(su_backend, "AUTH_TIMEOUT", 3)
    p = su_backend.SuProcess("x" * 20, "true")
    with pytest.raises(LocalAdminError) as e:
        p.authenticate()
    assert e.value.code == "backend_unavailable"
