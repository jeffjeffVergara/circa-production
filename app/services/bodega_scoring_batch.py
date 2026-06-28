"""Ejecución batch del modelo de score operativo de bodegas."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import db
from app.services.bodega_score import compute_bodega_score

logger = logging.getLogger("circa.bodega_scoring_batch")

_PEDIDO_SELECT = "bodega_id, estado, monto_financiado, fecha_vencimiento, created_at"
_CHUNK = 50


def _chunked(ids: list[str]) -> list[list[str]]:
    return [ids[i : i + _CHUNK] for i in range(0, len(ids), _CHUNK)]


def _fetch_bodegas(test: Optional[str]) -> list[dict[str, Any]]:
    q = db.sb.table("bodegas").select(
        "id, razon_social, nombre_comercial, representante_legal, telefono_whatsapp,"
        "estado, es_test, linea_aprobada, linea_disponible, scoring, scoring_alta, linea_alta, distrito"
    )
    if test == "real":
        q = q.eq("es_test", False)
    elif test == "test":
        q = q.eq("es_test", True)
    return q.order("nombre_comercial").limit(2000).execute().data or []


def _fetch_features(bodega_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunked(bodega_ids):
        rows = (
            db.sb.table("bodega_features_v1")
            .select("*")
            .in_("bodega_id", chunk)
            .limit(_CHUNK)
            .execute()
            .data
            or []
        )
        for row in rows:
            out[row["bodega_id"]] = row
    return out


def _fetch_pedidos(bodega_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {bid: [] for bid in bodega_ids}
    for chunk in _chunked(bodega_ids):
        rows = (
            db.sb.table("pedidos")
            .select(_PEDIDO_SELECT)
            .in_("bodega_id", chunk)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
            .data
            or []
        )
        for row in rows:
            bid = row.get("bodega_id")
            if bid in out:
                out[bid].append(row)
    return out


def _stats_from_pedidos(pedidos: list[dict[str, Any]]) -> dict[str, Any]:
    pagados = sum(1 for p in pedidos if p.get("estado") == "pagado")
    return {"total_pedidos": len(pedidos), "pedidos_pagados": pagados}


def _persist_scores(rows: list[dict[str, Any]]) -> int:
    updated = 0
    for row in rows:
        try:
            db.sb.table("bodegas").update({
                "scoring": row["score"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", row["bodega_id"]).execute()
            updated += 1
        except Exception as exc:
            logger.warning("No se pudo guardar scoring bodega %s: %s", row.get("bodega_id"), exc)
    return updated


def run_bodega_scoring_batch(
    *,
    test: Optional[str] = "real",
    persist: bool = False,
    bodega_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Calcula score 0–100 para cada bodega (modelo operativo en bodega_score.py).
    Si persist=True, escribe el resultado en bodegas.scoring.
    """
    bodegas = _fetch_bodegas(test)
    if bodega_ids:
        allowed = {str(x) for x in bodega_ids}
        bodegas = [b for b in bodegas if str(b.get("id")) in allowed]
    if not bodegas:
        return {
            "modelo": "circa_operativo_v1",
            "modelo_descripcion": "Pagos 40%, actividad 30%, WhatsApp 15%, crédito 15%",
            "ejecutado_at": datetime.now(timezone.utc).isoformat(),
            "persistido": False,
            "total": 0,
            "actualizadas": 0,
            "resumen_grados": {"A": 0, "B": 0, "C": 0, "D": 0},
            "bodegas": [],
        }

    ids = [b["id"] for b in bodegas]
    features_map = _fetch_features(ids)
    pedidos_map = _fetch_pedidos(ids)

    results: list[dict[str, Any]] = []
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}

    for b in bodegas:
        bid = b["id"]
        pedidos = pedidos_map.get(bid) or []
        features = features_map.get(bid) or {"bodega_id": bid}
        score_payload = compute_bodega_score(
            bodega=b,
            features=features,
            stats=_stats_from_pedidos(pedidos),
            pedidos=pedidos,
        )
        grade = score_payload.get("grade") or "D"
        if grade in grade_counts:
            grade_counts[grade] += 1

        nombre = (
            b.get("nombre_comercial")
            or b.get("razon_social")
            or b.get("representante_legal")
            or "?"
        )
        linea_alta = b.get("linea_alta")
        scoring_alta = b.get("scoring_alta")
        score_hoy = score_payload["score"]

        results.append({
            "bodega_id": bid,
            "nombre": nombre,
            "telefono_whatsapp": b.get("telefono_whatsapp"),
            "estado": b.get("estado"),
            "es_test": b.get("es_test"),
            "distrito": b.get("distrito"),
            "linea_aprobada": float(b.get("linea_aprobada") or 0),
            "linea_disponible": float(b.get("linea_disponible") or 0),
            "linea_alta": float(linea_alta) if linea_alta is not None else None,
            "scoring_alta": int(float(scoring_alta)) if scoring_alta is not None else None,
            "scoring_anterior": float(b.get("scoring") or 0) if b.get("scoring") is not None else None,
            "score": score_hoy,
            "grade": grade,
            "label": score_payload.get("label"),
            "breakdown": score_payload.get("breakdown") or {},
            "metrics": score_payload.get("metrics") or {},
        })

    results.sort(key=lambda r: (-r["score"], r["nombre"]))

    actualizadas = _persist_scores(results) if persist else 0

    return {
        "modelo": "circa_operativo_v1",
        "modelo_descripcion": "Pagos 40%, actividad 30%, WhatsApp 15%, crédito 15%",
        "ejecutado_at": datetime.now(timezone.utc).isoformat(),
        "persistido": bool(persist),
        "actualizadas": actualizadas,
        "total": len(results),
        "resumen_grados": grade_counts,
        "bodegas": results,
    }
