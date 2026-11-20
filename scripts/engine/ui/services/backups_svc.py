#!/usr/bin/env python3
"""Config de backups (network/backups.yaml): serviços de backup (quem + quando)
e acesso aos configs já coletados.

Modelo v3: uma LISTA de serviços nomeados com alvos inteiros e histórico legado.
Cada serviço
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
import sys
import time
import zipfile
from pathlib import Path

from ruamel.yaml import YAML

import deps
from lib import i18n
from services import inventory_svc, yaml_io
from lib.host_identity import host_index, require_host_id, resolve_reference
from lib.inventory_lock import ensure_migration_complete

_DEF_SCHEDULE = {"frequency": "daily", "time": "03:00", "weekday": "sun"}


def _default() -> dict:
    return {"version": 3, "services": [], "legacy_sources": []}


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


@yaml_io.serialized
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
            "hostname": h["effective"].get("hostname"),
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


@yaml_io.serialized
def save(config: dict, rev: str | None) -> dict:
    """Valida os serviços (ids únicos + alvos existentes) e grava. Retorna {rev}."""
    ensure_migration_complete(deps.HOSTS_FILE.parent)
    services = config.get("services")
    if not isinstance(services, list):
        raise deps.ValidationFailed([{"loc": "services", "msg": i18n.t("api_backups.services_missing")}])

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
            try:
                require_host_id(hid)
            except (TypeError, ValueError):
                errors.append({"loc": f"services/{sid}/hosts", "msg": i18n.t("api_backups.host_id_int")})
                continue
            if hid not in valid_hosts:
                errors.append({"loc": f"services/{sid}/hosts/{hid}", "msg": i18n.t("api_backups.host_not_in_inventory")})
        for g in tgt.get("groups") or []:
            if g not in valid_groups:
                errors.append({"loc": f"services/{sid}/groups/{g}", "msg": i18n.t("api_backups.group_not_in_inventory")})
    current_sources = load()["config"].get("legacy_sources") or []
    if config.get("legacy_sources", []) != current_sources:
        errors.append({"loc": "legacy_sources", "msg": i18n.t("api_backups.legacy_immutable")})
    if errors:
        raise deps.ValidationFailed(errors)
    config["version"] = 3
    config["legacy_sources"] = current_sources

    # Força aspas em 'time' p/ não ser interpretado como sexagesimal (YAML 1.1).
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString  # noqa: PLC0415
    for s in services:
        sch = s.get("schedule")
        if isinstance(sch, dict) and "time" in sch:
            sch["time"] = DoubleQuotedScalarString(str(sch["time"]))

    y = YAML()
    new_rev = yaml_io.write_rt(deps.BACKUPS_FILE, y, config, expected=rev, backup=True)
    return {"rev": new_rev}


def cascade_host_delete(host_id: int, writes: list, checks: list) -> None:
    """Inclui a remoção dos alvos na transação de exclusão do inventário.

    O histórico e suas associações são preservados: IDs excluídos nunca são reutilizados.
    """
    require_host_id(host_id)
    data, rev, y = yaml_io.load_rt(deps.BACKUPS_FILE)
    if data is None:
        return
    changed = False
    services = data.get("services") or ([data] if "targets" in data else [])
    for service in services:
        targets = service.get("targets") or {}
        hosts = targets.get("hosts") or []
        if host_id in hosts:
            targets["hosts"] = [hid for hid in hosts if hid != host_id]
            changed = True
    if changed:
        writes.append((deps.BACKUPS_FILE, yaml_io.dump_rt(y, data), 0o644))
        checks.append((deps.BACKUPS_FILE, rev))


# --------------------------------------------------------------------------- #
# Backups armazenados (leitura/download dos configs coletados)
# --------------------------------------------------------------------------- #
MAX_VIEW_BYTES = 2 * 1024 * 1024  # 2 MB p/ visualização inline


def _safe_path(relpath: str) -> Path:
    """Resolve relpath DENTRO de BACKUPS_STORE. Barra path traversal (../, absoluto, symlink)."""
    root = deps.BACKUPS_STORE.resolve()
    if not relpath or relpath.startswith("/") or ".." in Path(relpath).parts:
        raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.invalid_path")}])
    target = (root / relpath).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.outside_dir")}])
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
        raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.file_not_found")}])
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
        raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.file_not_found")}])
    return target


# --------------------------------------------------------------------------- #
# Execução sob demanda (botão Run) — job efêmero + status em disco
# --------------------------------------------------------------------------- #
_RUN_ID_RE = None  # validado abaixo por _safe_run_id


def _safe_run_id(run_id: str) -> str:
    import re  # noqa: PLC0415
    if not run_id or not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise deps.ValidationFailed([{"loc": "run_id", "msg": i18n.t("api_backups.invalid_run_id")}])
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
    hosts = host_index(data)
    tgt = service.get("targets") or {}
    picked, seen = [], set()
    for ref in tgt.get("hosts") or []:
        # Formato legado só é aceito quando ainda resolve para um host cadastrado.
        hid = resolve_reference(ref, data)
        if hid not in seen:
            seen.add(hid); picked.append(hid)
    for g in tgt.get("groups") or []:
        for hid, hv in hosts.items():
            if (hv or {}).get("group") == g and hid not in seen:
                seen.add(hid); picked.append(hid)
    return picked


@yaml_io.serialized
def start_run(service_id: str) -> dict:
    """Dispara um job de backup para o serviço. Retorna {run_id}. Exige cofre destrancado."""
    ensure_migration_complete(deps.HOSTS_FILE.parent)
    cfg = load()["config"]
    service = next((s for s in cfg.get("services") or [] if s.get("id") == service_id), None)
    if not service:
        raise KeyError(i18n.t("api_backups.service_not_exists", id=service_id))

    # Exige cofre destrancado (senão VaultLocked -> 423 com dica de unlock).
    from lib.vault_session import get_session_key  # noqa: PLC0415
    get_session_key()

    targets = _expand_targets(service)
    hosts_data, _ = inventory_svc.load_hosts()
    records = host_index(hosts_data)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    status = {
        "run_id": run_id,
        "service_id": service_id,
        "service_name": service.get("name", service_id),
        "state": "running",
        "started_at": int(time.time()),
        "finished_at": None,
        "note": i18n.t("api_backups.pilot_note"),
        "hosts": [{"id": h, "hostname": records[h].get("hostname"), "state": "pending", "detail": ""}
                  for h in targets],
    }
    _write_run(run_id, status)

    deps.BACKUPS_RUNS.mkdir(parents=True, exist_ok=True)
    runner = str(Path(deps.__file__).resolve().parent / "backup_runner.py")
    with (deps.BACKUPS_RUNS / f"{run_id}.log").open("ab") as log:
        subprocess.Popen(
            [sys.executable, runner, "--data-root", str(deps.DATA_ROOT), "--run-id", run_id],
            stdout=log, stderr=log, start_new_session=True, close_fds=True,
        )
    return {"run_id": run_id}


def read_run(run_id: str) -> dict:
    p = _run_path(run_id)
    if not p.is_file():
        raise KeyError(i18n.t("api_backups.run_not_found", run_id=run_id))
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
@yaml_io.serialized
def list_hosts_with_backups() -> dict:
    """Agrupa pelo ID canônico; diretórios legados são associados explicitamente.

    Diretórios sem dono permanecem disponíveis, mas não viram hosts fictícios.
    """
    root = deps.BACKUPS_STORE
    inv, _ = inventory_svc.load_hosts()
    records = host_index(inv)
    sources = {}
    for source in load()["config"].get("legacy_sources") or []:
        sources[source["directory"]] = source["host_id"]
    by_host = {}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root)
                directory = rel.parts[0] if len(rel.parts) > 1 else "(raiz)"
                host_id = None
                if directory == "by-id" and len(rel.parts) >= 3:
                    try:
                        host_id = require_host_id(int(rel.parts[1]))
                    except (TypeError, ValueError):
                        pass
                elif directory in sources:
                    host_id = sources[directory]
                elif inv.get("version", 1) == 1 and directory in records:
                    host_id = directory
                if directory == "by-id" and len(rel.parts) >= 3:
                    directory = "/".join(rel.parts[:2])
                if host_id not in records:
                    host_id = None
                key = (host_id, None if host_id is not None else directory)
                st = p.stat()
                by_host.setdefault(key, []).append(
                    {"path": str(rel), "name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    hosts = []
    for (host_id, directory), items in sorted(by_host.items(), key=lambda item: str(item[0])):
        backups = sorted(items, key=lambda b: b["mtime"], reverse=True)
        hosts.append({
            "host": host_id,
            "hostname": (records.get(host_id) or {}).get("hostname"),
            "directory": directory,
            "assigned": host_id is not None,
            "count": len(backups),
            "total_size": sum(b["size"] for b in backups),
            "latest_mtime": max(b["mtime"] for b in backups),
            "backups": backups,
        })
    return {"dir": str(root), "hosts": hosts}


def zip_paths(paths: list, name: str = "backups") -> tuple:
    """Empacota vários backups num zip (cada path validado no sandbox). Retorna (bytes, filename)."""
    if not paths:
        raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.none_selected")}])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in paths:
            target = _safe_path(rel)
            if not target.is_file():
                raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.file_not_found_path", path=rel)}])
            z.write(target, arcname=rel)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "backups"
    return buf.getvalue(), safe + ".zip"


# --------------------------------------------------------------------------- #
# Diff entre dois backups (linha a linha, tipo add/remove/change)
# --------------------------------------------------------------------------- #
def _read_for_diff(rel: str) -> str:
    t = _safe_path(rel)
    if not t.is_file():
        raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.file_not_found_path", path=rel)}])
    raw = t.read_bytes()
    if b"\x00" in raw[:8192]:
        raise deps.ValidationFailed([{"loc": "path", "msg": i18n.t("api_backups.binary_no_diff")}])
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


def delete_stored(paths: list) -> dict:
    """Apaga os backups indicados (cada path validado no sandbox). IRREVERSÍVEL.
    Remove o diretório do host se ficar vazio."""
    if not paths:
        raise deps.ValidationFailed([{"loc": "paths", "msg": i18n.t("api_backups.none_selected")}])
    root = deps.BACKUPS_STORE.resolve()
    deleted = []
    for rel in paths:
        target = _safe_path(rel)
        if target.is_file():
            target.unlink()
            deleted.append(rel)
            parent = target.parent
            try:
                if parent != root and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
    return {"deleted": deleted, "count": len(deleted)}
