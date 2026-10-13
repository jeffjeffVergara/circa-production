"""Entrantes: pedido del distribuidor antes del flujo de pre-venta."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.integration.service import data_mode_label, find_bodega, normalizar_telefono
from app.services import db
from app.services.preventa_excel import match_bodega_por_nombre

LIMA = ZoneInfo("America/Lima")
_FRAC = re.compile(r"\.(\d+)")

_SELECT = (
    "id,distribuidor_id,es_test,external_id,bodega_nombre,fecha,items,"
    "total_pedido,descuento_prorrateado,monto_productos,bodega_id,match_score,"
    "candidatos,existe_en_circa,bodega_activa,monto_credito,pago_confirmado,"
    "estado,created_at,updated_at"
)


def estado_entrante(
    *,
    bodega_id: str | None,
    monto_credito: float | None,
    pago_confirmado: bool,
    descartada: bool = False,
) -> str:
    if descartada:
        return "descartada"
    if not bodega_id:
        return "sin_match"
    if monto_credito is None or float(monto_credito) <= 0:
        return "pendiente_monto"
    if not pago_confirmado:
        return "pendiente_pago"
    return "lista"


def _es_regalo(descripcion: str, total: float, marca: bool = False) -> bool:
    return bool(marca) or total == 0 or descripcion.upper().startswith("BONIFICAC")


def _item_es_regalo(it: dict) -> bool:
    if it.get("es_regalo"):
        return True
    desc = str(it.get("descripcion") or it.get("nombre") or "")
    charged = it.get("total")
    if charged is None:
        charged = it.get("subtotal") if it.get("subtotal") is not None else 0
    return _es_regalo(desc, float(charged or 0))


def totales_items(items: list[dict]) -> tuple[float, float, float]:
    """Total cobrado, descuento y monto antes de descuento. Los regalos no suman."""
    total = desc = 0.0
    for it in items:
        if it.get("es_regalo"):
            continue
        line_total = float(it["total"])
        line_sub = float(it.get("subtotal") if it.get("subtotal") is not None else line_total)
        total += line_total
        gap = round(line_sub - line_total, 2)
        if gap > 0:
            desc += gap
    total, desc = round(total, 2), round(desc, 2)
    return total, desc, round(total + desc, 2)


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return round(float(value), 2)


def _out(row: dict, *, created: bool | None = None, bodega: dict | None = None) -> dict:
    out = {
        "id": row["id"],
        "external_id": row.get("external_id"),
        "es_test": bool(row.get("es_test")),
        "data_mode": data_mode_label(bool(row.get("es_test"))),
        "bodega_nombre": row.get("bodega_nombre"),
        "fecha": _fecha_lima(row.get("fecha")),
        "items": row.get("items") or [],
        "total_pedido": _f(row.get("total_pedido")) or 0,
        "descuento_prorrateado": _f(row.get("descuento_prorrateado")) or 0,
        "monto_productos": _f(row.get("monto_productos")) or 0,
        "n_items": sum(1 for it in (row.get("items") or []) if not _item_es_regalo(it)),
        "n_regalos": sum(1 for it in (row.get("items") or []) if _item_es_regalo(it)),
        "bodega_id": row.get("bodega_id"),
        "match_score": row.get("match_score"),
        "candidatos": row.get("candidatos") or [],
        "existe_en_circa": bool(row.get("existe_en_circa")),
        "bodega_activa": bool(row.get("bodega_activa")),
        "monto_credito": _f(row.get("monto_credito")),
        "pago_confirmado": bool(row.get("pago_confirmado")),
        "estado": row.get("estado"),
        "created_at": None if row.get("created_at") is None else str(row.get("created_at")),
        "updated_at": None if row.get("updated_at") is None else str(row.get("updated_at")),
    }
    if bodega:
        out["bodega_razon_social"] = bodega.get("razon_social")
        out["bodega_estado"] = bodega.get("estado")
    if created is not None:
        out["created"] = created
    return out


def _from_iso(raw: str) -> datetime:
    """Acepta la fracción de Postgres (3–6 dígitos no siempre) en Python 3.10."""
    s = raw.strip().replace("Z", "+00:00").replace(" ", "T")

    def _pad(match: re.Match) -> str:
        return "." + (match.group(1) + "000000")[:6]

    s = _FRAC.sub(_pad, s, count=1)
    return datetime.fromisoformat(s)


def _parse_fecha(value: str | None):
    """Fecha y hora. Sin zona se toma GMT-5. Solo día queda a las 00:00 GMT-5."""
    if not value:
        return None
    raw = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            y, m, d = (int(p) for p in raw.split("-"))
            dt = datetime(y, m, d, tzinfo=LIMA)
        else:
            dt = _from_iso(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=LIMA)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="fecha debe ser YYYY-MM-DD o YYYY-MM-DDTHH:MM[:SS], hora en GMT-5 si no trae zona",
        ) from exc
    return dt.astimezone(timezone.utc).isoformat()


def _fecha_lima(value) -> str | None:
    if value is None or value == "":
        return None
    raw = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            y, m, d = (int(p) for p in raw.split("-"))
            dt = datetime(y, m, d, tzinfo=LIMA)
        else:
            dt = _from_iso(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return raw
    return dt.astimezone(LIMA).isoformat(timespec="seconds")


def _norm_items(items: list[dict]) -> list[dict]:
    """Líneas con las columnas del Excel DIMAX. `sku`/`nombre` se aceptan como alias."""
    out = []
    for it in items:
        codigo = str(it.get("codigo") or it.get("sku") or "").strip()
        if not codigo:
            raise HTTPException(status_code=400, detail="cada ítem necesita codigo")
        desc = str(it.get("descripcion") or it.get("nombre") or "").strip()
        if not desc:
            raise HTTPException(status_code=400, detail="cada ítem necesita descripcion")
        cant = float(it["cantidad"])
        if cant <= 0:
            raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0")
        precio = round(float(it["precio_unitario"]), 4)
        if it.get("total") is not None:
            total_l = round(float(it["total"]), 2)
        elif it.get("subtotal") is not None:
            total_l = round(float(it["subtotal"]), 2)
        else:
            total_l = round(cant * precio, 2)
        if it.get("subtotal") is not None and it.get("total") is not None:
            subt = round(float(it["subtotal"]), 2)
        else:
            subt = total_l
        if subt + 0.009 < total_l:
            raise HTTPException(
                status_code=400,
                detail=f"subtotal no puede ser menor que total en {codigo}",
            )
        regalo = _es_regalo(desc, total_l, bool(it.get("es_regalo")))
        out.append({
            "codigo": codigo,
            "sku": codigo.lstrip("0") or "0",
            "descripcion": desc,
            "nombre": desc,
            "cantidad": cant,
            "unidad": str(it.get("unidad") or "UND").strip() or "UND",
            "precio_unitario": precio,
            "subtotal": subt,
            "total": total_l,
            "es_regalo": regalo,
        })
    return out


def _resolver_bodega(dist_id: str, body: dict, *, es_test: bool) -> tuple[dict | None, int | None, list[dict]]:
    bodega = None
    if body.get("bodega_id"):
        bodega = find_bodega(dist_id, bodega_id=str(body["bodega_id"]), es_test=es_test)
    if not bodega and body.get("bodega_external_id"):
        bodega = find_bodega(
            dist_id, external_id=str(body["bodega_external_id"]).strip(), es_test=es_test,
        )
    if not bodega and body.get("telefono_whatsapp"):
        tel = normalizar_telefono(body["telefono_whatsapp"])
        bodega = find_bodega(dist_id, telefono=tel, es_test=es_test)
    nombre = (body.get("bodega_nombre") or "").strip()
    sugerida, candidatos = match_bodega_por_nombre(nombre, dist_id) if nombre else (None, [])
    if candidatos:
        ids = [c["id"] for c in candidatos if c.get("id")]
        modo_rows = (
            db.sb.table("bodegas").select("id").in_("id", ids).eq("es_test", bool(es_test)).execute().data
            or []
        )
        ok_ids = {r["id"] for r in modo_rows}
        candidatos = [c for c in candidatos if c.get("id") in ok_ids]
        if sugerida and sugerida.get("id") not in ok_ids:
            sugerida = None
    if bodega:
        return bodega, 100, candidatos
    if sugerida:
        row = find_bodega(dist_id, bodega_id=sugerida["id"], es_test=es_test)
        if row:
            return row, int(sugerida.get("score") or 0), candidatos
    return None, (candidatos[0]["score"] if candidatos else None), candidatos


def _flags(bodega: dict | None) -> tuple[bool, bool]:
    if not bodega:
        return False, False
    activa = (bodega.get("estado") or "").strip().lower() == "activo"
    return True, activa


def _payload(
    dist_id: str,
    body: dict,
    *,
    es_test: bool,
    monto_credito: float | None,
    pago_confirmado: bool,
    descartada: bool = False,
) -> tuple[dict, dict | None]:
    items = _norm_items(body["items"]) if body.get("items") is not None else None
    bodega, score, candidatos = _resolver_bodega(dist_id, body, es_test=es_test)
    existe, activa = _flags(bodega)
    estado = estado_entrante(
        bodega_id=bodega["id"] if bodega else None,
        monto_credito=monto_credito,
        pago_confirmado=pago_confirmado,
        descartada=descartada,
    )
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "distribuidor_id": dist_id,
        "es_test": bool(es_test),
        "external_id": str(body["external_id"]).strip(),
        "bodega_nombre": str(body["bodega_nombre"]).strip(),
        "fecha": _parse_fecha(body.get("fecha")),
        "bodega_id": bodega["id"] if bodega else None,
        "match_score": score,
        "candidatos": candidatos,
        "existe_en_circa": existe,
        "bodega_activa": activa,
        "monto_credito": monto_credito,
        "pago_confirmado": bool(pago_confirmado),
        "estado": estado,
        "updated_at": now,
    }
    if items is not None:
        total, desc, productos = totales_items(items)
        if monto_credito is not None and float(monto_credito) > total + 0.009:
            raise HTTPException(
                status_code=400,
                detail="monto_credito no puede superar el total del entrante",
            )
        row["items"] = items
        row["total_pedido"] = total
        row["descuento_prorrateado"] = desc
        row["monto_productos"] = productos
    return row, bodega


def _get_own(dist_id: str, entrante_id: str, *, es_test: bool) -> dict:
    rows = (
        db.sb.table("entrantes")
        .select(_SELECT)
        .eq("id", entrante_id)
        .eq("distribuidor_id", dist_id)
        .eq("es_test", bool(es_test))
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Entrante no encontrado")
    return rows[0]


def upsert_entrante(dist: dict, body: dict, *, es_test: bool = False) -> dict:
    external_id = str(body.get("external_id") or "").strip()
    if not external_id:
        raise HTTPException(status_code=400, detail="external_id es obligatorio")
    if not str(body.get("bodega_nombre") or "").strip():
        raise HTTPException(status_code=400, detail="bodega_nombre es obligatorio")
    if not body.get("items"):
        raise HTTPException(status_code=400, detail="items es obligatorio")

    dist_id = dist["id"]
    existing_rows = (
        db.sb.table("entrantes")
        .select(_SELECT)
        .eq("distribuidor_id", dist_id)
        .eq("es_test", bool(es_test))
        .eq("external_id", external_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    existing = existing_rows[0] if existing_rows else None
    if "monto_credito" in body:
        monto = _f(body.get("monto_credito"))
    elif existing:
        monto = _f(existing.get("monto_credito"))
    else:
        monto = None
    pago = bool(body["pago_confirmado"]) if "pago_confirmado" in body else (
        bool(existing.get("pago_confirmado")) if existing else False
    )
    row, bodega = _payload(
        dist_id, body, es_test=es_test, monto_credito=monto, pago_confirmado=pago,
    )
    if existing:
        saved = (
            db.sb.table("entrantes").update(row).eq("id", existing["id"]).execute().data or [existing]
        )[0]
        return _out(saved, created=False, bodega=bodega)
    saved = (db.sb.table("entrantes").insert(row).execute().data or [row])[0]
    return _out(saved, created=True, bodega=bodega)


def list_entrantes(
    dist: dict,
    *,
    es_test: bool = False,
    estado: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    q = (
        db.sb.table("entrantes")
        .select(_SELECT)
        .eq("distribuidor_id", dist["id"])
        .eq("es_test", bool(es_test))
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if estado:
        q = q.eq("estado", estado)
    rows = q.execute().data or []
    return {"total": len(rows), "items": [_out(r) for r in rows]}


def get_entrante(dist: dict, entrante_id: str, *, es_test: bool = False) -> dict:
    return _out(_get_own(dist["id"], entrante_id, es_test=es_test))


def patch_entrante(dist: dict, entrante_id: str, body: dict, *, es_test: bool = False) -> dict:
    current = _get_own(dist["id"], entrante_id, es_test=es_test)
    merged = {
        "external_id": current["external_id"],
        "bodega_nombre": current["bodega_nombre"],
        "fecha": current.get("fecha"),
        "items": current.get("items") or [],
        "total_pedido": _f(current.get("total_pedido")),
        "descuento_prorrateado": _f(current.get("descuento_prorrateado")) or 0,
        "bodega_id": body["bodega_id"] if body.get("bodega_id") else current.get("bodega_id"),
    }
    monto = _f(current.get("monto_credito"))
    if "monto_credito" in body:
        monto = _f(body.get("monto_credito"))
    pago = bool(current.get("pago_confirmado"))
    if "pago_confirmado" in body and body.get("pago_confirmado") is not None:
        pago = bool(body["pago_confirmado"])
    descartada = current.get("estado") == "descartada"
    if "descartada" in body and body.get("descartada") is not None:
        descartada = bool(body["descartada"])
    row, bodega = _payload(
        dist["id"],
        merged,
        es_test=es_test,
        monto_credito=monto,
        pago_confirmado=pago,
        descartada=descartada,
    )
    saved = (
        db.sb.table("entrantes").update(row).eq("id", current["id"]).execute().data or [current]
    )[0]
    return _out(saved, bodega=bodega)


def list_entrantes_backoffice(*, es_test: bool | None, limit: int = 200) -> dict:
    limit = max(1, min(limit, 200))
    q = (
        db.sb.table("entrantes")
        .select(_SELECT)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if es_test is not None:
        q = q.eq("es_test", es_test)
    rows = q.execute().data or []
    return {"total": len(rows), "items": [_out(r) for r in rows]}


def patch_entrante_backoffice(entrante_id: str, body: dict) -> dict:
    rows = (
        db.sb.table("entrantes").select(_SELECT).eq("id", entrante_id).limit(1).execute().data or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Entrante no encontrado")
    current = rows[0]
    dist = {"id": current["distribuidor_id"]}
    return patch_entrante(dist, entrante_id, body, es_test=bool(current.get("es_test")))
