"""Servicios de integración: bodegas, preventas, pedidos."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.integration.franja import calcular_situacion
from app.services import db
from app.services.bodega_onboarding_snapshot import onboarding_alta_fields
from app.services.order_status import STATUS_FLOW, normalize_estado

logger = logging.getLogger("circa.integration")

_BODEGA_SELECT = (
    "id,external_id,telefono_whatsapp,dni_representante,ruc,razon_social,"
    "nombre_comercial,representante_legal,direccion_fiscal,distrito,estado,"
    "onboarding_fase,kyc_nivel,linea_aprobada,linea_disponible,distribuidor_id,"
    "solo_dni_sin_ruc,es_test,foto_dueno_url,foto_bodega_url,created_at,updated_at"
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
    out = {
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
        "tiene_foto_dueno": bool((row.get("foto_dueno_url") or "").strip()),
        "tiene_foto_bodega": bool((row.get("foto_bodega_url") or "").strip()),
        "es_test": bool(row.get("es_test")),
        "created": created,
    }
    out["situacion"] = calcular_situacion(out)
    return out


def data_mode_label(es_test: bool) -> str:
    return "test" if es_test else "prod"


def find_bodega(
    dist_id: str,
    *,
    bodega_id: str | None = None,
    external_id: str | None = None,
    telefono: str | None = None,
    ruc: str | None = None,
    dni: str | None = None,
    es_test: bool | None = None,
) -> dict | None:
    q = db.sb.table("bodegas").select(_BODEGA_SELECT).eq("distribuidor_id", dist_id)
    if es_test is not None:
        q = q.eq("es_test", es_test)
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


def _assert_bodega_mode(bodega: dict, es_test: bool) -> None:
    if bool(bodega.get("es_test")) != bool(es_test):
        modo = data_mode_label(es_test)
        raise HTTPException(
            status_code=404,
            detail=(
                f"Bodega no encontrada en modo '{modo}'. "
                "Use /api/v1/... para datos reales o /api/v1/test/... para pruebas."
            ),
        )


def _bodega_ids_modo(dist_id: str, es_test: bool) -> list[str]:
    rows = (
        db.sb.table("bodegas")
        .select("id")
        .eq("distribuidor_id", dist_id)
        .eq("es_test", es_test)
        .execute()
        .data
        or []
    )
    return [str(r["id"]) for r in rows if r.get("id")]


def upsert_bodega(dist: dict, body: dict, *, es_test: bool = False) -> dict:
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
        existing = find_bodega(dist_id, external_id=external_id, es_test=es_test)
    if not existing:
        existing = find_bodega(dist_id, telefono=tel, es_test=es_test)
    if not existing and ruc:
        existing = find_bodega(dist_id, ruc=ruc, es_test=es_test)
    if not existing and dni:
        existing = find_bodega(dist_id, dni=dni, es_test=es_test)

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
    if body.get("foto_dueno_url"):
        patch["foto_dueno_url"] = body["foto_dueno_url"]
    if body.get("foto_bodega_url"):
        patch["foto_bodega_url"] = body["foto_bodega_url"]

    # No tocar línea disponible en upsert de socio (regla: solo liberar al firmar contrato)
    patch = {k: v for k, v in patch.items() if v is not None}

    if existing:
        db.sb.table("bodegas").update(patch).eq("id", existing["id"]).execute()
        row = find_bodega(dist_id, bodega_id=existing["id"], es_test=es_test)
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
        "es_test": bool(es_test),
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
        row = find_bodega(dist_id, telefono=tel, es_test=es_test)
    if not row:
        raise HTTPException(status_code=500, detail="Bodega creada pero no se pudo leer")
    return _bodega_out(row, created=True)


def patch_bodega(dist: dict, bodega_id: str, body: dict, *, es_test: bool = False) -> dict:
    existing = find_bodega(dist["id"], bodega_id=bodega_id, es_test=es_test)
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
    row = find_bodega(dist["id"], bodega_id=bodega_id, es_test=es_test)
    return _bodega_out(row or existing, created=False)


def list_bodegas(
    dist: dict,
    *,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    es_test: bool = False,
) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    query = (
        db.sb.table("bodegas")
        .select(_BODEGA_SELECT)
        .eq("distribuidor_id", dist["id"])
        .eq("es_test", bool(es_test))
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
            or ql in (r.get("dni_representante") or "").lower()
            or ql in (r.get("ruc") or "").lower()
            or ql in (r.get("external_id") or "").lower()
            or ql in (r.get("telefono_whatsapp") or "").lower()
        ]
    items = [_bodega_out(r) for r in rows]
    if not items:
        situacion = "no_registrada"
    else:
        situacion = items[0].get("situacion") or calcular_situacion(items[0])
    return {"total": len(items), "items": items, "situacion": situacion}


def _resolve_bodega_for_preventa(dist: dict, body: dict, *, es_test: bool = False) -> dict:
    b = None
    if body.get("bodega_id"):
        b = find_bodega(dist["id"], bodega_id=body["bodega_id"], es_test=es_test)
    if not b and body.get("bodega_external_id"):
        b = find_bodega(dist["id"], external_id=body["bodega_external_id"], es_test=es_test)
    if not b and body.get("telefono_whatsapp"):
        b = find_bodega(dist["id"], telefono=body["telefono_whatsapp"], es_test=es_test)
    if not b:
        raise HTTPException(
            status_code=404,
            detail=(
                "Bodega no encontrada en este modo de datos. "
                "Envíe bodega_id, bodega_external_id o telefono_whatsapp "
                f"válidos para modo '{data_mode_label(es_test)}'."
            ),
        )
    _assert_bodega_mode(b, es_test)
    return b


def create_preventa(dist: dict, body: dict, *, es_test: bool = False) -> dict:
    bodega = _resolve_bodega_for_preventa(dist, body, es_test=es_test)

    estado_b = (bodega.get("estado") or "").strip().lower()
    try:
        linea_disp = float(bodega.get("linea_disponible") or 0)
    except (TypeError, ValueError):
        linea_disp = 0.0
    if estado_b != "activo" or linea_disp <= 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "La bodega no tiene línea disponible para financiar "
                f"(situacion esperada: con_linea; estado={bodega.get('estado')!r}, "
                f"linea_disponible={linea_disp})."
            ),
        )

    try:
        monto_fin = round(float(body["monto_a_financiar"]), 2)
        plazo = int(body["plazo_dias"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail="monto_a_financiar y plazo_dias son obligatorios",
        ) from e
    if monto_fin <= 0:
        raise HTTPException(status_code=400, detail="monto_a_financiar debe ser > 0")
    if plazo not in (7, 15, 30):
        raise HTTPException(status_code=400, detail="plazo_dias debe ser 7, 15 o 30")

    external_id = (body.get("external_id") or "").strip() or None
    if external_id:
        existing = (
            db.sb.table("pedidos")
            .select(
                "id,external_id,numero,bodega_id,estado,tipo_operacion,"
                "total_pedido,monto_financiado,plazo_dias,created_at,items_json"
            )
            .eq("distribuidor_id", dist["id"])
            .eq("external_id", external_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            # Solo reusar si la preventa pertenece a una bodega del mismo modo
            bid = existing[0].get("bodega_id")
            if bid and find_bodega(dist["id"], bodega_id=str(bid), es_test=es_test):
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
    total = round(total, 2)

    if monto_fin > total + 0.009:
        raise HTTPException(
            status_code=400,
            detail=f"monto_a_financiar ({monto_fin}) no puede superar el total de ítems ({total})",
        )
    if monto_fin > linea_disp + 0.009:
        raise HTTPException(
            status_code=409,
            detail=(
                f"monto_a_financiar ({monto_fin}) supera linea_disponible ({linea_disp})"
            ),
        )

    monto_contado = round(max(0.0, total - monto_fin), 2)

    payload = {
        "bodega_id": bodega["id"],
        "distribuidor_id": dist["id"],
        "estado": "preventa_confirmada",
        "tipo_operacion": "preventa",
        "origen": "preventa_socio_api_test" if es_test else "preventa_socio_api",
        "items_json": items,
        "total_pedido": total,
        "monto_productos": total,
        "monto_financiado": monto_fin,
        "monto_contado": monto_contado,
        "plazo_dias": plazo,
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
        for opt in ("notas", "vendedor_codigo", "origen", "external_id", "monto_productos", "monto_contado"):
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
        "plazo_dias": int(row["plazo_dias"]) if row.get("plazo_dias") is not None else None,
        "created_at": row.get("created_at"),
        "items": items,
    }


def get_pedido(dist: dict, pedido_id: str, *, es_test: bool = False) -> dict:
    rows = (
        db.sb.table("pedidos")
        .select("id,external_id,numero,bodega_id,estado,tipo_operacion,total_pedido,monto_financiado,plazo_dias,created_at,items_json,distribuidor_id")
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
    bid = ped.get("bodega_id")
    if not bid or not find_bodega(dist["id"], bodega_id=str(bid), es_test=es_test):
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return _pedido_out(ped)


def list_pedidos(
    dist: dict,
    *,
    estado: str | None = None,
    tipo: str | None = None,
    bodega_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    es_test: bool = False,
) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    if bodega_id:
        b = find_bodega(dist["id"], bodega_id=bodega_id, es_test=es_test)
        if not b:
            return {"total": 0, "items": []}
        allowed_ids = [bodega_id]
    else:
        allowed_ids = _bodega_ids_modo(dist["id"], es_test)
        if not allowed_ids:
            return {"total": 0, "items": []}

    q = (
        db.sb.table("pedidos")
        .select("id,external_id,numero,bodega_id,estado,tipo_operacion,total_pedido,monto_financiado,plazo_dias,created_at,items_json")
        .eq("distribuidor_id", dist["id"])
        .in_("bodega_id", allowed_ids)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if estado:
        q = q.eq("estado", estado)
    if tipo:
        q = q.eq("tipo_operacion", tipo)
    rows = q.execute().data or []
    return {"total": len(rows), "items": [_pedido_out(r) for r in rows]}


_PREVENTA_NEXT = {
    "preventa_confirmada": ["preventa_aceptada", "preventa_cancelada", "cancelado"],
    "preventa_aceptada": ["recibido", "en_preparacion", "preventa_cancelada", "cancelado"],
    "preventa_borrador": ["preventa_confirmada", "preventa_cancelada", "cancelado"],
}


def patch_pedido_estado(
    dist: dict,
    pedido_id: str,
    nuevo_estado: str,
    comentario: str | None = None,
    *,
    es_test: bool = False,
) -> dict:
    # Valida modo vía get_pedido
    get_pedido(dist, pedido_id, es_test=es_test)

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
    return get_pedido(dist, pedido_id, es_test=es_test)
