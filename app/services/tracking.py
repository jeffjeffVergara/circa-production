"""
Circa — Order Tracking & Status Management.

Alineado con el portal distribuidor (order_status.STATUS_FLOW).
"""
import logging
from datetime import datetime

from app.services import db
from app.services import meta_client
from app.services.order_status import STATUS_MESSAGES, can_transition, normalize_estado

logger = logging.getLogger("circa.tracking")


async def update_order_status(
    pedido_id: str,
    nuevo_estado: str,
    actor: str = "distribuidor",
    notas: str = None,
    estimado_entrega: str = None,
) -> dict:
    pedido = db.sb.table("pedidos").select(
        "*, bodegas(telefono_whatsapp, nombre_comercial)"
    ).eq("id", pedido_id).single().execute().data

    if not pedido:
        return {"ok": False, "message": "Pedido no encontrado"}

    estado_actual = pedido.get("estado", "")
    nxt = normalize_estado(nuevo_estado)

    if not can_transition(estado_actual, nxt):
        from app.services.order_status import VALID_TRANSITIONS

        allowed = VALID_TRANSITIONS.get(normalize_estado(estado_actual), [])
        return {
            "ok": False,
            "message": f"No se puede cambiar de '{estado_actual}' a '{nxt}'. Permitidos: {allowed}",
        }

    update_data = {"estado": nxt}
    ts = datetime.utcnow().isoformat()
    if nxt == "en_preparacion":
        update_data["preparando_at"] = ts
    elif nxt == "despachado":
        update_data["despachado_at"] = ts
    elif nxt == "en_camino":
        update_data["despachado_at"] = ts
        if estimado_entrega:
            update_data["estimado_entrega"] = estimado_entrega
    elif nxt == "entregado":
        update_data["entregado_at"] = ts
    elif nxt == "cancelado":
        update_data["cancelado_at"] = ts

    if notas:
        update_data["notas_distribuidor"] = notas

    db.sb.table("pedidos").update(update_data).eq("id", pedido_id).execute()

    db.log_evento(
        pedido_id=pedido_id,
        bodega_id=pedido.get("bodega_id"),
        accion=f"estado_{nxt}",
        estado_anterior=estado_actual,
        estado_nuevo=nxt,
        actor=actor,
    )

    bodega = pedido.get("bodegas", {})
    telefono = bodega.get("telefono_whatsapp", "")
    numero_pedido = pedido.get("numero", "")

    if telefono:
        detalle = STATUS_MESSAGES.get(nxt, "")
        if estimado_entrega and nxt == "en_camino":
            detalle += f"\n🕐 Llegada estimada: {estimado_entrega}"
        if notas:
            detalle += f"\n📝 {notas}"

        await meta_client.send_tracking_update(
            to=telefono,
            order_number=numero_pedido,
            estado=nxt,
            detalle=detalle,
        )

        if nxt == "entregado":
            financiamiento = db.sb.table("financiamientos").select("*").eq(
                "pedido_id", pedido_id
            ).limit(1).execute().data

            if financiamiento:
                fin = financiamiento[0]
                await meta_client.send_payment_instructions(
                    to=telefono,
                    order_number=numero_pedido,
                    monto=fin["monto_total"],
                    vencimiento=fin.get("fecha_vencimiento", ""),
                )

    logger.info("Order %s: %s → %s (by %s)", numero_pedido, estado_actual, nxt, actor)
    return {"ok": True, "message": f"Estado actualizado a '{nxt}'"}


async def get_order_timeline(pedido_id: str) -> list[dict]:
    eventos = db.sb.table("eventos").select("*").eq(
        "pedido_id", pedido_id
    ).order("created_at").execute().data

    return [
        {
            "accion": e["accion"],
            "estado": e["estado_nuevo"],
            "actor": e["actor"],
            "fecha": e["created_at"],
        }
        for e in eventos
    ]
