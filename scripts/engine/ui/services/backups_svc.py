#!/usr/bin/env python3
"""Config de backups (network/backups.yaml): serviços de backup (quem + quando)
e acesso aos configs já coletados.

Modelo v2: uma LISTA de serviços nomeados (estilo jobs do Proxmox). Cada serviço
tem id, nome, agendamento e alvos (hosts/grupos). Contrato dos outros serviços da
UI: leitura devolve (config, rev sha256); escrita usa concorrência otimista.

Este serviço NÃO executa backup — só persiste a configuração e serve os arquivos
coletados. A execução no horário é de um runner externo (servidor stateless).
"""
from __future__ import annotations

import difflib
import io
import json
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path

from ruamel.yaml import YAML

import deps
from services import inventory_svc, yaml_io

_DEF_SCHEDULE = {"frequency": "daily", "time": "03:00", "weekday": "sun"}


def _default() -> dict:
    return {"version": 2, "services": []}


def _normalize_service(svc: dict) -> dict:
    """'time' sempre string HH:MM. `time: 03:00` sem aspas vira sexagesimal (YAML 1.1)
    => 180. Reconstrói a string nesse caso."""
    sch = svc.get("schedule")
    if isinstance(sch, dict) and isinstance(sch.get("time"), int):
        t = sch["time"]
        sch["time"] = f"{t // 60:02d}:{t % 60:02d}"
    return svc


def _migrate(data: dict) -> dict:
    """Aceita o formato v1 (schedule/targets único) e converte p/ v2 (lista de serviços)."""
    if "services" in data:
        return data
    tgt = data.get("targets") or {}
    if tgt.get("hosts") or tgt.get("groups"):
        return {"version": 2, "services": [{
            "id": "default",
            "name": "Backup padrão",
            "enabled": data.get("enabled", True),
            "schedule": data.get("schedule") or dict(_DEF_SCHEDULE),
            "targets": {"hosts": tgt.get("hosts") or [], "groups": tgt.get("groups") or []},
        }]}
    return _default()


def load() -> dict:
    """Retorna {config, rev}. Arquivo ausente/vazio => esqueleto default."""
    import yaml  # noqa: PLC0415
    text, rev, _ = yaml_io.read_text_meta(deps.BACKUPS_FILE)
    raw = yaml.safe_load(text) if text.strip() else None
    data = _migrate(raw) if raw else _default()
    for svc in data.get("services") or []:
        _normalize_service(svc)
    return {"config": data, "rev": rev}


def candidates() -> dict:
    """Hosts e grupos disponíveis p/ escolher (a partir do inventário)."""
    inv = inventory_svc.list_hosts_detailed()
    hosts = [
        {
            "id": h["id"],
            "vendor": h["effective"].get("vendor"),
            "role": h["effective"].get("role"),
            "group": h["explicit"].get("group"),
            "mgmt_ip": h["effective"].get("mgmt_ip"),
        }
        for h in inv["hosts"]
    ]
    groups = [
        {"name": g["name"], "used_by": g["used_by"]}
        for g in inventory_svc.list_groups()["groups"]
    ]
    return {"hosts": hosts, "groups": groups}


def save(config: dict, rev: str | None) -> dict:
    """Valida os serviços (ids únicos + alvos existentes) e grava. Retorna {rev}."""
    services = config.get("services")
    if not isinstance(services, list):
        raise deps.ValidationFailed([{"loc": "services", "msg": "lista de serviços ausente"}])

    inv = inventory_svc.list_hosts_detailed()
    valid_hosts = {h["id"] for h in inv["hosts"]}
    valid_groups = set(inv["groups"])

    errors = []
    seen = set()
    for i, s in enumerate(services):
        sid = s.get("id")
        if sid in seen:
            errors.append({"loc": f"services/{i}/id", "msg": f"id duplicado: {sid}"})
        seen.add(sid)
        tgt = s.get("targets") or {}
        for hid in tgt.get("hosts") or []:
            if hid not in valid_hosts:
                errors.append({"loc": f"services/{sid}/hosts/{hid}", "msg": "host inexistente no inventário"})
        for g in tgt.get("groups") or []:
            if g not in valid_groups:
                errors.append({"loc": f"services/{sid}/groups/{g}", "msg": "grupo inexistente no inventário"})
    if errors:
        raise deps.ValidationFailed(errors)

    # Força aspas em 'time' p/ não ser interpretado como sexagesimal (YAML 1.1).
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString  # noqa: PLC0415
    for s in services:
        sch = s.get("schedule")
        if isinstance(sch, dict) and "time" in sch:
            sch["time"] = DoubleQuotedScalarString(str(sch["time"]))

    y = YAML()
    new_rev = yaml_io.write_rt(deps.BACKUPS_FILE, y, config, expected=rev, backup=True)
    return {"rev": new_rev}


# --------------------------------------------------------------------------- #
# Backups armazenados (leitura/download dos configs coletados)
# --------------------------------------------------------------------------- #
MAX_VIEW_BYTES = 2 * 1024 * 1024  # 2 MB p/ visualização inline


def _safe_path(relpath: str) -> Path:
    """Resolve relpath DENTRO de BACKUPS_STORE. Barra path traversal (../, absoluto, symlink)."""
    root = deps.BACKUPS_STORE.resolve()
    if not relpath or relpath.startswith("/") or ".." in Path(relpath).parts:
        raise deps.ValidationFailed([{"loc": "path", "msg": "caminho invalido"}])
    target = (root / relpath).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise deps.ValidationFailed([{"loc": "path", "msg": "fora do diretorio de backups"}])
    return target


def list_stored() -> dict:
    """Lista (recursiva) os arquivos de backup + onde eles vivem."""
    root = deps.BACKUPS_STORE
    files = []
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                st = p.stat()
                files.append({
                    "path": str(p.relative_to(root)),
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                })
    return {"dir": str(root), "files": files}


def read_stored(relpath: str) -> dict:
    """Conteúdo textual de um backup p/ visualização inline (trunca em MAX_VIEW_BYTES)."""
    target = _safe_path(relpath)
    if not target.is_file():
        raise deps.ValidationFailed([{"loc": "path", "msg": "arquivo nao encontrado"}])
    raw = target.read_bytes()
    binary = b"\x00" in raw[:8192]
    truncated = len(raw) > MAX_VIEW_BYTES
    if truncated:
        raw = raw[:MAX_VIEW_BYTES]
    text = "" if binary else raw.decode("utf-8", errors="replace")
    return {"path": relpath, "size": target.stat().st_size,
            "binary": binary, "truncated": truncated, "text": text}


def resolve_stored(relpath: str) -> Path:
    """Path absoluto validado p/ download (FileResponse)."""
    target = _safe_path(relpath)
    if not target.is_file():
        raise deps.ValidationFailed([{"loc": "path", "msg": "arquivo nao encontrado"}])
    return target


# --------------------------------------------------------------------------- #
# Execução sob demanda (botão Run) — job efêmero + status em disco
# --------------------------------------------------------------------------- #
_RUN_ID_RE = None  # validado abaixo por _safe_run_id


def _safe_run_id(run_id: str) -> str:
    import re  # noqa: PLC0415
    if not run_id or not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise deps.ValidationFailed([{"loc": "run_id", "msg": "run_id invalido"}])
    return run_id


def _run_path(run_id: str) -> Path:
    return deps.BACKUPS_RUNS / f"{_safe_run_id(run_id)}.json"


def _write_run(run_id: str, status: dict) -> None:
    deps.BACKUPS_RUNS.mkdir(parents=True, exist_ok=True)
    tmp = _run_path(run_id).with_suffix(f".json.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _run_path(run_id))


def _expand_targets(service: dict) -> list:
    """IDs de host do serviço: hosts explícitos + expansão dos grupos (sem duplicar)."""
    data, _ = inventory_svc.load_hosts()
    hosts = data.get("hosts") or {}
    tgt = service.get("targets") or {}
    picked, seen = [], set()
    for hid in tgt.get("hosts") or []:
        if hid in hosts and hid not in seen:
            seen.add(hid); picked.append(hid)
    for g in tgt.get("groups") or []:
        for hid, hv in hosts.items():
            if (hv or {}).get("group") == g and hid not in seen:
                seen.add(hid); picked.append(hid)
    return picked


def start_run(service_id: str) -> dict:
    """Dispara um job de backup para o serviço. Retorna {run_id}. Exige cofre destrancado."""
    cfg = load()["config"]
    service = next((s for s in cfg.get("services") or [] if s.get("id") == service_id), None)
    if not service:
        raise KeyError(f"serviço '{service_id}' não existe")

    # Exige cofre destrancado (senão VaultLocked -> 423 com dica de unlock).
    from lib.vault_session import get_session_key  # noqa: PLC0415
    get_session_key()

    targets = _expand_targets(service)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    status = {
        "run_id": run_id,
        "service_id": service_id,
        "service_name": service.get("name", service_id),
        "state": "running",
        "started_at": int(time.time()),
        "finished_at": None,
        "note": "Piloto: coleta apenas MikroTik via SSH.",
        "hosts": [{"id": h, "state": "pending", "detail": ""} for h in targets],
    }
    _write_run(run_id, status)

    deps.BACKUPS_RUNS.mkdir(parents=True, exist_ok=True)
    log = open(deps.BACKUPS_RUNS / f"{run_id}.log", "ab")
    runner = str(Path(deps.__file__).resolve().parent / "backup_runner.py")
    subprocess.Popen(
        ["/opt/netops/.venv/bin/python3", runner, "--run-id", run_id],
        stdout=log, stderr=log, start_new_session=True, close_fds=True,
    )
    return {"run_id": run_id}


def read_run(run_id: str) -> dict:
    p = _run_path(run_id)
    if not p.is_file():
        raise KeyError(f"run '{run_id}' não encontrado")
    return json.loads(p.read_text(encoding="utf-8"))


def list_latest_runs() -> dict:
    """Último run por serviço (p/ o card reabrir o modal e mostrar status)."""
    latest = {}
    root = deps.BACKUPS_RUNS
    if root.exists():
        for p in root.glob("*.json"):
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            sid = st.get("service_id")
            if not sid:
                continue
            cur = latest.get(sid)
            if cur is None or (st.get("started_at") or 0) > (cur.get("started_at") or 0):
                hosts = st.get("hosts") or []
                latest[sid] = {
                    "run_id": st.get("run_id"),
                    "state": st.get("state"),
                    "started_at": st.get("started_at"),
                    "ok": sum(1 for h in hosts if h.get("state") == "ok"),
                    "fail": sum(1 for h in hosts if h.get("state") == "fail"),
                    "total": len(hosts),
                }
    return latest


# --------------------------------------------------------------------------- #
# Backups agrupados por host + download em lote (zip)
# --------------------------------------------------------------------------- #
def list_hosts_with_backups() -> dict:
    """Só hosts que TÊM backup. Cada host: contagem, tamanho total, mais recente e a lista."""
    root = deps.BACKUPS_STORE
    by_host = {}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root)
                host = rel.parts[0] if len(rel.parts) > 1 else "(raiz)"
                st = p.stat()
                by_host.setdefault(host, []).append(
                    {"path": str(rel), "name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    hosts = []
    for host in sorted(by_host):
        backups = sorted(by_host[host], key=lambda b: b["mtime"], reverse=True)
        hosts.append({
            "host": host,
            "count": len(backups),
            "total_size": sum(b["size"] for b in backups),
            "latest_mtime": max(b["mtime"] for b in backups),
            "backups": backups,
        })
    return {"dir": str(root), "hosts": hosts}


def zip_paths(paths: list, name: str = "backups") -> tuple:
    """Empacota vários backups num zip (cada path validado no sandbox). Retorna (bytes, filename)."""
    if not paths:
        raise deps.ValidationFailed([{"loc": "path", "msg": "nenhum backup selecionado"}])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in paths:
            target = _safe_path(rel)
            if not target.is_file():
                raise deps.ValidationFailed([{"loc": "path", "msg": f"arquivo nao encontrado: {rel}"}])
            z.write(target, arcname=rel)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "backups"
    return buf.getvalue(), safe + ".zip"


# --------------------------------------------------------------------------- #
# Diff entre dois backups (linha a linha, tipo add/remove/change)
# --------------------------------------------------------------------------- #
def _read_for_diff(rel: str) -> str:
    t = _safe_path(rel)
    if not t.is_file():
        raise deps.ValidationFailed([{"loc": "path", "msg": f"arquivo nao encontrado: {rel}"}])
    raw = t.read_bytes()
    if b"\x00" in raw[:8192]:
        raise deps.ValidationFailed([{"loc": "path", "msg": "arquivo binario nao pode ser comparado"}])
    return raw.decode("utf-8", errors="replace")


def diff_files(a: str, b: str) -> dict:
    """Compara dois backups. Retorna linhas com tipo: equal|added|removed|changed."""
    la = _read_for_diff(a).splitlines()
    lb = _read_for_diff(b).splitlines()
    sm = difflib.SequenceMatcher(a=la, b=lb, autojunk=False)
    lines = []
    counts = {"added": 0, "removed": 0, "changed": 0}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                lines.append({"type": "equal", "text": la[k]})
        elif tag == "insert":
            for k in range(j1, j2):
                lines.append({"type": "added", "text": lb[k]}); counts["added"] += 1
        elif tag == "delete":
            for k in range(i1, i2):
                lines.append({"type": "removed", "text": la[k]}); counts["removed"] += 1
        elif tag == "replace":
            na, nb = i2 - i1, j2 - j1
            common = min(na, nb)
            for k in range(common):
                al, bl = la[i1 + k], lb[j1 + k]
                if difflib.SequenceMatcher(None, al, bl).ratio() >= 0.6:
                    lines.append({"type": "changed", "text": bl, "old": al}); counts["changed"] += 1
                else:
                    lines.append({"type": "removed", "text": al}); counts["removed"] += 1
                    lines.append({"type": "added", "text": bl}); counts["added"] += 1
            for k in range(common, nb):
                lines.append({"type": "added", "text": lb[j1 + k]}); counts["added"] += 1
            for k in range(common, na):
                lines.append({"type": "removed", "text": la[i1 + k]}); counts["removed"] += 1
    return {"a": a, "b": b, "counts": counts, "lines": lines}
