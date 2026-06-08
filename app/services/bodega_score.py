"""Score operativo de bodega (0–100) para backoffice."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_ts(val: Any) -> datetime:
    if isinstance(val, datetime):
        dt = val
    else:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_bodega_score(
    *,
    bodega: dict[str, Any],
    features: dict[str, Any],
    stats: dict[str, Any],
    pedidos: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combina features SQL, pedidos y línea de crédito en un score 0–100."""
    now = datetime.now(timezone.utc)
    financiados = [
        p for p in pedidos
        if float(p.get("monto_financiado") or 0) > 0
        and p.get("estado") not in ("rechazado", "preventa_cancelada")
    ]
    pagados = sum(1 for p in financiados if p.get("estado") == "pagado")
    vencidos = 0
    for p in financiados:
        if p.get("estado") == "pagado":
            continue
        fv = p.get("fecha_vencimiento")
        if not fv:
            continue
        try:
            if _parse_ts(fv) < now:
                vencidos += 1
        except Exception:
            continue

    total_cob = pagados + vencidos
    if total_cob == 0:
        pagos_score = 72
    else:
        pagos_score = round(100 * pagados / total_cob)

    freq = int(features.get("frecuencia_compra") or stats.get("total_pedidos") or 0)
    dias = features.get("dias_desde_ultima_compra")
    freq_score = min(100, freq * 12)
    if dias is None:
        recency_score = 45
    elif dias <= 14:
        recency_score = 100
    elif dias <= 45:
        recency_score = 78
    elif dias <= 90:
        recency_score = 52
    else:
        recency_score = 28
    actividad_score = round(freq_score * 0.55 + recency_score * 0.45)

    inb = int(features.get("mensajes_inbound") or 0)
    outb = int(features.get("mensajes_outbound") or 0)
    if inb == 0 and outb == 0:
        eng_score = 50
    elif outb == 0:
        eng_score = 65
    else:
        ratio = min(2.0, inb / outb)
        eng_score = round(min(100, 50 + ratio * 25))

    aprob = float(bodega.get("linea_aprobada") or 0)
    disp = float(bodega.get("linea_disponible") or 0)
    if aprob <= 0:
        credit_score = 75
    elif disp < 0:
        credit_score = max(15, round(40 + (disp / aprob) * 40))
    else:
        uso = 1 - (disp / aprob) if aprob else 0
        credit_score = round(68 + min(32, max(0, uso) * 35))

    total = round(
        pagos_score * 0.40
        + actividad_score * 0.30
        + eng_score * 0.15
        + credit_score * 0.15
    )
    total = max(0, min(100, total))

    if total >= 85:
        grade, label = "A", "Excelente"
    elif total >= 70:
        grade, label = "B", "Bueno"
    elif total >= 55:
        grade, label = "C", "Regular"
    else:
        grade, label = "D", "En riesgo"

    return {
        "score": total,
        "grade": grade,
        "label": label,
        "breakdown": {
            "pagos": pagos_score,
            "actividad": actividad_score,
            "engagement": eng_score,
            "credito": credit_score,
        },
        "metrics": {
            "pedidos_pagados": pagados,
            "pedidos_vencidos": vencidos,
            "frecuencia_compra": freq,
            "dias_desde_ultima_compra": dias,
            "ticket_promedio": float(features.get("ticket_promedio") or 0),
            "usa_credito": bool(features.get("usa_credito")),
            "mensajes_inbound": inb,
            "mensajes_outbound": outb,
        },
    }
