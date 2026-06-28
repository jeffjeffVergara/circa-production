"""
Recordatorios de cobranza — mismo criterio que la pestaña Cobranzas del backoffice.

Un pedido es elegible si muestra el botón «Recordatorio»: entregado o pago reportado,
con monto financiado > 0 y aún no pagado.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services import db
from app.services.fees import resolver_fecha_vencimiento_pedido, total_pagar_desde_pedido

logger = logging.getLogger("circa.cobranza_recordatorios")

COBRANZA_TEMPLATES = {
    "dia2": {"name": "recordatorio_dia2_v1", "vars": ["nombre", "cuota", "vence"]},
    "dia4": {"name": "cobranza_dia_4", "vars": ["nombre", "cuota", "vence", "linea"]},
    "dia6": {"name": "cobranza_dia_6", "vars": ["nombre", "cuota", "linea"]},
}


def _bodega_ids_por_test(test_param: Optional[str]) -> Optional[set[str]]:
    if not test_param or str(test_param).lower() in ("all", "todas", "todos"):
        return None
    is_test = str(test_param).lower() in ("test", "true", "prueba", "pruebas", "1")
    try:
        rows = (
            db.sb.table("bodegas")
            .select("id")
            .eq("es_test", is_test)
            .limit(2000)
            .execute()
            .data
            or []
        )
        return {str(r["id"]) for r in rows if r.get("id")}
    except Exception:
        return None


def status_cobranza_pedido(pedido: dict, hoy: date) -> str:
    if pedido.get("estado") == "pagado":
        return "pagado"
    if pedido.get("estado") == "pago_reportado":
        return "pago_reportado"
    venc = resolver_fecha_vencimiento_pedido(pedido, hoy)
    if venc is None:
        return "pendiente"
    dias = (venc - hoy).days
    if dias < 0:
        return "vencido"
    if dias <= 3:
        return "por_vencer"
    return "al_dia"


def pedido_elegible_recordatorio(pedido: dict, hoy: Optional[date] = None) -> bool:
    """Mismo criterio que el botón Recordatorio en la tabla de Cobranzas."""
    if float(pedido.get("monto_financiado") or 0) <= 0:
        return False
    if pedido.get("estado") == "pagado":
        return False
    return pedido.get("estado") in ("entregado", "pago_reportado")


def _dias_desde_despacho(pedido: dict) -> int:
    fecha_ref = pedido.get("fecha_despachado") or pedido.get("fecha_entregado") or pedido.get("created_at")
    if not fecha_ref:
        return 0
    try:
        fr = datetime.fromisoformat(str(fecha_ref).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - fr).days
    except (ValueError, TypeError):
        return 0


def plantilla_recordatorio_key(pedido: dict) -> str:
    dias = _dias_desde_despacho(pedido)
    if dias <= 3:
        return "dia2"
    if dias <= 5:
        return "dia4"
    return "dia6"


def _fmt_monto(x: Any) -> str:
    try:
        val = float(x or 0)
    except (TypeError, ValueError):
        val = 0.0
    return str(int(val)) if val == int(val) else f"{val:.2f}"


def _vence_label(pedido: dict) -> str:
    plazo = pedido.get("plazo_dias") or 7
    vence_str = pedido.get("fecha_vencimiento") or ""
    fecha_entregado = pedido.get("fecha_entregado") or pedido.get("created_at")
    if not vence_str and fecha_entregado:
        try:
            fe = datetime.fromisoformat(str(fecha_entregado).replace("Z", "+00:00"))
            vence_str = (fe + timedelta(days=plazo)).strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            vence_str = ""
    try:
        if vence_str and len(str(vence_str)) == 10 and str(vence_str)[4] == "-":
            vence_str = datetime.fromisoformat(str(vence_str)).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        pass
    return str(vence_str) if vence_str else "tu fecha de vencimiento"


def _fetch_bodegas_map(bodega_ids: list[str]) -> dict[str, dict]:
    if not bodega_ids:
        return {}
    out: dict[str, dict] = {}
    chunk = 80
    for i in range(0, len(bodega_ids), chunk):
        part = bodega_ids[i : i + chunk]
        rows = (
            db.sb.table("bodegas")
            .select(
                "id, nombre_comercial, telefono_whatsapp, es_test, "
                "representante_nombre_corto, linea_aprobada"
            )
            .in_("id", part)
            .execute()
            .data
            or []
        )
        for row in rows:
            if row.get("id"):
                out[row["id"]] = row
    return out


def compose_recordatorio_mensaje(pedido: dict, bodega: dict) -> dict[str, Any]:
    """Arma plantilla, variables y texto de vista previa (sin enviar)."""
    telefono = (bodega.get("telefono_whatsapp") or "").strip()
    monto_fin = float(pedido.get("monto_financiado") or 0)
    fee = float(pedido.get("fee_monto") or 0)
    cuota = float(pedido.get("monto_total_credito") or 0) or round(monto_fin + fee, 2)
    linea = float(bodega.get("linea_aprobada") or 0)
    nombre = (bodega.get("representante_nombre_corto") or bodega.get("nombre_comercial") or "").strip()
    tkey = plantilla_recordatorio_key(pedido)
    tpl = COBRANZA_TEMPLATES[tkey]
    valores = {
        "nombre": nombre or "estimado cliente",
        "cuota": _fmt_monto(cuota),
        "vence": _vence_label(pedido),
        "linea": _fmt_monto(linea),
    }
    var_lines = [f"{{{i}}} {v} = {valores[v]}" for i, v in enumerate(tpl["vars"], 1)]
    preview_lines = [
        f"Plantilla Meta: {tpl['name']}",
        f"Destino WA: {telefono or '(sin teléfono)'}",
        f"Bodega: {bodega.get('nombre_comercial') or '—'}",
        f"Pedido: {pedido.get('numero', '')}",
        "",
        "Variables de la plantilla:",
        *var_lines,
    ]
    return {
        "plantilla": tpl["name"],
        "template_key": tkey,
        "telefono_destino": telefono or None,
        "variables": [{"name": v, "value": valores[v]} for v in tpl["vars"]],
        "mensaje_preview": "\n".join(preview_lines),
        "mensaje_tipo": "whatsapp_template",
    }


def list_recordatorio_preview_items(*, test: Optional[str] = None) -> list[dict[str, Any]]:
    hoy = datetime.utcnow().date()
    pedidos = (
        db.sb.table("pedidos")
        .select("*")
        .in_("estado", ["entregado", "pago_reportado", "pagado"])
        .order("created_at", desc=True)
        .limit(500)
        .execute()
        .data
        or []
    )
    ids_filter = _bodega_ids_por_test(test)
    if ids_filter is not None:
        pedidos = [p for p in pedidos if p.get("bodega_id") in ids_filter]

    bodega_ids = list({p["bodega_id"] for p in pedidos if p.get("bodega_id")})
    bodegas_map = _fetch_bodegas_map(bodega_ids)

    items: list[dict[str, Any]] = []
    for pedido in pedidos:
        if not pedido_elegible_recordatorio(pedido, hoy):
            continue
        bodega = bodegas_map.get(pedido.get("bodega_id")) or {}
        telefono = (bodega.get("telefono_whatsapp") or "").strip()
        status = status_cobranza_pedido(pedido, hoy)
        venc = resolver_fecha_vencimiento_pedido(pedido, hoy)
        dias = (venc - hoy).days if venc else None
        tp = total_pagar_desde_pedido(pedido, hoy=hoy)
        tkey = plantilla_recordatorio_key(pedido)
        tpl_name = COBRANZA_TEMPLATES[tkey]["name"]
        msg = compose_recordatorio_mensaje(pedido, bodega)

        detalle = (
            f"Pedido {pedido.get('numero', '')} · {status} · "
            f"S/{float(tp['total_pagar']):.2f}"
        )
        if dias is not None:
            detalle += f" · {'vencido' if dias < 0 else str(dias) + 'd'}"
        detalle += f" · {tpl_name}"

        items.append({
            "item_id": str(pedido["id"]),
            "pedido_id": pedido["id"],
            "bodega_id": pedido.get("bodega_id"),
            "bodega_nombre": bodega.get("nombre_comercial") or "—",
            "telefono": telefono or None,
            "es_test": bool(bodega.get("es_test")),
            "detalle": detalle,
            "accion": f"Enviar plantilla {tpl_name}" if telefono else "Omitido (sin teléfono)",
            "status_cobranza": status,
            "plantilla": msg["plantilla"],
            "mensaje_preview": msg["mensaje_preview"],
            "mensaje_tipo": msg["mensaje_tipo"],
            "variables": msg["variables"],
        })
    return items


async def send_recordatorio_pedido(pedido_id: str) -> dict[str, Any]:
    """Envía el recordatorio WhatsApp (misma lógica que POST /cobranza/{id}/recordatorio)."""
    from app.routes import distribuidor as dist

    rows = db.sb.table("pedidos").select("*").eq("id", pedido_id).limit(1).execute().data or []
    if not rows:
        return {"ok": False, "error": "Pedido no encontrado"}
    ped = rows[0]

    if not pedido_elegible_recordatorio(ped):
        return {"ok": False, "error": "Pedido no elegible para recordatorio"}

    bid = ped.get("bodega_id", "")
    bodega_rows = (
        db.sb.table("bodegas")
        .select("telefono_whatsapp,nombre_comercial,representante_nombre_corto,linea_aprobada,es_test")
        .eq("id", bid)
        .limit(1)
        .execute()
        .data
        or []
    )
    bodega = bodega_rows[0] if bodega_rows else {}
    tel = (bodega.get("telefono_whatsapp") or "").strip()
    if not tel:
        return {"ok": False, "error": "Bodega sin telefono"}

    monto_fin = float(ped.get("monto_financiado") or 0)
    fee = float(ped.get("fee_monto") or 0)
    cuota = float(ped.get("monto_total_credito") or 0) or round(monto_fin + fee, 2)
    if cuota <= 0:
        return {"ok": False, "error": "Este pedido no tiene saldo financiado por cobrar"}

    linea = float(bodega.get("linea_aprobada") or 0)
    nombre = (bodega.get("representante_nombre_corto") or bodega.get("nombre_comercial") or "").strip()
    msg = compose_recordatorio_mensaje(ped, bodega)
    tkey = msg["template_key"]
    tpl = COBRANZA_TEMPLATES[tkey]
    valores = {v["name"]: v["value"] for v in msg["variables"]}
    variables = [valores[v] for v in tpl["vars"]]

    resultado = dist._send_wa_template(tel, tpl["name"], variables)
    if not resultado.get("ok"):
        return {"ok": False, "error": resultado.get("error") or "Meta rechazo el envio"}

    wamid = ""
    try:
        wamid = ((resultado.get("response") or {}).get("messages") or [{}])[0].get("id", "")
    except (IndexError, KeyError, TypeError):
        wamid = ""

    try:
        from app.services.analytics import track_message

        track_message(
            telefono=tel,
            direction="outbound",
            bodega_id=bid,
            message_id=wamid,
            message_type="cobranza_recordatorio",
            template_name=tpl["name"],
            content=f"Recordatorio de cobranza ({tkey}) - pedido {ped.get('numero', '')}",
            metadata={
                "pedido_id": pedido_id,
                "numero": ped.get("numero", ""),
                "dia": tkey,
                "dias_desde_despacho": _dias_desde_despacho(ped),
            },
            measure_response_latency=False,
        )
    except Exception as e:
        logger.error("[cobranza track_message] %s", e)

    return {
        "ok": True,
        "enviado_a": tel,
        "pedido": ped.get("numero", ""),
        "plantilla": tpl["name"],
        "dias_desde_despacho": _dias_desde_despacho(ped),
    }


async def send_recordatorios_batch(
    *,
    pedido_ids: Optional[list[str]] = None,
    test: Optional[str] = None,
) -> dict[str, Any]:
    allowed = {str(x) for x in pedido_ids} if pedido_ids else None
    items = list_recordatorio_preview_items(test=test)
    sent = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    for item in items:
        pid = str(item.get("pedido_id") or item.get("item_id") or "")
        if allowed is not None and pid not in allowed:
            continue
        if not item.get("telefono"):
            skipped += 1
            continue
        result = await send_recordatorio_pedido(pid)
        if result.get("ok"):
            sent += 1
            logger.info("Reminder sent: %s — %s", result.get("pedido"), result.get("plantilla"))
        else:
            errors.append({"pedido_id": pid, "error": str(result.get("error") or "error")})

    return {"sent": sent, "skipped": skipped, "errors": errors}
