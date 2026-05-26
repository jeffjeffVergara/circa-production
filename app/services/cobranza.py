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


# ── Facturación Circa — emisión de comprobantes vía NubeFact ──
#
# Al confirmar el pago de un pedido financiado se emite una boleta o factura
# por el fee de plataforma de Circa usando la API de NubeFact.
# El modo lo controla la variable de entorno NUBEFACT_MODO (demo | produccion);
# si no esta definida, se asume "demo".

import os
from datetime import timezone

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

# Series de comprobantes en NubeFact (4 caracteres exactos).
# Factura empieza con "F", boleta con "B".
NUBEFACT_SERIE_FACTURA = "FFF1"
NUBEFACT_SERIE_BOLETA = "BBB1"

# Texto del concepto que aparece en el comprobante (servicio afecto a IGV 18%).
CIRCA_FEE_CONCEPTO = "Servicio de uso de plataforma Circa"

# Zona horaria de Peru (UTC-5, sin horario de verano).
_PERU_TZ = timezone(timedelta(hours=-5))


def _nubefact_modo() -> str:
    """Devuelve 'produccion' o 'demo' (por defecto)."""
    modo = (os.environ.get("NUBEFACT_MODO") or "demo").strip().lower()
    return "produccion" if modo == "produccion" else "demo"


def _nubefact_proveedor() -> str:
    """
    Etiqueta del proveedor segun el modo. Mantiene separada la numeracion
    correlativa de demo y de produccion.
    """
    return "nubefact" if _nubefact_modo() == "produccion" else "nubefact_demo"


async def _nubefact_emitir(payload: dict) -> dict:
    """
    Envia un comprobante a la API de NubeFact y devuelve la respuesta JSON.
    Lanza RuntimeError si faltan credenciales o si NubeFact responde un error.
    """
    if httpx is None:
        raise RuntimeError("La libreria 'httpx' no esta disponible")

    ruta = (os.environ.get("NUBEFACT_RUTA") or "").strip()
    token = (os.environ.get("NUBEFACT_TOKEN") or "").strip()
    if not ruta or not token:
        raise RuntimeError("Faltan las variables NUBEFACT_RUTA / NUBEFACT_TOKEN")

    headers = {"Authorization": token, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(ruta, json=payload, headers=headers)

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(
            f"NubeFact respondio HTTP {resp.status_code} sin JSON valido"
        )

    # NubeFact reporta los errores con la clave "errors".
    if isinstance(data, dict) and data.get("errors"):
        raise RuntimeError(
            f"NubeFact error {data.get('codigo', '?')}: {data.get('errors')}"
        )
    if resp.status_code != 200:
        raise RuntimeError(f"NubeFact respondio HTTP {resp.status_code}")

    return data


def _siguiente_numero(serie: str, proveedor: str) -> int:
    """
    Calcula el siguiente correlativo para una serie. Empieza en 1.
    Solo cuenta los comprobantes ya emitidos por el proveedor actual, para
    que la numeracion de demo y la de produccion no se mezclen.
    """
    rows = (
        db.sb.table("comprobantes_circa")
        .select("correlativo")
        .eq("serie", serie)
        .eq("proveedor", proveedor)
        .execute()
        .data
    ) or []
    max_n = 0
    for r in rows:
        c = r.get("correlativo")
        if c is None or str(c).strip() == "":
            continue
        try:
            max_n = max(max_n, int(str(c).strip()))
        except (TypeError, ValueError):
            continue
    return max_n + 1


def _tipo_comprobante_bodega(bodega: dict) -> str:
    """
    Decide 'factura' o 'boleta' para una bodega. Factura solo si la bodega
    tiene un RUC valido de 11 digitos y no esta marcada como solo_dni_sin_ruc.
    Respeta tipo_comprobante_preferido cuando es compatible.
    """
    ruc = (bodega.get("ruc") or "").strip()
    tiene_ruc = (
        ruc.isdigit()
        and len(ruc) == 11
        and not bodega.get("solo_dni_sin_ruc")
    )
    pref = (bodega.get("tipo_comprobante_preferido") or "").strip().lower()
    if pref == "boleta":
        return "boleta"
    if pref == "factura" and tiene_ruc:
        return "factura"
    return "factura" if tiene_ruc else "boleta"


async def emitir_comprobante_circa(pedido: dict) -> None:
    """
    Emite el comprobante (boleta o factura) por el fee de plataforma de Circa
    a traves de NubeFact. Se llama despues de marcar un pedido como pagado.

    Nunca lanza excepcion: si algo falla, registra el error y deja el pedido
    SIN facturar, de modo que se pueda reintentar.
    """
    pedido_id = pedido.get("id")
    try:
        # Idempotencia: si el pedido ya fue facturado, no hacer nada.
        if pedido.get("facturado"):
            return

        # Resolver el monto del fee (cadena de respaldo).
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

        # Pedido al contado o sin fee -> no se factura.
        if monto_fee <= 0:
            return

        # El fee mostrado a la bodega ya incluye el IGV 18%.
        total = monto_fee
        subtotal = round(total / 1.18, 2)
        igv = round(total - subtotal, 2)

        fee_ajustado = bool(
            fee_monto_final is not None
            and fee_monto is not None
            and round(float(fee_monto_final), 2) != round(float(fee_monto), 2)
        )
        fee_final = fee_monto_final if fee_monto_final is not None else total

        # Datos de la bodega (es el cliente del comprobante).
        bod_rows = (
            db.sb.table("bodegas")
            .select(
                "id,ruc,razon_social,nombre_comercial,direccion_fiscal,"
                "distrito,dni_representante,solo_dni_sin_ruc,"
                "email_facturacion,tipo_comprobante_preferido"
            )
            .eq("id", pedido["bodega_id"])
            .limit(1)
            .execute()
            .data
        )
        if not bod_rows:
            raise RuntimeError(f"Bodega {pedido.get('bodega_id')} no encontrada")
        bodega = bod_rows[0]

        tipo = _tipo_comprobante_bodega(bodega)
        if tipo == "factura":
            tipo_cpe = 1
            serie = NUBEFACT_SERIE_FACTURA
            cliente_tipo_doc = 6
            cliente_num_doc = (bodega.get("ruc") or "").strip()
        else:
            tipo_cpe = 2
            serie = NUBEFACT_SERIE_BOLETA
            dni = (bodega.get("dni_representante") or "").strip()
            if dni:
                cliente_tipo_doc = 1
                cliente_num_doc = dni
            else:
                # Venta menor sin documento del cliente.
                cliente_tipo_doc = "-"
                cliente_num_doc = "0"

        denominacion = (
            bodega.get("razon_social")
            or bodega.get("nombre_comercial")
            or "CLIENTE VARIOS"
        ).strip()
        direccion = (
            bodega.get("direccion_fiscal")
            or bodega.get("distrito")
            or "-"
        ).strip()
        email = (bodega.get("email_facturacion") or "").strip()

        proveedor = _nubefact_proveedor()
        numero = _siguiente_numero(serie, proveedor)
        numero_pedido = str(pedido.get("numero") or pedido_id or "")
        fecha_emision = datetime.now(_PERU_TZ).strftime("%d-%m-%Y")

        descripcion = CIRCA_FEE_CONCEPTO
        if numero_pedido:
            descripcion = f"{CIRCA_FEE_CONCEPTO} - Pedido {numero_pedido}"

        # Construir el archivo JSON para NubeFact.
        payload = {
            "operacion": "generar_comprobante",
            "tipo_de_comprobante": tipo_cpe,
            "serie": serie,
            "numero": numero,
            "sunat_transaction": 1,
            "cliente_tipo_de_documento": cliente_tipo_doc,
            "cliente_numero_de_documento": cliente_num_doc,
            "cliente_denominacion": denominacion[:100],
            "cliente_direccion": direccion[:100],
            "cliente_email": email,
            "fecha_de_emision": fecha_emision,
            "moneda": 1,
            "porcentaje_de_igv": 18.00,
            "total_gravada": subtotal,
            "total_igv": igv,
            "total": total,
            "enviar_automaticamente_a_la_sunat": True,
            "enviar_automaticamente_al_cliente": False,
            "codigo_unico": numero_pedido[:20],
            "items": [
                {
                    "unidad_de_medida": "ZZ",
                    "codigo": "CIRCA-FEE",
                    "descripcion": descripcion[:250],
                    "cantidad": 1,
                    "valor_unitario": subtotal,
                    "precio_unitario": total,
                    "subtotal": subtotal,
                    "tipo_de_igv": 1,
                    "igv": igv,
                    "total": total,
                    "anticipo_regularizacion": False,
                }
            ],
        }

        # Emitir en NubeFact.
        data = await _nubefact_emitir(payload)

        # Interpretar la respuesta.
        enlace = (data.get("enlace") or "").strip()
        pdf_url = (data.get("enlace_del_pdf") or "").strip()
        xml_url = (data.get("enlace_del_xml") or "").strip()
        cdr_url = (data.get("enlace_del_cdr") or "").strip()
        if enlace and not pdf_url:
            pdf_url = enlace + ".pdf"
        if enlace and not xml_url:
            xml_url = enlace + ".xml"
        if enlace and not cdr_url:
            cdr_url = enlace + ".cdr"

        aceptada = bool(data.get("aceptada_por_sunat"))
        sunat_estado = "aceptado" if aceptada else "enviado"
        sunat_desc = (
            data.get("sunat_description")
            or data.get("sunat_soap_error")
            or ""
        )

        ahora = datetime.utcnow().isoformat()

        # Guardar el comprobante emitido.
        db.sb.table("comprobantes_circa").insert({
            "pedido_id": pedido["id"],
            "bodega_id": pedido["bodega_id"],
            "tipo_comprobante": tipo,
            "serie": serie,
            "correlativo": str(numero),
            "concepto": CIRCA_FEE_CONCEPTO,
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
            "proveedor": proveedor,
            "proveedor_id": enlace,
            "sunat_estado": sunat_estado,
            "pdf_url": pdf_url,
            "xml_url": xml_url,
            "cdr_url": cdr_url,
            "error_mensaje": None if aceptada else (sunat_desc[:500] or None),
            "issued_at": ahora,
            "created_at": ahora,
        }).execute()

        # Marcar el pedido como facturado.
        db.sb.table("pedidos").update({
            "facturado": True,
            "fecha_facturado": ahora,
        }).eq("id", pedido["id"]).execute()

        logger.info(
            f"Comprobante Circa emitido ({proveedor}) - {tipo} "
            f"{serie}-{numero}, pedido {numero_pedido}, "
            f"total S/{total:.2f}, sunat={sunat_estado}"
        )

    except Exception as e:
        # Nunca bloquear la confirmacion de pago: registrar el error.
        msg = str(e)
        logger.error(
            f"Error emitiendo comprobante Circa (pedido {pedido_id}): {msg}",
            exc_info=True,
        )
        try:
            fee_err = round(float(pedido.get("fee_monto") or 0), 2)
            ya_existe = "error 23" in msg.lower()
            ahora = datetime.utcnow().isoformat()
            db.sb.table("comprobantes_circa").insert({
                "pedido_id": pedido_id,
                "bodega_id": pedido.get("bodega_id"),
                "tipo_comprobante": "pendiente_definir",
                "concepto": CIRCA_FEE_CONCEPTO,
                "monto_fee": fee_err,
                "total": fee_err,
                "proveedor": _nubefact_proveedor(),
                "sunat_estado": "error",
                "error_mensaje": msg[:500],
                "created_at": ahora,
            }).execute()
            # Si NubeFact dice que el documento ya existe, no reintentar en bucle.
            if ya_existe and pedido_id:
                db.sb.table("pedidos").update({
                    "facturado": True,
                    "fecha_facturado": ahora,
                }).eq("id", pedido_id).execute()
        except Exception as e2:
            logger.error(
                f"Tambien fallo registrar el error del comprobante: {e2}"
            )


# Alias de compatibilidad: el handler verificar-pago en distribuidor.py llama
# crear_comprobante_circa_simulado. Ahora delega en la emision real.
async def crear_comprobante_circa_simulado(pedido: dict) -> None:
    await emitir_comprobante_circa(pedido)
