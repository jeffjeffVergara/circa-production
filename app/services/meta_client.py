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

async def send_list(to: str, body: str, button_text: str, sections: list[dict], header: str = None, footer: str = None) -> dict | None:
    """
    Send interactive list message.
    
    Args:
        sections: [{
            "title": "Bebidas",
            "rows": [{"id": "1", "title": "Coca-Cola", "description": "Pack 12 — S/18"}]
        }]
    """
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

async def send_menu(to: str, linea_disponible: float):
    """Send the main menu with quick reply buttons."""
    return await send_buttons(
        to=to,
        body=f"📋 ¿Qué deseas hacer?\n\nLínea disponible: S/{linea_disponible:.2f}",
        buttons=[
            {"id": "PEDIDO", "title": "🛒 Hacer pedido"},
            {"id": "LINEA", "title": "💰 Mi línea"},
            {"id": "ESTADO", "title": "📦 Mis pedidos"},
        ]
    )


async def send_onboarding_flow(to: str, bodega_id: str, nombre: str, linea: float):
    """Send the onboarding Flow to activate account."""
    flow_id = os.getenv("FLOW_ONBOARDING_ID", "")
    return await send_flow(
        to=to,
        flow_id=flow_id,
        flow_cta="Activar cuenta 🚀",
        body=f"¡Hola! {nombre} tiene una línea de crédito pre-aprobada de S/{linea:.2f}.\n\nActiva tu cuenta para empezar a comprar inventario financiado.",
        header="Circa — Crédito para tu bodega",
        screen="RUC_INPUT",
        data={"bodega_id": bodega_id},
    )


async def send_catalogo_flow(to: str, bodega_id: str):
    """Send the catalog Flow to start shopping."""
    flow_id = os.getenv("FLOW_CATALOGO_ID", "")
    return await send_flow(
        to=to,
        flow_id=flow_id,
        flow_cta="Ver catálogo 🛒",
        body="Elige productos de tu distribuidor y arma tu pedido. Financia con tu línea Circa.",
        header="Catálogo Circa",
        screen="CATEGORIAS",
        data={"bodega_id": bodega_id},
    )


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
    yape_phone = os.getenv("YAPE_PHONE", "987654321")
    yape_name = os.getenv("YAPE_NAME", "Circa Lab S.A.C.")
    
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
