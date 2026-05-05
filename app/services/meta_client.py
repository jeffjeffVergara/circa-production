"""
Meta WhatsApp Cloud API Client — Replaces Twilio.

Handles all outgoing messages:
- Text messages
- Interactive buttons (quick replies)
- Interactive lists
- WhatsApp Flows (onboarding + catalog)
- Template messages (for proactive/outbound)
- Media messages (images)

API: POST https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages
Auth: Bearer {ACCESS_TOKEN}
"""
import httpx
import logging
import os
import json

logger = logging.getLogger("circa.meta")

# ── Config from env ──
GRAPH_API_VERSION = "v23.0"
GRAPH_API_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def _phone_number_id() -> str:
    return os.getenv("META_PHONE_NUMBER_ID", "")

def _access_token() -> str:
    return os.getenv("META_ACCESS_TOKEN", "")

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_access_token()}",
        "Content-Type": "application/json",
    }


# ══════════════════════════════════════════════
# CORE: Send any message payload
# ══════════════════════════════════════════════

async def _send(to: str, payload: dict) -> dict | None:
    """
    Send a message via Meta Cloud API.
    
    Args:
        to: Phone number with country code (e.g., "51987654321")
        payload: Message payload (type-specific)
    
    Returns:
        API response dict or None on error
    """
    # Normalize phone number
    to = to.lstrip("+").replace(" ", "")
    
    url = f"{GRAPH_API_URL}/{_phone_number_id()}/messages"
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        **payload,
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=_headers(), json=body)
            
            if r.status_code not in (200, 201):
                logger.error(f"Meta API error {r.status_code}: {r.text}")
                return None
            
            data = r.json()
            msg_id = data.get("messages", [{}])[0].get("id", "")
            logger.info(f"📤 Sent to {to}: {payload.get('type', '?')} (wamid={msg_id})")
            try:
                from app.services.analytics import track_message
                from app.services import db as _db

                b = _db.get_bodega_by_phone(f"+{to}") or _db.get_bodega_by_phone(to)
                bodega_id = b.get("id") if b else None
                msg_type = payload.get("type", "")
                content = ""
                template_name = ""
                if msg_type == "text":
                    content = payload.get("text", {}).get("body", "")
                elif msg_type == "interactive":
                    content = payload.get("interactive", {}).get("body", {}).get("text", "")
                elif msg_type == "template":
                    template_name = payload.get("template", {}).get("name", "")
                track_message(
                    telefono=f"+{to}",
                    direction="outbound",
                    bodega_id=bodega_id,
                    message_id=msg_id,
                    message_type=msg_type,
                    content=content,
                    template_name=template_name,
                    metadata={"payload_type": msg_type},
                )
            except Exception:
                pass
            return data
            
    except Exception as e:
        logger.error(f"Failed to send to {to}: {e}", exc_info=True)
        return None


# ══════════════════════════════════════════════
# TEXT MESSAGES
# ══════════════════════════════════════════════

async def send_text(to: str, text: str, preview_url: bool = False) -> dict | None:
    """Send a plain text message."""
    return await _send(to, {
        "type": "text",
        "text": {
            "preview_url": preview_url,
            "body": text,
        }
    })


# ══════════════════════════════════════════════
# INTERACTIVE: REPLY BUTTONS (max 3)
# ══════════════════════════════════════════════

async def send_buttons(to: str, body: str, buttons: list[dict], header: str = None, footer: str = None) -> dict | None:
    """
    Send interactive reply buttons (max 3).
    
    Args:
        buttons: [{"id": "btn_1", "title": "Opción 1"}, ...]
    """
    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
                for b in buttons[:3]
            ]
        }
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}
    
    return await _send(to, {"type": "interactive", "interactive": interactive})


# ══════════════════════════════════════════════
# INTERACTIVE: LIST (max 10 rows, max 10 sections)
# ══════════════════════════════════════════════

# Límites API WhatsApp Cloud (lista interactiva)
_WA_LIST_BODY_MAX = 1024
_WA_LIST_SECTION_TITLE_MAX = 24
_WA_LIST_ROW_TITLE_MAX = 24
_WA_LIST_ROW_DESC_MAX = 72
_WA_LIST_ROW_ID_MAX = 200


def _normalize_list_sections(sections: list[dict]) -> list[dict]:
    """Recorta títulos/descripciones; si exceden límites, Meta devuelve 400 y el mensaje no se envía."""
    out: list[dict] = []
    for sec in sections or []:
        s = {
            "title": (sec.get("title") or "")[:_WA_LIST_SECTION_TITLE_MAX],
            "rows": [],
        }
        for r in sec.get("rows") or []:
            row: dict = {
                "id": (r.get("id") or "")[:_WA_LIST_ROW_ID_MAX],
                "title": (r.get("title") or "")[:_WA_LIST_ROW_TITLE_MAX],
            }
            d = (r.get("description") or "").strip()
            if d:
                row["description"] = d[:_WA_LIST_ROW_DESC_MAX]
            s["rows"].append(row)
        out.append(s)
    return out


async def send_list(to: str, body: str, button_text: str, sections: list[dict], header: str = None, footer: str = None) -> dict | None:
    """
    Send interactive list message.

    Args:
        sections: [{
            "title": "Bebidas",
            "rows": [{"id": "1", "title": "Coca-Cola", "description": "Pack 12 — S/18"}]
        }]
    """
    body = (body or "")[:_WA_LIST_BODY_MAX]
    sections = _normalize_list_sections(sections)
    interactive = {
        "type": "list",
        "body": {"text": body},
        "action": {
            "button": button_text[:20],
            "sections": sections,
        }
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}
    
    return await _send(to, {"type": "interactive", "interactive": interactive})


# ══════════════════════════════════════════════
# WHATSAPP FLOWS
# ══════════════════════════════════════════════

async def send_flow(to: str, flow_id: str, flow_cta: str, body: str, 
                     screen: str = None, data: dict = None,
                     header: str = None, footer: str = None,
                     mode: str = "published") -> dict | None:
    """
    Send a WhatsApp Flow message.
    
    Args:
        flow_id: Flow ID from WhatsApp Manager
        flow_cta: Call-to-action button text (e.g., "Activar cuenta")
        body: Message body text
        screen: First screen to show (optional)
        data: Data to pass to the first screen (optional)
        mode: "published" or "draft" (for testing)
    """
    parameters = {
        "flow_message_version": "3",
        "flow_id": flow_id,
        "flow_cta": flow_cta,
        "mode": mode,
    }
    
    if screen:
        parameters["flow_action"] = "navigate"
        parameters["flow_action_payload"] = {
            "screen": screen,
        }
        if data:
            parameters["flow_action_payload"]["data"] = data
    
    interactive = {
        "type": "flow",
        "body": {"text": body},
        "action": {
            "name": "flow",
            "parameters": parameters,
        }
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}
    
    return await _send(to, {"type": "interactive", "interactive": interactive})


# ══════════════════════════════════════════════
# TEMPLATE MESSAGES (for outbound/proactive)
# ══════════════════════════════════════════════

async def send_template(to: str, template_name: str, language: str = "es", 
                         components: list = None) -> dict | None:
    """
    Send a pre-approved template message.
    Used for proactive outbound (first contact, reminders, etc.)
    
    Args:
        template_name: Approved template name
        language: Language code (default "es" for Spanish)
        components: Template components (header, body params, buttons)
    """
    template = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template["components"] = components
    
    return await _send(to, {"type": "template", "template": template})


# ══════════════════════════════════════════════
# MEDIA MESSAGES
# ══════════════════════════════════════════════

async def send_image(to: str, image_url: str, caption: str = None) -> dict | None:
    """Send an image message."""
    image = {"link": image_url}
    if caption:
        image["caption"] = caption
    return await _send(to, {"type": "image", "image": image})


async def send_document(to: str, document_url: str, filename: str, caption: str = None) -> dict | None:
    """Send a document (PDF, etc.)."""
    doc = {"link": document_url, "filename": filename}
    if caption:
        doc["caption"] = caption
    return await _send(to, {"type": "document", "document": doc})


# ══════════════════════════════════════════════
# MARK AS READ
# ══════════════════════════════════════════════

async def mark_as_read(message_id: str) -> dict | None:
    """Mark an incoming message as read (blue checkmarks)."""
    url = f"{GRAPH_API_URL}/{_phone_number_id()}/messages"
    body = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, headers=_headers(), json=body)
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ══════════════════════════════════════════════
# CIRCA-SPECIFIC HELPERS
# ══════════════════════════════════════════════

async def send_menu(to: str, linea_disponible: float, preventa_pendiente: dict = None):
    """Main menu. Si hay preventa DIMAX pendiente, la muestra como primera opción."""
    rows_normales = [
        {"id": "PEDIDO", "title": "Hacer un nuevo pedido", "description": "Arma tu pedido del catálogo"},
        {"id": "REPETIR", "title": "Repetir pedido anterior", "description": "Pide lo mismo de antes"},
        {"id": "LINEA", "title": "Ver mi tope Circa", "description": "Cuánto te queda para pedir"},
        {"id": "ESTADO", "title": "Estado de mis pedidos", "description": "Seguimiento y pagos"},
        {"id": "CONTACTO", "title": "Contactar a Circa", "description": "Equipo Circa por WhatsApp"},
    ]
    
    if preventa_pendiente:
        total = float(preventa_pendiente.get("total_pedido") or 0)
        pid = preventa_pendiente["id"]
        primera = {
            "id": f"PAGAR_PREVENTA_{pid}",
            "title": "🛒 Pagar mi preventa",
            "description": f"S/{total:.2f} de DIMAX — listo para despacho",
        }
        rows = [primera] + rows_normales
        body_text = f"💰 Línea Circa disponible: *S/{linea_disponible:.2f}*\n\nTienes una preventa lista. ¿Qué deseas hacer?"
    else:
        rows = [
            {"id": "PREVENTA", "title": "Hacer una pre-venta", "description": "Reserva para próxima entrega"},
        ] + rows_normales
        body_text = f"💰 Línea Circa disponible: *S/{linea_disponible:.2f}*\n\n¿Qué deseas hacer?"
    
    return await send_list(
        to=to,
        body=body_text,
        button_text="Ver opciones",
        sections=[{"title": "Menú", "rows": rows}]
    )


async def send_welcome(to: str, nombre: str, linea: float, distribuidor: str):
    """Welcome message."""
    return await send_buttons(
        to=to,
        header="Circa",
        body=(
            f"\u00a1Hola, *{nombre}*! \U0001f44b\n\n"
            f"\U0001f389 *\u00a1Felicitaciones!* Por tu buen historial con *{distribuidor}*, "
            f"puedes comprar hasta:\n\n"
            f"\U0001f4b0 *S/{linea:.2f}* para comprar mercader\u00eda y pagarla en cuotas con Circa\n\n"
            f"\u00bfC\u00f3mo funciona?\n\n"
            f"1. Pide lo que necesites a *{distribuidor}*\n"
            f"2. Circa le paga directo al distribuidor\n"
            f"3. T\u00fa eliges pagar en *7, 15 o 30 d\u00edas*\n"
            f"4. Pagas a Circa por *Yape o Plin*\n"
            f"5. Tu cr\u00e9dito se renueva al pagar\n\n"
            f"No necesitas ir a ning\u00fan banco. Todo por WhatsApp."
        ),
        buttons=[
            {"id": "SI", "title": "Activar mi cuenta"},
            {"id": "MAS_INFO", "title": "\u00bfC\u00f3mo funciona?"},
        ]
    )


async def send_ruc_request(to: str):
    """Ask bodeguero to enter RUC."""
    return await send_text(
        to=to,
        text="Para activar, necesito verificar tu negocio.\n\n📝 *Escribe tu RUC (11 dígitos):*"
    )


async def send_ruc_verified(to: str, razon_social: str, ruc: str, direccion: str, representante: str):
    """Show verified RUC info from SUNAT with confirm button."""
    return await send_buttons(
        to=to,
        body=(
            f"✅ *RUC verificado en SUNAT:*\n\n"
            f"*{razon_social}*\n"
            f"RUC: {ruc}\n"
            f"📍 {direccion}\n"
            f"👤 Rep. Legal: {representante}\n\n"
            f"La dirección fiscal será tu dirección de despacho.\n\n"
            f"¿Los datos son correctos?"
        ),
        buttons=[
            {"id": "SI", "title": "Sí, correcto ✅"},
            {"id": "NO", "title": "No, corregir"},
        ]
    )


async def send_dni_request(to: str):
    """Ask for DNI — rep legal must do it."""
    return await send_text(
        to=to,
        text=(
            "*Paso 2 de 4: Verificar identidad*\n\n"
            "Este paso debe completarlo el *representante legal* personalmente. Se le pedirá:\n\n"
            "1. Escribir su número de DNI\n"
            "2. Enviar foto de su DNI físico\n"
            "3. Tomarse una selfie en vivo\n\n"
            "Empecemos. Escribe el *DNI del representante legal* (8 digitos):"
        ),
    )


async def send_biometria_request(to: str, nombre_rep: str):
    """Ask for selfie photo for Claude Vision verification."""
    nombre_rep = (nombre_rep or "").strip()
    if nombre_rep:
        cuerpo = (
            f"Ahora necesito una *selfie en vivo* para verificación biométrica.\n\n"
            f"\U0001f933 {nombre_rep}, toma una foto de tu rostro mirando a la camara "
            f"y enviala como imagen en este chat.\n\n"
            f"\U0001f512 Tip: enviala como *Vista unica* (\u2460) para mayor seguridad."
        )
    else:
        cuerpo = (
            f"Ahora necesito una *selfie en vivo* para verificación biométrica.\n\n"
            f"\U0001f933 Toma una foto de tu rostro mirando a la camara "
            f"y enviala como imagen en este chat.\n\n"
            f"\U0001f512 Tip: enviala como *Vista unica* (\u2460) para mayor seguridad."
        )
    return await send_text(to=to, text=cuerpo)


async def send_linea_oferta(to: str, nombre: str, linea: float, distribuidor: str):
    """Show credit line offer for explicit acceptance."""
    return await send_buttons(
        to=to,
        body=(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📋 *Tu tope con Circa*\n\n"
            f"Bodega: *{nombre}*\n"
            f"Hasta: *S/{linea:.2f}* para pedir al distribuidor\n"
            f"Distribuidor: {distribuidor}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"Al aceptar, podrás pedir mercadería y pagarla a Circa en 7, 15 o 30 días.\n\n"
            f"¿Te parece bien este tope?"
        ),
        buttons=[
            {"id": "ACEPTO_LINEA", "title": "Sí, acepto ✅"},
            {"id": "NO_GRACIAS", "title": "No, gracias"},
        ]
    )


async def send_contrato(to: str, linea: float):
    """Show contract summary with terms."""
    return await send_buttons(
        to=to,
        body=(
            f"📋 *Contrato de Facilidad de Financiamiento Circa*\n\n"
            f"*Resumen de términos:*\n"
            f"• Línea de crédito revolving (se renueva al pagar)\n"
            f"• Tasa según día de pago: 3% (1-7d), 5% (8-15d), 7% (16-30d) — mín S/3\n"
            f"• Plazos: 7, 15 o 30 días\n"
            f"• El dinero va directo al proveedor\n"
            f"• Sin costo de apertura ni mantenimiento\n"
            f"• Mora: 0.03% diario desde el día 31\n\n"
            f"Al aceptar, autorizas:\n"
            f"✅ Tratamiento de datos personales (Ley 29733)\n"
            f"✅ Distribuidor comparta historial de compras\n"
            f"✅ Consulta en centrales de riesgo"
        ),
        buttons=[
            {"id": "ACEPTO", "title": "Acepto los términos ✅"},
        ],
        footer="Ver contrato completo: circa.pe/contrato"
    )


async def send_pin_request(to: str, mode: str = "create", bodega_id: str = ""):
    """Ask to create or enter PIN via WhatsApp Flow (masked input)."""
    flow_create_id = os.getenv("FLOW_PIN_CREATE_ID", "")
    flow_verify_id = os.getenv("FLOW_PIN_VERIFY_ID", "")
    flow_legacy_id = os.getenv("FLOW_PIN_ID", "")

    # Prefer split IDs; fallback to legacy single ID.
    create_flow_id = flow_create_id or flow_legacy_id
    verify_flow_id = flow_verify_id or flow_legacy_id

    logger.info(
        "PIN_FLOW_DEBUG mode=%s bodega_id=%s create_id=%s verify_id=%s legacy_id=%s",
        mode,
        bodega_id,
        create_flow_id or "<empty>",
        verify_flow_id or "<empty>",
        flow_legacy_id or "<empty>",
    )

    # Create mode (onboarding PIN setup)
    if create_flow_id and mode == "create":
        logger.info(
            "PIN_FLOW_DEBUG invoking flow mode=create flow_id=%s screen=%s",
            create_flow_id,
            "PIN_CREATE",
        )
        return await send_flow(
            to=to,
            flow_id=create_flow_id,
            flow_cta="Crear clave 🔐",
            body="Crea tu clave Circa de 4 dígitos. La necesitarás para confirmar cada pedido financiado.",
            mode="published",
            screen="PIN_CREATE",
            data={"bodega_id": bodega_id, "mode": "create"},
        )
    
    # Verify mode — confirm order/payment with PIN
    if verify_flow_id and mode == "verify":
        verify_screen = "PIN_VERIFY" if flow_verify_id else "PIN_CREATE"
        logger.info(
            "PIN_FLOW_DEBUG invoking flow mode=verify flow_id=%s screen=%s",
            verify_flow_id,
            verify_screen,
        )
        return await send_flow(
            to=to,
            flow_id=verify_flow_id,
            flow_cta="Confirmar con clave",
            body="Ingresa tu clave Circa de 4 digitos para confirmar tu pedido.",
            mode="published",
            screen=verify_screen,
            data={"bodega_id": bodega_id, "mode": "verify"},
        )
    
    # Fallback to text if flow not configured
    if mode == "create":
        return await send_text(
            to=to,
            text=(
                "🔐 *Crea tu clave Circa de 4 dígitos.*\n\n"
                "La necesitarás para confirmar cada pedido financiado.\n"
                "No uses fechas de nacimiento ni números consecutivos.\n\n"
                "Escribe tu clave ahora:"
            )
        )
    else:
        return await send_text(
            to=to,
            text="🔐 *Ingresa tu clave Circa para confirmar:*\n\n⏱ Tienes 5 minutos."
        )


async def send_cuenta_activa(to: str, linea: float):
    """Send account activation confirmation + menu."""
    await send_text(
        to=to,
        text=(
            f"🎉 *¡Tu cuenta Circa está activa!*\n\n"
            f"Tu clave fue creada correctamente.\n"
            f"Tope disponible para comprar: *S/{linea:.2f}*"
        )
    )
    # Follow with menu
    return await send_menu(to, linea)


async def send_linea_info(to: str, aprobada: float, disponible: float, scoring: float):
    """Show credit line details."""
    barra = "█" * int(disponible/aprobada*10) + "░" * (10 - int(disponible/aprobada*10))
    return await send_buttons(
        to=to,
        body=(
            f"💰 *Tu tope Circa*\n\n"
            f"Tope máximo: S/{aprobada:.2f}\n"
            f"Te queda para pedir: *S/{disponible:.2f}*\n"
            f"[{barra}]\n"
            f"Confianza Circa: {scoring:.0f}/100 (según tu historial con el distribuidor)"
        ),
        buttons=[
            {"id": "PEDIDO", "title": "🛍 Hacer pedido"},
            {"id": "MENU", "title": "🏠 Menú principal"},
        ]
    )


async def send_contacto_circa(to: str, wa_link: str | None) -> dict | None:
    """
    Contacto soporte Circa: botón CTA que abre wa.me (sin mostrar el número en el cuerpo).
    Si no hay CIRCA_SOPORTE_WHATSAPP, texto + botón de menú.
    """
    body_con_link = (
        "📞 *Circa*\n\n"
        "¿Necesitas ayuda? Pulsa el botón y se abrirá el chat con nuestro equipo.\n\n"
        "Cuando termines, escribe *MENU* para volver al menú."
    )
    body_sin_link = (
        "📞 *Contacto Circa*\n\n"
        "El soporte por WhatsApp aún no está configurado.\n\n"
        "Escribe *MENU* o habla con tu distribuidor."
    )
    if wa_link and str(wa_link).strip().lower().startswith("http"):
        url = str(wa_link).strip()
        return await _send(to, {
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {"text": body_con_link[:1024]},
                "action": {
                    "name": "cta_url",
                    "parameters": {
                        "display_text": "Chatear con Circa",
                        "url": url,
                    },
                },
            },
        })
    return await send_buttons(
        to=to,
        body=body_sin_link,
        buttons=[{"id": "MENU", "title": "Menú principal"}],
    )


async def send_catalogo_flow(to: str, bodega_id: str, tipo_operacion: str = "venta"):
    """Send catalog as CTA URL button - opens in WhatsApp in-app browser."""
    base = os.getenv("APP_BASE_URL", "https://circa-production-c517.up.railway.app")
    t = "preventa" if tipo_operacion == "preventa" else "venta"
    url = f"{base}/catalogo-v2?b={bodega_id}&t={t}"
    texto = (
        "Arma tu pre-venta del catalogo.\n"
        "Busca por nombre o marca, elige cantidades y confirma."
        if t == "preventa"
        else "Arma tu pedido del catalogo.\nBusca por nombre o marca, elige cantidades y confirma."
    )
    return await _send(to, {
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {
                "text": texto
            },
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": "Abrir catalogo",
                    "url": url
                }
            }
        }
    })

async def send_order_confirmation(to: str, order_number: str, total_credito: float, pago_contado: float):
    """Send order confirmation message after Flow completes."""
    return await send_text(
        to=to,
        text=(
            f"✅ *¡Pedido confirmado!*\n\n"
            f"Número: *{order_number}*\n"
            f"Total crédito: S/{total_credito:.2f}\n"
            f"Pago contado: S/{pago_contado:.2f}\n\n"
            f"Recibirás actualizaciones cuando tu pedido cambie de estado.\n\n"
            f"Escribe *MENU* para volver al menú principal."
        )
    )


async def send_tracking_update(to: str, order_number: str, estado: str, detalle: str = ""):
    """Send order tracking update."""
    estados_emoji = {
        "confirmado": "📦",
        "preparando": "🔧",
        "en_camino": "🚚",
        "entregado": "✅",
    }
    emoji = estados_emoji.get(estado, "📦")
    
    text = f"{emoji} *Pedido {order_number}*\nEstado: *{estado.replace('_', ' ').title()}*"
    if detalle:
        text += f"\n{detalle}"
    
    return await send_text(to=to, text=text)


async def send_payment_instructions(to: str, order_number: str, monto: float, vencimiento: str):
    """Send payment instructions with Yape details."""
    yape_phone = os.getenv("YAPE_PHONE", "986311567")
    yape_name = os.getenv("YAPE_NAME", "PALI SAC")
    
    return await send_buttons(
        to=to,
        body=(
            f"💰 *Pago pendiente — {order_number}*\n\n"
            f"Monto: *S/{monto:.2f}*\n"
            f"Vence: *{vencimiento}*\n\n"
            f"Paga por Yape al:\n"
            f"📱 *{yape_phone}*\n"
            f"👤 {yape_name}\n\n"
            f"Cuando hayas pagado, toca el botón:"
        ),
        buttons=[
            {"id": "YA_PAGUE", "title": "Ya pagué ✅"},
            {"id": "MENU", "title": "Menú principal"},
        ]
    )


async def send_payment_confirmed(to: str, linea_disponible: float):
    """Send payment confirmation and line renewal."""
    return await send_text(
        to=to,
        text=(
            f"✅ *¡Pago recibido!*\n\n"
            f"Tu línea fue renovada.\n"
            f"💚 Línea disponible: *S/{linea_disponible:.2f}*\n\n"
            f"Escribe *MENU* para hacer otro pedido."
        )
    )


async def send_reminder(to: str, order_number: str, monto: float, dias_restantes: int):
    """Send payment reminder."""
    if dias_restantes > 0:
        urgencia = f"Faltan *{dias_restantes} días* para el vencimiento."
    elif dias_restantes == 0:
        urgencia = "⚠️ *Tu pago vence HOY.*"
    else:
        urgencia = f"🔴 *Tu pago está vencido hace {abs(dias_restantes)} días.*"
    
    return await send_buttons(
        to=to,
        body=f"📋 *Recordatorio — {order_number}*\n\nMonto: S/{monto:.2f}\n{urgencia}",
        buttons=[
            {"id": "YA_PAGUE", "title": "Ya pagué ✅"},
            {"id": "MENU", "title": "Menú principal"},
        ]
    )


# ══════════════════════════════════════════════
# DISTRIBUTOR NOTIFICATIONS
# ══════════════════════════════════════════════

async def notify_distribuidor_new_order(distribuidor_wa: str, order_number: str, 
                                         bodega_nombre: str, bodega_direccion: str,
                                         bodega_telefono: str, items_text: str, 
                                         total: float):
    """Notify distributor of a new order via WhatsApp."""
    return await send_buttons(
        to=distribuidor_wa,
        body=(
            f"📦 *NUEVA ORDEN — {order_number}*\n\n"
            f"Bodega: {bodega_nombre}\n"
            f"Dirección: {bodega_direccion}\n"
            f"WhatsApp: {bodega_telefono}\n\n"
            f"Productos:\n{items_text}\n\n"
            f"*TOTAL: S/{total:.2f}*\n"
            f"Pago Circa: S/{total:.2f} (24-48h a su cuenta)"
        ),
        buttons=[
            {"id": f"CONFIRMAR_{order_number}", "title": "✅ Confirmar"},
            {"id": f"RECHAZAR_{order_number}", "title": "❌ Rechazar"},
        ]
    )


# ══════════════════════════════════════════════
# IMAGE SENDING (for branded cards)
# ══════════════════════════════════════════════

async def send_image_bytes(to: str, image_bytes: bytes, caption: str = "") -> bool:
    """Upload and send an image from bytes."""
    import tempfile, os as _os
    
    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(image_bytes)
    tmp.close()
    
    try:
        url_upload = f"{GRAPH_API_URL}/{_phone_number_id()}/media"
        async with httpx.AsyncClient(timeout=30) as client:
            with open(tmp.name, "rb") as f:
                resp = await client.post(
                    url_upload,
                    headers={"Authorization": f"Bearer {_access_token()}"},
                    data={"messaging_product": "whatsapp", "type": "image/png"},
                    files={"file": ("card.png", f, "image/png")},
                )
        
        if resp.status_code != 200:
            logger.error(f"Card upload failed: {resp.text}")
            return False
        
        media_id = resp.json().get("id")
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"id": media_id},
        }
        if caption:
            payload["image"]["caption"] = caption
        
        result = await _send(to, payload)
        return result is not None
    finally:
        _os.unlink(tmp.name)


# ══════════════════════════════════════════════
# CONTRACT PDF SENDING
# ══════════════════════════════════════════════

async def send_contract_document(to: str, file_path: str, bodega_nombre: str) -> bool:
    """Upload and send contract PDF via WhatsApp."""
    import os as _os
    
    # 1) Upload PDF to Meta
    url_upload = f"{GRAPH_API_URL}/{_phone_number_id()}/media"
    filename = _os.path.basename(file_path)
    
    async with httpx.AsyncClient(timeout=30) as client:
        with open(file_path, "rb") as f:
            resp = await client.post(
                url_upload,
                headers={"Authorization": f"Bearer {_access_token()}"},
                data={"messaging_product": "whatsapp", "type": "application/pdf"},
                files={"file": (filename, f, "application/pdf")},
            )
    
    if resp.status_code != 200:
        logger.error(f"Contract upload failed: {resp.text}")
        return False
    
    media_id = resp.json().get("id")
    
    # 2) Send as document message
    safe_name = bodega_nombre.replace(" ", "_").replace(".", "")
    result = await _send(to, {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": f"Contrato_Circa_{safe_name}.pdf",
            "caption": f"Contrato de Facilidad de Financiamiento — {bodega_nombre}\n\nEste documento confirma tu aceptacion de los terminos de Circa."
        }
    })
    
    if result:
        logger.info(f"Contract PDF sent to {to}")
    return result is not None
