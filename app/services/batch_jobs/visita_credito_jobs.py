"""Job batch: recordatorio visita crédito (plantilla Meta configurable)."""

from __future__ import annotations

from typing import Any, Optional

from app.services.visita_credito_recordatorios import (
    DEFAULT_TEMPLATE_CONFIG,
    list_visita_credito_preview_items,
    send_visita_credito_batch,
)


async def run_recordatorio_visita_credito(
    *,
    dry_run: bool = False,
    test: Optional[str] = None,
    selected_ids: Optional[list[str]] = None,
    template_config: Optional[dict[str, Any]] = None,
    custom_items: Optional[list[dict[str, Any]]] = None,
    bodega_ids: Optional[list[str]] = None,
    **_kwargs,
) -> dict[str, Any]:
    cfg = template_config or DEFAULT_TEMPLATE_CONFIG
    items = list_visita_credito_preview_items(
        bodega_ids=bodega_ids,
        custom_items=custom_items,
        template_config=cfg,
    )

    if test == "real":
        items = [i for i in items if not i.get("es_test")]
    elif test == "test":
        items = [i for i in items if i.get("es_test")]

    if dry_run:
        from app.services.batch_jobs.selection import filter_preview_items

        preview = {
            "job_id": "recordatorio_visita_credito",
            "total": len(items),
            "items": items,
            "template_config": cfg,
        }
        preview = filter_preview_items(preview, selected_ids)
        n = preview["total"]
        return {
            "processed": n,
            "ok": n,
            "failed": 0,
            "errors": [],
            "details": preview,
        }

    if selected_ids:
        items = [i for i in items if str(i.get("item_id")) in {str(x) for x in selected_ids}]

    result = await send_visita_credito_batch(
        items=items,
        selected_ids=None,
        template_config=cfg,
    )
    sent = int(result.get("sent") or 0)
    errs = result.get("errors") or []
    return {
        "processed": sent + len(errs) + int(result.get("skipped") or 0),
        "ok": sent,
        "failed": len(errs),
        "errors": errs,
        "details": result,
    }
