"""
WhatsApp Flow Endpoint — Catálogo & Checkout.

Handles the multi-screen catalog and purchase flow:
  CATEGORIAS → PRODUCTOS → DETALLE → AGREGADO → CARRITO →
  FINANCIAR_DECISION → MONTO → PLAZO → RESUMEN_PIN

Dynamic endpoint: loads products from Supabase, manages cart,
calculates fees, validates PIN, creates order atomically.
"""
import logging
import json
import hashlib
from app.services import db
from app.services.financing import calculate_eligibility, calculate_quote, calculate_summary
from app.services.pin import check_pin

logger = logging.getLogger("circa.flows.catalogo")


async def handle_catalogo(flow_data: dict) -> dict:
    """
    Route catalog flow requests to the appropriate handler.
    """
    screen = flow_data.get("screen", "")
    action = flow_data.get("action", "")
    data = flow_data.get("data", {})
    flow_token = flow_data.get("flow_token", "")
    
    logger.info(f"Catálogo: screen={screen}, action={action}, data_keys={list(data.keys())}")
    
    # ── HEALTH CHECK ──
    if action == "ping":
        return {"version": "3.0", "data": {"status": "active"}}

    # ── INIT or navigate: Show categories ──
    if action in ("INIT", "data_exchange", "navigate") or (not screen and not action):
        return await _screen_categorias(data)
    
    # ── Route by screen ──
    handlers = {
        "CATEGORIAS": _handle_categoria_selected,
        "PRODUCTOS": _handle_producto_selected,
        "DETALLE": _handle_agregar_al_carrito,
        "AGREGADO": _handle_agregado_action,
        "CARRITO": _handle_carrito_action,
        "FINANCIAR_DECISION": _handle_financiar_decision,
        "MONTO": _handle_monto_selected,
        "PLAZO": _handle_plazo_selected,
        "RESUMEN_PIN": _handle_confirmar_pedido,
    }
    
    handler = handlers.get(screen)
    if handler:
        return await handler(data, flow_token)
    
    logger.warning(f"Unknown catalog screen: {screen}")
    return {"data": {"error": "Pantalla no reconocida."}}


# ══════════════════════════════════════════════
# SCREEN: CATEGORIAS
# ══════════════════════════════════════════════

async def _screen_categorias(data: dict) -> dict:
    """Show product categories as NavigationList."""
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    
    # Get categories from catalog
    bodega = db.sb.table("bodegas").select("distribuidor_id").eq("id", bodega_id).single().execute().data
    if not bodega:
        return {"data": {"error": "Bodega no encontrada."}}
    
    categorias_raw = db.get_categorias(bodega["distribuidor_id"])
    
    # Map to NavigationList items
    emoji_map = {
        "bebidas": "🥤", "lácteos": "🥛", "lacteos": "🥛",
        "abarrotes": "🛒", "cuidado": "🧴", "cuidado personal": "🧴",
    }
    
    items = []
    for cat in categorias_raw:
        cat_lower = cat.lower()
        items.append({
            "id": cat,
            "title": cat,
            "description": f"Ver productos de {cat}",
            "image": emoji_map.get(cat_lower, "📦"),
        })
    
    return {
        "screen": "CATEGORIAS",
        "data": {
            "categorias": items,
            "bodega_id": bodega_id,
            "distribuidor_id": bodega["distribuidor_id"],
        }
    }


# ══════════════════════════════════════════════
# SCREEN: PRODUCTOS (by category)
# ══════════════════════════════════════════════

async def _handle_categoria_selected(data: dict, flow_token: str) -> dict:
    """Load products for selected category."""
    categoria = data.get("categoria", "")
    distribuidor_id = data.get("distribuidor_id", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    
    productos = db.get_catalogo(distribuidor_id, categoria=categoria)
    
    items = []
    for p in productos:
        # Get cheapest pack price for "desde" display
        precios = []
        if p.get("precio_pack_6"): precios.append(p["precio_pack_6"])
        if p.get("precio_pack_12"): precios.append(p["precio_pack_12"])
        if p.get("precio_pack_24"): precios.append(p["precio_pack_24"])
        
        min_price = min(precios) if precios else 0
        dist_name = p.get("distribuidores", {}).get("nombre_comercial", "")
        
        items.append({
            "id": p["id"],
            "title": p.get("nombre", ""),
            "description": dist_name,
            "end_title": f"S/{min_price:.2f}",
            "end_description": "desde",
        })
    
    return {
        "screen": "PRODUCTOS",
        "data": {
            "productos": items,
            "categoria": categoria,
            "bodega_id": bodega_id,
            "distribuidor_id": distribuidor_id,
        }
    }


# ══════════════════════════════════════════════
# SCREEN: DETALLE (pack + quantity selection)
# ══════════════════════════════════════════════

async def _handle_producto_selected(data: dict, flow_token: str) -> dict:
    """Show product detail with pack and quantity selection."""
    producto_id = data.get("producto_id", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    
    # Load product
    p = db.sb.table("catalogo").select("*, distribuidores(nombre_comercial)").eq("id", producto_id).single().execute().data
    if not p:
        return {"data": {"error": "Producto no encontrado."}}
    
    # Build pack options
    packs = []
    if p.get("precio_pack_6"):
        packs.append({"id": "6", "title": f"Pack 6 — S/{p['precio_pack_6']:.2f}"})
    if p.get("precio_pack_12"):
        packs.append({"id": "12", "title": f"Pack 12 — S/{p['precio_pack_12']:.2f}"})
    if p.get("precio_pack_24"):
        packs.append({"id": "24", "title": f"Pack 24 — S/{p['precio_pack_24']:.2f}"})
    
    return {
        "screen": "DETALLE",
        "data": {
            "producto_id": producto_id,
            "nombre": p.get("nombre", ""),
            "distribuidor": p.get("distribuidores", {}).get("nombre_comercial", ""),
            "categoria": p.get("categoria", ""),
            "packs": packs,
            "cantidades": [{"id": str(i), "title": str(i)} for i in range(1, 11)],
            "bodega_id": bodega_id,
        }
    }


# ══════════════════════════════════════════════
# SCREEN: AGREGADO (item added to cart)
# ══════════════════════════════════════════════

async def _handle_agregar_al_carrito(data: dict, flow_token: str) -> dict:
    """Add item to cart and show confirmation."""
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    producto_id = data.get("producto_id", "")
    pack_size = int(data.get("pack", "12"))
    cantidad = int(data.get("cantidad", "1"))
    
    # Load product to get price
    p = db.sb.table("catalogo").select("*").eq("id", producto_id).single().execute().data
    if not p:
        return {"data": {"error": "Producto no encontrado."}}
    
    precio_key = f"precio_pack_{pack_size}"
    precio = p.get(precio_key, 0)
    subtotal = precio * cantidad
    
    # Add to cart in Supabase
    carrito = db.get_carrito(bodega_id)
    cart_items = json.loads(carrito["items"]) if carrito and carrito.get("items") else []
    
    # Check if same product+pack already in cart
    found = False
    for item in cart_items:
        if item.get("catalogo_id") == producto_id and item.get("pack_size") == pack_size:
            item["cantidad"] += cantidad
            item["subtotal"] = item["cantidad"] * precio
            found = True
            break
    
    if not found:
        cart_items.append({
            "catalogo_id": producto_id,
            "nombre": p.get("nombre", ""),
            "pack_size": pack_size,
            "cantidad": cantidad,
            "precio": precio,
            "subtotal": subtotal,
        })
    
    db.save_carrito(bodega_id, cart_items)
    
    # Calculate totals
    total_packs = sum(i["cantidad"] for i in cart_items)
    total_monto = sum(i["subtotal"] for i in cart_items)
    
    return {
        "screen": "AGREGADO",
        "data": {
            "mensaje": f"✅ {cantidad}x Pack {pack_size} {p.get('nombre', '')} — S/{subtotal:.2f}",
            "carrito_resumen": f"Carrito: {total_packs} packs · S/{total_monto:.2f}",
            "bodega_id": bodega_id,
        }
    }


# ══════════════════════════════════════════════
# SCREEN: CARRITO (cart review)
# ══════════════════════════════════════════════

async def _handle_agregado_action(data: dict, flow_token: str) -> dict:
    """Handle "add more" or "review cart" action."""
    accion = data.get("accion", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    
    if accion == "mas":
        return await _screen_categorias({"bodega_id": bodega_id})
    else:  # revisar
        return await _show_carrito(bodega_id)


async def _show_carrito(bodega_id: str) -> dict:
    """Build cart review screen."""
    carrito = db.get_carrito(bodega_id)
    cart_items = json.loads(carrito["items"]) if carrito and carrito.get("items") else []
    
    if not cart_items:
        return {
            "screen": "CARRITO",
            "data": {"items_text": "Tu carrito está vacío.", "total": 0, "bodega_id": bodega_id}
        }
    
    bodega = db.sb.table("bodegas").select("linea_disponible").eq("id", bodega_id).single().execute().data
    linea = bodega.get("linea_disponible", 0) if bodega else 0
    
    total = sum(i["subtotal"] for i in cart_items)
    items_text = "\n".join(f"{i['cantidad']}x Pk{i['pack_size']} {i['nombre']} — S/{i['subtotal']:.2f}" for i in cart_items)
    
    eligibility = calculate_eligibility(total, linea)
    
    return {
        "screen": "CARRITO",
        "data": {
            "items_text": items_text,
            "total": total,
            "total_label": f"S/{total:.2f}",
            "linea_disponible": linea,
            "financiable_max": eligibility["financiable_max"],
            "contado_min": eligibility["contado_min"],
            "linea_info": f"Línea: S/{linea:.2f}. Financias hasta S/{eligibility['financiable_max']:.2f}"
                + (f", pagas S/{eligibility['contado_min']:.2f} al contado" if eligibility['contado_min'] > 0 else ""),
            "bodega_id": bodega_id,
        }
    }


# ══════════════════════════════════════════════
# SCREENS: FINANCING FLOW
# ══════════════════════════════════════════════

async def _handle_carrito_action(data: dict, flow_token: str) -> dict:
    """Handle cart actions: financiar, agregar, vaciar."""
    accion = data.get("accion", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    
    if accion == "agregar":
        return await _screen_categorias({"bodega_id": bodega_id})
    elif accion == "vaciar":
        db.clear_carrito(bodega_id)
        return await _screen_categorias({"bodega_id": bodega_id})
    else:  # financiar
        return {
            "screen": "FINANCIAR_DECISION",
            "data": {
                "bodega_id": bodega_id,
                "total": data.get("total", 0),
            }
        }


async def _handle_financiar_decision(data: dict, flow_token: str) -> dict:
    """Handle finance vs pay all decision."""
    decision = data.get("decision", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    total = data.get("total", 0)
    
    if decision == "pagar_todo":
        # TODO: Create order without financing
        return {"data": {"message": "Pedido sin financiamiento — próximamente"}}
    
    # Show financing amount options
    bodega = db.sb.table("bodegas").select("linea_disponible").eq("id", bodega_id).single().execute().data
    linea = bodega.get("linea_disponible", 0) if bodega else 0
    eligibility = calculate_eligibility(total, linea)
    
    return {
        "screen": "MONTO",
        "data": {
            "opciones": eligibility["opciones"],
            "bodega_id": bodega_id,
            "total": total,
        }
    }


async def _handle_monto_selected(data: dict, flow_token: str) -> dict:
    """User selected financing amount, show term options."""
    monto = data.get("monto", 0)
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    total = data.get("total", 0)
    
    quote = calculate_quote(monto)
    
    return {
        "screen": "PLAZO",
        "data": {
            "plazos": quote["plazos"],
            "monto_financiar": monto,
            "contado": total - monto,
            "bodega_id": bodega_id,
            "total": total,
        }
    }


async def _handle_plazo_selected(data: dict, flow_token: str) -> dict:
    """User selected term, show final summary with PIN input."""
    plazo_dias = int(data.get("plazo", 7))
    monto = data.get("monto_financiar", 0)
    total = data.get("total", 0)
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    
    summary = calculate_summary(total, monto, plazo_dias)
    
    return {
        "screen": "RESUMEN_PIN",
        "data": {
            **summary,
            "bodega_id": bodega_id,
            "resumen_text": (
                f"Pedido: S/{summary['pedido_total']:.2f}\n"
                f"Financiar: S/{summary['monto_financiado']:.2f}\n"
                f"Tasa: {summary['tasa_pct']}\n"
                f"Plazo: {summary['plazo_dias']} días\n"
                f"Fee: S/{summary['fee']:.2f}\n"
                f"Total crédito: S/{summary['total_credito']:.2f}\n"
                f"Vencimiento: {summary['vencimiento_label']}\n"
                f"Contado: S/{summary['pago_contado']:.2f}"
            ),
        }
    }


# ══════════════════════════════════════════════
# SCREEN: CONFIRM ORDER (PIN + atomic operation)
# ══════════════════════════════════════════════

async def _handle_confirmar_pedido(data: dict, flow_token: str) -> dict:
    """Validate PIN and create order atomically."""
    pin = data.get("pin", "")
    bodega_id = data.get("bodega_id", "") or "b1b2c3d4-0001-4000-8000-000000000001"
    
    # Verify PIN
    bodega = db.sb.table("bodegas").select("pin_hash, distribuidor_id").eq("id", bodega_id).single().execute().data
    if not bodega:
        return {"data": {"error": "Bodega no encontrada."}}
    
    if not check_pin(pin, bodega["pin_hash"]):
        return {
            "screen": "RESUMEN_PIN",
            "data": {
                **{k: v for k, v in data.items() if k != "pin"},
                "error_messages": {"pin": "Clave incorrecta. Intenta de nuevo."},
            }
        }
    
    # Load cart
    carrito = db.get_carrito(bodega_id)
    cart_items = json.loads(carrito["items"]) if carrito and carrito.get("items") else []
    
    if not cart_items:
        return {"data": {"error": "Tu carrito está vacío."}}
    
    # Create order atomically
    try:
        monto_financiado = data.get("monto_financiado", 0)
        plazo_dias = int(data.get("plazo_dias", 7))
        fee = data.get("fee", 0)
        total = data.get("pedido_total", 0)
        
        pedido = db.create_pedido(
            bodega_id=bodega_id,
            distribuidor_id=bodega["distribuidor_id"],
            items=cart_items,
            monto_productos=total,
            monto_financiado=monto_financiado,
            monto_contado=total - monto_financiado,
            fee_tasa=data.get("tasa", 0.05),
            fee_monto=fee,
            plazo_dias=plazo_dias,
        )
        
        # Clear cart after successful order
        db.clear_carrito(bodega_id)
        
        logger.info(f"Order created: {pedido['numero']} for bodega {bodega_id}")
        
        # Terminal response — closes the Flow and returns data to chat
        return {
            "screen": "SUCCESS",
            "data": {
                "extension_message_response": {
                    "params": {
                        "flow_token": flow_token,
                        "status": "order_confirmed",
                        "order_number": pedido["numero"],
                        "bodega_id": bodega_id,
                        "total_credito": monto_financiado + fee,
                        "pago_contado": total - monto_financiado,
                    }
                }
            }
        }
    
    except Exception as e:
        logger.error(f"Order creation failed: {e}", exc_info=True)
        return {"data": {"error": "Error al crear tu pedido. Intenta de nuevo."}}
