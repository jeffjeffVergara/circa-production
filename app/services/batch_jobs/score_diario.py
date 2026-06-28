"""Job: score operativo diario + historial."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from app.services import db
from app.services.bodega_scoring_batch import run_bodega_scoring_batch


def _persist_daily_scores(rows: list[dict[str, Any]], *, dry_run: bool) -> int:
    if dry_run or not rows:
        return 0
    hoy = date.today().isoformat()
    saved = 0
    for row in rows:
        try:
            db.sb.table("bodega_scoring_diario").upsert(
                {
                    "bodega_id": row["bodega_id"],
                    "fecha": hoy,
                    "score": row["score"],
                    "grade": row.get("grade"),
                    "breakdown": row.get("breakdown") or {},
                    "linea_aprobada": row.get("linea_aprobada"),
                    "linea_disponible": row.get("linea_disponible"),
                },
                on_conflict="bodega_id,fecha",
            ).execute()
            saved += 1
        except Exception:
            pass
    return saved


async def run(
    *,
    test: Optional[str] = "real",
    dry_run: bool = False,
    **_kwargs,
) -> dict[str, Any]:
    if dry_run:
        from app.services.batch_jobs.preview import preview_score_bodegas

        preview = await preview_score_bodegas(test=test)
        return {
            "processed": preview["total"],
            "ok": preview["total"],
            "failed": 0,
            "errors": [],
            "details": preview,
        }
    result = run_bodega_scoring_batch(test=test, persist=not dry_run)
    rows = result.get("bodegas") or []
    historial = _persist_daily_scores(rows, dry_run=dry_run)

    processed = result.get("total", 0)
    ok = result.get("actualizadas", 0) if not dry_run else processed
    return {
        "processed": processed,
        "ok": ok,
        "failed": 0,
        "errors": [],
        "details": {
            "persistido_scoring": not dry_run,
            "historial_diario": historial,
            "resumen_grados": result.get("resumen_grados"),
            "fecha": date.today().isoformat(),
            "ejecutado_at": datetime.now(timezone.utc).isoformat(),
        },
    }
