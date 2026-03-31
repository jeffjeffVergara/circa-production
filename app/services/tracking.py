"""
Circa — Order Tracking & Status Management.

Handles order lifecycle:
  confirmado → preparando → en_camino → entregado → (completed)

Sends proactive WhatsApp notifications on each state change.
"""
import logging
from datetime import datetime
from app.services import db
from app.services import meta_client

logger = logging.getLogger("circa.tracking")

# Valid state transitions
VALID_TRANSITIONS = {
    "confirmado": ["preparando", "cancelado"],
    "preparando": ["en_camino", "cancelado"],
    "en_camino": ["entregado", "cancelado"],
    "entregado": ["completed"],
    "completed": [],
    "cancelado": [],
}

STATUS_MESSAGES = {
    "confirmado": "Tu pedido ha sido recibido y confirmado.",
    "preparando": "Tu pedido está siendo preparado por el distribuidor.",
    "en_camino": "Tu pedido está en camino.",
    "entregado": "Tu pedido ha sido entregado.",
    "cancelado": "Tu pedido ha sido cancelado.",
}


async def update_order_status(pedido_id: str, nuevo_estado: str, 
                                actor: str = "distribuidor",
                                notas: str = None,
                                estimado_entrega: str = None) -> dict:
    """
    Update order status and notify the bodeguero.
    
    Args:
        pedido_id: Order UUID
        nuevo_estado: New status
        actor: Who triggered the change (distribuidor, sistema, bodeguero)
        notas: Optional notes
        estimado_entrega: Estimated delivery time (e.g., "2-4 PM")
    
    Returns:
        {"ok": True/False, "message": "..."}
    """
    # Get current order
    pedido = db.sb.table("pedidos").select(
        "*, bodegas(telefono_whatsapp, nombre_comercial)"
    ).eq("id", pedido_id).single().execute().data
    
    if not pedido:
        return {"ok": False, "message": "Pedido no encontrado"}
    
    estado_actual = pedido.get("estado", "")
    
    # Validate transition
    allowed = VALID_TRANSITIONS.get(estado_actual, [])
    if nuevo_estado not in allowed:
        return {
            "ok": False, 
            "message": f"No se puede cambiar de '{estado_actual}' a '{nuevo_estado}'. Permitidos: {allowed}"
        }
    
    # Update in DB
    update_data = {
        "estado": nuevo_estado,
    }
    
    ts = datetime.utcnow().isoformat()
    if nuevo_estado == "preparando":
        update_data["preparando_at"] = ts
    elif nuevo_estado == "en_camino":
        update_data["despachado_at"] = ts
        if estimado_entrega:
            update_data["estimado_entrega"] = estimado_entrega
    elif nuevo_estado == "entregado":
        update_data["entregado_at"] = ts
    elif nuevo_estado == "cancelado":
        update_data["cancelado_at"] = ts
    
    if notas:
        update_data["notas_distribuidor"] = notas
    
    db.sb.table("pedidos").update(update_data).eq("id", pedido_id).execute()
    
    # Log event
    db.log_evento(
        pedido_id=pedido_id,
        bodega_id=pedido.get("bodega_id"),
        accion=f"estado_{nuevo_estado}",
        estado_anterior=estado_actual,
        estado_nuevo=nuevo_estado,
        actor=actor,
    )
    
    # Notify bodeguero
    bodega = pedido.get("bodegas", {})
    telefono = bodega.get("telefono_whatsapp", "")
    numero_pedido = pedido.get("numero", "")
    
    if telefono:
        detalle = STATUS_MESSAGES.get(nuevo_estado, "")
        if estimado_entrega and nuevo_estado == "en_camino":
            detalle += f"\n🕐 Llegada estimada: {estimado_entrega}"
        if notas:
            detalle += f"\n📝 {notas}"
        
        await meta_client.send_tracking_update(
            to=telefono,
            order_number=numero_pedido,
            estado=nuevo_estado,
            detalle=detalle,
        )
        
        # If delivered, send payment instructions
        if nuevo_estado == "entregado":
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
    
    logger.info(f"Order {numero_pedido}: {estado_actual} → {nuevo_estado} (by {actor})")
    
    return {"ok": True, "message": f"Estado actualizado a '{nuevo_estado}'"}


async def get_order_timeline(pedido_id: str) -> list[dict]:
    """Get order event timeline."""
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
