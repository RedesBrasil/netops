#!/usr/bin/env python3
"""Config de backups: quem faz backup e quando (network/backups.yaml)."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response

from models import BackupsConfig, BackupDeleteRequest
from services import backups_svc

router = APIRouter(tags=["backups"])


def _rev(request: Request) -> str | None:
    return request.headers.get("if-match") or request.query_params.get("rev")


@router.get("/backups")
def get_backups():
    """Configuração atual de backup + rev (concorrência otimista)."""
    return backups_svc.load()


@router.get("/backups/candidates")
def backup_candidates():
    """Hosts e grupos do inventário disponíveis para seleção."""
    return backups_svc.candidates()


@router.put("/backups")
def save_backups(body: BackupsConfig, request: Request):
    """Substitui a configuração de backup (valida alvos contra o inventário)."""
    return backups_svc.save(body.model_dump(), _rev(request))


@router.get("/backups/files")
def backup_files():
    """Lista os backups armazenados + o diretorio onde vivem."""
    return backups_svc.list_stored()


@router.get("/backups/files/view")
def backup_file_view(path: str = Query(...)):
    """Conteudo textual de um backup (visualizacao inline)."""
    return backups_svc.read_stored(path)


@router.get("/backups/files/download")
def backup_file_download(path: str = Query(...)):
    """Download de um backup como anexo."""
    target = backups_svc.resolve_stored(path)
    return FileResponse(str(target), filename=target.name, media_type="application/octet-stream")


@router.post("/backups/{service_id}/run")
def run_service(service_id: str):
    """Dispara um backup sob demanda para o serviço (job em segundo plano)."""
    return backups_svc.start_run(service_id)


@router.get("/backups/runs")
def backup_runs():
    """Último run por serviço."""
    return backups_svc.list_latest_runs()


@router.get("/backups/runs/{run_id}")
def backup_run(run_id: str):
    """Status detalhado de uma execução (polling da UI)."""
    return backups_svc.read_run(run_id)


@router.get("/backups/hosts")
def backup_hosts():
    """Backups agrupados por host (só hosts que têm backup)."""
    return backups_svc.list_hosts_with_backups()


@router.get("/backups/files/zip")
def backup_files_zip(path: list[str] = Query(default=[]), name: str = "backups"):
    """Baixa vários backups de uma vez, empacotados num zip."""
    data, fname = backups_svc.zip_paths(path, name)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/backups/files/diff")
def backup_files_diff(a: str = Query(...), b: str = Query(...)):
    """Diferença linha a linha entre dois backups."""
    return backups_svc.diff_files(a, b)


@router.post("/backups/files/delete")
def backup_files_delete(body: BackupDeleteRequest):
    """Apaga os backups selecionados (IRREVERSÍVEL). Sandbox anti path-traversal."""
    return backups_svc.delete_stored(body.paths)
