"""Vista previa de procesos batch (sin ejecutar ni persistir)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.services import db
from app.services.bodega_scoring_batch import run_bodega_scoring_batch
from app.services.batch_jobs.registry import JOBS_BY_ID

_PREVIEW_LIMIT = 500


def _filter_es_test(items: list[dict[str, Any]], test: Optional[str]) -> list[dict[str, Any]]:
    if not test:
        return items
    if test == "real":
        return [i for i in items if not i.get("es_test")]
    if test == "test":
        return [i for i in items if i.get("es_test")]
    return items


def _wrap(job_id: str, items: list[dict[str, Any]], *, test: Optional[str], note: str = "") -> dict[str, Any]:
    job = JOBS_BY_ID[job_id]
    total = len(items)
    truncated = total > _PREVIEW_LIMIT
    shown = items[:_PREVIEW_LIMIT]
    wa_count = sum(1 for i in shown if i.get("telefono"))
    return {
        "job_id": job_id,
        "nombre": job.nombre,
        "test_filter": test,
        "afecta_whatsapp": job.afecta_whatsapp,
        "total": total,
        "mostrando": len(shown),
        "truncated": truncated,
        "con_telefono": wa_count,
        "note": note,
        "items": shown,
    }


async def preview_score_bodegas(*, test: Optional[str] = "real") -> dict[str, Any]:
    result = run_bodega_scoring_batch(test=test, persist=False)
    items = []
    for r in result.get("bodegas") or []:
        prev = r.get("scoring_anterior")
        prev_txt = f"{int(prev)}" if prev is not None else "—"
        items.append({
            "bodega_id": r.get("bodega_id"),
            "bodega_nombre": r.get("nombre"),
            "telefono": r.get("telefono_whatsapp"),
            "es_test": bool(r.get("es_test")),
            "detalle": (
                f"Score {r.get('score')} ({r.get('grade')}) · "
                f"BD {prev_txt} · Línea S/{float(r.get('linea_disponible') or 0):.0f}"
            ),
            "score": r.get("score"),
            "grade": r.get("grade"),
            "accion": "Guardar score en bodegas.scoring + snapshot diario",
        })
    note = (
        f"Modo {'pruebas' if test == 'test' else 'reales' if test == 'real' else 'todos'}: "
        f"se recalcularía el score de {len(items)} bodega(s)."
    )
    return _wrap("score_bodegas_diario", items, test=test, note=note)


async def preview_recordatorios(*, test: Optional[str] = None) -> dict[str, Any]:
    hoy = date.today().isoformat()
    reminders = (
        db.sb.table("recordatorios")
        .select(
            "id, pedido_id, tipo, fecha_envio, "
            "pedidos(numero, bodega_id, bodegas(telefono_whatsapp, nombre_comercial, es_test))"
        )
        .eq("enviado", False)
        .lte("fecha_envio", hoy)
        .execute()
        .data
        or []
    )
    items: list[dict[str, Any]] = []
    for rem in reminders:
        pedido = rem.get("pedidos") or {}
        bodega = pedido.get("bodegas") or {}
        telefono = bodega.get("telefono_whatsapp") or ""
        fin_rows = (
            db.sb.table("financiamientos")
            .select("monto_total, fecha_vencimiento, estado")
            .eq("pedido_id", rem["pedido_id"])
            .in_("estado", ["activo", "vencido"])
            .limit(1)
            .execute()
            .data
            or []
        )
        if not fin_rows:
            continue
        fin = fin_rows[0]
        if not telefono:
            detalle = f"Pedido {pedido.get('numero', '')} · {rem.get('tipo', '')} — sin teléfono WA"
        else:
            venc = datetime.strptime(fin["fecha_vencimiento"], "%Y-%m-%d").date()
            dias = (venc - date.today()).days
            detalle = (
                f"Pedido {pedido.get('numero', '')} · {rem.get('tipo', '')} · "
                f"S/{float(fin['monto_total']):.2f} · vence en {dias}d"
            )
        items.append({
            "bodega_id": pedido.get("bodega_id"),
            "bodega_nombre": bodega.get("nombre_comercial") or "—",
            "telefono": telefono or None,
            "es_test": bool(bodega.get("es_test")),
            "detalle": detalle,
            "accion": "Enviar recordatorio WhatsApp" if telefono else "Omitido (sin teléfono)",
        })
    items = _filter_es_test(items, test)
    note = f"Recordatorios pendientes con fecha ≤ hoy: {len(items)} destinatario(s) potencial(es)."
    if test:
        note += f" Filtro: solo bodegas {'de prueba' if test == 'test' else 'reales'}."
    return _wrap("recordatorios_cobranza", items, test=test, note=note)


async def preview_marcar_vencidos(*, test: Optional[str] = None) -> dict[str, Any]:
    hoy = date.today().isoformat()
    overdue = (
        db.sb.table("financiamientos")
        .select(
            "id, bodega_id, monto_total, fecha_vencimiento, "
            "pedidos(numero), bodegas(telefono_whatsapp, nombre_comercial, es_test)"
        )
        .eq("estado", "activo")
        .lt("fecha_vencimiento", hoy)
        .execute()
        .data
        or []
    )
    items = []
    for fin in overdue:
        b = fin.get("bodegas") or {}
        items.append({
            "bodega_id": fin.get("bodega_id"),
            "bodega_nombre": b.get("nombre_comercial") or "—",
            "telefono": b.get("telefono_whatsapp"),
            "es_test": bool(b.get("es_test")),
            "detalle": (
                f"Pedido {(fin.get('pedidos') or {}).get('numero', '')} · "
                f"S/{float(fin.get('monto_total') or 0):.2f} · venció {fin.get('fecha_vencimiento')}"
            ),
            "accion": "Cambiar financiamiento activo → vencido",
        })
    items = _filter_es_test(items, test)
    note = f"Financiamientos activos con fecha vencida: {len(items)}."
    if test:
        note += f" Filtro: solo bodegas {'de prueba' if test == 'test' else 'reales'}."
    return _wrap("marcar_vencidos", items, test=test, note=note)


async def preview_placeholder(job_id: str, *, test: Optional[str] = None) -> dict[str, Any]:
    job = JOBS_BY_ID[job_id]
    return _wrap(
        job_id,
        [],
        test=test,
        note=f"{job.nombre}: implementación pendiente; no hay destinatarios simulados aún.",
    )


_HANDLERS = {
    "score_bodegas_diario": preview_score_bodegas,
    "recordatorios_cobranza": preview_recordatorios,
    "marcar_vencidos": preview_marcar_vencidos,
    "onboarding_abandonado": lambda **kw: preview_placeholder("onboarding_abandonado", **kw),
    "reactivacion_inactivos": lambda **kw: preview_placeholder("reactivacion_inactivos", **kw),
}


async def build_preview(job_id: str, *, test: Optional[str] = "real") -> dict[str, Any]:
    job = JOBS_BY_ID.get(job_id)
    if not job:
        raise ValueError(f"Job desconocido: {job_id}")
    if not job.permite_dry_run:
        raise ValueError(f"El job {job_id} no admite vista previa")
    handler = _HANDLERS.get(job_id)
    if not handler:
        raise ValueError(f"Sin vista previa para {job_id}")
    effective_test = test if job.soporta_test_filter else test
    return await handler(test=effective_test)
