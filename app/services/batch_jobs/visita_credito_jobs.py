"""Job batch: recordatorio visita crédito (plantilla Meta configurable)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.visita_credito_recordatorios import (
    DEFAULT_TEMPLATE_CONFIG,
    build_items_for_send,
    list_visita_credito_preview_items,
    send_visita_credito_batch,
)

logger = logging.getLogger("circa.visita_credito_batch")


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
    send_log: list[str] = []

    logger.info(
        "visita_credito job inicio dry_run=%s test=%s custom_items=%s selected_ids=%s",
        dry_run,
        test,
        len(custom_items or []),
        len(selected_ids or []) if selected_ids else 0,
    )

    if custom_items is not None:
        items = build_items_for_send(custom_items, template_config=cfg)
        send_log.append(f"build_items_for_send: {len(items)} desde {len(custom_items)} payload(s)")
    else:
        items = list_visita_credito_preview_items(
            bodega_ids=bodega_ids,
            template_config=cfg,
        )
        send_log.append(f"list_visita_credito_preview_items: {len(items)} item(s)")

    before_test = len(items)
    if test == "real":
        items = [i for i in items if not i.get("es_test")]
    elif test == "test":
        items = [i for i in items if i.get("es_test")]
    if before_test != len(items):
        msg = f"test_filter={test}: {before_test} -> {len(items)} item(s)"
        send_log.append(msg)
        logger.info("visita_credito %s", msg)
        if not items and before_test:
            warn = (
                f"Ningún destinatario pasó filtro '{test}'. "
                "Prueba modo prueba/test si son bodegas es_test."
            )
            send_log.append(warn)
            logger.warning("visita_credito %s", warn)

    if dry_run:
        from app.services.batch_jobs.selection import filter_preview_items

        preview = {
            "job_id": "recordatorio_visita_credito",
            "total": len(items),
            "items": items,
            "template_config": cfg,
            "send_log": send_log,
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
        allowed = {str(x) for x in selected_ids}
        before_sel = len(items)
        built_ids_sample = [str(i.get("item_id")) for i in items[:5]]
        items = [i for i in items if str(i.get("item_id")) in allowed]
        msg = f"selected_ids: {before_sel} -> {len(items)} coincidencia(s)"
        send_log.append(msg)
        logger.info("visita_credito %s (ids solicitados=%s)", msg, list(allowed)[:5])
        if before_sel and not items:
            warn = (
                f"Ningún item_id coincide con selected_ids. "
                f"selected={list(allowed)[:3]} built={built_ids_sample}"
            )
            send_log.append(warn)
            logger.warning("visita_credito %s", warn)

    if not items:
        send_log.append("Sin destinatarios para enviar tras filtros")
        logger.warning("visita_credito sin destinatarios para enviar")

    result = await send_visita_credito_batch(
        items=items,
        selected_ids=None,
        template_config=cfg,
    )
    send_log.extend(result.get("send_log") or [])
    sent = int(result.get("sent") or 0)
    errs = result.get("errors") or []
    return {
        "processed": sent + len(errs) + int(result.get("skipped") or 0),
        "ok": sent,
        "failed": len(errs),
        "errors": errs,
        "details": {**result, "send_log": send_log},
    }
