"""Servicios de integración: bodegas, preventas, pedidos."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.services import db
from app.services.bodega_onboarding_snapshot import onboarding_alta_fields
from app.services.order_status import STATUS_FLOW, normalize_estado

logger = logging.getLogger("circa.integration")

_BODEGA_SELECT = (
    "id,external_id,telefono_whatsapp,dni_representante,ruc,razon_social,"
    "nombre_comercial,representante_legal,direccion_fiscal,distrito,estado,"
    "onboarding_fase,kyc_nivel,linea_aprobada,linea_disponible,distribuidor_id,"
    "solo_dni_sin_ruc,created_at,updated_at"
)


def normalizar_telefono(tel: str) -> str:
    t = re.sub(r"[^\d+]", "", (tel or "").strip())
    if t.startswith("+51") and len(re.sub(r"\D", "", t)) >= 11:
        return "+51" + re.sub(r"\D", "", t)[-9:]
    digits = re.sub(r"\D", "", t)
    if len(digits) == 9 and digits.startswith("9"):
        return "+51" + digits
    if len(digits) == 11 and digits.startswith("51"):
        return "+" + digits
    raise HTTPException(status_code=400, detail="telefono_whatsapp inválido (Perú, 9 dígitos)")


def _bodega_out(row: dict, *, created: bool = False) -> dict:
    return {
        "id": row["id"],
        "external_id": row.get("external_id"),
        "telefono_whatsapp": row.get("telefono_whatsapp"),
        "dni_representante": row.get("dni_representante"),
        "ruc": row.get("ruc"),
        "razon_social": row.get("razon_social"),
        "nombre_comercial": row.get("nombre_comercial"),
        "estado": row.get("estado"),
        "onboarding_fase": row.get("onboarding_fase"),
        "kyc_nivel": row.get("kyc_nivel"),
        "linea_aprobada": float(row["linea_aprobada"]) if row.get("linea_aprobada") is not None else None,
        "linea_disponible": float(row["linea_disponible"]) if row.get("linea_disponible") is not None else None,
        "created": created,
    }


def find_bodega(dist_id: str, *, bodega_id: str | None = None, external_id: str | None = None,
                telefono: str | None = None, ruc: str | None = None,
                dni: str | None = None) -> dict | None:
    q = db.sb.table("bodegas").select(_BODEGA_SELECT).eq("distribuidor_id", dist_id)
    if bodega_id:
        rows = q.eq("id", bodega_id).limit(1).execute().data or []
        return rows[0] if rows else None
    if external_id:
        rows = q.eq("external_id", external_id).limit(1).execute().data or []
        return rows[0] if rows else None
    if telefono:
        tel = normalizar_telefono(telefono)
        rows = q.eq("telefono_whatsapp", tel).limit(1).execute().data or []
        return rows[0] if rows else None
    if ruc:
        rows = q.eq("ruc", re.sub(r"\D", "", ruc)).limit(1).execute().data or []
        return rows[0] if rows else None
    if dni:
        rows = q.eq("dni_representante", re.sub(r"\D", "", dni)).limit(1).execute().data or []
        return rows[0] if rows else None
    return None


def upsert_bodega(dist: dict, body: dict) -> dict:
    dist_id = dist["id"]
    tel = normalizar_telefono(body["telefono_whatsapp"])
    external_id = (body.get("external_id") or "").strip() or None
    dni = re.sub(r"\D", "", body.get("dni_representante") or "") or None
    ruc = re.sub(r"\D", "", body.get("ruc") or "") or None

    if dni and len(dni) not in (8, 9):
        raise HTTPException(status_code=400, detail="dni_representante debe tener 8 (DNI) o 9 (CE) dígitos")
    if ruc and len(ruc) != 11:
        raise HTTPException(status_code=400, detail="ruc debe tener 11 dígitos")

    existing = None
    if external_id:
        existing = find_bodega(dist_id, external_id=external_id)
    if not existing:
        existing = find_bodega(dist_id, telefono=tel)
    if not existing and ruc:
        existing = find_bodega(dist_id, ruc=ruc)
    if not existing and dni:
        existing = find_bodega(dist_id, dni=dni)

    razon = (body.get("razon_social") or body.get("nombre_comercial") or "").strip()
    if not razon and dni:
        razon = f"PENDIENTE VERIFICAR - DOC {dni}"
    if not razon:
        razon = "BODEGA SIN NOMBRE"

    patch = {
        "telefono_whatsapp": tel,
        "razon_social": razon,
        "nombre_comercial": (body.get("nombre_comercial") or razon).strip(),
        "representante_legal": body.get("representante_legal") or razon,
        "direccion_fiscal": body.get("direccion_fiscal"),
        "distrito": body.get("distrito"),
        "solo_dni_sin_ruc": bool(body.get("solo_dni_sin_ruc", True if not ruc else False)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if dni:
        patch["dni_representante"] = dni
    if ruc:
        patch["ruc"] = ruc
        patch["solo_dni_sin_ruc"] = False
    if external_id:
        patch["external_id"] = external_id

    # No tocar línea disponible en upsert de socio (regla: solo liberar al firmar contrato)
    patch = {k: v for k, v in patch.items() if v is not None}

    if existing:
        db.sb.table("bodegas").update(patch).eq("id", existing["id"]).execute()
        row = find_bodega(dist_id, bodega_id=existing["id"])
        return _bodega_out(row or existing, created=False)

    linea_aprobada = 200.0  # provisional; el modelo puede ajustar después
    insert = {
        **patch,
        "distribuidor_id": dist_id,
        "estado": "inactivo",
        "onboarding_fase": "precargada",
        "kyc_nivel": "ninguno",
        "linea_aprobada": linea_aprobada,
        "linea_disponible": 0,  # nunca liberar en precarga
        "es_test": False,
        "en_piloto": True,
        **onboarding_alta_fields(linea_aprobada),
    }
    try:
        res = db.sb.table("bodegas").insert(insert).execute()
    except Exception as e:
        logger.error("upsert_bodega insert failed: %s", e)
        raise HTTPException(status_code=500, detail=f"No se pudo crear bodega: {e}") from e

    row = (res.data or [None])[0]
    if not row:
        row = find_bodega(dist_id, telefono=tel)
    if not row:
        raise HTTPException(status_code=500, detail="Bodega creada pero no se pudo leer")
    return _bodega_out(row, created=True)


def patch_bodega(dist: dict, bodega_id: str, body: dict) -> dict:
    existing = find_bodega(dist["id"], bodega_id=bodega_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Bodega no encontrada")
    updates: dict[str, Any] = {}
    if body.get("telefono_whatsapp"):
        updates["telefono_whatsapp"] = normalizar_telefono(body["telefono_whatsapp"])
    for k in ("razon_social", "nombre_comercial", "representante_legal", "direccion_fiscal", "distrito", "external_id"):
        if body.get(k) is not None:
            updates[k] = body[k]
    if not updates:
        raise HTTPException(status_code=400, detail="Sin campos para actualizar")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.sb.table("bodegas").update(updates).eq("id", bodega_id).execute()
    row = find_bodega(dist["id"], bodega_id=bodega_id)
    return _bodega_out(row or existing, created=False)


def list_bodegas(dist: dict, *, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    query = (
        db.sb.table("bodegas")
        .select(_BODEGA_SELECT)
        .eq("distribuidor_id", dist["id"])
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    rows = query.execute().data or []
    if q:
        ql = q.lower().strip()
        rows = [
            r for r in rows
            if ql in (r.get("razon_social") or "").lower()
            or ql in (r.get("nombre_comercial") or "").lower()
            or ql in (r.get("dni_representante") or "")
            or ql in (r.get("ruc") or "")
            or ql in (r.get("external_id") or "")
            or ql in (r.get("telefono_whatsapp") or "")
        ]
    return {"total": len(rows), "items": [_bodega_out(r) for r in rows]}


def _resolve_bodega_for_preventa(dist: dict, body: dict) -> dict:
    b = None
    if body.get("bodega_id"):
        b = find_bodega(dist["id"], bodega_id=body["bodega_id"])
    if not b and body.get("bodega_external_id"):
        b = find_bodega(dist["id"], external_id=body["bodega_external_id"])
    if not b and body.get("telefono_whatsapp"):
        b = find_bodega(dist["id"], telefono=body["telefono_whatsapp"])
    if not b:
        raise HTTPException(
            status_code=404,
            detail="Bodega no encontrada. Envíe bodega_id, bodega_external_id o telefono_whatsapp.",
            # code used by clients
        )
    return b


def create_preventa(dist: dict, body: dict) -> dict:
    bodega = _resolve_bodega_for_preventa(dist, body)
    external_id = (body.get("external_id") or "").strip() or None
    if external_id:
        existing = (
            db.sb.table("pedidos")
            .select("id,external_id,numero,bodega_id,estado,tipo_operacion,total_pedido,monto_financiado,created_at,items_json")
            .eq("distribuidor_id", dist["id"])
            .eq("external_id", external_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            return _pedido_out(existing[0])

    items = []
    total = 0.0
    for it in body["items"]:
        cant = float(it["cantidad"])
        pu = float(it["precio_unitario"])
        sub = round(cant * pu, 2)
        total += sub
        items.append({
            "sku": it.get("sku"),
            "nombre": it["nombre"],
            "cantidad": cant,
            "precio_unitario": pu,
            "precio": pu,
            "subtotal": sub,
            "unidad": it.get("unidad") or "UND",
        })

    payload = {
        "bodega_id": bodega["id"],
        "distribuidor_id": dist["id"],
        "estado": "preventa_confirmada",
        "tipo_operacion": "preventa",
        "origen": "preventa_socio_api",
        "items_json": items,
        "total_pedido": round(total, 2),
        "monto_financiado": 0,
        "external_id": external_id,
    }
    if body.get("notas"):
        payload["notas"] = body["notas"]
    if body.get("vendedor_codigo"):
        payload["vendedor_codigo"] = body["vendedor_codigo"]

    try:
        res = db.sb.table("pedidos").insert(payload).execute()
    except Exception as e:
        # columnas opcionales
        for opt in ("notas", "vendedor_codigo", "origen", "external_id"):
            if opt in str(e).lower() or opt in str(e):
                payload.pop(opt, None)
        try:
            res = db.sb.table("pedidos").insert(payload).execute()
        except Exception as e2:
            logger.error("create_preventa failed: %s", e2)
            raise HTTPException(status_code=500, detail=f"No se pudo crear preventa: {e2}") from e2

    row = (res.data or [None])[0]
    if not row:
        raise HTTPException(status_code=500, detail="Preventa creada pero no se pudo leer")
    return _pedido_out(row)


def _pedido_out(row: dict) -> dict:
    items = row.get("items_json")
    if isinstance(items, str):
        import json
        try:
            items = json.loads(items)
        except Exception:
            items = []
    return {
        "id": row["id"],
        "external_id": row.get("external_id"),
        "numero": row.get("numero"),
        "bodega_id": row.get("bodega_id"),
        "estado": row.get("estado"),
        "tipo_operacion": row.get("tipo_operacion"),
        "total_pedido": float(row["total_pedido"]) if row.get("total_pedido") is not None else None,
        "monto_financiado": float(row["monto_financiado"]) if row.get("monto_financiado") is not None else None,
        "created_at": row.get("created_at"),
        "items": items,
    }


def get_pedido(dist: dict, pedido_id: str) -> dict:
    rows = (
        db.sb.table("pedidos")
        .select("id,external_id,numero,bodega_id,estado,tipo_operacion,total_pedido,monto_financiado,created_at,items_json,distribuidor_id")
        .eq("id", pedido_id)
        .eq("distribuidor_id", dist["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return _pedido_out(rows[0])


def list_pedidos(
    dist: dict,
    *,
    estado: str | None = None,
    tipo: str | None = None,
    bodega_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    q = (
        db.sb.table("pedidos")
        .select("id,external_id,numero,bodega_id,estado,tipo_operacion,total_pedido,monto_financiado,created_at,items_json")
        .eq("distribuidor_id", dist["id"])
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if estado:
        q = q.eq("estado", estado)
    if tipo:
        q = q.eq("tipo_operacion", tipo)
    if bodega_id:
        q = q.eq("bodega_id", bodega_id)
    rows = q.execute().data or []
    return {"total": len(rows), "items": [_pedido_out(r) for r in rows]}


_PREVENTA_NEXT = {
    "preventa_confirmada": ["preventa_aceptada", "preventa_cancelada", "cancelado"],
    "preventa_aceptada": ["recibido", "en_preparacion", "preventa_cancelada", "cancelado"],
    "preventa_borrador": ["preventa_confirmada", "preventa_cancelada", "cancelado"],
}


def patch_pedido_estado(dist: dict, pedido_id: str, nuevo_estado: str, comentario: str | None = None) -> dict:
    rows = (
        db.sb.table("pedidos")
        .select("*")
        .eq("id", pedido_id)
        .eq("distribuidor_id", dist["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    ped = rows[0]
    actual = normalize_estado(ped.get("estado") or "")
    nuevo = normalize_estado(nuevo_estado)

    allowed = list(_PREVENTA_NEXT.get(actual, []))
    # flujo venta normal
    nxt = STATUS_FLOW.get(actual)
    if nxt:
        allowed.append(nxt)
    # permitir estados del portal
    if actual in ("confirmado", "recibido", "en_preparacion", "despachado", "en_camino"):
        from app.services.order_status import VALID_TRANSITIONS
        allowed.extend(VALID_TRANSITIONS.get(actual, []))

    allowed = list({normalize_estado(a) for a in allowed})
    if nuevo not in allowed and nuevo != actual:
        raise HTTPException(
            status_code=400,
            detail=f"Transición no permitida: {actual} → {nuevo}. Permitidos: {allowed}",
        )

    upd = {"estado": nuevo, "updated_at": datetime.now(timezone.utc).isoformat()}
    db.sb.table("pedidos").update(upd).eq("id", pedido_id).execute()
    return get_pedido(dist, pedido_id)
