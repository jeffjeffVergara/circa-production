"""Ejecución y monitoreo de procesos batch."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import db
from app.services.batch_jobs.registry import JOB_DEFINITIONS, JOBS_BY_ID

logger = logging.getLogger("circa.batch_jobs")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_last_runs(limit_per_job: int = 1) -> dict[str, dict[str, Any]]:
    try:
        rows = (
            db.sb.table("batch_runs")
            .select("*")
            .order("started_at", desc=True)
            .limit(200)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning("batch_runs no disponible: %s", exc)
        return {}

    out: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        jid = row.get("job_id")
        if not jid:
            continue
        counts[jid] = counts.get(jid, 0) + 1
        if counts[jid] <= limit_per_job and jid not in out:
            out[jid] = row
    return out


def list_jobs_with_status() -> list[dict[str, Any]]:
    last = _fetch_last_runs()
    items = []
    for job in JOB_DEFINITIONS:
        lr = last.get(job.id)
        items.append({
            "id": job.id,
            "nombre": job.nombre,
            "descripcion": job.descripcion,
            "frecuencia_sugerida": job.frecuencia_sugerida,
            "afecta_whatsapp": job.afecta_whatsapp,
            "permite_dry_run": job.permite_dry_run,
            "soporta_test_filter": job.soporta_test_filter,
            "ultima_ejecucion": lr,
        })
    return items


def fetch_runs(*, job_id: Optional[str] = None, limit: int = 30) -> list[dict[str, Any]]:
    try:
        q = db.sb.table("batch_runs").select("*").order("started_at", desc=True).limit(limit)
        if job_id:
            q = q.eq("job_id", job_id)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("No se pudo leer batch_runs: %s", exc)
        return []


def _create_run(
    *,
    job_id: str,
    trigger: str,
    test_filter: Optional[str],
    dry_run: bool,
    user_email: str,
    comment: str,
) -> str:
    row = {
        "job_id": job_id,
        "status": "running",
        "trigger": trigger,
        "test_filter": test_filter,
        "dry_run": dry_run,
        "started_at": _iso_now(),
        "user_email": user_email,
        "comment": comment,
    }
    ins = db.sb.table("batch_runs").insert(row).execute()
    return ins.data[0]["id"]


def _finish_run(
    run_id: str,
    *,
    status: str,
    stats: dict[str, Any],
    error: Optional[str] = None,
) -> None:
    db.sb.table("batch_runs").update({
        "status": status,
        "finished_at": _iso_now(),
        "stats": stats,
        "error": error,
    }).eq("id", run_id).execute()


async def run_batch_job(
    job_id: str,
    *,
    test: Optional[str] = "real",
    dry_run: bool = False,
    trigger: str = "manual",
    user_email: str = "",
    comment: str = "",
) -> dict[str, Any]:
    job = JOBS_BY_ID.get(job_id)
    if not job:
        raise ValueError(f"Job desconocido: {job_id}")

    run_id = None
    try:
        run_id = _create_run(
            job_id=job_id,
            trigger=trigger,
            test_filter=test if job.soporta_test_filter else None,
            dry_run=dry_run,
            user_email=user_email,
            comment=comment,
        )
    except Exception as exc:
        logger.warning("batch_runs insert falló (¿migración?): %s", exc)

    try:
        kwargs: dict[str, Any] = {"dry_run": dry_run}
        if job.soporta_test_filter:
            kwargs["test"] = test
        result = await job.handler(**kwargs)
    except Exception as exc:
        if run_id:
            _finish_run(run_id, status="failed", stats={}, error=str(exc))
        raise

    processed = int(result.get("processed") or 0)
    ok = int(result.get("ok") or 0)
    failed = int(result.get("failed") or 0)
    status = "ok"
    if failed and ok:
        status = "partial"
    elif failed or (processed and not ok):
        status = "failed"
    elif processed == 0 and result.get("errors"):
        status = "partial"

    payload = {
        "job_id": job_id,
        "dry_run": dry_run,
        "processed": processed,
        "ok": ok,
        "failed": failed,
        "errors": result.get("errors") or [],
        "details": result.get("details") or {},
    }
    if run_id:
        _finish_run(run_id, status=status, stats=payload, error=None)
        payload["run_id"] = run_id
    payload["status"] = status
    return payload
