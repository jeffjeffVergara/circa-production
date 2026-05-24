"""
Circa — Cobranza (Payment Collection) & Line Renewal.

Handles:
- Payment registration ("Ya pagué")
- Payment confirmation (manual or automated)
- Credit line renewal after payment
- Payment reminders schedule
- Overdue detection
"""
import logging
from datetime import datetime, date, timedelta
from app.services import db, meta_client
from app.services.financing import generate_reminders_schedule
from app.services.fees import total_pagar_desde_pedido

logger = logging.getLogger("circa.cobranza")


async def register_payment_claim(bodega_id: str, pedido_id: str = None) -> dict:
    """
    Bodeguero claims they paid ("Ya pagué" button).
    Registers the claim for manual verification.
    
    Returns:
        {"ok": True, "message": "...", "pedido_numero": "CRC-001"}
    """
    # Find the active financiamiento
    query = db.sb.table("financiamientos").select(
        "*, pedidos(numero, bodega_id)"
    ).eq("bodega_id", bodega_id).eq("estado", "activo")
    
    if pedido_id:
        query = query.eq("pedido_id", pedido_id)
    
    financiamientos = query.order("created_at", desc=True).limit(1).execute().data
    
    if not financiamientos:
        return {"ok": False, "message": "No tienes pagos pendientes."}
    
    fin = financiamientos[0]
    
    # Update financiamiento to pending verification
    db.sb.table("financiamientos").update({
        "estado": "verificando",
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", fin["id"]).execute()
    
    # Log event
    db.log_evento(
        pedido_id=fin["pedido_id"],
        bodega_id=bodega_id,
        accion="pago_reportado",
        estado_anterior="activo",
        estado_nuevo="verificando",
        actor="bodeguero",
    )
    
    numero = fin.get("pedidos", {}).get("numero", "")
    
    logger.info(f"Payment claim registered: {numero} by bodega {bodega_id}")
    
    return {
        "ok": True,
        "message": f"Pago reportado para {numero}. Verificaremos en las próximas horas.",
        "pedido_numero": numero,
        "financiamiento_id": fin["id"],
    }


async def confirm_payment(financiamiento_id: str, monto_pagado: float = None,
                           metodo: str = "yape", actor: str = "sistema") -> dict:
    """
    Confirm a payment and renew the credit line.
    Called by backoffice or automated reconciliation.
    
    Returns:
        {"ok": True, "message": "...", "linea_renovada": 500.00}
    """
    # Get financiamiento
    fin = db.sb.table("financiamientos").select(
        "*, pedidos(numero), bodegas(telefono_whatsapp, linea_aprobada)"
    ).eq("id", financiamiento_id).single().execute().data
    
    if not fin:
        return {"ok": False, "message": "Financiamiento no encontrado"}
    
    if fin["estado"] not in ("activo", "verificando", "vencido"):
        return {"ok": False, "message": f"Estado '{fin['estado']}' no permite confirmar pago"}
    
    monto = monto_pagado or fin["monto_total"]
    
    # Update financiamiento
    db.sb.table("financiamientos").update({
        "estado": "pagado",
        "fecha_pago": datetime.utcnow().isoformat(),
        "monto_pagado": monto,
        "metodo_pago": metodo,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", financiamiento_id).execute()
    
    # Update pedido
    db.sb.table("pedidos").update({
        "estado": "completed",
        "pagado_at": datetime.utcnow().isoformat(),
    }).eq("id", fin["pedido_id"]).execute()
    
    # Renew credit line
    bodega_id = fin["bodega_id"]
    linea_aprobada = fin.get("bodegas", {}).get("linea_aprobada", 500)
    
    # Recalculate: sum all active (unpaid) financiamientos
    activos = db.sb.table("financiamientos").select("monto_principal").eq(
        "bodega_id", bodega_id
    ).in_("estado", ["activo", "verificando"]).execute().data
    
    total_activo = sum(f["monto_principal"] for f in activos)
    nueva_linea = max(0, linea_aprobada - total_activo)
    
    db.sb.table("bodegas").update({
        "linea_disponible": nueva_linea,
    }).eq("id", bodega_id).execute()
    
    # Log movement
    db.sb.table("movimientos_linea").insert({
        "bodega_id": bodega_id,
        "tipo": "liberacion",
        "monto": fin["monto_principal"],
        "financiamiento_id": financiamiento_id,
        "pedido_id": fin["pedido_id"],
        "disponible_antes": nueva_linea - fin["monto_principal"],
        "disponible_despues": nueva_linea,
        "descripcion": f"Pago confirmado - {fin.get('pedidos', {}).get('numero', '')}",
    }).execute()
    
    # Log event
    db.log_evento(
        pedido_id=fin["pedido_id"],
        bodega_id=bodega_id,
        accion="pago_confirmado",
        estado_anterior="verificando",
        estado_nuevo="pagado",
        actor=actor,
    )
    
    # Notify bodeguero
    telefono = fin.get("bodegas", {}).get("telefono_whatsapp", "")
    if telefono:
        await meta_client.send_payment_confirmed(
            to=telefono,
            linea_disponible=nueva_linea,
        )
    
    numero = fin.get("pedidos", {}).get("numero", "")
    logger.info(f"Payment confirmed: {numero}, line renewed to S/{nueva_linea:.2f}")
    
    return {
        "ok": True,
        "message": f"Pago confirmado para {numero}",
        "linea_renovada": nueva_linea,
    }


async def check_overdue_loans() -> list[dict]:
    """
    Check for overdue financiamientos and update their status.
    Called periodically (e.g., daily cron job).
    
    Returns list of overdue financiamientos.
    """
    hoy = date.today().isoformat()
    
    # Find active financiamientos past due date
    overdue = db.sb.table("financiamientos").select(
        "*, pedidos(numero), bodegas(telefono_whatsapp, nombre_comercial)"
    ).eq("estado", "activo").lt("fecha_vencimiento", hoy).execute().data
    
    results = []
    for fin in overdue:
        # Mark as overdue
        db.sb.table("financiamientos").update({
            "estado": "vencido",
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", fin["id"]).execute()
        
        # Log event
        db.log_evento(
            pedido_id=fin["pedido_id"],
            bodega_id=fin["bodega_id"],
            accion="credito_vencido",
            estado_anterior="activo",
            estado_nuevo="vencido",
            actor="sistema",
        )
        
        results.append({
            "financiamiento_id": fin["id"],
            "pedido_numero": fin.get("pedidos", {}).get("numero", ""),
            "bodega": fin.get("bodegas", {}).get("nombre_comercial", ""),
            "monto_total": fin["monto_total"],
            "fecha_vencimiento": fin["fecha_vencimiento"],
        })
        
        logger.warning(f"Overdue: {fin.get('pedidos', {}).get('numero', '')} — S/{fin['monto_total']}")
    
    return results


async def send_pending_reminders() -> int:
    """
    Send payment reminders that are due today.
    Called periodically (e.g., every hour or daily).
    
    Returns count of reminders sent.
    """
    hoy = date.today().isoformat()
    count = 0
    
    # Find unsent reminders due today
    reminders = db.sb.table("recordatorios").select(
        "*, pedidos(numero, bodega_id, bodegas(telefono_whatsapp))"
    ).eq("enviado", False).lte("fecha_envio", hoy).execute().data
    
    for rem in reminders:
        pedido = rem.get("pedidos", {})
        bodega = pedido.get("bodegas", {})
        telefono = bodega.get("telefono_whatsapp", "")
        
        if not telefono:
            continue
        
        # Get the financiamiento for this order
        fin = db.sb.table("financiamientos").select("*").eq(
            "pedido_id", rem["pedido_id"]
        ).in_("estado", ["activo", "vencido"]).limit(1).execute().data
        
        if not fin:
            continue
        
        fin = fin[0]
        venc = datetime.strptime(fin["fecha_vencimiento"], "%Y-%m-%d").date()
        dias_restantes = (venc - date.today()).days
        
        # Send reminder
        await meta_client.send_reminder(
            to=telefono,
            order_number=pedido.get("numero", ""),
            monto=fin["monto_total"],
            dias_restantes=dias_restantes,
        )
        
        # Mark as sent
        db.sb.table("recordatorios").update({
            "enviado": True,
            "enviado_at": datetime.utcnow().isoformat(),
        }).eq("id", rem["id"]).execute()
        
        count += 1
        logger.info(f"Reminder sent: {pedido.get('numero', '')} — {rem['tipo']} ({dias_restantes}d)")
    
    return count


async def get_pending_payments(bodega_id: str) -> list[dict]:
    """Get all pending payments for a bodega."""
    financiamientos = db.sb.table("financiamientos").select(
        "*, pedidos(numero)"
    ).eq("bodega_id", bodega_id).in_(
        "estado", ["activo", "verificando", "vencido"]
    ).order("fecha_vencimiento").execute().data
    
    out = []
    for f in financiamientos:
        pedido = f.get("pedidos") or {}
        if isinstance(pedido, list):
            pedido = pedido[0] if pedido else {}
        p_row = {
            "monto_financiado": f.get("monto_principal"),
            "fee_monto": (f.get("monto_total") or 0) - (f.get("monto_principal") or 0),
            "fecha_vencimiento": f.get("fecha_vencimiento"),
            "monto_total_credito": f.get("monto_total"),
        }
        if pedido:
            p_row.update(pedido)
        tp = total_pagar_desde_pedido(p_row)
        out.append({
            "pedido_numero": pedido.get("numero", "") if pedido else "",
            "monto_total": f["monto_total"],
            "mora_monto": tp["mora_monto"],
            "total_pagar": tp["total_pagar"],
            "fecha_vencimiento": f["fecha_vencimiento"],
            "estado": f["estado"],
            "dias_restantes": (
                datetime.strptime(f["fecha_vencimiento"], "%Y-%m-%d").date() - date.today()
            ).days if f.get("fecha_vencimiento") else None,
        })
    return out


# ── Facturación Circa — comprobante simulado por el fee de plataforma ──

async def crear_comprobante_circa_simulado(pedido: dict) -> None:
    """
    Crea un comprobante Circa (modo simulado, sin SUNAT) por el fee de la
    plataforma. Se llama despues de marcar un pedido como pagado.
    Nunca lanza excepcion: si algo falla, solo registra el error.
    """
    try:
        # Idempotencia: si el pedido ya fue facturado, no hacer nada
        if pedido.get("facturado"):
            return

        # Resolver el monto del fee (cadena de respaldo)
        fee_monto = pedido.get("fee_monto")
        fee_monto_final = pedido.get("fee_monto_final")
        monto_fee = fee_monto_final
        if monto_fee is None:
            monto_fee = fee_monto
        if monto_fee is None:
            mtc = pedido.get("monto_total_credito")
            mfin = pedido.get("monto_financiado")
            if mtc is not None and mfin is not None:
                monto_fee = float(mtc) - float(mfin)
        monto_fee = round(float(monto_fee or 0), 2)

        # Pedido al contado o sin fee -> no se factura
        if monto_fee <= 0:
            return

        # El fee mostrado a la bodega ya incluye IGV 18%
        total = monto_fee
        subtotal = round(total / 1.18, 2)
        igv = round(total - subtotal, 2)

        # fee_ajustado: True solo si el fee final difiere del calculado
        fee_ajustado = bool(
            fee_monto_final is not None
            and fee_monto is not None
            and round(float(fee_monto_final), 2) != round(float(fee_monto), 2)
        )
        fee_final = fee_monto_final if fee_monto_final is not None else total

        ahora = datetime.utcnow().isoformat()

        # Insertar el comprobante (modo simulado, sin SUNAT)
        db.sb.table("comprobantes_circa").insert({
            "pedido_id": pedido["id"],
            "bodega_id": pedido["bodega_id"],
            "tipo_comprobante": "pendiente_definir",
            "concepto": "Servicio de uso de plataforma Circa",
            "monto_fee": total,
            "subtotal": subtotal,
            "igv": igv,
            "total": total,
            "fee_base": pedido.get("monto_financiado"),
            "fee_porcentaje": pedido.get("fee_tasa"),
            "fee_calculado": fee_monto,
            "fee_final": fee_final,
            "fee_ajustado": fee_ajustado,
            "plazo_dias": pedido.get("plazo_dias"),
            "tasa_aplicada": pedido.get("fee_tasa"),
            "regla_fee": pedido.get("fee_regimen"),
            "proveedor": "simulado",
            "sunat_estado": "simulado",
            "issued_at": ahora,
            "created_at": ahora,
        }).execute()

        # Marcar el pedido como facturado
        db.sb.table("pedidos").update({
            "facturado": True,
            "fecha_facturado": ahora,
        }).eq("id", pedido["id"]).execute()

        logger.info(
            f"Comprobante Circa simulado creado - pedido "
            f"{pedido.get('numero', pedido['id'])}, fee S/{total:.2f}"
        )
    except Exception as e:
        logger.error(
            f"Error creando comprobante Circa (pedido {pedido.get('id', '?')}): {e}",
            exc_info=True,
        )
