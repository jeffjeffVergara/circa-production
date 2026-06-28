"""Jobs batch de cobranza (recordatorios, vencidos)."""

from __future__ import annotations

from typing import Any, Optional

from app.services.cobranza import check_overdue_loans, send_pending_reminders


async def run_recordatorios(
    *,
    dry_run: bool = False,
    test: Optional[str] = None,
    **_kwargs,
) -> dict[str, Any]:
    if dry_run:
        from app.services.batch_jobs.preview import preview_recordatorios

        preview = await preview_recordatorios(test=test)
        return {
            "processed": preview["total"],
            "ok": preview["total"],
            "failed": 0,
            "errors": [],
            "details": preview,
        }
    count = await send_pending_reminders()
    return {
        "processed": count,
        "ok": count,
        "failed": 0,
        "errors": [],
        "details": {"reminders_sent": count},
    }


async def run_marcar_vencidos(
    *,
    dry_run: bool = False,
    test: Optional[str] = None,
    **_kwargs,
) -> dict[str, Any]:
    if dry_run:
        from app.services.batch_jobs.preview import preview_marcar_vencidos

        preview = await preview_marcar_vencidos(test=test)
        return {
            "processed": preview["total"],
            "ok": preview["total"],
            "failed": 0,
            "errors": [],
            "details": preview,
        }
    overdue = await check_overdue_loans()
    n = len(overdue)
    return {
        "processed": n,
        "ok": n,
        "failed": 0,
        "errors": [],
        "details": {"overdue_marked": n, "items": overdue[:20]},
    }
